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

BASE = "https://data.binance.vision/data/futures/um/monthly/klines"
LIST_API = ("https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
            "?delimiter=/&prefix=data/futures/um/monthly/klines/{sym}/{tf}/")

COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]


def list_months(symbol: str, tf: str) -> list[str]:
    url = LIST_API.format(sym=symbol, tf=tf)
    with urllib.request.urlopen(url, timeout=60) as r:
        body = r.read().decode()
    import re
    names = re.findall(rf"{symbol}-{tf}-(\d{{4}}-\d{{2}})\.zip", body)
    return sorted(set(names))


def download_month(symbol: str, tf: str, month: str, verify: bool = True) -> pd.DataFrame | None:
    stem = f"{symbol}-{tf}-{month}.zip"
    url = f"{BASE}/{symbol}/{tf}/{stem}"
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
          workers: int = 12, skip_existing: bool = True) -> Path | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{symbol}_{tf}.csv"
    if skip_existing and out.exists():
        print(f"  {symbol} {tf}: มีอยู่แล้ว ข้าม ({out})")
        return out

    months = list_months(symbol, tf)
    print(f"  {symbol} {tf}: พบ {len(months)} เดือน ({months[0]} ถึง {months[-1]})")

    # ดาวน์โหลดขนานกัน — ไฟล์เหล่านี้เป็น static object บน S3 การไล่ทีละไฟล์
    # กับประวัติ 79 เดือน x หลายสิบเหรียญ ใช้เวลาเป็นชั่วโมงโดยไม่จำเป็น
    with ThreadPoolExecutor(max_workers=workers) as pool:
        frames = [d for d in pool.map(
            lambda m: download_month(symbol, tf, m, verify=verify), months)
            if d is not None and len(d)]
    if not frames:
        print(f"    ข้าม {symbol} — ดึงข้อมูลไม่ได้เลย")
        return None

    df = pd.concat(frames, ignore_index=True)

    # open_time เป็น ms ในไฟล์เก่า แต่บางไฟล์รุ่นใหม่เป็น microseconds
    # ถ้าเดาหน่วยผิด เวลาจะเพี้ยนไปพันเท่าและ resample 4H จะผิดทั้งหมด
    unit = "us" if df["open_time"].astype("int64").max() > 1e15 else "ms"
    df["time"] = pd.to_datetime(df["open_time"].astype("int64"), unit=unit, utc=True)

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

    print(f"ดึงข้อมูลจาก data.binance.vision (futures USDⓈ-M, {args.tf})")
    failed = []
    for sym in symbols:
        # เหรียญเดียวที่มีปัญหา (ชื่อแปลก, ไม่มีข้อมูล, เครือข่ายสะดุด) ไม่ควร
        # ทำให้ทั้งรอบล้ม โดยเฉพาะรอบที่ใช้เวลานานหลายสิบนาที
        try:
            build(sym, args.tf, Path(args.out), verify=not args.no_verify,
                  workers=args.workers, skip_existing=not args.refresh)
        except Exception as exc:
            print(f"  {sym}: ล้มเหลว — {type(exc).__name__}: {str(exc)[:120]}")
            failed.append(sym)
    if failed:
        print(f"\nโหลดไม่สำเร็จ {len(failed)} เหรียญ: {', '.join(failed)}")


if __name__ == "__main__":
    main()
