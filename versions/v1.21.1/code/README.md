# QM Pattern Signal Bot

**[English](#english) · [ภาษาไทย](README.th.md)**

Scans Binance USDⓈ-M perpetual futures for **QM (Quasimodo)** reversal
patterns, confirms each one against RSI momentum and candle quality, and
pushes the setup to **LINE** with an annotated chart.

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
3. Checks the break was a real one (candle body, not a wick) and that the
   retest has no momentum behind it (RSI on the BOS→RS leg)
4. Grades what is left **A / B / C** and sends it to LINE with entry, stop,
   two targets, risk:reward, position size and a chart

```
SELL  ·  QM                    ┌─ price panel: LS / L1 / HEAD / BOS / RS
BTC/USDT   1h wide             │  entry, stop, TP1, TP2 drawn as lines
─────────────────────────      │
Entry (QML)      63,450.00     └─ RSI panel: the momentum readings
Stop Loss        64,092.98
TP1              61,297.00
TP2              59,632.29
R:R              1 : 3.35
BOS              body close ✓
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

---

# How it works

Read this part before deciding whether to run it. Every design choice below
is a tradeoff, and some of them are ones you may not want.

## One pass, end to end

The bot wakes at **:01 past the hour** — one minute after the 1H candle
closes. 4H closes are a subset of hourly ones, so a single hourly pass
covers both timeframes.

```
universe          top-N futures pairs by 24h volume (cached 24h)
   ↓
candles           500 closed 1H + 4H bars per symbol, public API, no key
   ↓
structure         QM detection: LS → L1 → HEAD → BOS → RS
   ↓
gate 1  R:R       drop if TP1 cannot pay 1.5× the stop
gate 2  momentum  drop if the retest bounced with strength behind it
gate 3  candle    drop if the break was only a wick
gate 4  fresh     drop patterns that triggered more than 1 bar ago
   ↓
dedupe            SQLite, keyed on the Head candle's timestamp
   ↓
chart + upload    PNG → R2 → HTTPS URL
   ↓
LINE              Flex bubble + image, one push
```

## 1. Which symbols it looks at

The top `universe.top_n` (default 100) USDT perpetuals by 24h volume, with
BTC and ETH pinned in regardless of where they rank. Leveraged tokens,
stablecoin-vs-stablecoin pairs and tokenised stocks/metals are removed —
they do not behave like coins and their structure means something else. The
list is cached for 24 hours rather than refetched every scan.

**Consequence to be aware of:** the universe is *today's* high-volume list.
Coins that died are not in it, in live trading or in the backtest.

## 2. How a QM is detected

A QM is five points, and the detector requires them **in this order**:

| point | meaning |
|---|---|
| **LS** | left shoulder — the swing that leaves resting liquidity above (below) it |
| **L1** | the pullback after LS — this is the structure that must later break |
| **HEAD** | a higher high (lower low) than LS: the sweep that takes that liquidity |
| **BOS / L2** | price closes through L1 — the break of structure |
| **RS** | price returns to the QM Level (= the LS price) — this is where you enter |

Swings come from fractal pivots: a bar is a pivot high when it is the
highest of the `pivot_left` bars before it and the `pivot_right` bars after
it. Consecutive same-type pivots are collapsed so LS / L1 / HEAD always
alternate high-low-high and the pattern cannot be assembled out of order.

Every size threshold is measured in **ATR**, never in dollars or percent:
the sweep must exceed `min_sweep_atr` × ATR, the break must exceed
`min_bos_atr` × ATR, the stop sits `sl_buffer_atr` × ATR beyond the Head.
That is what lets one config run over BTC at $60,000 and a coin at
$0.00004 without per-symbol tuning.

## 3. Why signals arrive a few bars late — and never disappear

A pivot cannot be known until `pivot_right` bars have closed after it. The
bot waits for that confirmation instead of guessing, and it also discards
the still-open candle before doing anything else.

**The cost:** on the `short` profile the Head is only confirmed 3 bars
later; on `wide`, 15 bars later.

**What you get for it:** nothing repaints. A signal you received was true
when it was sent and will still be in the chart history tomorrow. Tools
that mark the pattern the instant it forms are showing a shape that can be
revised away — they look better on screen and cannot be backtested
honestly.

The delay rarely costs the entry, because the entry sits at the QM Level
and price is *travelling back toward* that level when the signal fires.

## 4. The four gates

### Gate 1 — Risk:reward (`min_rr: 1.5`)

Applied inside the detector. If the distance from the QM Level to TP1 is
less than 1.5× the distance to the stop, the setup is dropped no matter how
clean it looks. This is the strongest filter in the bot, and the reason a
win rate near 50% is profitable rather than a problem.

### Gate 2 — Momentum on the last swing (`divergence.bos_rs_max`)

Not the classic LS↔HEAD divergence. It is measured on the **BOS→RS leg** —
the final push back up into your entry. If RSI climbs hard on that leg, the
retest has real buying behind it and is more likely to run straight through
your level. `bos_rs_max` caps how far RSI may travel on that leg: **10**
points on `short`, **20** on `wide`.

The two thresholds are not cosmetic. A wide-profile leg spans days and
naturally moves RSI further; a single shared threshold silently strangled
the wide profile down to a 2% pass rate until it was split per profile.

The same measurement produces the **A / B / C grade** in the message: **A**
when momentum faded by ≥5 RSI points in the direction you are trading,
**B** when it faded at all, **C** otherwise.

### Gate 3 — Candle body vs wick at the break

The BOS must be a **body close** through L1 — not a wick that pokes past
and closes back inside. Price-action research puts continuation after a
body close at 59–64%, and after a wick-through-then-close-back at 25–27%,
which is *below* the base rate: that shape is a reversal signal, not a
break. A "BOS" that is only a wick is a liquidity sweep of the other side,
so the pattern's premise was never actually met.

Measured across 98 symbols out-of-sample:

| | trades | win | expectancy | PF |
|---|---|---|---|---|
| no candle gate | 1578 | 45.8% | +0.634R | 2.02 |
| **BOS body close (default)** | **462** | **50.6%** | **+0.966R** | **2.74** |
| inverse: wick-only breaks | 654 | 44.6% | +0.510R | 1.81 |

The inverse row is the check that matters — a filter that helps *and* whose
opposite also helps is measuring noise, not an effect.

**This removes ~71% of signals.** If you would rather see more and judge
yourself, set `candle_quality.enabled: false`. The value is tagged on every
signal either way, so the LINE message still tells you which kind of break
it was.

### Gate 4 — Freshness (`fresh_bars: 1`)

Only patterns that triggered on the most recently closed bar are sent. An
older one is history: price has already left the entry.

## 5. Where the numbers in the message come from

| field | how it is derived |
|---|---|
| **Entry** | the QM Level = the Left Shoulder price. A **limit** order, not a market order |
| **Stop Loss** | beyond the Head, plus `sl_buffer_atr` (0.25) × ATR of the trigger bar |
| **TP1** | the BOS extreme — the swing price reached when it broke structure |
| **TP2** | TP1 extended by `tp2_extension` (0.618) × the Head-to-BOS range |
| **R:R** | (Entry→TP1) ÷ (Entry→Stop); gate 1 rejects anything below 1.5 |
| **Size** | `risk.equity` × `risk.risk_pct` ÷ (Entry − Stop) — default 10,000 × 1% = 100 risked per trade |

Set `risk.equity` to your own account, or the Size row is meaningless to
you. Backtests exit at **TP1**; TP2 is shown for people who scale out and
run a remainder, and has not been validated as a full-position exit.

## 6. Two profiles on 1H, one on 4H

1H is scanned twice per pass, with different swing sizes:

| profile | pivot | retest window | finds |
|---|---|---|---|
| `short` | 3 | 50 bars (~2 days) | intraday patterns |
| `wide` | 15 | 168 bars (1 week) | week-scale patterns |

The best swing size is not stable across regimes — small swings won
2020–2024, large swings won 2024–2026. Running both is steadier than
betting on either, and the profile name appears in the message so you know
which one fired.

## 7. Not sending the same thing twice

Each signal gets an id built from symbol, timeframe, profile and the **Head
candle's timestamp** — never its bar index. Indexes shift every time a new
bar arrives, so an index-keyed id resends the same pattern every hour. The
ids live in SQLite (`signals.db`), so restarting the bot does not replay
everything you already received.

## What it deliberately does not do

- **No auto-trading.** There is no exchange API key anywhere in the
  codebase. It reads public market data and cannot place an order.
- **No higher-timeframe trend filter by default.** It exists
  (`htf_filter.py`) and measured roughly neutral, so it costs signals for
  no gain. Enable it if you want 4H alignment enforced.
- **No news, sentiment or funding data.** Price and volume only.
- **No LS↔HEAD divergence requirement.** Classic QM teaching asks for it;
  on this dataset it did not pay for the signals it cost, so it is
  reported (`required: false`) rather than enforced.

---

## What is actually verified

Backtested on **2.6M 1H candles** — 99 symbols, up to 6.6 years from
Binance's official archives, split in-sample / out-of-sample:

| profile | out-of-sample, no candle gate | with candle gate (default) |
|---|---|---|
| `1h short` (small swings, 0.5–3 days) | n=1428, win 46.7%, +0.634R | win 53.0%, +0.979R |
| `1h wide` (large swings, 3–10 days) | n=150, win 36.7%, +0.631R | win 38.4%, +0.897R |
| **both combined** | n=1578, win 45.8%, +0.634R, PF 2.02 | **n=462, win 50.6%, +0.966R, PF 2.74** |

Every filter is verified **per profile**, not just on the combined number —
a filter can improve the total while quietly destroying one profile, which
has happened here before and is how the per-profile threshold in gate 2 was
found.

**How the simulation is run:** entry as a limit fill at the QM Level; exit
at TP1 or stop; **the stop is assumed to fill first** whenever one candle
covers both stop and target; 0.05% fee per side plus 0.02% slippage charged
in R; 200-bar maximum hold; no bar the detector had not yet closed is ever
read.

**Read the numbers with care.** The simulation still cannot model funding
payments, real order-book fills, or your own execution. The symbol universe
is today's high-volume list, so failed and delisted coins are absent
(survivorship bias). Past results do not predict future ones.

Reproduce any of it yourself:

```bash
python fetch_binance_vision.py BTCUSDT ETHUSDT SOLUSDT
python backtest_full.py --data-dir data/vision --split 0.3
```

## Is this for you?

**Probably yes if** you swing-trade crypto manually, want a shortlist of
structural setups rather than a black box, and are comfortable being handed
~50 signals a month of which about half lose.

**Probably not if** you want automated execution, a high win rate, signals
on demand rather than on the hour, or anything outside crypto perpetuals.

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
| `candle_quality.enabled` | `false` restores ~3.4× more signals at a lower expectancy |
| `candle_quality.require_head_wick` | also demand the Head be a wick sweep — better alone, worse combined with the BOS rule |
| `divergence.bos_rs_max` | how weak the retest bounce must be (per profile) |
| `divergence.last_swing.min_diff` | set to `5` to receive only grade A |
| `risk.equity` / `risk_pct` | the account the Size row is computed from |
| `daily_report.quota_throttle` | drops the daily summary to weekly once LINE quota passes 50% |

### Signal volume vs LINE quota

Roughly **50 signals/month** at defaults with 100 symbols, plus 30 daily
summaries — about 80 of the free tier's 300. Turning the candle gate off
takes it to ~170/month (~200 total), which still fits but leaves little
room. To go the other way: raise `min_rr`, cut `universe.top_n`, or set
`last_swing.min_diff: 5` for grade A only.

## Layout

```
bot.py                 hourly scan loop
qm_detector.py         QM structure detection (pure, no I/O)
divergence.py          RSI confirmation + A/B/C grading
candle_quality.py      body-vs-wick quality at HEAD and BOS
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
- **Reversal patterns fail often.** ~50% win rate with the candle gate, ~45%
  without, is the design — not a bug. The RR gate is what makes it work.
- **Signals are hourly, not instant.** Nothing is sent between candle closes.
- **The edge may not persist.** It was measured on past data; markets change.
- **You are risking your own money.** Start on paper, size small, and treat
  every signal as one input among several.

## License

MIT — see [LICENSE](LICENSE). Use it, fork it, change it. No warranty of any
kind: if it loses you money, that is on you.
