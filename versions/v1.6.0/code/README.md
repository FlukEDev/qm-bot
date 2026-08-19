# QM Pattern Signal Bot — Crypto Futures (Binance) → LINE

Scans the top Binance **USDⓈ-M perpetual futures** contracts (BTC, ETH + top
N by 24h volume — see `universe.top_n` in `config.yaml`) on the 1H and 4H
timeframes for QM (Quasimodo) reversal patterns, confirms each one with RSI
divergence between the Left Shoulder and Head pivots, and pushes a LINE
message (entry / SL / TP + annotated chart) for every confirmed signal.

This reads the **futures** chart, not spot — prices and swing structure can
differ slightly from spot (funding-rate basis, no delivery), which is
expected since this matches what the chart looks like on the exchange most
retail futures traders are actually trading. If you specifically wanted
COIN-M (inverse) contracts or dated quarterly futures instead of USDT-M
perpetuals, this isn't that — say so and it can be pointed elsewhere.

Crypto only in this version — gold (XAUUSD) was intentionally left out; see
the skill's `references/data-sources.md` if you want to add it later, since
gold data sourcing and weekend gaps need separate handling.

## 1. Install

```bash
cd "/Users/fluke/Desktop/Bot QM signal/qm-bot"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 2. Set up a LINE Official Account (one-time)

1. Create an OA at [LINE Official Account Manager](https://manager.line.biz/).
2. In [LINE Developers Console](https://developers.line.biz/console/), create
   a Provider, then a **Messaging API channel** linked to that OA.
3. In the channel's **Messaging API** tab, issue a long-lived **channel
   access token** → put it in `.env` as `LINE_CHANNEL_ACCESS_TOKEN`.
4. In **OA Manager → Settings → Response settings**, turn OFF auto-reply and
   greeting messages (otherwise the OA will chat back at you).
5. Add the OA as a friend on your phone (QR code is in the same console tab).

## 3. Get your LINE userId (one-time)

The bot pushes to you directly (`to: <userId>`), and LINE has no lookup API
for that — it only comes from a webhook event.

```bash
python webhook_capture.py                       # starts on localhost:8000
# in a second terminal, expose it publicly:
cloudflared tunnel --url http://localhost:8000   # or: ngrok http 8000
```
Then in the Developers Console → Messaging API tab: set **Webhook URL** to
`https://<tunnel-domain>/line-webhook`, click **Verify**, enable **Use
webhook**. Send the OA any message from your phone — your `userId` (starts
with `U`) prints in the terminal and is appended to `userid.txt`. Put it in
`.env` as `LINE_TO_USER_ID`, then stop `webhook_capture.py` and the tunnel —
neither is needed once the bot is running (it only ever pushes, never
receives).

## 4. Set up Cloudflare R2 (one-time)

LINE fetches chart images itself over HTTPS — it cannot accept an upload — so
every chart needs a public URL first.

1. Cloudflare dashboard → R2 → create a bucket (e.g. `qm-bot-charts`).
2. Bucket **Settings → Public access** → enable it (either the `r2.dev`
   subdomain or your own custom domain).
3. R2 → **Manage API tokens** → create a token scoped to that bucket
   (Object Read & Write).
4. Fill in `.env`: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`,
   `R2_BUCKET`, and `R2_PUBLIC_BASE_URL` (the `https://pub-....r2.dev` domain
   or your custom domain, no trailing slash).

## 5. Sanity-check the detector before anything else

```bash
python qm_detector.py --symbol "BTC/USDT:USDT" --timeframe 1h --exchange binanceusdm --plot
```
Note the `:USDT` suffix and `--exchange binanceusdm` — that's ccxt's unified
symbol for the futures contract; leaving these as the script's spot defaults
would sanity-check a different (spot) chart than what the live bot scans.
This talks to Binance's public API only (no LINE, no R2) and confirms QM
detection is finding real structure before you wire up delivery.

## 6. Dry run

```bash
python bot.py --config config.yaml --dry-run
```
Resolves the universe (`universe.top_n` in `config.yaml`), scans both
timeframes for every symbol, prints any signal that passed the RR gate and
divergence confirmation — no LINE
push, no R2 upload, no state written.

## 7. One real signal, restricted scope

Before turning the full universe loose on your LINE quota, edit
`config.yaml` temporarily to a single market:
```yaml
universe:
  always_include: [BTC/USDT]
  top_n: 0
```
Then:
```bash
python bot.py --config config.yaml
```
Check your phone: the Flex bubble should show correct Entry/SL/TP/RR and a
Divergence row, and the attached image should show the QM structure on the
price panel plus the RSI divergence connector on the panel underneath.
Revert `config.yaml` once this looks right.

## 8. Run it as a background service — `qmbotctl.py`

The smallest timeframe is 1H, so a bar closes at most once an hour — there is
no benefit to scanning more often than that (the detector ignores unclosed
bars by design). `bot.py --loop` already does its own hourly scheduling;
`qmbotctl.py` wraps that in start/stop/status commands plus daily log files,
so no `cron` entry is needed.

```bash
python qmbotctl.py start          # launches the bot in the background (hourly scan),
                                   # then streams the live log — Ctrl+C only detaches,
                                   # the bot keeps running
python qmbotctl.py start --no-attach   # start and return immediately, no log stream
python qmbotctl.py start --keep-awake  # also prevent this Mac from idle/AC sleep
                                        # while the bot is running (see below)
python qmbotctl.py status         # is it running? PID? since when?
python qmbotctl.py logs -f        # attach to the live log from another terminal
python qmbotctl.py stop           # stop the background process
```

**What happens if the Mac sleeps.** System sleep suspends the whole machine at
the kernel level — the bot process is paused, not killed, and resumes on its
own when the Mac wakes (`qmbotctl.py status` shows it running the entire
time). The real risk isn't the process dying, it's **missed signals**: a QM
pattern that triggers while the Mac is asleep can fall outside
`fresh_bars` (how many recent closed bars still count as "new") by the time
the bot wakes and finally scans, and gets silently skipped — no error, no
retry. The longer the sleep, the more likely that is.

`--keep-awake` uses macOS's built-in `caffeinate` to hold a sleep-prevention
assertion for exactly as long as the bot process lives (it releases itself
automatically on `stop` or a crash — nothing to clean up manually). It only
prevents *idle* sleep and sleep-while-on-AC-power; it does **not** override
closing a MacBook's lid with no external display attached — that's a
hardware clamshell-sleep policy no software assertion can touch. If this bot
needs to run unattended on a laptop that gets closed and carried around, keep
it plugged in with the lid open, or move it to a machine that's always on.

Logs are written to `logs/YYYY-MM-DD.log` (one plain-text file per day,
rolling over automatically at midnight) as well as to the console when
attached. Crashes that happen outside the bot's own per-scan error handling
(e.g. a bad import) land in `qmbot.crash.log` as a last-resort net.

## 9. Deploying to Google Cloud (always-on, no sleep issues)

Running this on a Mac means it stops scanning whenever the Mac sleeps (see
`--keep-awake` above, which only gets you so far — it can't override a
closed laptop lid). A small always-on Compute Engine VM avoids that
entirely. What's already set up (currently deployed):

- **Instance**: `qm-bot`, e2-micro, Debian 12, zone `asia-southeast1-a`
  (Singapore)
- **Why Singapore, not a US free-tier region**: Binance returns HTTP 451
  ("restricted location") to US-based IPs — this is a hard geo-block, not
  something fixable in code, and Binance.US (the separate US platform)
  doesn't offer futures trading at all. This means the VM does **not**
  qualify for GCP's Always Free e2-micro (only available in
  us-west1/us-central1/us-east1) — expect roughly $7-8/month.
- **Supervision**: a systemd unit (`deploy/qmbot.service`) runs
  `bot.py --loop --interval 3600` as a dedicated `qmbot` user, auto-restarts
  on crash, and auto-starts on VM reboot (`systemctl enable`d already).
  This is more robust than `qmbotctl.py` for an unattended server — no
  Ctrl+C/caffeinate concerns exist here, systemd's default SIGTERM-to-stop
  is exactly what `bot.py --loop` already expects.

**Operating the VM:**
```bash
# status / logs
gcloud compute ssh qm-bot --zone=asia-southeast1-a --command="sudo systemctl status qmbot --no-pager"
gcloud compute ssh qm-bot --zone=asia-southeast1-a --command="tail -f /opt/qmbot/logs/\$(date +%Y-%m-%d).log"

# stop / start / restart
gcloud compute ssh qm-bot --zone=asia-southeast1-a --command="sudo systemctl stop qmbot"
gcloud compute ssh qm-bot --zone=asia-southeast1-a --command="sudo systemctl start qmbot"

# tear down entirely (stops billing)
gcloud compute instances delete qm-bot --zone=asia-southeast1-a
```

**Redeploying after a code change** — re-sync files and re-run setup (idempotent):
```bash
rsync -av --exclude='.venv' --exclude='__pycache__' --exclude='logs' \
  --exclude='data' --exclude='*.pid' --exclude='qmbot.crash.log' \
  --exclude='signals.db' --exclude='universe_cache.json' \
  --exclude='.DS_Store' --exclude='bot.log' --exclude='userid.txt' \
  ./ /tmp/qm-bot-deploy/
gcloud compute scp --recurse /tmp/qm-bot-deploy/* qm-bot:/opt/qmbot/ --zone=asia-southeast1-a
gcloud compute scp /tmp/qm-bot-deploy/.env qm-bot:/opt/qmbot/ --zone=asia-southeast1-a  # dotfiles need listing separately — `*` doesn't match them
gcloud compute ssh qm-bot --zone=asia-southeast1-a --command="sudo bash /opt/qmbot/deploy/setup_vm.sh"
```

Note that `signals.db` (dedupe state) now lives only on the VM, not on your
Mac — don't run `bot.py` in both places against the same LINE account or
you'll get duplicate alerts from two independent dedupe stores.

## 10. Backtest before trusting live signals

```bash
python qm_detector.py --csv data/BTCUSDT_1h.csv --symbol BTC/USDT --timeframe 1h  # sanity
python backtest.py --csv data/BTCUSDT_1h.csv --symbol BTC/USDT --timeframe 1h --split 0.3
```
Report trades / win rate / expectancy (R) / profit factor / max drawdown —
win rate alone is misleading for an RR-gated strategy. Check in-sample vs
out-of-sample don't diverge wildly (overfitting) before trusting the bot.

## Notes

- **HTF (higher-timeframe) structure filter** (`htf_filter` in `config.yaml`,
  enabled by default): rejects a 1H signal that clearly fights the 4H trend
  (a bearish signal while 4H is making higher-highs/higher-lows, or the
  mirror). This is the single highest-value confluence filter per the
  skill's own theory doc and the multi-timeframe research behind it — see
  `htf_filter.py`. It only ever removes signals, never adds ones the RR/
  divergence gates wouldn't have found, so expect noticeably *fewer* signals
  than before this was added — that's the intended tradeoff (fewer, higher
  quality). Set `htf_filter.enabled: false` to turn it off and compare via
  `backtest.py --split`.
- `signals.db` (SQLite) de-dupes by `signal_id`, keyed on the QM head bar's
  timestamp — never delete it while the bot is live, or you'll get repeat
  alerts for patterns already sent.
- `universe_cache.json` holds the universe list (`universe.top_n` in
  `config.yaml`, currently 50) for 24h; delete it to force an immediate
  refresh.
- Every LINE message carries the disclaimer *"สัญญาณอัตโนมัติเพื่อการศึกษา
  ไม่ใช่คำแนะนำการลงทุน"* — this is an alerting tool, not investment advice,
  and it does not place any orders.
- LINE free-tier quota is a few hundred messages/month. With `universe.top_n`
  symbols × 2 timeframes each, tune `min_rr` up in `config.yaml` first if
  you're getting more signals than your plan can take — see the skill's
  `references/line-messaging-api.md` for the quota math. A larger `top_n`
  (currently 50) means more scan work and a higher ceiling on how many
  signals could fire in a busy hour — watch `qmbotctl.py logs -f` for a
  few days and see actual volume before assuming the default is right.
