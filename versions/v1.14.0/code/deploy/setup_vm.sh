#!/usr/bin/env bash
# Runs ON the GCP VM (as root, via `gcloud compute ssh ... --command`) after
# the project files have already been copied to /opt/qmbot via scp.
#
# Idempotent: safe to re-run after a code update (re-scp files, then re-run
# this) — it just reinstalls deps and restarts the service.
set -euo pipefail

echo "--- setting timezone to Asia/Bangkok ---"
# GCP VMs default to UTC regardless of region. Bangkok time makes the daily
# log files (logs/YYYY-MM-DD.log) roll over at Thailand midnight instead of
# UTC midnight, and journalctl/qmbotctl-style timestamps read naturally for
# a Thailand-based operator. LINE messages/chart timestamps are converted to
# Bangkok time separately in code (see timeutil.py) — that conversion does
# not depend on this system timezone setting, but both are set to match.
timedatectl set-timezone Asia/Bangkok

echo "--- installing system packages ---"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip

echo "--- creating dedicated service user ---"
id -u qmbot &>/dev/null || useradd -m -s /usr/sbin/nologin qmbot

echo "--- setting up venv + dependencies ---"
cd /opt/qmbot
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "--- fixing ownership / permissions ---"
chown -R qmbot:qmbot /opt/qmbot
chmod 600 /opt/qmbot/.env

echo "--- installing systemd units ---"
cp /opt/qmbot/deploy/qmbot.service /etc/systemd/system/qmbot.service
cp /opt/qmbot/deploy/qmbot-daily.service /etc/systemd/system/qmbot-daily.service
cp /opt/qmbot/deploy/qmbot-daily.timer /etc/systemd/system/qmbot-daily.timer
systemctl daemon-reload
systemctl enable qmbot
systemctl restart qmbot
# The daily report is driven by the TIMER; the .service is what the timer
# starts, so only the timer gets enabled.
systemctl enable --now qmbot-daily.timer

sleep 2
echo "--- status ---"
systemctl status qmbot --no-pager -l | head -15
echo "--- daily report timer ---"
systemctl list-timers qmbot-daily.timer --no-pager
