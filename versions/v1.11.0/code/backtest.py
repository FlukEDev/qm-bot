"""
Backtest QM signals over historical OHLCV.

It reuses qm_detector.detect_qm unchanged — same code path as the live bot, which
is the only way the numbers below mean anything. Two rules make the results
honest rather than flattering:

  1. Pivots are only used once confirmed (handled inside the detector), so no
     look-ahead bias.
  2. When a bar's range covers BOTH the stop and the target, the stop is assumed
     to hit first. Without intrabar data you cannot know the order, and the
     pessimistic assumption is the only one that will not disappoint you live.

    python backtest.py --csv data/BTCUSDT_1h.csv --symbol BTC/USDT --timeframe 1h
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np
import pandas as pd

from qm_detector import QMConfig, detect_qm


@dataclass
class Trade:
    signal_id: str
    direction: str
    entry_idx: int
    exit_idx: int
    entry: float
    exit_price: float
    outcome: str            # "tp1" | "tp2" | "sl" | "timeout"
    r_multiple: float
    bars_held: int


def simulate(
    df: pd.DataFrame,
    signals,
    fee_pct: float = 0.0005,
    slippage_pct: float = 0.0002,
    max_hold: int = 200,
    target: str = "tp1",
) -> list[Trade]:
    highs = df["high"].to_numpy(float)
    lows = df["low"].to_numpy(float)
    trades: list[Trade] = []

    for s in signals:
        tp = s.take_profit_1 if target == "tp1" else s.take_profit_2
        risk = abs(s.entry - s.stop_loss)
        if risk <= 0:
            continue

        # Entry is a limit at QML which the trigger bar already touched.
        # Costs are charged on both legs, in R units.
        cost_r = (s.entry * (fee_pct * 2 + slippage_pct)) / risk

        start = s.trigger_idx + 1
        end = min(start + max_hold, len(df) - 1)
        outcome, exit_idx, exit_price = "timeout", end, float(df["close"].iloc[end])

        for i in range(start, end + 1):
            if s.direction == "bearish":
                hit_sl, hit_tp = highs[i] >= s.stop_loss, lows[i] <= tp
            else:
                hit_sl, hit_tp = lows[i] <= s.stop_loss, highs[i] >= tp
            if hit_sl:  # checked first on purpose — see module docstring
                outcome, exit_idx, exit_price = "sl", i, s.stop_loss
                break
            if hit_tp:
                outcome, exit_idx, exit_price = target, i, tp
                break

        gross = (s.entry - exit_price) if s.direction == "bearish" else (exit_price - s.entry)
        trades.append(
            Trade(
                signal_id=s.signal_id,
                direction=s.direction,
                entry_idx=s.trigger_idx,
                exit_idx=exit_idx,
                entry=s.entry,
                exit_price=exit_price,
                outcome=outcome,
                r_multiple=round(gross / risk - cost_r, 3),
                bars_held=exit_idx - s.trigger_idx,
            )
        )
    return trades


def report(trades: list[Trade]) -> dict:
    """Win rate alone is a vanity metric — a 40% win rate at 1:3 prints money.
    Expectancy in R is the number that decides whether the strategy is viable."""
    if not trades:
        return {"trades": 0}

    r = np.array([t.r_multiple for t in trades])
    wins, losses = r[r > 0], r[r <= 0]
    equity = r.cumsum()
    drawdown = equity - np.maximum.accumulate(equity)

    return {
        "trades": len(trades),
        "win_rate": round(len(wins) / len(r) * 100, 1),
        "expectancy_R": round(float(r.mean()), 3),
        "total_R": round(float(r.sum()), 2),
        "profit_factor": round(float(wins.sum() / abs(losses.sum())), 2) if losses.size and losses.sum() else None,
        "avg_win_R": round(float(wins.mean()), 2) if wins.size else 0,
        "avg_loss_R": round(float(losses.mean()), 2) if losses.size else 0,
        "max_drawdown_R": round(float(drawdown.min()), 2),
        "avg_bars_held": round(float(np.mean([t.bars_held for t in trades])), 1),
        "by_outcome": {k: int(sum(1 for t in trades if t.outcome == k))
                       for k in ("tp1", "tp2", "sl", "timeout")},
        "by_direction": {
            d: round(float(np.mean([t.r_multiple for t in trades if t.direction == d])), 3)
            for d in ("bearish", "bullish")
            if any(t.direction == d for t in trades)
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--symbol", default="?")
    ap.add_argument("--timeframe", default="?")
    ap.add_argument("--min-rr", type=float, default=1.5)
    ap.add_argument("--pivot", type=int, default=3)
    ap.add_argument("--mode", default="close_reject", choices=["touch", "close_reject"])
    ap.add_argument("--target", default="tp1", choices=["tp1", "tp2"])
    ap.add_argument("--fee-pct", type=float, default=0.0005)
    ap.add_argument("--split", type=float, default=0.0,
                    help="fraction held out as out-of-sample, e.g. 0.3")
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    tcol = next(c for c in df.columns if c.lower() in ("time", "timestamp", "date"))
    df[tcol] = pd.to_datetime(df[tcol], utc=True)
    df = df.set_index(tcol)
    df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close"]].astype(float).dropna()

    cfg = QMConfig(pivot_left=args.pivot, pivot_right=args.pivot,
                   min_rr=args.min_rr, trigger_mode=args.mode)

    def run(frame: pd.DataFrame, label: str) -> None:
        sig = detect_qm(frame, cfg, symbol=args.symbol, timeframe=args.timeframe)
        tr = simulate(frame, sig, fee_pct=args.fee_pct, target=args.target)
        print(f"\n=== {label} ({len(frame)} bars) ===")
        for k, v in report(tr).items():
            print(f"  {k:<16} {v}")

    if args.split > 0:
        cut = int(len(df) * (1 - args.split))
        # Tuning on the in-sample half and then checking out-of-sample is the
        # cheapest defence against fitting parameters to noise.
        run(df.iloc[:cut], "IN-SAMPLE")
        run(df.iloc[cut:], "OUT-OF-SAMPLE")
    else:
        run(df, "FULL")


if __name__ == "__main__":
    main()
