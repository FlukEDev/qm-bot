# QM Pattern Signal Bot

**[English](README.md) · [ภาษาไทย](#ภาษาไทย)**

บอทสแกนหารูปแบบกลับตัว **QM (Quasimodo)** บน Binance USDⓈ-M perpetual futures
ยืนยันด้วยโมเมนตัม RSI แล้วส่งเข้า **LINE** พร้อมกราฟที่วาดเส้นให้ครบ

บอทบอกว่าจุดน่าสนใจอยู่ตรงไหน — **ไม่ได้ส่งคำสั่งซื้อขาย และไม่ใช่คำแนะนำการลงทุน**
คุณเป็นคนตัดสินใจเองว่าจะเข้าไม้ไหน

<a name="ภาษาไทย"></a>

---

## บอททำอะไร

ทุกชั่วโมง หลังแท่งเทียนปิด 1 นาที บอทจะ:

1. ดึงเหรียญ futures ที่วอลุ่มสูงสุด N อันดับจาก Binance (กรอง leveraged token,
   คู่ stablecoin และหุ้น/ทองแบบ tokenized ออกแล้ว)
2. หาโครงสร้าง QM ในแต่ละเหรียญ — Left Shoulder → Head (กวาด liquidity) →
   Break of Structure → ราคากลับมาเทสที่ระดับ QM
3. ตรวจว่าการเด้งกลับมาเทสนั้น**ไม่มีแรง** (ดู RSI บนขา BOS→RS)
4. ให้เกรด **A / B / C** แล้วส่งเข้า LINE พร้อมจุดเข้า จุดตัดขาดทุน เป้าหมาย 2 จุด
   อัตราส่วนเสี่ยงต่อผลตอบแทน ขนาดไม้ และรูปกราฟ

```
SELL  ·  QM                    ┌─ พาเนลราคา: LS / L1 / HEAD / BOS / RS
BTC/USDT   1h wide             │  พร้อมเส้น entry, stop, TP1, TP2
─────────────────────────      │
Entry (QML)      63,450.00     └─ พาเนล RSI: ตัววัดโมเมนตัม 2 เส้น
Stop Loss        64,092.98
TP1              61,297.00
TP2              59,632.29
R:R              1 : 3.35
เกรด A           สูง (RSI +23)
Size             0.1555 BTC
Time             07/07 20:00 ICT
```

มีสรุปภาพรวม Bitcoin รายวันแยกอีกฉบับ (ราคา, เทรนด์ 1D/4H, RSI, ความผันผวน,
แนวรับ-แนวต้านที่ใกล้ที่สุด) ส่งทุกเช้า 10:00 น. ตามเวลาไทย

## ทำไมต้อง QM

QM เป็นรูปแบบกลับตัวที่มี 2 เรื่องเกิดพร้อมกัน: **Head แทงขึ้นไปกวาด liquidity**
เหนือ Left Shoulder แล้วราคา**ทำลายโครงสร้าง** ด้วยการหลุด low เดิมลงมา
ถ้าไม่มีการทำลายโครงสร้างนี้ มันก็เป็นแค่ Head & Shoulders ธรรมดาที่ต้องรอเบรก
neckline ก่อน — การหลุดโครงสร้างคือสิ่งที่ทำให้เข้าไม้ที่ระดับ QM ได้เลย
โดยตั้ง stop ได้แคบกว่า

## สิ่งที่ทดสอบแล้วจริง

Backtest บนแท่งเทียน 1H จำนวน **2.6 ล้านแท่ง** — 99 เหรียญ ย้อนหลังสูงสุด 6.6 ปี
จากคลังข้อมูลทางการของ Binance พร้อมแบ่ง in-sample / out-of-sample:

| โปรไฟล์ | in-sample | out-of-sample |
|---|---|---|
| `1h short` (swing เล็ก 0.5–3 วัน) | n=3027, +0.592R, PF 1.94 | n=1428, +0.634R, PF 2.04 |
| `1h wide` (swing ใหญ่ 3–10 วัน) | n=416, +0.290R, PF 1.41 | n=150, +0.631R, PF 1.93 |

Win rate อยู่ราว 45% ซึ่ง**เป็นเรื่องปกติและตั้งใจให้เป็นแบบนั้น** — เพราะมีตัวกรอง
RR (`min_rr: 1.5`) จึงไม่จำเป็นต้องถูกเกินครึ่งก็ยังกำไรได้

**อ่านตัวเลขนี้ด้วยความระมัดระวัง** — backtest สมมติว่าโดน stop ก่อนเสมอเมื่อแท่ง
เดียวครอบทั้ง stop และเป้าหมาย, คิดค่าธรรมเนียมและ slippage แล้ว, และไม่มองอนาคต
แต่มันยังจำลอง funding rate, การจับคู่คำสั่งจริง หรือวิธีเทรดของคุณเองไม่ได้
อีกทั้งรายชื่อเหรียญคือเหรียญที่วอลุ่มสูง**ในวันนี้** เหรียญที่ตายไปแล้วจึงไม่อยู่ในชุดทดสอบ
(survivorship bias) **ผลในอดีตไม่ได้รับประกันอนาคต**

ทดสอบซ้ำเองได้:

```bash
python fetch_binance_vision.py BTCUSDT ETHUSDT SOLUSDT
python backtest_full.py --data-dir data/vision --split 0.3
```

## สิ่งที่ต้องมี

- Python 3.11 ขึ้นไป
- **LINE Official Account** ที่เปิด Messaging API (แผนฟรี 300 ข้อความ/เดือน)
- **Cloudflare R2** หรือ S3-compatible storage อื่นที่เปิดสาธารณะได้ สำหรับเก็บรูปกราฟ
- ถ้าอยากให้รัน 24 ชม. ต้องมี VM เล็กๆ ที่เปิดตลอด

**ไม่ต้องใช้ API key ของ exchange** เพราะบอทอ่านข้อมูลตลาดสาธารณะอย่างเดียว
ไม่แตะบัญชีเทรดของคุณเลย

## ติดตั้ง

### 1. ติดตั้งโปรแกรม

```bash
git clone https://github.com/FlukEDev/qm-bot.git
cd qm-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. ตั้งค่า LINE Official Account

1. สร้าง OA ที่ [LINE Official Account Manager](https://manager.line.biz/)
2. ที่ [LINE Developers Console](https://developers.line.biz/console/):
   สร้าง Provider → สร้าง **Messaging API channel** ผูกกับ OA นั้น
3. ออก **channel access token** แบบ long-lived → ใส่ใน `.env` ที่
   `LINE_CHANNEL_ACCESS_TOKEN`
4. ที่ OA Manager → Settings → Response settings ให้**ปิด** auto-reply
   และ greeting message
5. แอด OA เป็นเพื่อนในมือถือ

### 3. หา userId ของตัวเอง

บอทส่งข้อความหาคุณโดยตรง แต่ LINE ไม่มี API ให้ค้นหา userId — ต้องได้จาก
webhook เท่านั้น

```bash
python webhook_capture.py                       # รันที่พอร์ต 8000
cloudflared tunnel --url http://localhost:8000   # หรือ ngrok http 8000
```

เอา URL ของ tunnel ต่อท้ายด้วย `/line-webhook` ไปใส่เป็น Webhook URL ในคอนโซล
กด **Verify** เปิด **Use webhook** แล้วทักแชทหา OA — userId ของคุณ (ขึ้นต้นด้วย `U`)
จะขึ้นในเทอร์มินัล เอาไปใส่ `.env` ที่ `LINE_TO_USER_ID` แล้วปิดสคริปต์กับ tunnel ได้เลย
ไม่ต้องใช้อีก เพราะบอทมีหน้าที่ส่งออกอย่างเดียว

### 4. ที่เก็บรูปกราฟ

LINE เป็นฝ่ายไปดึงรูปเองผ่าน HTTPS อัปโหลดตรงเข้า API ไม่ได้ รูปจึงต้องมี URL สาธารณะ

1. Cloudflare → R2 → สร้าง bucket แล้วเปิด public access
2. สร้าง API token ที่จำกัดสิทธิ์เฉพาะ bucket นั้น (Object Read & Write)
3. กรอก `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`,
   `R2_BUCKET`, `R2_PUBLIC_BASE_URL` ใน `.env`

ใช้ S3-compatible เจ้าอื่นก็ได้ — ดู `chart_uploader.py` มีแค่ ~40 บรรทัด

### 5. ทดสอบก่อนส่งจริง

```bash
python bot.py --config config.yaml --dry-run
```

จะดึงรายชื่อเหรียญ สแกนทุกตัว แล้วพิมพ์สิ่งที่จะส่งออกมาให้ดู — **ไม่ส่ง LINE
ไม่อัปโหลดรูป ไม่บันทึกสถานะ** ควรรันอันนี้ก่อนเสมอ

จากนั้นลองส่งจริง 1 ครั้ง:

```bash
python bot.py --config config.yaml
```

## การใช้งาน

```bash
python qmbotctl.py start          # รันเบื้องหลังทุกชั่วโมง พร้อมแสดง log สด
python qmbotctl.py start --no-attach
python qmbotctl.py status
python qmbotctl.py logs -f
python qmbotctl.py stop
```

กด Ctrl+C แค่ออกจากหน้าจอ log — **บอทยังทำงานต่อ** ถ้าใช้ macOS ใส่
`--keep-awake` เพื่อกันเครื่องหลับระหว่างรอสแกน (แต่กันการปิดฝาโน้ตบุ๊กไม่ได้)

Log เก็บที่ `logs/YYYY-MM-DD.log` แยกไฟล์ตามวัน

**ถ้าอยากให้รันตลอด 24 ชม.**: ในโฟลเดอร์ `deploy/` มี systemd unit และสคริปต์
ติดตั้งสำหรับ Linux VM ให้แล้ว — **ข้อควรระวัง: Binance บล็อค IP จากสหรัฐฯ
(ตอบ HTTP 451)** ดังนั้นอย่าเลือก region ในอเมริกา

## การปรับแต่ง

ทุกอย่างอยู่ใน `config.yaml` และแต่ละค่ามีผล backtest กำกับไว้ในคอมเมนต์
ค่าที่ควรรู้จัก:

| ค่า | ควบคุมอะไร |
|---|---|
| `universe.top_n` | สแกนกี่เหรียญ |
| `qm.1h[].pivot_left/right` | ขนาด swing — 3 = รูปแบบเล็ก, 15 = รูปแบบระดับสัปดาห์ |
| `qm.1h[].max_bars_to_retest` | ยอมรอ retest ได้นานกี่แท่ง |
| `qm.1h[].min_rr` | **ตัวกรองที่ทรงพลังที่สุด** ถ้าสัญญาณเยอะเกินให้ปรับขึ้นก่อน |
| `divergence.bos_rs_max` | การเด้งกลับต้องอ่อนแรงแค่ไหน (แยกตามโปรไฟล์) |
| `divergence.last_swing.min_diff` | ตั้ง `5` เพื่อรับเฉพาะเกรด A |
| `daily_report.quota_throttle` | ลดสรุปรายวันเหลือสัปดาห์ละครั้งเมื่อโควตา LINE เกิน 50% |

Timeframe 1H จะถูกสแกน **2 โปรไฟล์พร้อมกัน** (swing เล็กและ swing ใหญ่) เพราะ
ขนาด swing ที่ดีที่สุด**ไม่คงที่** — ช่วง 2020–2024 swing เล็กชนะ แต่ช่วง 2024–2026
swing ใหญ่ชนะ การรันทั้งสองแบบจึงนิ่งกว่าการเดิมพันกับแบบใดแบบหนึ่ง

### จำนวนสัญญาณกับโควตา LINE

ค่าเริ่มต้นที่ 100 เหรียญจะได้ราว **170 สัญญาณ/เดือน** บวกสรุปรายวัน 30 =
ประมาณ 200 จากโควตาฟรี 300 ถ้ารู้สึกว่าเบียดไป: เพิ่ม `min_rr`, ลด
`universe.top_n`, หรือตั้ง `last_swing.min_diff: 5` เพื่อรับเฉพาะเกรด A
(เหลือ ~33/เดือน)

## โครงสร้างไฟล์

```
bot.py                 วนสแกนทุกชั่วโมง
qm_detector.py         ตรวจจับโครงสร้าง QM (ฟังก์ชันบริสุทธิ์ ไม่มี I/O)
divergence.py          ยืนยันด้วย RSI + ให้เกรด A/B/C
htf_filter.py          ตัวกรองแนวโน้ม TF ใหญ่ (ปิดไว้โดย default)
universe.py            เลือกเหรียญที่จะสแกน
chart_renderer.py      วาดกราฟ PNG
chart_uploader.py      อัปโหลดขึ้น S3/R2
line_notifier.py       ส่งผ่าน LINE Messaging API
daily_report.py        สรุป Bitcoin รายวัน
qmbotctl.py            start/stop/status/logs
backtest_full.py       backtest ทั้ง pipeline
fetch_binance_vision.py  ดึงข้อมูลย้อนหลังลึกจาก data.binance.vision
make_version.py        เก็บ snapshot เวอร์ชัน -> versions/
deploy/                systemd unit + สคริปต์ติดตั้งบน VM
```

โฟลเดอร์ `versions/` เก็บ snapshot และบันทึกการเปลี่ยนแปลงของทุกครั้งที่แก้บอท
**รวมถึงการเปลี่ยนแปลงที่ภายหลังพบว่าผิดและถูกยกเลิก พร้อมเหตุผล**

## ข้อจำกัดที่ต้องรู้

- **ไม่ใช่บอทเทรดอัตโนมัติ** — ส่งข้อความอย่างเดียว ไม่มีการส่งคำสั่งซื้อขาย
- **ไม่ใช่คำแนะนำการลงทุน** — ทุกข้อความมี disclaimer กำกับ และบรรทัดนี้ก็เช่นกัน
- **คริปโตเท่านั้น** — ถ้าจะทำทอง/ค่าเงินต้องใช้แหล่งข้อมูลอื่นและจัดการ gap
  วันหยุดสุดสัปดาห์เพิ่ม
- **รูปแบบกลับตัวพลาดบ่อยเป็นเรื่องปกติ** — win rate ~45% คือสิ่งที่ออกแบบไว้
  ไม่ใช่ข้อผิดพลาด
- **edge อาจไม่คงอยู่ตลอดไป** — วัดจากข้อมูลในอดีต ตลาดเปลี่ยนได้เสมอ
- **คุณเสี่ยงด้วยเงินของคุณเอง** — เริ่มจากเทรดกระดาษก่อน ลงไม้เล็กๆ และใช้สัญญาณ
  เป็นแค่ข้อมูลประกอบหนึ่งอย่าง ไม่ใช่คำตอบสุดท้าย

## สัญญาอนุญาต

MIT — ดู [LICENSE](LICENSE) เอาไปใช้ ดัดแปลง ต่อยอดได้เลย **ไม่มีการรับประกันใดๆ
ทั้งสิ้น** ถ้าขาดทุนถือเป็นความรับผิดชอบของผู้ใช้เอง
