"""
Standalone scanner: fetch closed bars from Binance USDⓈ-M perpetual futures ->
detect QM -> confirm with RSI divergence -> de-dupe -> render chart -> upload
to R2 -> LINE.

Run it on a schedule matched to the smallest timeframe scanned (hourly for
1H+4H). Scanning more often does not find signals sooner: the detector only
looks at closed bars on purpose, so extra runs just burn exchange API calls.

    python bot.py --config config.yaml           # one pass
    python bot.py --config config.yaml --loop    # stay resident, scan every --interval
                                                  # seconds (normally launched by
                                                  # qmbotctl.py start, not run directly)
    python bot.py --config config.yaml --dry-run # print, do not send or upload
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import time
from pathlib import Path

import pandas as pd
import yaml

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # fine if the user exports env vars some other way

from divergence import attach_divergence
from htf_filter import htf_allows, htf_structure
from logging_setup import setup_logging
from qm_detector import QMConfig, detect_qm, position_size
from state import SignalStore
from universe import display_symbol, top_usdt_pairs

log = logging.getLogger("qm-bot")


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def fetch_ohlcv(exchange, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    """Return a DatetimeIndex(UTC) frame of open/high/low/close, newest last.

    The final row is dropped: it is the bar still forming, and feeding it to
    the detector is the classic way to build a repainting bot.
    """
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["time", "open", "high", "low", "close", "volume"])
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df = df.set_index("time")[["open", "high", "low", "close"]].astype(float).dropna()
    return df.iloc[:-1]


def profiles_for(qm_cfg_by_tf: dict, tf: str) -> list[tuple[str, dict]]:
    """Return [(label, QMConfig kwargs), ...] for one timeframe.

    A timeframe may be scanned with more than one swing-size setting, so the
    same 1H chart yields both short-range patterns (small pivots, ~1-3 days)
    and week-scale ones (large pivots) — the trader decides which to act on
    rather than the bot silently picking a single scale.

    Accepts either shape, so an existing single-profile config keeps working:
        "4h": {pivot_left: 5, ...}                      -> one unnamed profile
        "1h": [{name: short, ...}, {name: wide, ...}]   -> two named profiles
    """
    entry = qm_cfg_by_tf.get(tf, {})
    if isinstance(entry, dict):
        return [(tf, entry)]
    out = []
    for prof in entry:
        prof = dict(prof)
        name = prof.pop("name", None)
        out.append((f"{tf} {name}" if name else tf, prof))
    return out


# --------------------------------------------------------------------------- #
def scan_once(cfg: dict, exchange, store: SignalStore, notifier, dry_run: bool = False) -> int:
    uni_cfg = cfg.get("universe", {})
    symbols = top_usdt_pairs(
        exchange,
        n=uni_cfg.get("top_n", 20),
        always_include=uni_cfg.get("always_include", []),
        cache_path=uni_cfg.get("cache_path", "universe_cache.json"),
        cache_ttl_hours=uni_cfg.get("cache_ttl_hours", 24),
    )
    timeframes = cfg.get("timeframes", ["1h", "4h"])
    qm_cfg_by_tf = cfg.get("qm", {})
    div_cfg = cfg.get("divergence", {})
    htf_cfg = cfg.get("htf_filter", {})
    htf_enabled = htf_cfg.get("enabled", False)
    htf_reference = htf_cfg.get("reference", {})
    risk = cfg.get("risk", {})
    equity = float(risk.get("equity", 10_000))
    risk_pct = float(risk.get("risk_pct", 0.01))
    limit = cfg.get("limit", 500)
    fresh_bars = cfg.get("fresh_bars", 2)
    unit = cfg.get("unit", "coin")
    line_to = cfg.get("line", {}).get("to") or os.environ.get("LINE_TO_USER_ID")
    sent = 0

    for symbol in symbols:  # ccxt-ready perpetual futures symbol, e.g. "BTC/USDT:USDT"
        disp = display_symbol(symbol)  # human-friendly form, e.g. "BTC/USDT" — used
                                        # for everything a person reads (logs, LINE,
                                        # chart title, signal_id / dedupe key)

        # Fetch every configured timeframe up front for this symbol. The HTF
        # filter needs cross-timeframe access (a 1H signal checked against 4H
        # structure) and both timeframes are scanned anyway, so this reuses
        # data instead of fetching 4H twice.
        dfs: dict[str, pd.DataFrame] = {}
        for tf in timeframes:
            try:
                dfs[tf] = fetch_ohlcv(exchange, symbol, tf, limit)
            except Exception as exc:  # a dead feed must not kill the whole scan
                log.warning("fetch failed %s %s: %s", disp, tf, exc)

        for tf in timeframes:
            df = dfs.get(tf)
            if df is None:
                continue

            for label, qm_kwargs in profiles_for(qm_cfg_by_tf, tf):
                qm_cfg = QMConfig(**qm_kwargs)
                # `label` ("1h short" / "1h wide") rather than plain `tf`: it
                # shows the user which view a signal came from, and because
                # signal_id is built from it, the same head bar found by two
                # different profiles stays two separate alerts instead of one
                # silently swallowing the other in the dedupe store.
                signals = detect_qm(df, qm_cfg, symbol=disp, timeframe=label)
                signals = attach_divergence(
                    signals,
                    df,
                    rsi_period=div_cfg.get("rsi_period", 14),
                    min_rsi_diff=div_cfg.get("min_rsi_diff", 2.0),
                    required=div_cfg.get("required", True),
                )

                if htf_enabled and tf in htf_reference:
                    ref_tf = htf_reference[tf]
                    ref_df = dfs.get(ref_tf)
                    if ref_df is not None:
                        structure = htf_structure(
                            ref_df,
                            pivot_left=htf_cfg.get("pivot_left", 3),
                            pivot_right=htf_cfg.get("pivot_right", 3),
                            lookback=htf_cfg.get("lookback", 6),
                        )
                        before = len(signals)
                        for s in signals:
                            s.htf_structure = structure  # tag every signal, even if dropped
                        signals = [s for s in signals if htf_allows(s.direction, structure)]
                        dropped = before - len(signals)
                        if dropped:
                            log.info(
                                "HTF filter %s structure=%s dropped %d/%d %s %s signal(s)",
                                ref_tf, structure, dropped, before, disp, label,
                            )

                # Only alert on patterns that triggered on the most recent closed
                # bars — older ones are history, and the price has moved on.
                fresh_from = len(df) - 1 - fresh_bars
                for s in signals:
                    if s.trigger_idx < fresh_from or not store.is_new(s.signal_id):
                        continue

                    units = position_size(equity, risk_pct, s.entry, s.stop_loss)
                    size_text = f"{units:,.4f} {unit}"
                    log.info(
                        "SIGNAL %s %s %s entry=%.4f RR=%.2f span=%db divergence=%s htf=%s",
                        disp, label, s.direction, s.entry, s.risk_reward,
                        s.trigger_idx - s.ls_idx,
                        getattr(s, "divergence_confirmed", None),
                        getattr(s, "htf_structure", None),
                    )

                    if dry_run:
                        print(s.to_dict())
                    else:
                        from chart_renderer import render_signal
                        from chart_uploader import upload_chart

                        safe = s.signal_id.replace("|", "_").replace("/", "-").replace(" ", "-")
                        png = render_signal(df, s, out_path=f"/tmp/{safe}.png")
                        chart_url = upload_chart(png)
                        notifier.send_signal(s, to=line_to, chart_url=chart_url,
                                             size_text=size_text)

                    store.mark(s)
                    sent += 1
    return sent


def _seconds_until_aligned(interval: int, buffer_sec: int = 60) -> float:
    """Seconds to sleep so the next scan lands `buffer_sec` seconds after the
    next wall-clock boundary of `interval` seconds — e.g. interval=3600
    (1h bars) lands at :01 past every hour, not just "3600s after whenever
    this process happened to start."

    This matters because a flat `time.sleep(interval)` drifts to whatever
    minute the loop originally started at and stays there: a bar that closes
    at HH:00:00 might not get scanned until HH:47 depending on that drift,
    which can push a real signal outside `fresh_bars` and cause it to be
    silently skipped. Using time.time() (UTC epoch) keeps this correct
    regardless of the machine's local timezone setting.
    """
    now = time.time()
    next_boundary = (now // interval + 1) * interval
    return (next_boundary + buffer_sec) - now


def _build_exchange(cfg: dict):
    import ccxt

    # binanceusdm = Binance USDⓈ-M futures (linear, USDT-margined perpetuals) —
    # a distinct ccxt exchange class from spot `binance`, with its own unified
    # symbol format ("BTC/USDT:USDT") handled by universe.to_perp_symbol().
    ex_name = cfg.get("source", {}).get("exchange", "binanceusdm")
    return getattr(ccxt, ex_name)({"enableRateLimit": True})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=3600)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.loop:
        # Running as a background daemon (spawned detached by qmbotctl.py) —
        # the only supported way to stop this process is `qmbotctl.py stop`
        # (SIGTERM, handled below by simply falling out of the loop). SIGINT
        # is ignored so a Ctrl+C in whatever terminal/shell/session it happens
        # to reach — including edge cases where process-group detachment
        # doesn't fully isolate it — can't kill a bot that's meant to keep
        # scanning unattended between hourly runs.
        signal.signal(signal.SIGINT, signal.SIG_IGN)

    cfg = yaml.safe_load(Path(args.config).read_text())
    setup_logging(log_dir=cfg.get("log_dir", "logs"))
    store = SignalStore(cfg.get("state_db", "signals.db"))
    exchange = _build_exchange(cfg)

    notifier = None
    if not args.dry_run:
        from line_notifier import LineNotifier

        token = cfg.get("line", {}).get("channel_access_token") or os.environ.get(
            "LINE_CHANNEL_ACCESS_TOKEN"
        )
        notifier = LineNotifier(token)

    while True:
        try:
            n = scan_once(cfg, exchange, store, notifier, dry_run=args.dry_run)
            log.info("scan complete — %d new signal(s)", n)
        except Exception:
            log.exception("scan failed")
        if not args.loop:
            break
        sleep_for = _seconds_until_aligned(args.interval)
        log.info("next scan in %.0fs (aligned to :01 past each %dm boundary)",
                  sleep_for, args.interval // 60)
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
