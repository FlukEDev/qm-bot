"""
SignalStore — remembers which QM signals were already sent to LINE.

Every QM stays "valid" for many bars after it triggers, so without this the
user gets the same alert on every single scan until the pattern expires or
gets invalidated. Keyed on the head bar's TIMESTAMP (never its index — see
qm_detector.QMSignal.__post_init__ for why an index-keyed store silently
resends signals as the rolling fetch window shifts).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


class SignalStore:
    def __init__(self, path: str = "signals.db"):
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS sent ("
            " signal_id TEXT PRIMARY KEY, symbol TEXT, timeframe TEXT,"
            " direction TEXT, entry REAL, sl REAL, tp1 REAL, rr REAL,"
            " divergence_confirmed INTEGER, sent_at TEXT)"
        )
        self.conn.commit()

    def is_new(self, signal_id: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM sent WHERE signal_id = ?", (signal_id,))
        return cur.fetchone() is None

    def mark(self, s) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO sent VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                s.signal_id, s.symbol, s.timeframe, s.direction,
                s.entry, s.stop_loss, s.take_profit_1, s.risk_reward,
                int(bool(getattr(s, "divergence_confirmed", False))),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()
