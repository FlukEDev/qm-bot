"""ตัดแท่งเทียนช่วงที่ "ตลาดจริงปิด" ออกก่อนตรวจจับรูปแบบ

ปัญหา: Binance เปิดให้เทรด perpetual ของทอง/เงิน (XAU, XAG) ตลอด 24/7
แต่ตลาดทองจริงที่อยู่เบื้องหลังปิดสุดสัปดาห์ ราคาบนกระดานจึงยังมีแท่งเทียน
ครบทุกชั่วโมง แต่เป็นแท่งที่แทบไม่ขยับ

วัดจริงบน XAU/USDT (median hourly range เทียบกับค่ากลางของทั้งสัปดาห์):
    จันทร์-ศุกร์ ช่วงตลาดเปิด   100-230%
    ศุกร์ 22:00 UTC ถึง อาทิตย์ 21:00 UTC   17-35%   <- ตายสนิท
    อาทิตย์ 22:00 UTC            189%   <- เอเชียเปิด กลับมาปกติทันที

ทำไมต้องตัดทิ้ง ไม่ใช่แค่ปล่อยผ่าน:
  * ATR(14) ที่คำนวณคร่อมแท่งตายจะถูกกดให้เล็กลงผิดจริง และเกณฑ์ทุกตัวของ
    บอท (min_sweep_atr, min_bos_atr, sl_buffer_atr) วัดเป็น ATR ทั้งหมด
  * pivot ที่เกิดจากการแกว่ง 0.02% บนแท่งวันเสาร์ไม่ใช่ swing จริง แต่ตัว
    ตรวจจับแยกไม่ออก โดยเฉพาะโปรไฟล์ short (pivot=3)
  * max_bars_to_retest นับแท่งตายรวมไปด้วย ทำให้เวลาที่ตลาดเปิดจริงเหลือน้อย
    กว่าที่ตั้งใจไว้มาก (48 จาก 50 แท่งอาจเป็นวันหยุด)

หมายเหตุเรื่อง DST: ตลาดทองอิงเวลาลอนดอน/นิวยอร์กซึ่งขยับปีละ 2 ครั้ง
ขอบของหน้าต่างจึงเลื่อนได้ 1 ชั่วโมง ค่าที่ตั้งไว้กินเผื่อทั้งสองฝั่งแล้ว

ยังไม่ผ่านการ backtest ยืนยัน — XAU เพิ่งเปิดเทรดเดือน ธ.ค. 2025 ข้อมูล
ทั้งหมดให้สัญญาณแค่ 3 ไม้ ซึ่งน้อยเกินกว่าจะสรุปอะไรได้ เหตุผลที่ใช้คือ
เหตุผลเชิงกลไกข้างบน ไม่ใช่ผลการวัด — ต่างจากตัวกรองอื่นในบอทนี้ทุกตัว
"""

from __future__ import annotations

import pandas as pd

# (วันที่ปิด, ชั่วโมง UTC ที่ปิด) -> (วันที่เปิด, ชั่วโมง UTC ที่เปิด)
# 4 = ศุกร์, 6 = อาทิตย์ (ตามการนับของ pandas: จันทร์ = 0)
GOLD_CLOSE = (4, 21)
GOLD_OPEN = (6, 22)


def drop_closed_hours(df: pd.DataFrame,
                      close: tuple[int, int] = GOLD_CLOSE,
                      open_: tuple[int, int] = GOLD_OPEN) -> pd.DataFrame:
    """คืนเฟรมที่ตัดแท่งช่วงตลาดปิดสุดสัปดาห์ออกแล้ว

    index ต้องเป็น DatetimeIndex แบบ UTC (ซึ่งเป็นรูปแบบเดียวกับที่
    fetch_ohlcv และไฟล์จาก data.binance.vision ให้มา)

    การตัดแถวทิ้งทำให้เกิด "ช่อง" ระหว่างศุกร์กับจันทร์ ซึ่งถูกต้องแล้ว —
    กราฟทองมาตรฐาน (เช่นบน TradingView) ก็ไม่มีแท่งวันหยุดเหมือนกัน
    ราคาปิดวันศุกร์ต่อกับราคาเปิดวันจันทร์โดยตรง
    """
    if df.empty:
        return df
    idx = df.index
    dow, hour = idx.dayofweek, idx.hour
    close_dow, close_hr = close
    open_dow, open_hr = open_

    after_close = (dow > close_dow) | ((dow == close_dow) & (hour >= close_hr))
    before_open = (dow < open_dow) | ((dow == open_dow) & (hour < open_hr))
    return df[~(after_close & before_open)]


def session_filter_for(symbol: str, closed_symbols) -> bool:
    """สัญลักษณ์นี้ต้องกรองชั่วโมงตลาดปิดไหม

    เทียบแบบไม่สนรูปแบบ symbol เพราะ config เขียน 'XAU/USDT' แต่ ccxt ใช้
    'XAU/USDT:USDT' — ถ้าเทียบตรงๆ จะไม่มีทางตรงกันเลยและตัวกรองจะเงียบ
    """
    if not closed_symbols:
        return False
    base = symbol.split("/")[0].upper()
    return base in {s.split("/")[0].upper() for s in closed_symbols}
