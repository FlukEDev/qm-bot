"""
สรุปเทรนด์ Bitcoin รายวัน ส่งเข้า LINE

แยกจาก bot.py เพราะเป็นคนละงานคนละจังหวะเวลา: bot.py เฝ้าหาสัญญาณเข้าเทรด
ทุกชั่วโมง ส่วนไฟล์นี้รายงานภาพรวมวันละครั้ง ไม่มีจุดเข้า/SL/TP ให้เทรด
เป็นแค่บริบทว่าตอนนี้ตลาดอยู่ตรงไหน

ทุกตัวเลขคำนวณจากราคาที่ดึงจาก Binance โดยตรง ไม่มีการเรียกบริการภายนอกอื่น
จึงไม่มีค่าใช้จ่ายเพิ่มและไม่มีอะไรพังจากฝั่งผู้ให้บริการที่สาม

    python daily_report.py --dry-run     # พิมพ์ออกจอ ไม่ส่งเข้า LINE
    python daily_report.py               # ส่งจริง
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import pandas as pd
import yaml

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from divergence import rsi
from htf_filter import htf_structure
from logging_setup import setup_logging
from qm_detector import atr, alternate, find_pivots
from timeutil import format_bangkok, BANGKOK

log = logging.getLogger("qm-daily")

TREND_TH = {
    "bullish": ("ขาขึ้น", "#26A69A"),
    "bearish": ("ขาลง", "#EF5350"),
    "neutral": ("ไซด์เวย์", "#8C8C8C"),
}


def fetch(exchange, symbol: str, tf: str, limit: int) -> pd.DataFrame:
    raw = exchange.fetch_ohlcv(symbol, timeframe=tf, limit=limit)
    df = pd.DataFrame(raw, columns=["time", "open", "high", "low", "close", "volume"])
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df = df.set_index("time")[["open", "high", "low", "close"]].astype(float).dropna()
    return df.iloc[:-1]  # ตัดแท่งที่ยังไม่ปิด เหมือน bot.py


def pct(a: float, b: float) -> float:
    return (a - b) / b * 100 if b else 0.0


def nearest_levels(df: pd.DataFrame, price: float, pivot: int = 5) -> tuple[float | None, float | None]:
    """หาแนวต้านที่ใกล้ที่สุดเหนือราคา และแนวรับที่ใกล้ที่สุดใต้ราคา
    จาก swing pivot ที่ยืนยันแล้วบนกราฟรายวัน"""
    pivots = alternate(find_pivots(df, pivot, pivot))
    highs = [p.price for p in pivots if p.kind == "high" and p.price > price]
    lows = [p.price for p in pivots if p.kind == "low" and p.price < price]
    return (min(highs) if highs else None, max(lows) if lows else None)


def build_report(exchange, symbol: str = "BTC/USDT:USDT") -> dict:
    d1 = fetch(exchange, symbol, "1d", 250)
    h4 = fetch(exchange, symbol, "4h", 250)
    h1 = fetch(exchange, symbol, "1h", 250)

    price = float(h1["close"].iloc[-1])
    chg24 = pct(price, float(h1["close"].iloc[-25])) if len(h1) > 25 else 0.0
    chg7d = pct(price, float(h1["close"].iloc[-169])) if len(h1) > 169 else 0.0

    rsi_d = float(rsi(d1, 14).iloc[-1])
    rsi_4h = float(rsi(h4, 14).iloc[-1])

    # ความผันผวนวันนี้เทียบกับ 90 วันที่ผ่านมา — บอกว่า "แรงผิดปกติไหม"
    atr_d = atr(d1, 14)
    atr_now = float(atr_d.iloc[-1])
    atr_avg = float(atr_d.iloc[-90:].mean())
    atr_pct = atr_now / price * 100
    vol_ratio = atr_now / atr_avg if atr_avg else 1.0

    res, sup = nearest_levels(d1, price)

    return {
        "symbol": "BTC/USDT",
        "price": price,
        "chg24": chg24,
        "chg7d": chg7d,
        "trend_1d": htf_structure(d1, 5, 5, lookback=6),
        "trend_4h": htf_structure(h4, 5, 5, lookback=6),
        "rsi_d": rsi_d,
        "rsi_4h": rsi_4h,
        "atr_pct": atr_pct,
        "vol_ratio": vol_ratio,
        "resistance": res,
        "support": sup,
        "asof": str(h1.index[-1]),
    }


# --------------------------------------------------------------------------- #
def _fmt_price(x: float) -> str:
    return f"{x:,.0f}" if x >= 1000 else f"{x:,.2f}"


def _rsi_note(v: float) -> str:
    if v >= 70:
        return "ซื้อมากเกิน"
    if v <= 30:
        return "ขายมากเกิน"
    return "ปกติ"


def flex_report(r: dict, disclaimer: str) -> dict:
    from line_notifier import _row

    up = r["chg24"] >= 0
    accent = "#26A69A" if up else "#EF5350"
    t1d, c1d = TREND_TH.get(r["trend_1d"], ("-", "#8C8C8C"))
    t4h, c4h = TREND_TH.get(r["trend_4h"], ("-", "#8C8C8C"))

    vol_note = ("สูงกว่าปกติ" if r["vol_ratio"] >= 1.25
                else "ต่ำกว่าปกติ" if r["vol_ratio"] <= 0.8 else "ปกติ")

    body = [
        _row("ราคา", _fmt_price(r["price"]), "#FFFFFF", bold=True),
        _row("24 ชม.", f"{r['chg24']:+.2f}%", accent, bold=True),
        _row("7 วัน", f"{r['chg7d']:+.2f}%", "#26A69A" if r["chg7d"] >= 0 else "#EF5350"),
        {"type": "separator", "margin": "md", "color": "#333333"},
        _row("เทรนด์ 1D", t1d, c1d, bold=True),
        _row("เทรนด์ 4H", t4h, c4h),
        _row("RSI 1D", f"{r['rsi_d']:.0f} ({_rsi_note(r['rsi_d'])})", "#DDDDDD"),
        _row("RSI 4H", f"{r['rsi_4h']:.0f} ({_rsi_note(r['rsi_4h'])})", "#DDDDDD"),
        _row("ผันผวน", f"{r['atr_pct']:.1f}% ({vol_note})", "#DDDDDD"),
    ]
    if r["resistance"]:
        body.append(_row("แนวต้าน", f"{_fmt_price(r['resistance'])} "
                                     f"({pct(r['resistance'], r['price']):+.1f}%)", "#EF5350"))
    if r["support"]:
        body.append(_row("แนวรับ", f"{_fmt_price(r['support'])} "
                                    f"({pct(r['support'], r['price']):+.1f}%)", "#26A69A"))
    body.append(_row("ณ เวลา", f"{format_bangkok(r['asof'])} ICT", "#8C8C8C"))

    return {
        "type": "flex",
        "altText": f"สรุป BTC {_fmt_price(r['price'])} ({r['chg24']:+.2f}% 24ชม.) — {t1d}",
        "contents": {
            "type": "bubble", "size": "mega",
            "header": {
                "type": "box", "layout": "vertical", "backgroundColor": accent,
                "paddingAll": "12px",
                "contents": [
                    {"type": "text", "text": "สรุปเทรนด์ Bitcoin",
                     "color": "#FFFFFF", "weight": "bold", "size": "lg"},
                    {"type": "text", "text": format_bangkok(r["asof"], "%A %d/%m/%Y"),
                     "color": "#FFFFFF", "size": "sm"},
                ],
            },
            "body": {"type": "box", "layout": "vertical", "backgroundColor": "#1E222D",
                     "spacing": "sm", "paddingAll": "14px", "contents": body},
            "footer": {"type": "box", "layout": "vertical", "backgroundColor": "#1E222D",
                       "paddingAll": "10px",
                       "contents": [{"type": "text", "text": disclaimer, "size": "xxs",
                                     "color": "#6E6E6E", "wrap": True}]},
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    setup_logging(log_dir=cfg.get("log_dir", "logs"))

    import ccxt

    ex = getattr(ccxt, cfg.get("source", {}).get("exchange", "binanceusdm"))(
        {"enableRateLimit": True})
    r = build_report(ex)
    log.info("daily report BTC price=%.0f 24h=%+.2f%% trend1d=%s rsi=%.0f",
             r["price"], r["chg24"], r["trend_1d"], r["rsi_d"])

    disclaimer = "สรุปอัตโนมัติเพื่อการศึกษา ไม่ใช่คำแนะนำการลงทุน"
    msg = flex_report(r, disclaimer)

    if args.dry_run:
        for row in msg["contents"]["body"]["contents"]:
            if row.get("type") == "box":
                print("  " + " | ".join(c["text"] for c in row["contents"]))
        print(f"\naltText: {msg['altText']}")
        return

    from line_notifier import LineNotifier

    token = cfg.get("line", {}).get("channel_access_token") or os.environ.get(
        "LINE_CHANNEL_ACCESS_TOKEN")
    to = cfg.get("line", {}).get("to") or os.environ.get("LINE_TO_USER_ID")
    LineNotifier(token).push(to, [msg])
    log.info("daily report sent to LINE")


if __name__ == "__main__":
    main()
