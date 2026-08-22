# QM Pattern Signal Bot

**[English](#english) · [ภาษาไทย](README.th.md)**

Scans Binance USDⓈ-M perpetual futures for **QM (Quasimodo)** reversal
patterns, confirms each one against RSI momentum, and pushes the setup to
**LINE** with an annotated chart.

It tells you where a setup is. It does not place orders, and it is not
advice — you decide what to trade.

<a name="english"></a>

---

## What it does

Every hour, one minute after the candle closes, the bot:

1. Pulls the top-N Binance futures pairs by 24h volume (leveraged tokens,
   stablecoin pairs and tokenised stocks/metals filtered out)
2. Detects QM structure on each — Left Shoulder → Head (liquidity sweep) →
   Break of Structure → retest of the QM Level
3. Confirms the retest has no momentum behind it (RSI on the BOS→RS leg)
4. Grades what is left **A / B / C** and sends it to LINE with entry, stop,
   two targets, risk:reward, position size and a chart

```
SELL  ·  QM                    ┌─ price panel: LS / L1 / HEAD / BOS / RS
BTC/USDT   1h wide             │  entry, stop, TP1, TP2 drawn as lines
─────────────────────────      │
Entry (QML)      63,450.00     └─ RSI panel: the two momentum readings
Stop Loss        64,092.98
TP1              61,297.00
TP2              59,632.29
R:R              1 : 3.35
เกรด A           สูง (RSI +23)
Size             0.1555 BTC
Time             07/07 20:00 ICT
```

A separate daily Bitcoin summary (price, 1D/4H trend, RSI, volatility,
nearest support/resistance) is sent each morning at 10:00 Asia/Bangkok.

## Why QM

QM is a reversal pattern with two things happening at once: the Head sweeps
liquidity above the Left Shoulder, then price **breaks structure** by taking
out the prior low. Without that break it is an ordinary head-and-shoulders
and you must wait for the neckline. The break is what lets the entry sit at
the QM Level instead, with a tighter stop.

## What is actually verified

Backtested on **2.6M 1H candles** — 99 symbols, up to 6.6 years from Binance's
official archives, with an in-sample / out-of-sample split:

| profile | in-sample | out-of-sample |
|---|---|---|
| `1h short` (small swings, 0.5–3 days) | n=3027, +0.592R, PF 1.94 | n=1428, +0.634R, PF 2.04 |
| `1h wide` (large swings, 3–10 days) | n=416, +0.290R, PF 1.41 | n=150, +0.631R, PF 1.93 |

Win rate sits near 45%. That is fine and expected — the RR gate (`min_rr:
1.5`) means it does not need to be right half the time to come out ahead.

**Read these numbers with care.** Backtests assume the stop fills first when
a candle covers both stop and target, charge fees and slippage, and never
look ahead — but they still cannot model funding, real fills, or your own
execution. The symbol universe is today's high-volume list, so failed and
delisted coins are absent (survivorship bias). Past results do not predict
future ones.

Reproduce any of it yourself:

```bash
python fetch_binance_vision.py BTCUSDT ETHUSDT SOLUSDT
python backtest_full.py --data-dir data/vision --split 0.3
```

## Requirements

- Python 3.11+
- A **LINE Official Account** with Messaging API (free tier: 300 msg/month)
- **Cloudflare R2** or any S3-compatible public bucket, for chart images
- Optional: a small always-on VM if you want it running 24/7

No exchange API key is needed — the bot only reads public market data and
never touches an account.

## Setup

### 1. Install

```bash
git clone https://github.com/FlukEDev/qm-bot.git
cd qm-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. LINE Official Account

1. Create an OA at [LINE Official Account Manager](https://manager.line.biz/)
2. In [LINE Developers Console](https://developers.line.biz/console/): new
   Provider → **Messaging API channel** linked to that OA
3. Issue a long-lived **channel access token** → `.env` as
   `LINE_CHANNEL_ACCESS_TOKEN`
4. In OA Manager → Settings → Response settings, turn **off** auto-reply and
   greeting messages
5. Add the OA as a friend on your phone

### 3. Your LINE userId

The bot pushes to you directly, and LINE has no lookup API for that — the id
only arrives through a webhook.

```bash
python webhook_capture.py                       # listens on :8000
cloudflared tunnel --url http://localhost:8000   # or: ngrok http 8000
```

Set the tunnel URL + `/line-webhook` as the Webhook URL in the console,
click **Verify**, enable **Use webhook**, then message your OA. Your userId
(starts with `U`) prints in the terminal — put it in `.env` as
`LINE_TO_USER_ID`, then stop the script and tunnel. Neither is needed again;
the bot only ever pushes.

### 4. Chart hosting

LINE fetches images itself over HTTPS and cannot accept an upload, so charts
need a public URL.

1. Cloudflare → R2 → create a bucket, enable public access
2. Create an API token scoped to that bucket (Object Read & Write)
3. Fill `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`,
   `R2_BUCKET`, `R2_PUBLIC_BASE_URL` in `.env`

Any S3-compatible host works — see `chart_uploader.py`, it is ~40 lines.

### 5. Check it before sending anything

```bash
python bot.py --config config.yaml --dry-run
```

Resolves the universe, scans every symbol and prints what it would send. No
LINE messages, no uploads, no state written. Run this first.

Then a single real signal:

```bash
python bot.py --config config.yaml
```

## Running it

```bash
python qmbotctl.py start          # background, hourly, streams the log
python qmbotctl.py start --no-attach
python qmbotctl.py status
python qmbotctl.py logs -f
python qmbotctl.py stop
```

Ctrl+C only detaches the log view — the bot keeps running. On macOS,
`--keep-awake` stops the machine idle-sleeping through scans (it cannot
override closing a laptop lid).

Logs land in `logs/YYYY-MM-DD.log`, one file per day.

**Always-on**: `deploy/` has a systemd unit and a setup script for a Linux
VM. Note that **Binance blocks US IPs** (HTTP 451), so a US-region VM will
fail — pick a region elsewhere.

## Tuning

Everything lives in `config.yaml`, and each setting carries the backtest
numbers behind it in a comment. The ones worth knowing:

| setting | what it changes |
|---|---|
| `universe.top_n` | how many symbols to scan |
| `qm.1h[].pivot_left/right` | swing size — 3 finds small patterns, 15 finds week-scale ones |
| `qm.1h[].max_bars_to_retest` | how long a pattern may wait for its retest |
| `qm.1h[].min_rr` | the single strongest filter; raise it if you get too many signals |
| `divergence.bos_rs_max` | how weak the retest bounce must be (per profile) |
| `divergence.last_swing.min_diff` | set to `5` to receive only grade A |
| `daily_report.quota_throttle` | drops the daily summary to weekly once LINE quota passes 50% |

1H is scanned with **two profiles at once** — small swings and large ones —
because the best swing size is not stable: small swings won 2020–2024, large
swings won 2024–2026. Running both is steadier than betting on either.

### Signal volume vs LINE quota

Roughly 170 signals/month at defaults with 100 symbols, plus 30 daily
summaries — about 200 of the free tier's 300. If that is tight: raise
`min_rr`, cut `universe.top_n`, or set `last_swing.min_diff: 5` for grade-A
only (~33/month).

## Layout

```
bot.py                 hourly scan loop
qm_detector.py         QM structure detection (pure, no I/O)
divergence.py          RSI confirmation + A/B/C grading
htf_filter.py          higher-timeframe alignment (off by default)
universe.py            symbol selection
chart_renderer.py      annotated PNG
chart_uploader.py      S3/R2 upload
line_notifier.py       LINE Messaging API
daily_report.py        daily Bitcoin summary
qmbotctl.py            start/stop/status/logs
backtest_full.py       full-pipeline backtest
fetch_binance_vision.py  deep history from data.binance.vision
make_version.py        version snapshots -> versions/
deploy/                systemd units + VM setup
```

`versions/` holds a snapshot and a changelog for every change made to the
bot, including the ones that were later reversed and why.

## Honest limitations

- **Not auto-trading.** It sends messages. Nothing is ordered.
- **Not advice.** Every message carries a disclaimer, and so does this line.
- **Crypto only.** Gold/FX would need a different data source and weekend-gap
  handling.
- **Reversal patterns fail often.** ~45% win rate is the design, not a bug.
- **The edge may not persist.** It was measured on past data; markets change.
- **You are risking your own money.** Start on paper, size small, and treat
  every signal as one input among several.

## License

MIT — see [LICENSE](LICENSE). Use it, fork it, change it. No warranty of any
kind: if it loses you money, that is on you.
