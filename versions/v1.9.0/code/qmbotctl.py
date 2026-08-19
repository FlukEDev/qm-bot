"""
CLI process manager for the QM signal bot — start/stop/status/logs.

This runs bot.py as a detached background process on an hourly loop
(bot.py's own --loop --interval, no cron needed) and gives you commands to
control it and watch its output:

    python qmbotctl.py start           # start hourly scanning in the background,
                                        # then stream the live log until Ctrl+C
                                        # (Ctrl+C only detaches — the bot keeps running)
    python qmbotctl.py start --no-attach   # start and return immediately, no log stream
    python qmbotctl.py status          # is it running? since when?
    python qmbotctl.py logs -f         # attach to the live log from another terminal
    python qmbotctl.py stop            # stop the background process

Logs are written by bot.py itself via logging_setup.DailyFileHandler to
logs/YYYY-MM-DD.log — this script only starts/stops the process and tails
whatever file is "today's" file at the moment you ask.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PID_FILE = SCRIPT_DIR / "qmbot.pid"
LOG_DIR = SCRIPT_DIR / "logs"
CRASH_LOG = SCRIPT_DIR / "qmbot.crash.log"


def _today_log_path() -> Path:
    return LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log"


def _read_pid() -> tuple[int, str] | None:
    if not PID_FILE.exists():
        return None
    try:
        pid_str, started_at = PID_FILE.read_text().strip().split("\n")
        return int(pid_str), started_at
    except (ValueError, OSError):
        return None


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists, just owned by someone else — treat as alive


def _bot_python() -> str:
    """Prefer this project's own venv interpreter over whatever ran
    qmbotctl.py itself. qmbotctl.py only needs the stdlib, so it happily runs
    under a bare `python3` — but if that's also used to spawn bot.py, bot.py
    dies instantly with ModuleNotFoundError (pandas/ccxt/etc. only live in
    .venv). Resolving the venv path here means `python3 qmbotctl.py start`
    works correctly whether or not you remembered to activate the venv."""
    venv_python = SCRIPT_DIR / ".venv" / "bin" / "python"
    return str(venv_python) if venv_python.exists() else sys.executable


def _start_keep_awake(bot_pid: int) -> None:
    """Hold a macOS `caffeinate` sleep-prevention assertion for exactly as
    long as the bot process is alive (`-w` ties its lifetime to bot_pid, so
    it releases itself automatically on stop/crash — nothing to clean up).

    Only prevents IDLE sleep and sleep-while-on-AC-power (`-i -s`). It does
    NOT override closing a MacBook's lid with no external display attached —
    that's a hardware clamshell-sleep policy caffeinate can't touch. This is
    also a real gap either way: `bot.py` only alerts on signals within the
    last `fresh_bars` closed bars, so any pattern that triggers while the
    Mac is genuinely asleep can be missed silently once it wakes.
    """
    if sys.platform != "darwin":
        print("--keep-awake ใช้ได้เฉพาะ macOS (caffeinate) — ข้ามการตั้งค่านี้")
        return
    try:
        subprocess.Popen(
            ["caffeinate", "-i", "-s", "-w", str(bot_pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        print("กันเครื่อง sleep แล้ว (caffeinate) — จะปิดเองอัตโนมัติเมื่อบอทหยุด")
        print("หมายเหตุ: กันได้เฉพาะ sleep จากไม่มีการใช้งาน/ตอนเสียบปลั๊ก ไม่กันการปิดฝาเครื่อง (clamshell) ถ้าไม่ได้ต่อจอนอก")
    except FileNotFoundError:
        print("ไม่พบคำสั่ง caffeinate — ข้ามการตั้งค่ากันเครื่อง sleep")


def start(args: argparse.Namespace) -> None:
    existing = _read_pid()
    if existing and _is_alive(existing[0]):
        print(f"บอทกำลังทำงานอยู่แล้ว (PID {existing[0]}, เริ่มเมื่อ {existing[1]})")
        print("ใช้ 'python qmbotctl.py logs -f' เพื่อดู log สด หรือ 'stop' เพื่อหยุด")
        return

    cmd = [
        _bot_python(), str(SCRIPT_DIR / "bot.py"),
        "--config", args.config,
        "--loop", "--interval", str(args.interval),
    ]
    LOG_DIR.mkdir(exist_ok=True)
    crash_f = open(CRASH_LOG, "a", encoding="utf-8")
    crash_f.write(f"\n--- started {datetime.now().isoformat()} ---\n")
    crash_f.flush()

    proc = subprocess.Popen(
        cmd,
        cwd=str(SCRIPT_DIR),
        stdout=subprocess.DEVNULL,
        stderr=crash_f,
        start_new_session=True,  # detach from this terminal so it survives Ctrl+C / logout
    )

    # bot.py fails fast on a bad import, missing config, or bad credentials —
    # give it a moment and check it's actually still alive before telling the
    # user it started. Without this, a crash 50ms in looks identical to a
    # healthy start and the only trace is a line in qmbot.crash.log nobody
    # thinks to check.
    time.sleep(1.0)
    if proc.poll() is not None:
        crash_f.close()
        print(f"บอทเริ่มไม่สำเร็จ — ออกจากการทำงานทันที (exit code {proc.returncode})")
        print(f"--- ท้าย {CRASH_LOG.name} ---")
        tail = CRASH_LOG.read_text(encoding="utf-8").strip().splitlines()[-15:]
        print("\n".join(tail))
        return

    PID_FILE.write_text(f"{proc.pid}\n{datetime.now().isoformat(timespec='seconds')}\n")

    if args.keep_awake:
        _start_keep_awake(proc.pid)

    interval_text = f"{args.interval // 60} นาที" if args.interval >= 60 else f"{args.interval} วินาที"
    print(f"เริ่มบอทแล้ว (PID {proc.pid}) — สแกนทุก {interval_text}")
    print(f"log วันนี้: {_today_log_path()}")

    if not args.no_attach:
        print("กำลังแสดง log สด — กด Ctrl+C เพื่อออก (บอทจะยังทำงานต่อในพื้นหลัง)\n")
        _follow(from_start=False)


def stop(args: argparse.Namespace) -> None:
    existing = _read_pid()
    if not existing or not _is_alive(existing[0]):
        print("บอทไม่ได้ทำงานอยู่")
        PID_FILE.unlink(missing_ok=True)
        return

    pid, _ = existing
    print(f"กำลังหยุดบอท (PID {pid}) ...")
    os.kill(pid, signal.SIGTERM)

    for _ in range(20):  # up to 10s for a graceful shutdown
        if not _is_alive(pid):
            break
        time.sleep(0.5)
    else:
        print("บอทไม่หยุดภายในเวลาที่กำหนด — บังคับปิด (SIGKILL)")
        os.kill(pid, signal.SIGKILL)

    PID_FILE.unlink(missing_ok=True)
    print("หยุดบอทแล้ว")


def status(args: argparse.Namespace) -> None:
    existing = _read_pid()
    if not existing or not _is_alive(existing[0]):
        if existing:
            PID_FILE.unlink(missing_ok=True)  # stale pidfile from a crash
        print("สถานะ: ไม่ได้ทำงาน (stopped)")
        return
    pid, started_at = existing
    print(f"สถานะ: กำลังทำงาน (running)\nPID: {pid}\nเริ่มเมื่อ: {started_at}")
    print(f"log วันนี้: {_today_log_path()}")


def _follow(from_start: bool) -> None:
    """Tail-follow whatever file is 'today's' log, switching files across midnight."""
    current_path = None
    fh = None
    try:
        while True:
            path = _today_log_path()
            if path != current_path:
                if fh:
                    fh.close()
                LOG_DIR.mkdir(exist_ok=True)
                path.touch(exist_ok=True)
                fh = open(path, "r", encoding="utf-8")
                if not from_start:
                    fh.seek(0, os.SEEK_END)
                current_path = path
                from_start = False  # only skip-to-end on the very first file

            line = fh.readline()
            if line:
                print(line, end="", flush=True)  # flush explicitly — stdout is
                                                   # fully buffered (not line-buffered)
                                                   # whenever it isn't a TTY, e.g. when
                                                   # piped or run under a supervisor
            else:
                time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n(ออกจากหน้าจอ log — บอทยังทำงานต่อในพื้นหลัง)")
    finally:
        if fh:
            fh.close()


def logs(args: argparse.Namespace) -> None:
    path = _today_log_path()
    if not path.exists():
        print(f"ยังไม่มี log สำหรับวันนี้ ({path})")
        if not args.follow:
            return
    else:
        lines = path.read_text(encoding="utf-8").splitlines()[-args.lines:]
        for line in lines:
            print(line)
    if args.follow:
        _follow(from_start=False)


def main() -> None:
    ap = argparse.ArgumentParser(description="ควบคุมบอทสัญญาณ QM (start/stop/status/logs)")
    sub = ap.add_subparsers(dest="command", required=True)

    p_start = sub.add_parser("start", help="เริ่มบอท สแกนทุกชั่วโมงในพื้นหลัง")
    p_start.add_argument("--config", default="config.yaml")
    p_start.add_argument("--interval", type=int, default=3600, help="วินาทีระหว่างการสแกน (ค่าเริ่มต้น 3600 = 1 ชม.)")
    p_start.add_argument("--no-attach", action="store_true", help="เริ่มแล้วคืนคำสั่งทันที ไม่แสดง log สด")
    p_start.add_argument("--keep-awake", action="store_true",
                          help="กันเครื่อง sleep ระหว่างบอททำงาน (macOS, caffeinate — ไม่กันปิดฝาเครื่อง)")
    p_start.set_defaults(func=start)

    p_stop = sub.add_parser("stop", help="หยุดบอทที่กำลังทำงานอยู่")
    p_stop.set_defaults(func=stop)

    p_status = sub.add_parser("status", help="เช็คว่าบอทกำลังทำงานอยู่หรือไม่")
    p_status.set_defaults(func=status)

    p_logs = sub.add_parser("logs", help="ดู log ของวันนี้")
    p_logs.add_argument("-f", "--follow", action="store_true", help="แสดง log สดต่อเนื่อง (เหมือน tail -f)")
    p_logs.add_argument("-n", "--lines", type=int, default=50, help="จำนวนบรรทัดล่าสุดที่แสดง (ค่าเริ่มต้น 50)")
    p_logs.set_defaults(func=logs)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        # stdout is fully (not line-) buffered whenever it isn't a TTY — piped,
        # redirected to a file, or run under a supervisor — which would delay
        # every message here, including "logs -f" output, until a large buffer
        # fills or the process exits normally. Force line buffering so output
        # is live regardless of how this is invoked.
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    main()
