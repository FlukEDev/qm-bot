"""
สร้าง snapshot ของโค้ดเป็นเวอร์ชันใหม่ในโฟลเดอร์ versions/

ใช้ทุกครั้งที่มีการเปลี่ยนแปลงโปรแกรม เพื่อเก็บสำเนาโค้ด ณ จุดนั้นไว้
พร้อมไฟล์ CHANGES.txt อธิบายว่าเปลี่ยนอะไรบ้าง

    python make_version.py 1.8.0 "เพิ่มตัวกรอง volume"
    python make_version.py 1.8.0 "เพิ่มตัวกรอง volume" --note "รายละเอียดเพิ่มเติม..."

สิ่งที่สคริปต์ทำให้อัตโนมัติ:
  1. คัดลอกไฟล์โค้ดทั้งหมดไปไว้ที่ versions/vX.Y.Z/code/
  2. เทียบกับเวอร์ชันก่อนหน้า แล้วสรุปว่าไฟล์ไหน เพิ่ม/แก้ไข/ลบ
  3. สร้าง CHANGES.txt (ถ้ามีอยู่แล้วจะไม่เขียนทับ)
  4. อัปเดตสารบัญที่ versions/INDEX.md

ความปลอดภัย: .env และไฟล์ความลับอื่นๆ จะไม่ถูกคัดลอกเด็ดขาด (ดู EXCLUDE)
เพราะโฟลเดอร์ versions/ ถูก commit ขึ้น git
"""

from __future__ import annotations

import argparse
import filecmp
import re
import shutil
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSIONS = ROOT / "versions"
# ปลายทางบน Google Drive — ตั้งค่า remote ชื่อ gdrive ครั้งเดียวด้วย `rclone config`
DEFAULT_REMOTE = "gdrive:QM-Bot/versions"
BANGKOK = timezone(timedelta(hours=7))

# ห้ามคัดลอกเข้า snapshot เด็ดขาด — ความลับ, ไฟล์ที่สร้างใหม่ได้, และตัว versions เอง
EXCLUDE_DIRS = {".venv", "__pycache__", "versions", "logs", ".git", "data"}
EXCLUDE_FILES = {
    ".env", "signals.db", "universe_cache.json", "userid.txt",
    "qmbot.pid", "qmbot.crash.log", "bot.log", ".DS_Store",
}
EXCLUDE_SUFFIX = {".pyc", ".png", ".log"}


def collect_files() -> list[Path]:
    out = []
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if p.name in EXCLUDE_FILES or p.suffix in EXCLUDE_SUFFIX:
            continue
        out.append(rel)
    return out


# X.Y.Z พร้อมส่วนต่อท้าย pre-release ที่ไม่บังคับ (เช่น v1.23.0-beta)
VERSION_RE = re.compile(r"v?\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?")


def version_key(name: str) -> tuple:
    """คีย์สำหรับเรียงเวอร์ชัน — pre-release มาก่อนตัวจริงตามธรรมเนียม semver

    ต้องใช้ตัวเดียวกันทุกที่ ไม่งั้นสารบัญกับการหาเวอร์ชันก่อนหน้าจะเรียงคนละแบบ
    """
    core, _, pre = name.lstrip("v").partition("-")
    return tuple(int(x) for x in core.split(".")) + (0 if pre else 1,)


def previous_version(current: str) -> str | None:
    key = version_key
    existing = []
    for d in VERSIONS.iterdir() if VERSIONS.exists() else []:
        if d.is_dir() and VERSION_RE.fullmatch(d.name):
            existing.append(d.name)
    earlier = [v for v in existing if key(v) < key(f"v{current}")]
    return max(earlier, key=key) if earlier else None


def diff_against(prev_code: Path, files: list[Path]) -> tuple[list, list, list]:
    added, modified, removed = [], [], []
    for rel in files:
        old = prev_code / rel
        if not old.exists():
            added.append(rel)
        elif not filecmp.cmp(ROOT / rel, old, shallow=False):
            modified.append(rel)
    if prev_code.exists():
        current = set(files)
        for p in prev_code.rglob("*"):
            if p.is_file() and p.relative_to(prev_code) not in current:
                removed.append(p.relative_to(prev_code))
    return added, modified, removed


def rebuild_index() -> None:
    rows = []
    for d in sorted(VERSIONS.iterdir()):
        if not (d.is_dir() and VERSION_RE.fullmatch(d.name)):
            continue
        changes = d / "CHANGES.txt"
        date, summary = "-", "-"
        if changes.exists():
            for line in changes.read_text(encoding="utf-8").splitlines():
                if line.startswith("วันที่:"):
                    date = line.split(":", 1)[1].strip()
                elif line.startswith("สรุป:"):
                    summary = line.split(":", 1)[1].strip()
        has_code = "✓" if (d / "code").exists() else "—"
        rows.append((d.name, date, has_code, summary))

    def key(r):
        return version_key(r[0])

    rows.sort(key=key, reverse=True)

    lines = [
        "# สารบัญเวอร์ชัน — QM Pattern Signal Bot",
        "",
        "ทุกครั้งที่มีการเปลี่ยนแปลงโปรแกรม จะเก็บสำเนาโค้ดไว้ที่ `versions/vX.Y.Z/code/`",
        "พร้อมไฟล์ `CHANGES.txt` อธิบายว่าเปลี่ยนอะไรและทำไม",
        "",
        "สร้างเวอร์ชันใหม่ด้วย:",
        "```bash",
        'python make_version.py 1.8.0 "คำอธิบายสั้นๆ"',
        "```",
        "",
        "| เวอร์ชัน | วันที่ | มีโค้ด | สรุปการเปลี่ยนแปลง |",
        "|---|---|---|---|",
    ]
    for name, date, has_code, summary in rows:
        lines.append(f"| [{name}]({name}/CHANGES.txt) | {date} | {has_code} | {summary} |")
    lines += [
        "",
        "**หมายเหตุเรื่องคอลัมน์ \"มีโค้ด\":** เวอร์ชันที่ขึ้น — คือเวอร์ชันที่เกิดขึ้น",
        "ก่อนจะเริ่มใช้ระบบเก็บเวอร์ชันนี้ จึงมีแต่บันทึกการเปลี่ยนแปลง ไม่มีสำเนาโค้ด",
        "(โค้ดตอนนั้นถูกแก้ทับไปแล้วก่อนที่จะมีระบบนี้ การสร้างย้อนหลังจะได้ไฟล์ที่",
        "ไม่เคยถูกทดสอบจริง จึงไม่ทำ)",
        "",
    ]
    (VERSIONS / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")


def sync_to_drive(remote: str, quiet: bool = False) -> bool:
    """ส่งโฟลเดอร์ versions/ ทั้งหมดขึ้น Google Drive ด้วย rclone

    ใช้ rclone แทน connector ของ Claude เพราะสคริปต์นี้ต้องรันได้ด้วยตัวเอง
    (ทั้งตอนสั่งเองและตอนรันบน VM) ไม่ใช่เฉพาะตอนที่มีเซสชันคุยกับ Claude อยู่

    เงียบๆ ข้ามไปถ้ายังไม่ได้ตั้งค่า rclone — การสร้างเวอร์ชันต้องไม่พังเพราะ
    เรื่องอัปโหลด ตัว snapshot บนเครื่องคือของจริงเสมอ Drive เป็นสำเนา
    """
    if not shutil.which("rclone"):
        print("  (ไม่พบ rclone — ข้ามการ sync ขึ้น Drive)")
        return False
    check = subprocess.run(["rclone", "listremotes"], capture_output=True, text=True)
    name = remote.split(":")[0] + ":"
    if name not in check.stdout:
        print(f"  (ยังไม่ได้ตั้งค่า remote '{name}' ใน rclone — ข้ามการ sync)")
        print("   ตั้งค่าครั้งเดียวด้วย: rclone config")
        return False

    cmd = ["rclone", "sync", str(VERSIONS), remote, "--create-empty-src-dirs"]
    if not quiet:
        cmd.append("--progress")
    print(f"  กำลัง sync ขึ้น {remote} ...")
    r = subprocess.run(cmd, capture_output=quiet, text=True)
    if r.returncode == 0:
        print(f"  sync ขึ้น Drive สำเร็จ -> {remote}")
        return True
    print(f"  sync ล้มเหลว (exit {r.returncode}) — snapshot บนเครื่องยังอยู่ครบ")
    if quiet and r.stderr:
        print("   " + r.stderr.strip().splitlines()[-1][:160])
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("version", help="เช่น 1.8.0")
    ap.add_argument("summary", help="สรุปสั้นๆ ว่าเปลี่ยนอะไร")
    ap.add_argument("--note", default="", help="รายละเอียดเพิ่มเติม")
    ap.add_argument("--index-only", action="store_true", help="สร้างสารบัญใหม่อย่างเดียว")
    ap.add_argument("--drive-remote", default=DEFAULT_REMOTE,
                    help=f"ปลายทาง rclone (ค่าเริ่มต้น {DEFAULT_REMOTE})")
    ap.add_argument("--no-drive", action="store_true", help="ไม่ต้อง sync ขึ้น Drive รอบนี้")
    ap.add_argument("--sync-only", action="store_true",
                    help="sync versions/ ขึ้น Drive อย่างเดียว ไม่สร้างเวอร์ชันใหม่")
    args = ap.parse_args()

    if args.sync_only:
        sync_to_drive(args.drive_remote)
        return

    VERSIONS.mkdir(exist_ok=True)
    if args.index_only:
        rebuild_index()
        print("อัปเดต versions/INDEX.md แล้ว")
        return

    # อนุญาตส่วนต่อท้ายแบบ pre-release (เช่น 1.23.0-beta) สำหรับเวอร์ชันที่
    # ยังทดลองอยู่และยังไม่ push ขึ้น GitHub — จะได้เก็บ snapshot ไว้อ้างอิงได้
    # เหมือนเวอร์ชันปกติ โดยไม่ปนกับเวอร์ชันที่ถือว่าเสร็จแล้ว
    if not VERSION_RE.fullmatch(args.version):
        raise SystemExit("รูปแบบเวอร์ชันต้องเป็น X.Y.Z หรือ X.Y.Z-ชื่อ เช่น 1.8.0 หรือ 1.23.0-beta")

    vdir = VERSIONS / f"v{args.version}"
    code = vdir / "code"
    if code.exists():
        raise SystemExit(f"มี {code} อยู่แล้ว — ใช้เลขเวอร์ชันใหม่ หรือลบโฟลเดอร์เดิมก่อน")

    files = collect_files()
    prev = previous_version(args.version)
    added, modified, removed = ([], [], [])
    if prev:
        added, modified, removed = diff_against(VERSIONS / prev / "code", files)

    code.mkdir(parents=True)
    for rel in files:
        dest = code / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dest)

    changes = vdir / "CHANGES.txt"
    if not changes.exists():
        now = datetime.now(BANGKOK).strftime("%Y-%m-%d %H:%M น. (เวลาไทย)")
        body = [
            f"เวอร์ชัน: v{args.version}",
            f"วันที่: {now}",
            f"สรุป: {args.summary}",
            f"เทียบกับ: {prev if prev else '(เวอร์ชันแรก)'}",
            "",
            "=" * 66,
            "รายละเอียดการเปลี่ยนแปลง",
            "=" * 66,
            "",
            args.note or "(ยังไม่ได้เขียนรายละเอียด)",
            "",
            "=" * 66,
            "ไฟล์ที่เปลี่ยน",
            "=" * 66,
            "",
        ]
        for label, group in (("เพิ่มใหม่", added), ("แก้ไข", modified), ("ลบออก", removed)):
            if group:
                body.append(f"[{label}]")
                body += [f"  - {p}" for p in group]
                body.append("")
        if not (added or modified or removed):
            body.append("(ไม่มีการเปลี่ยนแปลง หรือเป็นเวอร์ชันแรก)")
            body.append("")
        body += [
            "=" * 66,
            f"สำเนาโค้ดทั้งหมด {len(files)} ไฟล์ อยู่ในโฟลเดอร์ code/",
            "=" * 66,
            "",
        ]
        changes.write_text("\n".join(body), encoding="utf-8")

    rebuild_index()
    print(f"สร้าง {vdir.relative_to(ROOT)} แล้ว — {len(files)} ไฟล์")
    print(f"  เพิ่มใหม่ {len(added)} / แก้ไข {len(modified)} / ลบ {len(removed)}")
    print(f"  แก้รายละเอียดเพิ่มเติมได้ที่ {changes.relative_to(ROOT)}")

    if not args.no_drive:
        sync_to_drive(args.drive_remote, quiet=True)


if __name__ == "__main__":
    main()
