# บอทสัญญาณ QM Pattern — คริปโต Futures (Binance) → LINE

บอทนี้สแกนสัญญา **USDⓈ-M perpetual futures** บน Binance (BTC, ETH + เหรียญตามวอลุ่ม
ย้อนหลัง 24 ชม. อีก N ตัว — ดูค่า `universe.top_n` ใน `config.yaml`) บน Timeframe 1H
และ 4H เพื่อหารูปแบบ QM (Quasimodo) ที่กำลังจะกลับตัว จากนั้นยืนยันแต่ละรูปแบบด้วย
RSI divergence ระหว่างจุด Left Shoulder (LS) กับ Head แล้วส่งข้อความเข้า LINE
(จุดเข้า / SL / TP + กราฟที่วาดเส้นให้) สำหรับทุกสัญญาณที่ผ่านการยืนยันแล้วเท่านั้น

บอทนี้ดูกราฟฝั่ง **Futures** ไม่ใช่ Spot — ราคาและโครงสร้างสวิงอาจต่างจาก Spot เล็กน้อย
(มี funding rate เป็นตัวกำหนดส่วนต่างราคา ไม่มีวันส่งมอบ) ซึ่งเป็นเรื่องปกติ เพราะตรงกับ
กราฟที่นักเทรด futures ส่วนใหญ่ดูกันจริงๆ ถ้าคุณต้องการสัญญาแบบ COIN-M (inverse) หรือ
futures รายไตรมาส (dated) แทนที่จะเป็น USDT-M perpetual บอกได้เลย ปรับให้ได้

เวอร์ชันนี้ทำเฉพาะคริปโต — ทองคำ (XAUUSD) ยังไม่รวมไว้โดยตั้งใจ ถ้าจะเพิ่มทีหลังให้ดูที่
`references/data-sources.md` ของ skill ก่อน เพราะแหล่งข้อมูลทองคำและช่วง gap วันหยุดสุดสัปดาห์
ต้องจัดการแยกต่างหาก

## 1. ติดตั้ง

```bash
cd "/Users/fluke/Desktop/Bot QM signal/qm-bot"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 2. ตั้งค่า LINE Official Account (ทำครั้งเดียว)

1. สร้าง OA ที่ [LINE Official Account Manager](https://manager.line.biz/)
2. ไปที่ [LINE Developers Console](https://developers.line.biz/console/) สร้าง Provider
   แล้วสร้าง **Messaging API channel** ผูกกับ OA ที่สร้างไว้
3. ในแท็บ **Messaging API** ของ channel นั้น ออก **channel access token (long-lived)**
   แล้วนำไปใส่ใน `.env` ที่ตัวแปร `LINE_CHANNEL_ACCESS_TOKEN`
4. ไปที่ **OA Manager → Settings → Response settings** ปิด auto-reply และ greeting message
   (ไม่งั้นบอทจะมีข้อความตอบกลับอัตโนมัติกวนใจ)
5. แอด OA เป็นเพื่อนในมือถือของคุณ (สแกน QR code ได้จากคอนโซลหน้าเดียวกัน)

## 3. หา userId ของคุณเอง (ทำครั้งเดียว)

บอทจะส่งข้อความหาคุณโดยตรง (`to: <userId>`) แต่ LINE ไม่มี API ให้ค้นหา userId
จากชื่อหรือเบอร์โทร ต้องได้มาจาก webhook event เท่านั้น

```bash
python webhook_capture.py                       # รันที่ localhost:8000
# เปิดเทอร์มินัลอีกอันเพื่อเปิด public URL:
cloudflared tunnel --url http://localhost:8000   # หรือใช้ ngrok http 8000
```
จากนั้นในคอนโซล Developers → แท็บ Messaging API: ตั้ง **Webhook URL** เป็น
`https://<tunnel-domain>/line-webhook` กด **Verify** แล้วเปิด **Use webhook**
ทักแชทหา OA จากมือถือของคุณ (ข้อความอะไรก็ได้) — `userId` ของคุณ (ขึ้นต้นด้วย `U`)
จะปรากฏในเทอร์มินัลและถูกบันทึกต่อท้ายไฟล์ `userid.txt` นำค่านี้ไปใส่ใน `.env`
ที่ตัวแปร `LINE_TO_USER_ID` แล้วปิด `webhook_capture.py` และ tunnel ได้เลย —
ทั้งสองอย่างนี้ไม่จำเป็นอีกต่อไปเมื่อบอทเริ่มทำงานจริง (บอทมีหน้าที่ push ข้อความออกอย่างเดียว
ไม่ต้องรับ event ใดๆ)

## 4. ตั้งค่า Cloudflare R2 (ทำครั้งเดียว)

LINE เป็นฝ่ายไปดึงรูปกราฟเองผ่าน HTTPS (อัปโหลด binary ตรงเข้า API ไม่ได้) ดังนั้น
รูปทุกใบต้องมี public URL ก่อนเสมอ

1. Cloudflare dashboard → R2 → สร้าง bucket (เช่น `qm-bot-charts`)
2. bucket **Settings → Public access** → เปิดใช้งาน (จะใช้ subdomain `r2.dev` หรือ
   custom domain ของคุณเองก็ได้)
3. R2 → **Manage API tokens** → สร้าง token ที่จำกัดสิทธิ์เฉพาะ bucket นี้
   (Object Read & Write)
4. กรอกค่าใน `.env`: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`,
   `R2_BUCKET`, และ `R2_PUBLIC_BASE_URL` (โดเมน `https://pub-....r2.dev` หรือ
   custom domain ของคุณ ไม่ต้องมี `/` ต่อท้าย)

## 5. ทดสอบตัวตรวจจับก่อนทำอย่างอื่น

```bash
python qm_detector.py --symbol "BTC/USDT:USDT" --timeframe 1h --exchange binanceusdm --plot
```
สังเกตส่วนต่อท้าย `:USDT` และ `--exchange binanceusdm` — นี่คือ symbol แบบรวมของ ccxt
สำหรับสัญญา futures ถ้าใช้ค่า default ของสคริปต์ (ซึ่งเป็น spot) จะกลายเป็นทดสอบกราฟคนละ
อันกับที่บอทตัวจริงสแกน คำสั่งนี้เรียก public API ของ Binance เท่านั้น (ไม่ยุ่งกับ LINE
หรือ R2) ใช้ยืนยันว่าตัวตรวจจับ QM เจอรูปแบบที่สมเหตุสมผลจริง ก่อนจะไปต่อเรื่องการส่งข้อความ

## 6. Dry run (รันแบบไม่ส่งจริง)

```bash
python bot.py --config config.yaml --dry-run
```
คำสั่งนี้จะดึงรายชื่อ universe (ตามค่า `universe.top_n` ใน `config.yaml`) สแกนทั้งสอง timeframe สำหรับทุกเหรียญ แล้วพิมพ์ทุกสัญญาณที่
ผ่านทั้งเกณฑ์ RR และการยืนยัน divergence ออกมาให้ดู — ไม่มีการ push เข้า LINE ไม่มีการ
อัปโหลดขึ้น R2 และไม่มีการบันทึกสถานะใดๆ

## 7. ทดสอบส่งสัญญาณจริง 1 ครั้งแบบจำกัดขอบเขต

ก่อนปล่อยให้สแกนทั้ง universe ซึ่งจะกินโควตา LINE ให้แก้ `config.yaml` ชั่วคราวเป็น
market เดียวก่อน:
```yaml
universe:
  always_include: [BTC/USDT]
  top_n: 0
```
จากนั้นรัน:
```bash
python bot.py --config config.yaml
```
เช็คมือถือของคุณ: Flex bubble ควรแสดง Entry/SL/TP/RR ถูกต้อง พร้อมแถว Divergence
และรูปที่แนบมาควรเห็นโครงสร้าง QM บนพาเนลราคา และเส้นเชื่อม divergence ของ RSI
บนพาเนลด้านล่าง เมื่อเช็คแล้วว่าถูกต้อง ให้แก้ `config.yaml` กลับเป็นค่าเดิม

## 8. รันเป็นบริการเบื้องหลังด้วย `qmbotctl.py`

Timeframe ที่เล็กที่สุดคือ 1H แท่งจะปิดอย่างมากแค่ชั่วโมงละครั้ง จึงไม่มีประโยชน์ที่จะสแกน
ถี่กว่านั้น (ตัวตรวจจับถูกออกแบบให้ไม่สนใจแท่งที่ยังไม่ปิดอยู่แล้ว) `bot.py --loop` มีกลไก
ตั้งเวลาทุกชั่วโมงในตัวอยู่แล้ว `qmbotctl.py` ห่อคำสั่งนี้ไว้ในรูปแบบ start/stop/status
พร้อมเก็บ log เป็นไฟล์รายวันให้อัตโนมัติ ไม่ต้องใช้ `cron`

```bash
python qmbotctl.py start          # เริ่มบอททำงานในพื้นหลัง (สแกนทุกชั่วโมง)
                                   # แล้วแสดง log สดต่อทันที — กด Ctrl+C แค่ออกจากหน้าจอ
                                   # ดู log บอทยังทำงานต่อในพื้นหลัง
python qmbotctl.py start --no-attach   # เริ่มแล้วคืนคำสั่งทันที ไม่แสดง log สด
python qmbotctl.py start --keep-awake  # กันเครื่อง Mac หลับ (idle/AC) ระหว่างบอททำงานด้วย (ดูด้านล่าง)
python qmbotctl.py status         # เช็คว่ากำลังทำงานอยู่ไหม PID อะไร เริ่มเมื่อไหร่
python qmbotctl.py logs -f        # เปิดดู log สดจากเทอร์มินัลอีกหน้าต่างได้ทุกเมื่อ
python qmbotctl.py stop           # หยุดการทำงานในพื้นหลัง
```

**ถ้าเครื่อง Mac เข้าสู่โหมด sleep จะเกิดอะไรขึ้น** ตอน sleep ทั้งเครื่องจะถูกพักที่ระดับ
kernel — โปรเซสของบอทแค่ถูกหยุดชั่วคราว ไม่ได้ถูกฆ่าทิ้ง แล้วจะกลับมาทำงานต่อเองทันทีที่
เครื่องตื่น (`qmbotctl.py status` จะโชว์ว่า "กำลังทำงาน" ตลอดแม้ระหว่าง sleep) ความเสี่ยง
จริงๆ ไม่ใช่ที่โปรเซสตาย แต่คือ **สัญญาณอาจหลุดหายไปเงียบๆ**: ถ้ารูปแบบ QM เกิดขึ้นระหว่าง
เครื่องหลับ พอเครื่องตื่นแล้วบอทสแกนอีกที สัญญาณนั้นอาจเก่าเกินกว่าค่า `fresh_bars`
(จำนวนแท่งล่าสุดที่ยังนับว่า "ใหม่") ไปแล้ว จะถูกข้ามไปเงียบๆ โดยไม่มี error ใดๆ — ยิ่งหลับนาน
ยิ่งมีโอกาสพลาดสัญญาณสูงขึ้น

`--keep-awake` ใช้ `caffeinate` ซึ่งเป็นเครื่องมือในตัวของ macOS เพื่อกันไม่ให้เครื่อง sleep
ตลอดระยะเวลาที่บอทกำลังทำงานพอดี (ปิดตัวเองอัตโนมัติเมื่อบอทหยุดหรือ crash ไม่ต้องเคลียร์เอง)
แต่กันได้เฉพาะ sleep จาก idle และ sleep ตอนเสียบปลั๊กเท่านั้น **ไม่กันการปิดฝาเครื่อง MacBook**
ถ้าไม่ได้ต่อจอนอกอยู่ — นั่นเป็นนโยบาย clamshell sleep ระดับฮาร์ดแวร์ที่ software assertion
แตะต้องไม่ได้ ถ้าต้องการให้บอทรันแบบไม่มีใครดูแลบนโน้ตบุ๊กที่ต้องปิดฝาพกไปมา ให้เสียบปลั๊ก
เปิดฝาทิ้งไว้ หรือย้ายไปรันบนเครื่องที่เปิดอยู่ตลอดเวลาแทน

Log จะถูกเขียนลงไฟล์ `logs/YYYY-MM-DD.log` (ไฟล์ text แยกตามวัน เปลี่ยนไฟล์ให้เองอัตโนมัติ
ตอนเที่ยงคืน) และแสดงออกทางหน้าจอด้วยเมื่อ attach อยู่ ส่วน error ที่หลุดจากระบบดักจับ
ข้อผิดพลาดของบอทเอง (เช่น import ผิดพลาดร้ายแรง) จะถูกบันทึกไว้ที่ `qmbot.crash.log`
เป็นตาข่ายนิรภัยสำรอง

## 9. Deploy ขึ้น Google Cloud (รันตลอดเวลา ไม่ต้องกังวลเรื่อง sleep)

รันบน Mac แปลว่าบอทจะหยุดสแกนทุกครั้งที่ Mac sleep (ดู `--keep-awake` ด้านบน ซึ่งช่วยได้
แค่ระดับหนึ่ง เพราะกันการปิดฝาเครื่องไม่ได้) VM เล็กๆ ที่เปิดตลอดเวลาบน Compute Engine
แก้ปัญหานี้ได้เด็ดขาด ตอนนี้ deploy ไว้แล้วตามนี้:

- **Instance**: `qm-bot`, e2-micro, Debian 12, zone `asia-southeast1-a` (สิงคโปร์)
- **ทำไมต้องสิงคโปร์ ไม่ใช่ region ฟรีในสหรัฐฯ**: Binance ตอบ HTTP 451
  ("restricted location") ให้กับ IP ที่มาจากสหรัฐฯ — เป็นการบล็อคระดับเครือข่ายที่แก้ด้วยโค้ด
  ไม่ได้ และ Binance.US (แพลตฟอร์มแยกสำหรับสหรัฐฯ) ก็ไม่มี futures ให้เทรดเลย ผลคือ VM นี้
  **ไม่เข้าเกณฑ์ Always Free tier** ของ GCP (มีแค่ us-west1/us-central1/us-east1 เท่านั้นที่ฟรี)
  คาดว่าจะเสียประมาณ $7-8/เดือน
- **การดูแลโปรเซส**: ใช้ systemd unit (`deploy/qmbot.service`) รัน
  `bot.py --loop --interval 3600` ในนาม user `qmbot` โดยเฉพาะ, restart อัตโนมัติถ้า crash,
  และเริ่มเองอัตโนมัติเมื่อ VM reboot (ตั้ง `systemctl enable` ไว้แล้ว) แข็งแรงกว่า
  `qmbotctl.py` สำหรับรันบนเซิร์ฟเวอร์แบบไม่มีคนดูแล เพราะไม่ต้องกังวลเรื่อง Ctrl+C/caffeinate
  เลย — systemd หยุดด้วย SIGTERM เป็นค่า default ซึ่งตรงกับที่ `bot.py --loop` รองรับอยู่แล้ว

**คำสั่งดูแล VM:**
```bash
# ดูสถานะ / log
gcloud compute ssh qm-bot --zone=asia-southeast1-a --command="sudo systemctl status qmbot --no-pager"
gcloud compute ssh qm-bot --zone=asia-southeast1-a --command="tail -f /opt/qmbot/logs/\$(date +%Y-%m-%d).log"

# หยุด / เริ่ม / restart
gcloud compute ssh qm-bot --zone=asia-southeast1-a --command="sudo systemctl stop qmbot"
gcloud compute ssh qm-bot --zone=asia-southeast1-a --command="sudo systemctl start qmbot"

# ลบทิ้งทั้งหมด (หยุดเสียเงิน)
gcloud compute instances delete qm-bot --zone=asia-southeast1-a
```

**Deploy โค้ดใหม่หลังแก้ไข** — sync ไฟล์แล้วรัน setup อีกรอบ (idempotent):
```bash
rsync -av --exclude='.venv' --exclude='__pycache__' --exclude='logs' \
  --exclude='data' --exclude='*.pid' --exclude='qmbot.crash.log' \
  --exclude='signals.db' --exclude='universe_cache.json' \
  --exclude='.DS_Store' --exclude='bot.log' --exclude='userid.txt' \
  ./ /tmp/qm-bot-deploy/
gcloud compute scp --recurse /tmp/qm-bot-deploy/* qm-bot:/opt/qmbot/ --zone=asia-southeast1-a
gcloud compute scp /tmp/qm-bot-deploy/.env qm-bot:/opt/qmbot/ --zone=asia-southeast1-a  # ไฟล์ dotfile ต้องระบุแยก — `*` ไม่ match ไฟล์ที่ขึ้นต้นด้วยจุด
gcloud compute ssh qm-bot --zone=asia-southeast1-a --command="sudo bash /opt/qmbot/deploy/setup_vm.sh"
```

ข้อควรระวัง: `signals.db` (สถานะกันส่งซ้ำ) ตอนนี้อยู่บน VM เท่านั้น ไม่อยู่บน Mac แล้ว
**ห้ามรัน `bot.py` พร้อมกันทั้งบน Mac และ VM โดยใช้ LINE account เดียวกัน** ไม่งั้นจะได้รับ
แจ้งเตือนซ้ำจาก dedupe store สองชุดที่แยกจากกัน

## 10. Backtest ก่อนเชื่อสัญญาณที่รันจริง

```bash
python qm_detector.py --csv data/BTCUSDT_1h.csv --symbol BTC/USDT --timeframe 1h  # ตรวจสอบเบื้องต้น
python backtest.py --csv data/BTCUSDT_1h.csv --symbol BTC/USDT --timeframe 1h --split 0.3
```
ดูผลลัพธ์ที่ report: จำนวนไม้ / win rate / expectancy (หน่วย R) / profit factor /
max drawdown — win rate อย่างเดียวทำให้เข้าใจผิดได้สำหรับกลยุทธ์ที่กรองด้วย RR แบบนี้
เช็คด้วยว่าผลของ in-sample กับ out-of-sample ไม่ต่างกันจนน่าตกใจ (สัญญาณของ overfit)
ก่อนจะเชื่อสัญญาณของบอท

## ประวัติเวอร์ชัน — โฟลเดอร์ `versions/`

ทุกการเปลี่ยนแปลงของบอทจะถูกเก็บเป็นเวอร์ชันแยกโฟลเดอร์ พร้อมไฟล์ `CHANGES.txt`
อธิบายว่าเปลี่ยนอะไรและทำไม ดูสารบัญทั้งหมดได้ที่ [`versions/INDEX.md`](versions/INDEX.md)

```
versions/
├── INDEX.md            ← ตารางรวมทุกเวอร์ชัน
├── v1.6.0/
│   ├── CHANGES.txt     ← เปลี่ยนอะไร ทำไม ไฟล์ไหนบ้าง
│   └── code/           ← สำเนาโค้ดทั้งหมด ณ จุดนั้น
└── v1.7.0/
    ├── CHANGES.txt
    └── code/
```

**ทุกครั้งที่แก้โปรแกรม ให้บันทึกเวอร์ชันใหม่ด้วยคำสั่ง:**
```bash
python make_version.py 1.8.0 "สรุปสั้นๆ ว่าเปลี่ยนอะไร"
```
คำสั่งนี้จะคัดลอกโค้ดปัจจุบันไปไว้ที่ `versions/v1.8.0/code/` เทียบกับเวอร์ชัน
ก่อนหน้าเพื่อสรุปว่าไฟล์ไหนเพิ่ม/แก้/ลบ สร้าง `CHANGES.txt` ให้ แล้วอัปเดตสารบัญ
จากนั้นค่อยไปเขียนรายละเอียดเพิ่มใน `CHANGES.txt` (หรือใส่ `--note "..."` ตั้งแต่แรก)

**ความปลอดภัย:** ไฟล์ความลับจะไม่ถูกคัดลอกเข้า snapshot เด็ดขาด — `.env`,
`signals.db`, `userid.txt`, log, รูปกราฟ และข้อมูล cache ถูกกันออกทั้งหมด
เพราะโฟลเดอร์ `versions/` ถูก commit ขึ้น git

เวอร์ชัน v1.0.0–v1.5.0 มีแต่ `CHANGES.txt` ไม่มี `code/` เพราะเกิดขึ้นก่อนจะเริ่ม
ใช้ระบบนี้ โค้ดตอนนั้นถูกแก้ทับไปแล้วโดยไม่ได้ commit แยกไว้ การสร้างย้อนหลัง
จะได้ไฟล์ที่ไม่เคยถูกทดสอบจริง จึงเก็บไว้แค่บันทึกการเปลี่ยนแปลง

## หมายเหตุ

- **ตัวกรอง HTF (แนวโน้ม timeframe ใหญ่กว่า)** (`htf_filter` ใน `config.yaml`)
  ตอนนี้**ปิดใช้งานอยู่** และควรรู้เหตุผลก่อนจะเปิดกลับ ตัวกรองนี้ถูกเพิ่มเข้ามาตาม
  งานวิจัยเรื่อง multi-timeframe ทั่วไป แต่พอ backtest จริงบนข้อมูล 89,985 แท่ง 1H
  (15 เหรียญ ~250 วัน) กลับพบว่ามันทำให้**ทุกตัวชี้วัดแย่ลง** ทั้ง in-sample และ out-of-sample:

  | config | ไม้ | win% | expectancy | PF | maxDD |
  |---|---|---|---|---|---|
  | divergence อย่างเดียว | 171 | 39.8% | **+0.767R** | 2.07 | −13.4R |
  | + HTF alignment | 118 | 34.7% | +0.589R | 1.75 | −19.8R |

  เหตุผลน่าจะเป็นเรื่องแนวคิด: QM เป็นรูปแบบ**กลับตัว** ดังนั้น QM ขาลงที่ถูกต้อง
  *ควรจะ* เกิดตอนที่ TF ใหญ่ยังอ่านว่าขาขึ้นอยู่ — เพราะ 4H ยังไม่กลับตัว นั่นแหละคือจุดที่เทรด
  การบังคับให้ HTF เห็นด้วยจึงไปกรองทิ้งสัญญาณกลับตัวช่วงต้นซึ่งเป็นสิ่งที่รูปแบบนี้มีไว้จับพอดี
  โค้ดกับ config ยังเก็บไว้เผื่อทดสอบใหม่ — เปลี่ยนเป็น `enabled: true` แล้วเทียบด้วย
  `python backtest_full.py --bars 6000 --split 0.3`
- **ผล backtest ของ config ที่ใช้จริงตอนนี้** วัดบน **830,000 แท่ง 1H** — 15 เหรียญ
  × 6.6 ปี (2020-01 ถึง 2026-07) จากข้อมูลทางการของ Binance ผ่าน
  `fetch_binance_vision.py`:

  | ช่วง | ไม้ | win% | expectancy | PF |
  |---|---|---|---|---|
  | in-sample (2020–2024) | 1,154 | 31.9% | +0.434R | 1.56 |
  | out-of-sample (2024–2026) | 551 | 35.6% | +0.473R | 1.63 |
  | รวม 6.6 ปี | 1,707 | 33.0% | **+0.447R** | 1.58 |

  in-sample กับ out-of-sample ใกล้กันขนาดนี้คือจุดสำคัญที่สุดที่ต้องเช็ค — ตัวเลขที่ดี
  เฉพาะ in-sample คือ overfitting ไม่ใช่ edge จริง ส่วน win rate ที่ต่ำเป็นเรื่องปกติ
  ของกลยุทธ์ที่กรองด้วย RR (`min_rr: 1.5`) คือชนะแค่ 1 ใน 3 แต่ยังกำไรได้

- **ทำไมต้องรันสองโปรไฟล์ แทนที่จะจูนหาค่าเดียวที่ดีที่สุด** เพราะค่า `pivot` ที่ดีที่สุด
  ไม่ใช่คุณสมบัติถาวรของกลยุทธ์ แต่**เปลี่ยนไปตามยุคของตลาด**:

  | pivot | 2020–2024 | 2024–2026 |
  |---|---|---|
  | 3 | **+0.522R** | +0.420R |
  | 15 | +0.271R | **+0.572R** |

  swing เล็กชนะช่วงแรก swing ใหญ่ชนะช่วงหลัง การจูนไปทางใดทางหนึ่งคือการเดิมพันว่า
  ยุคไหนจะดำเนินต่อ การรันทั้งสองจึงทำให้ผลรวมนิ่ง — แต่ละโปรไฟล์เดี่ยวๆ แกว่งแรง
  (short 0.522→0.420, wide 0.187→0.693) แต่พอรวมกันแทบไม่ขยับ (0.434→0.473)
  การกระจายความเสี่ยงข้ามขนาด swing ดีกว่าการหาค่าที่ดีที่สุดค่าเดียว

  นี่เป็นข้อเตือนใจเรื่อง backtest ที่ข้อมูลสั้นเกินไปด้วย: รอบก่อนที่ทดสอบด้วยข้อมูล
  API ~500 วัน สรุปว่า pivot=15 ดีกว่าชัดเจนและควรเลิกใช้ pivot=3 — แต่ช่วงนั้น
  คือยุค 2024–2026 พอดี ข้อสรุปจึงไม่รอดเมื่อทดสอบข้ามประวัติศาสตร์ทั้งหมด
  เวลาจะตัดสินพารามิเตอร์ใดๆ ให้ใช้ `fetch_binance_vision.py` เสมอ
- `signals.db` (SQLite) ใช้กันการส่งซ้ำโดยอิง `signal_id` ซึ่งผูกกับเวลาของแท่ง HEAD —
  **ห้ามลบไฟล์นี้ขณะบอทกำลังทำงานจริง** ไม่งั้นจะได้รับแจ้งเตือนซ้ำสำหรับสัญญาณที่ส่งไปแล้ว
- `universe_cache.json` เก็บรายชื่อ universe (ตามค่า `universe.top_n` ใน
  `config.yaml` ตอนนี้ตั้งไว้ที่ 50) ไว้ 24 ชั่วโมง ลบไฟล์นี้ได้ถ้าอยากบังคับให้
  รีเฟรชทันที
- ทุกข้อความ LINE จะมี disclaimer กำกับว่า *"สัญญาณอัตโนมัติเพื่อการศึกษา
  ไม่ใช่คำแนะนำการลงทุน"* — บอทนี้เป็นเครื่องมือแจ้งเตือนเท่านั้น ไม่ใช่คำแนะนำการลงทุน
  และไม่มีการส่งคำสั่งเทรดใดๆ ทั้งสิ้น
- โควตาแผนฟรีของ LINE อยู่ที่หลักร้อยข้อความ/เดือน ด้วยเหรียญตามจำนวน `universe.top_n`
  × 2 timeframe ถ้าสัญญาณมาถี่เกินแผนที่มี ให้ปรับ `min_rr` ใน `config.yaml` ให้สูงขึ้น
  ก่อนเป็นอันดับแรก — top_n ที่ตั้งไว้ตอนนี้ (50) แปลว่าสแกนงานเยอะขึ้นและมีโอกาสยิงสัญญาณ
  พร้อมกันในชั่วโมงเดียวได้มากขึ้น ลองเฝ้าดูด้วย `qmbotctl.py logs -f` สักสองสามวันก่อน
  เพื่อดูปริมาณจริง — ดูวิธีคำนวณโควตาได้ที่ `references/line-messaging-api.md` ของ skill
