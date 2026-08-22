"""
คุณภาพของแท่งเทียนที่จุดสำคัญของ QM — เนื้อเทียน (body) กับไส้เทียน (wick)

QM ต้องการสองอย่างที่ตรงข้ามกันโดยสิ้นเชิง และการแยกให้ออกคือความต่าง
ระหว่าง "รูปแบบจริง" กับ "รูปทรงที่บังเอิญคล้าย":

  HEAD  ควรเป็น 'ไส้กวาด' — แทงเลย LS ขึ้นไปเก็บ stop แล้วถูกปฏิเสธกลับลงมา
        ถ้าเนื้อเทียนปิดเหนือ LS แปลว่านั่นคือการเบรกจริง ไม่ใช่การกวาด
        เรื่องเล่าทั้งหมดของ QM พังทันที

  BOS   ควรเป็น 'เนื้อปิดทะลุ' — ต้องมีแท่งปิดเลย L1 ลงไปจริง
        ถ้าแค่ไส้แทงลงไปแตะแล้วเด้งกลับ นั่นคือการกวาดฝั่งล่าง
        ไม่ใช่การทำลายโครงสร้าง

ตัวเลขจากงานวิจัย price action: แท่งที่ปิดเนื้อเลยระดับมีโอกาสไปต่อ 59-64%
ส่วนแท่งที่ไส้ทะลุแล้วปิดกลับเข้ามาเหลือ 25-27% ซึ่งต่ำกว่าค่าฐาน ~37%
กล่าวคือ 'ไส้ทะลุแล้วปิดกลับ' เป็นสัญญาณกลับตัว ไม่ใช่สัญญาณไปต่อ

วัดจริงบน 98 เหรียญ / 2.59 ล้านแท่ง 1H (out-of-sample):
    ไม่กรอง                  1578 ไม้  win 45.8%  +0.634R  PF 2.02
    BOS เนื้อปิดที่แท่ง L2    462 ไม้  win 50.6%  +0.966R  PF 2.74
ได้ผลกับทั้งสองโปรไฟล์ (short +0.634->+0.979, wide +0.631->+0.897)

แยกจาก qm_detector.py ด้วยเหตุผลเดียวกับ divergence.py — ตัวตรวจจับ
โครงสร้างยังเป็นฟังก์ชันบริสุทธิ์ของ OHLCV ส่วนนี่คือ gate ที่มาทีหลัง
"""

from __future__ import annotations

import pandas as pd


def tag_candle_quality(signals: list, df: pd.DataFrame) -> list:
    """ติดค่าคุณภาพแท่งเทียนให้ทุกสัญญาณ (ไม่กรองอะไรออก)

    ติดให้ทุกตัวไม่ว่าจะผ่านหรือไม่ผ่าน เพื่อให้ผู้เรียกเลือกได้เองว่าจะ
    กรองทิ้ง หรือแค่แสดงให้คนตัดสินใจ
    """
    if not signals:
        return signals
    o = df["open"].to_numpy()
    h = df["high"].to_numpy()
    lo = df["low"].to_numpy()
    c = df["close"].to_numpy()
    n = len(c)

    for s in signals:
        bear = s.direction == "bearish"
        hi_i, l2_i = s.head_idx, s.l2_idx
        if hi_i >= n or l2_i >= n:
            s.head_swept_by_wick = None
            s.head_wick_frac = None
            s.bos_body_close = None
            continue

        # HEAD: เนื้อเทียนปิดเลย LS ไปหรือไม่ (ปิดเลย = เบรกจริง ไม่ใช่กวาด)
        s.head_swept_by_wick = bool(c[hi_i] <= s.ls_price) if bear else bool(c[hi_i] >= s.ls_price)

        # สัดส่วนไส้ด้านที่กวาด เทียบความสูงทั้งแท่ง — ไว้ให้คนดูประกอบ
        rng = max(h[hi_i] - lo[hi_i], 1e-12)
        wick = (h[hi_i] - max(o[hi_i], c[hi_i])) if bear else (min(o[hi_i], c[hi_i]) - lo[hi_i])
        s.head_wick_frac = float(wick / rng)

        # BOS: แท่งที่ทำ L2 ปิดเนื้อเลย L1 ลงไปจริงไหม
        # ใช้แท่ง L2 เองไม่ใช่ "แท่งใดก็ได้ในขา" เพราะวัดแล้วเข้มกว่าและ
        # ให้ผลดีกว่าชัดเจน (+0.966R เทียบกับ +0.721R เมื่อยอมรับแท่งใดก็ได้)
        s.bos_body_close = bool(c[l2_i] < s.l1_price) if bear else bool(c[l2_i] > s.l1_price)

    return signals


def passes_candle_gate(signal, require_bos_body: bool = True,
                       require_head_wick: bool = False) -> bool:
    """สัญญาณผ่านเกณฑ์คุณภาพแท่งเทียนหรือไม่

    ค่าที่วัดไม่ได้ (None) ถือว่าผ่าน — ไม่ควรทิ้งสัญญาณเพราะข้อมูลไม่พอ
    ให้ตัดสิน นั่นเป็นคนละเรื่องกับการที่มันไม่ผ่านเกณฑ์จริงๆ
    """
    if require_bos_body and getattr(signal, "bos_body_close", None) is False:
        return False
    if require_head_wick and getattr(signal, "head_swept_by_wick", None) is False:
        return False
    return True
