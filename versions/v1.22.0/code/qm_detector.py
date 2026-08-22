"""
QM (Quasimodo) pattern detector — pure, no network, no side effects.

This module is deliberately dependency-light (pandas + numpy) and free of I/O so
that the live bot and the backtester run the EXACT same detection code. If you
ever find yourself writing a second copy of this logic for backtesting, stop —
the two copies will drift and your backtest numbers become fiction.

Bearish QM structure (bullish is the mirror image):

                    HEAD (h2)                 h2 > h1  ... sweep above left shoulder
      LS (h1)        /\
        /\          /  \        RS ..... price returns to QML = h1  -> ENTRY
       /  \        /    \       /\
   ___/    \______/      \_____/  \___
            L1 (l1)       L2 (l2)      l2 < l1  ... BREAK OF STRUCTURE

Entry = h1 (QML) | SL = h2 + buffer | TP1 = l2 | Invalidated by a CLOSE above h2.

Repainting: pivots are only confirmed `right` bars after they print, and this
module never inspects the final (possibly unclosed) bar unless you pass one in.
Feed it closed bars only.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field, asdict
from typing import Iterable, Literal

import numpy as np
import pandas as pd

Direction = Literal["bearish", "bullish"]
TriggerMode = Literal["touch", "close_reject"]


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
@dataclass
class QMConfig:
    """All thresholds are in ATR multiples, not absolute price.

    This is what lets one config work on BTC at $60,000 and XAUUSD at $2,400
    without retuning. A "0.1% move" means something completely different on a
    quiet gold session versus a volatile alt — ATR normalises that away.
    """

    pivot_left: int = 3
    pivot_right: int = 3
    atr_period: int = 14

    # Structure quality
    min_sweep_atr: float = 0.10   # head must clear the left shoulder by this much
    min_bos_atr: float = 0.10     # L2 must clear L1 by this much (break of structure)

    # Entry zone / risk
    over_tol_atr: float = 0.50    # Over-QM tolerance: zone extends above QML
    sl_buffer_atr: float = 0.25   # stop placed beyond the head by this much
    min_rr: float = 1.5           # reject setups that cannot pay for their own risk

    # Timing
    max_bars_to_retest: int = 50  # a QM that never gets retested goes stale
    trigger_mode: TriggerMode = "close_reject"

    # Output
    tp2_extension: float = 0.618  # TP2 = TP1 extended by this fraction of head->L2


# --------------------------------------------------------------------------- #
# Data structures
# --------------------------------------------------------------------------- #
@dataclass
class Pivot:
    idx: int
    price: float
    kind: Literal["high", "low"]


@dataclass
class QMSignal:
    symbol: str
    timeframe: str
    direction: Direction

    # structure
    ls_idx: int
    ls_price: float
    l1_idx: int
    l1_price: float
    head_idx: int
    head_price: float
    l2_idx: int
    l2_price: float

    # trade
    qml: float
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risk_reward: float

    # trigger
    trigger_idx: int
    trigger_time: str
    head_time: str                # timestamp, not index — see __post_init__
    atr: float
    overshoot: bool = False       # price traded above QML before reversing (Over-QM)
    signal_id: str = field(default="")

    def __post_init__(self) -> None:
        if not self.signal_id:
            # Keyed on the head bar's TIMESTAMP, never its index. Index is
            # tempting and wrong: each scan fetches a rolling window, so the
            # same head candle sits at a different index every time a new bar
            # closes, and an index-keyed store would happily re-send a signal it
            # had already sent. Timestamps are stable across fetches.
            self.signal_id = (
                f"{self.symbol}|{self.timeframe}|{self.direction}|{self.head_time}"
            )

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Indicators
# --------------------------------------------------------------------------- #
def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's ATR. Returns a Series aligned to df.index."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


# --------------------------------------------------------------------------- #
# Pivot detection
# --------------------------------------------------------------------------- #
def find_pivots(df: pd.DataFrame, left: int = 3, right: int = 3) -> list[Pivot]:
    """Fractal pivots. A pivot at i needs `right` bars after it to be confirmed,
    so the newest usable pivot sits at index len(df) - 1 - right.

    Ties are resolved with >= on the left and > on the right, which prevents a
    flat double-top from producing two adjacent pivots at the same price.
    """
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    n = len(df)
    pivots: list[Pivot] = []

    for i in range(left, n - right):
        wh_left, wh_right = highs[i - left : i], highs[i + 1 : i + 1 + right]
        if highs[i] >= wh_left.max() and highs[i] > wh_right.max():
            pivots.append(Pivot(i, float(highs[i]), "high"))
            continue  # a bar cannot be both a swing high and a swing low
        wl_left, wl_right = lows[i - left : i], lows[i + 1 : i + 1 + right]
        if lows[i] <= wl_left.min() and lows[i] < wl_right.min():
            pivots.append(Pivot(i, float(lows[i]), "low"))

    return pivots


def alternate(pivots: list[Pivot]) -> list[Pivot]:
    """Collapse runs of same-kind pivots, keeping the most extreme one.

    Raw fractals often produce high-high-low or low-low-high runs. QM is defined
    over a strictly alternating swing sequence, so we normalise first — matching
    on raw fractals is where most home-grown detectors quietly go wrong.
    """
    out: list[Pivot] = []
    for p in pivots:
        if out and out[-1].kind == p.kind:
            keep_new = (
                p.price > out[-1].price if p.kind == "high" else p.price < out[-1].price
            )
            if keep_new:
                out[-1] = p
        else:
            out.append(p)
    return out


# --------------------------------------------------------------------------- #
# Pattern matching
# --------------------------------------------------------------------------- #
def _scan_forward(
    df: pd.DataFrame,
    start: int,
    zone_lo: float,
    zone_hi: float,
    invalidation: float,
    direction: Direction,
    cfg: QMConfig,
) -> tuple[int, bool] | None:
    """Walk bars after the BOS looking for the retest into the QM zone.

    Returns (trigger_index, overshoot) or None. The invalidation check uses the
    CLOSE, not the wick: a wick through the head is exactly the liquidity grab
    the pattern is built on, while a close through it means the structure the
    trade relies on is simply gone.
    """
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    end = min(start + cfg.max_bars_to_retest, len(df) - 1)

    # The L2 pivot is not CONFIRMED until `pivot_right` bars after it prints, so
    # a trigger before that would be using knowledge the bot could not have had
    # in real time. Skipping those bars is what keeps backtests honest.
    start = start + cfg.pivot_right

    for i in range(start, end + 1):
        if direction == "bearish":
            if closes[i] > invalidation:
                return None
            entered = highs[i] >= zone_lo
            if not entered:
                continue
            overshoot = highs[i] > zone_hi
            if cfg.trigger_mode == "touch":
                return i, overshoot
            if closes[i] < zone_lo:  # close_reject: rejected back below QML
                return i, overshoot
        else:
            if closes[i] < invalidation:
                return None
            entered = lows[i] <= zone_hi
            if not entered:
                continue
            overshoot = lows[i] < zone_lo
            if cfg.trigger_mode == "touch":
                return i, overshoot
            if closes[i] > zone_hi:
                return i, overshoot

    return None


def detect_qm(
    df: pd.DataFrame,
    cfg: QMConfig | None = None,
    symbol: str = "UNKNOWN",
    timeframe: str = "?",
    directions: Iterable[Direction] = ("bearish", "bullish"),
) -> list[QMSignal]:
    """Find every QM setup that triggered inside `df`.

    `df` needs columns: open, high, low, close (volume optional) and ideally a
    DatetimeIndex. Pass CLOSED bars only.
    """
    cfg = cfg or QMConfig()
    if len(df) < cfg.atr_period + cfg.pivot_left + cfg.pivot_right + 10:
        return []

    df = df.reset_index().rename(columns={df.index.name or "index": "time"})
    atr_series = atr(df, cfg.atr_period).to_numpy(dtype=float)
    pivots = alternate(find_pivots(df, cfg.pivot_left, cfg.pivot_right))
    signals: list[QMSignal] = []

    for a in range(len(pivots) - 3):
        p1, p2, p3, p4 = pivots[a : a + 4]

        for direction in directions:
            want = ("high", "low", "high", "low") if direction == "bearish" else (
                "low", "high", "low", "high"
            )
            if tuple(p.kind for p in (p1, p2, p3, p4)) != want:
                continue

            ls, l1, head, l2 = p1, p2, p3, p4
            a_val = atr_series[l2.idx]
            if not math.isfinite(a_val) or a_val <= 0:
                continue

            if direction == "bearish":
                # head sweeps above the left shoulder, then structure breaks down
                if head.price <= ls.price + cfg.min_sweep_atr * a_val:
                    continue
                if l2.price >= l1.price - cfg.min_bos_atr * a_val:
                    continue
                zone_lo, zone_hi = ls.price, ls.price + cfg.over_tol_atr * a_val
                invalidation = head.price
            else:
                if head.price >= ls.price - cfg.min_sweep_atr * a_val:
                    continue
                if l2.price <= l1.price + cfg.min_bos_atr * a_val:
                    continue
                zone_hi, zone_lo = ls.price, ls.price - cfg.over_tol_atr * a_val
                invalidation = head.price

            hit = _scan_forward(
                df, l2.idx + 1, zone_lo, zone_hi, invalidation, direction, cfg
            )
            if hit is None:
                continue
            trig_idx, overshoot = hit
            trig_atr = atr_series[trig_idx]
            if not math.isfinite(trig_atr) or trig_atr <= 0:
                trig_atr = a_val

            qml = ls.price
            if direction == "bearish":
                entry = qml
                sl = head.price + cfg.sl_buffer_atr * trig_atr
                tp1 = l2.price
                tp2 = l2.price - cfg.tp2_extension * (head.price - l2.price)
                risk, reward = sl - entry, entry - tp1
            else:
                entry = qml
                sl = head.price - cfg.sl_buffer_atr * trig_atr
                tp1 = l2.price
                tp2 = l2.price + cfg.tp2_extension * (l2.price - head.price)
                risk, reward = entry - sl, tp1 - entry

            if risk <= 0 or reward <= 0:
                continue
            rr = reward / risk
            if rr < cfg.min_rr:
                continue

            signals.append(
                QMSignal(
                    symbol=symbol,
                    timeframe=timeframe,
                    direction=direction,
                    ls_idx=int(ls.idx),
                    ls_price=float(ls.price),
                    l1_idx=int(l1.idx),
                    l1_price=float(l1.price),
                    head_idx=int(head.idx),
                    head_price=float(head.price),
                    l2_idx=int(l2.idx),
                    l2_price=float(l2.price),
                    qml=float(qml),
                    entry=float(entry),
                    stop_loss=float(sl),
                    take_profit_1=float(tp1),
                    take_profit_2=float(tp2),
                    risk_reward=round(float(rr), 2),
                    trigger_idx=int(trig_idx),
                    trigger_time=str(df["time"].iloc[trig_idx]),
                    head_time=str(df["time"].iloc[head.idx]),
                    atr=float(trig_atr),
                    overshoot=bool(overshoot),
                )
            )

    return signals


def position_size(equity: float, risk_pct: float, entry: float, stop_loss: float) -> float:
    """Units to trade so that a stop-out costs exactly `risk_pct` of equity.

    A signal without a size is not yet actionable — always attach this before
    sending anything to a human.
    """
    per_unit = abs(entry - stop_loss)
    if per_unit <= 0:
        return 0.0
    return (equity * risk_pct) / per_unit


# --------------------------------------------------------------------------- #
# CLI — quick sanity check before you wire anything to LINE
# --------------------------------------------------------------------------- #
def _load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    tcol = cols.get("time") or cols.get("timestamp") or cols.get("date")
    if tcol:
        df[tcol] = pd.to_datetime(df[tcol], utc=True, errors="coerce")
        df = df.set_index(tcol)
    df.columns = [c.lower() for c in df.columns]
    return df[["open", "high", "low", "close"]].astype(float).dropna()


def _load_ccxt(symbol: str, timeframe: str, limit: int, exchange: str) -> pd.DataFrame:
    import ccxt  # imported lazily so the detector stays dependency-light

    ex = getattr(ccxt, exchange)({"enableRateLimit": True})
    raw = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["time", "open", "high", "low", "close", "volume"])
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    return df.set_index("time")[["open", "high", "low", "close"]].astype(float)


def main() -> None:
    ap = argparse.ArgumentParser(description="Detect QM patterns in OHLCV data")
    ap.add_argument("--csv", help="CSV with time,open,high,low,close")
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--exchange", default="binance")
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--min-rr", type=float, default=1.5)
    ap.add_argument("--pivot", type=int, default=3)
    ap.add_argument("--mode", default="close_reject", choices=["touch", "close_reject"])
    ap.add_argument("--plot", action="store_true", help="render the newest signal")
    args = ap.parse_args()

    df = _load_csv(args.csv) if args.csv else _load_ccxt(
        args.symbol, args.timeframe, args.limit, args.exchange
    )
    df = df.iloc[:-1]  # drop the still-forming bar

    cfg = QMConfig(
        pivot_left=args.pivot,
        pivot_right=args.pivot,
        min_rr=args.min_rr,
        trigger_mode=args.mode,
    )
    signals = detect_qm(df, cfg, symbol=args.symbol, timeframe=args.timeframe)

    print(f"bars={len(df)}  signals={len(signals)}")
    for s in signals[-10:]:
        print(
            f"  {s.trigger_time}  {s.direction:<7} entry={s.entry:.4f} "
            f"SL={s.stop_loss:.4f} TP1={s.take_profit_1:.4f} RR={s.risk_reward} "
            f"{'[over-QM]' if s.overshoot else ''}"
        )

    if args.plot and signals:
        from chart_renderer import render_signal

        out = render_signal(df, signals[-1], out_path="qm_signal.png")
        print(f"chart -> {out}")
    elif not args.plot:
        print(json.dumps([s.to_dict() for s in signals[-3:]], indent=2, default=str))


if __name__ == "__main__":
    main()
