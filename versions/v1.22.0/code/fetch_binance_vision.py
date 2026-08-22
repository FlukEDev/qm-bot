"""
ดึงข้อมูลแท่งเทียนย้อนหลังลึกๆ จากคลังข้อมูลทางการของ Binance
(https://data.binance.vision) แทนการเรียกผ่าน API

ทำไมต้องใช้: REST API ให้ได้สูงสุด ~1,500 แท่งต่อ request และการไล่ดึงย้อนหลัง
ไปเรื่อยๆ ช้าและติด rate limit ส่วนคลังนี้เก็บเป็นไฟล์ ZIP รายเดือนตั้งแต่ปี 2020
ทำให้ได้ข้อมูลหลายปีในไม่กี่วินาที และเป็นชุดเดียวกันทุกครั้งที่ดึง (reproducible)

    python fetch_binance_vision.py BTCUSDT
    python fetch_binance_vision.py BTCUSDT ETHUSDT SOLUSDT --tf 1h

ผลลัพธ์: data/vision/<SYMBOL>_<TF>.csv พร้อมใช้กับ
    python backtest_full.py --data-dir data/vision
"""

from __future__ import annotations

import argparse
import hashlib
import io
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

# futures = USDⓈ-M perpetuals (ที่บอทเทรดจริง)
# spot    = ตลาด spot ซึ่งบางสินทรัพย์มีประวัติยาวกว่าฝั่ง futures มาก
#           เช่น PAXGUSDT: spot มีตั้งแต่ 2020 ส่วน futures เพิ่งเปิด 2025
#           ใช้ตอนที่ต้องการความยาวของข้อมูลเพื่อ backtest ตัวรูปแบบราคา
_PREFIX = {
    "futures": "data/futures/um/monthly/klines",
    "spot": "data/spot/monthly/klines",
}
BASE_HOST = "https://data.binance.vision"
LIST_HOST = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"


def _paths(market: str) -> tuple[str, str]:
    try:
        prefix = _PREFIX[market]
    except KeyError:
        raise SystemExit(f"--market ต้องเป็น {' หรือ '.join(_PREFIX)} (ได้ {market!r})")
    return f"{BASE_HOST}/{prefix}", LIST_HOST + "?delimiter=/&prefix=" + prefix + "/{sym}/{tf}/"

COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]


def list_months(symbol: str, tf: str, market: str = "futures") -> list[str]:
    _, list_api = _paths(market)
    url = list_api.format(sym=symbol, tf=tf)
    with urllib.request.urlopen(url, timeout=60) as r:
        body = r.read().decode()
    import re
    names = re.findall(rf"{symbol}-{tf}-(\d{{4}}-\d{{2}})\.zip", body)
    return sorted(set(names))


def download_month(symbol: str, tf: str, month: str, verify: bool = True,
                   market: str = "futures") -> pd.DataFrame | None:
    base, _ = _paths(market)
    stem = f"{symbol}-{tf}-{month}.zip"
    url = f"{base}/{symbol}/{tf}/{stem}"
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            blob = r.read()
    except urllib.error.HTTPError as exc:
        print(f"    {month}: HTTP {exc.code} — ข้าม")
        return None

    if verify:
        # Binance ให้ไฟล์ .CHECKSUM มาด้วย — เช็คไว้กันไฟล์เสียระหว่างโหลด
        # ซึ่งถ้าไม่เช็คแล้วไฟล์เพี้ยน ผล backtest จะผิดแบบเงียบๆ
        try:
            with urllib.request.urlopen(url + ".CHECKSUM", timeout=60) as r:
                expect = r.read().decode().split()[0]
            actual = hashlib.sha256(blob).hexdigest()
            if actual != expect:
                print(f"    {month}: checksum ไม่ตรง — ข้าม")
                return None
        except urllib.error.HTTPError:
            pass  # บางเดือนไม่มีไฟล์ checksum

    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        raw = z.read(z.namelist()[0]).decode()

    # ไฟล์รุ่นใหม่มีบรรทัดหัวตาราง รุ่นเก่าไม่มี — ต้องรองรับทั้งสองแบบ
    has_header = raw.lstrip().lower().startswith("open_time")
    df = pd.read_csv(io.StringIO(raw), header=0 if has_header else None,
                     names=None if has_header else COLUMNS)
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df[["open_time", "open", "high", "low", "close"]]


def build(symbol: str, tf: str, out_dir: Path, verify: bool = True,
          workers: int = 12, skip_existing: bool = True,
          market: str = "futures") -> Path | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{symbol}_{tf}.csv"
    if skip_existing and out.exists():
        print(f"  {symbol} {tf}: มีอยู่แล้ว ข้าม ({out})")
        return out

    months = list_months(symbol, tf, market)
    print(f"  {symbol} {tf}: พบ {len(months)} เดือน ({months[0]} ถึง {months[-1]})")

    # ดาวน์โหลดขนานกัน — ไฟล์เหล่านี้เป็น static object บน S3 การไล่ทีละไฟล์
    # กับประวัติ 79 เดือน x หลายสิบเหรียญ ใช้เวลาเป็นชั่วโมงโดยไม่จำเป็น
    with ThreadPoolExecutor(max_workers=workers) as pool:
        frames = [d for d in pool.map(
            lambda m: download_month(symbol, tf, m, verify=verify, market=market), months)
            if d is not None and len(d)]
    if not frames:
        print(f"    ข้าม {symbol} — ดึงข้อมูลไม่ได้เลย")
        return None

    df = pd.concat(frames, ignore_index=True)

    # open_time เป็น ms ในไฟล์เก่า แต่ไฟล์รุ่นใหม่เป็น microseconds
    # ถ้าเดาหน่วยผิด เวลาจะเพี้ยนไปพันเท่าและ resample 4H จะผิดทั้งหมด
    #
    # ต้องดูเป็น "รายแถว" ไม่ใช่ทั้งไฟล์: Binance เปลี่ยนหน่วยกลางคัน สินทรัพย์
    # ที่มีประวัติคร่อมช่วงนั้น (เช่น PAXGUSDT spot 2020-2026) จะมีทั้งสองหน่วย
    # อยู่ในเฟรมเดียวกันหลัง concat การตัดสินหน่วยจากค่า max ของทั้งเฟรมทำให้
    # แถวที่เป็น ms ทั้งหมดกลายเป็นวันที่ปี 1970 แบบเงียบๆ (เจอจริง: 38,057
    # จาก 51,905 แถว) แล้ว sort_values จะดันแถวขยะเหล่านั้นไปไว้ต้นไฟล์
    #
    # ms ปัจจุบัน ~1.8e12 / us ปัจจุบัน ~1.8e15 — เส้นแบ่งที่ 1e14 จึงห่างจาก
    # ทั้งสองฝั่งมากพอที่จะไม่มีทางตัดสินผิด
    t = df["open_time"].astype("int64")
    df["time"] = pd.to_datetime(t.where(t < 1e14, t // 1000), unit="ms", utc=True)

    df = (df.drop(columns=["open_time"])
            .drop_duplicates("time")
            .sort_values("time")
            .set_index("time")[["open", "high", "low", "close"]]
            .astype(float)
            .dropna())
    df.reset_index().to_csv(out, index=False)
    span = (df.index[-1] - df.index[0]).days
    print(f"    -> {out}  {len(df):,} แท่ง  {df.index[0].date()} ถึง {df.index[-1].date()}"
          f"  ({span/365:.1f} ปี)")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="*", help="เช่น BTCUSDT ETHUSDT")
    ap.add_argument("--symbols-file", default=None,
                    help="อ่านรายชื่อเหรียญจากไฟล์ (บรรทัดละตัว) — เลี่ยงปัญหา\n                         shell แยกคำผิดเมื่อรายชื่อยาวมาก")
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--market", default="futures", choices=sorted(_PREFIX),
                    help="futures = USDⓈ-M perp (ค่าเริ่มต้น), spot = ตลาด spot\n                         ใช้ spot เมื่อสินทรัพย์นั้นมีประวัติยาวกว่าฝั่ง futures")
    ap.add_argument("--out", default="data/vision")
    ap.add_argument("--no-verify", action="store_true", help="ข้ามการเช็ค checksum")
    ap.add_argument("--workers", type=int, default=12, help="จำนวนการโหลดพร้อมกัน")
    ap.add_argument("--refresh", action="store_true", help="โหลดใหม่แม้มีไฟล์อยู่แล้ว")
    args = ap.parse_args()

    symbols = list(args.symbols)
    if args.symbols_file:
        symbols += Path(args.symbols_file).read_text().split()
    symbols = [s for s in dict.fromkeys(symbols) if s]
    if not symbols:
        raise SystemExit("ไม่มีรายชื่อเหรียญ — ระบุเป็น argument หรือใช้ --symbols-file")

    label = "futures USDⓈ-M" if args.market == "futures" else "spot"
    print(f"ดึงข้อมูลจาก data.binance.vision ({label}, {args.tf})")
    failed = []
    for sym in symbols:
        # เหรียญเดียวที่มีปัญหา (ชื่อแปลก, ไม่มีข้อมูล, เครือข่ายสะดุด) ไม่ควร
        # ทำให้ทั้งรอบล้ม โดยเฉพาะรอบที่ใช้เวลานานหลายสิบนาที
        try:
            build(sym, args.tf, Path(args.out), verify=not args.no_verify,
                  workers=args.workers, skip_existing=not args.refresh,
                  market=args.market)
        except Exception as exc:
            print(f"  {sym}: ล้มเหลว — {type(exc).__name__}: {str(exc)[:120]}")
            failed.append(sym)
    if failed:
        print(f"\nโหลดไม่สำเร็จ {len(failed)} เหรียญ: {', '.join(failed)}")


if __name__ == "__main__":
    main()
