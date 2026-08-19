"""
Full-pipeline backtest: replays the EXACT gates the live bot applies, over
deep history, with an in-sample / out-of-sample split.

Why this exists alongside backtest.py: that one runs detect_qm() only. The
live bot additionally requires RSI divergence and 4H structure alignment
before it will send anything, so a detect-only backtest measures a strategy
the bot does not actually trade. This module wires all three gates together.

Look-ahead safety — the thing that makes or breaks a backtest like this:
  * detect_qm already delays pivot confirmation by `pivot_right` bars.
  * The HTF filter is evaluated PER SIGNAL using only the 4H bars that had
    actually closed by that signal's trigger time (a 4H bar opening at `o`
    is not known until `o + 4h`). Using the full 4H frame instead would let
    the filter judge a 2026 signal with 2026 hindsight and quietly inflate
    every number below.
  * simulate() assumes the stop fills first when a bar's range covers both
    stop and target, since intrabar order is unknowable from OHLCV.

    python backtest_full.py --bars 6000 --split 0.3
    python backtest_full.py --sweep max_bars_to_retest=15,30,50,80
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

from backtest import report, simulate
from divergence import attach_divergence
from htf_filter import htf_allows, htf_structure
from qm_detector import QMConfig, detect_qm
from universe import display_symbol

TF_MS = {"1h": 3_600_000, "4h": 14_400_000}
DEFAULT_SYMBOLS = [
    "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT",
    "DOGE/USDT:USDT", "ADA/USDT:USDT", "LINK/USDT:USDT", "AVAX/USDT:USDT",
    "TRX/USDT:USDT", "DOT/USDT:USDT", "LTC/USDT:USDT", "BCH/USDT:USDT",
    "ETC/USDT:USDT", "UNI/USDT:USDT", "FIL/USDT:USDT",
]


# --------------------------------------------------------------------------- #
# Data — paginated fetch, cached to disk so results stay reproducible
# --------------------------------------------------------------------------- #
def fetch_history(exchange, symbol: str, tf: str, bars: int, cache_dir: Path) -> pd.DataFrame:
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe = display_symbol(symbol).replace("/", "")
    path = cache_dir / f"{safe}_{tf}_{bars}.csv"
    if path.exists():
        df = pd.read_csv(path, parse_dates=["time"])
        return df.set_index("time")[["open", "high", "low", "close"]].astype(float)

    step = TF_MS[tf]
    since = exchange.milliseconds() - bars * step
    rows: list = []
    while len(rows) < bars:
        batch = exchange.fetch_ohlcv(symbol, timeframe=tf, since=since, limit=1000)
        if not batch:
            break
        rows += batch
        since = batch[-1][0] + step
        time.sleep(exchange.rateLimit / 1000)
        if len(batch) < 1000:
            break

    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df = df.drop_duplicates("time").set_index("time")[["open", "high", "low", "close"]]
    df = df.astype(float).dropna().iloc[:-1]  # drop the still-forming bar
    df.reset_index().to_csv(path, index=False)
    return df


# --------------------------------------------------------------------------- #
# Pipeline — the same gates, in the same order, as bot.scan_once()
# --------------------------------------------------------------------------- #
def run_pipeline(
    df_ltf: pd.DataFrame,
    df_htf: pd.DataFrame | None,
    symbol: str,
    tf: str,
    qm_cfg: QMConfig,
    min_rsi_diff: float = 2.0,
    rsi_period: int = 14,
    require_divergence: bool = True,
    use_htf: bool = True,
    htf_pivot: int = 3,
    htf_lookback: int = 6,
) -> list:
    signals = detect_qm(df_ltf, qm_cfg, symbol=symbol, timeframe=tf)
    signals = attach_divergence(
        signals, df_ltf,
        rsi_period=rsi_period,
        min_rsi_diff=min_rsi_diff,
        required=require_divergence,
    )
    if not (use_htf and df_htf is not None):
        return signals

    htf_step = pd.Timedelta(milliseconds=TF_MS["4h"])
    kept = []
    for s in signals:
        ts = df_ltf.index[s.trigger_idx]
        # only 4H bars that had CLOSED by the trigger time (open + 4h <= ts)
        visible = df_htf[df_htf.index <= ts - htf_step]
        if len(visible) < 20:
            kept.append(s)          # not enough HTF history to judge — don't block
            continue
        structure = htf_structure(visible, htf_pivot, htf_pivot, htf_lookback)
        s.htf_structure = structure
        if htf_allows(s.direction, structure):
            kept.append(s)
    return kept


def collect_trades(data: dict, qm_kwargs: dict, tf: str = "1h", **pipe_kwargs) -> list:
    trades = []
    for sym, frames in data.items():
        df_ltf = frames[tf]
        df_htf = frames.get("4h") if tf == "1h" else None
        cfg = QMConfig(**qm_kwargs)
        sigs = run_pipeline(df_ltf, df_htf, display_symbol(sym), tf, cfg, **pipe_kwargs)
        trades += simulate(df_ltf, sigs, target="tp1")
    return trades


def show(label: str, trades: list) -> dict:
    r = report(trades)
    if not r.get("trades"):
        print(f"  {label:<26} no trades")
        return r
    print(
        f"  {label:<26} n={r['trades']:<4} win={r['win_rate']:>5}%  "
        f"E={r['expectancy_R']:>7}R  PF={str(r['profit_factor']):>6}  "
        f"totR={r['total_R']:>8}  maxDD={r['max_drawdown_R']:>7}R"
    )
    return r


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", type=int, default=6000, help="1H bars per symbol")
    ap.add_argument("--split", type=float, default=0.3, help="out-of-sample fraction")
    ap.add_argument("--symbols", default=None, help="comma-separated, default = 15 majors")
    ap.add_argument("--cache", default="data/history")
    ap.add_argument("--sweep", default=None,
                    help="param=v1,v2,v3 — compare one QMConfig field")
    ap.add_argument("--grid", default=None,
                    help="'a=1,2;b=3,4' — sweep two fields together. Use the "
                         "pseudo-field `pivot` to move pivot_left/right as a pair.")
    ap.add_argument("--no-htf", action="store_true", help="disable the 4H alignment gate")
    ap.add_argument("--no-divergence", action="store_true")
    args = ap.parse_args()

    import ccxt

    ex = ccxt.binanceusdm({"enableRateLimit": True})
    symbols = args.symbols.split(",") if args.symbols else DEFAULT_SYMBOLS
    cache = Path(args.cache)

    print(f"fetching {len(symbols)} symbols x {args.bars} 1H bars (cached in {cache}/) ...")
    data = {}
    for sym in symbols:
        try:
            d1 = fetch_history(ex, sym, "1h", args.bars, cache)
            d4 = fetch_history(ex, sym, "4h", args.bars // 4, cache)
            data[sym] = {"1h": d1, "4h": d4}
            print(f"  {display_symbol(sym):<14} 1h={len(d1):<6} 4h={len(d4)}")
        except Exception as exc:
            print(f"  {display_symbol(sym):<14} FAILED: {exc}")

    total_bars = sum(len(f["1h"]) for f in data.values())
    span = max(len(f["1h"]) for f in data.values()) / 24
    print(f"\ntotal 1H bars: {total_bars:,}  (~{span:.0f} days per symbol)")

    pipe = dict(
        require_divergence=not args.no_divergence,
        use_htf=not args.no_htf,
    )
    base_qm = dict(pivot_left=3, pivot_right=3)

    def split_data(frac_from: float, frac_to: float) -> dict:
        out = {}
        for sym, frames in data.items():
            d1 = frames["1h"]
            a, b = int(len(d1) * frac_from), int(len(d1) * frac_to)
            out[sym] = {"1h": d1.iloc[a:b], "4h": frames["4h"]}
        return out

    def expand(field: str, value) -> dict:
        """`pivot` is a pseudo-field: swing size must move on both sides at
        once, since a pivot confirmed with a different left/right window is a
        different pivot, not a tuning knob."""
        return ({"pivot_left": value, "pivot_right": value}
                if field == "pivot" else {field: value})

    if args.grid:
        (fa, ra), (fb, rb) = [p.split("=") for p in args.grid.split(";")]
        va = [int(v) for v in ra.split(",")]
        vb = [int(v) for v in rb.split(",")]
        cut = 1 - args.split
        for label, dset in (("IN-SAMPLE", split_data(0, cut)),
                            ("OUT-OF-SAMPLE", split_data(cut, 1.0))):
            print(f"\n=== grid {fa} x {fb} — {label} ===")
            print(f"  {'':<12}" + "".join(f"{fb}={v:<16}" for v in vb))
            for a in va:
                cells = []
                for b in vb:
                    qm = {**base_qm, **expand(fa, a), **expand(fb, b)}
                    r = report(collect_trades(dset, qm, **pipe))
                    cells.append(
                        f"n={r['trades']:<4}E={r['expectancy_R']:<7}" if r.get("trades")
                        else "n=0            "
                    )
                print(f"  {fa}={a:<8}" + "".join(f"{c:<20}" for c in cells))
        print("\nPick a cell that is good in BOTH tables AND whose neighbours are")
        print("also good — a single strong cell surrounded by weak ones is noise.")
        return

    if args.sweep:
        field, raw = args.sweep.split("=")
        values = [float(v) if "." in v else int(v) for v in raw.split(",")]
        cut = 1 - args.split
        print(f"\n=== sweep {field} — IN-SAMPLE (first {cut:.0%}) ===")
        for v in values:
            show(f"{field}={v}", collect_trades(split_data(0, cut), {**base_qm, **expand(field, v)}, **pipe))
        print(f"\n=== sweep {field} — OUT-OF-SAMPLE (last {args.split:.0%}) ===")
        for v in values:
            show(f"{field}={v}", collect_trades(split_data(cut, 1.0), {**base_qm, **expand(field, v)}, **pipe))
        print("\nA value that only looks good in-sample is overfitting, not an edge.")
        return

    print(f"\n=== live config (divergence={'off' if args.no_divergence else 'on'}, "
          f"HTF={'off' if args.no_htf else 'on'}) ===")
    if args.split > 0:
        cut = 1 - args.split
        show("IN-SAMPLE", collect_trades(split_data(0, cut), base_qm, **pipe))
        show("OUT-OF-SAMPLE", collect_trades(split_data(cut, 1.0), base_qm, **pipe))
    show("FULL", collect_trades(data, base_qm, **pipe))

    print("\n=== gate ablation (full period) ===")
    show("no gates (QM only)", collect_trades(data, base_qm, require_divergence=False, use_htf=False))
    show("+ divergence", collect_trades(data, base_qm, require_divergence=True, use_htf=False))
    show("+ divergence + HTF", collect_trades(data, base_qm, require_divergence=True, use_htf=True))


if __name__ == "__main__":
    main()
