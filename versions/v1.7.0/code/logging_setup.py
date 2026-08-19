"""
Logging setup shared by bot.py and qmbotctl.py: every log line goes to both
the console (so `qmbotctl start` can stream it live) and a text file named
after the current date — `logs/YYYY-MM-DD.log` — so history is kept per day
without any log-rotation configuration to get wrong.

Deliberately not `logging.handlers.TimedRotatingFileHandler`: that handler
names the *current* day's file without a date suffix and only renames it once
rotation happens at midnight, which means "today's" file doesn't actually
have today's date in its name until tomorrow. `DailyFileHandler` below opens
the correctly-named file for "today" from the very first line written.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from datetime import datetime


class DailyFileHandler(logging.Handler):
    def __init__(self, log_dir: str = "logs", encoding: str = "utf-8"):
        super().__init__()
        self.log_dir = log_dir
        self.encoding = encoding
        os.makedirs(log_dir, exist_ok=True)
        self._lock2 = threading.Lock()
        self._current_date: str | None = None
        self._stream = None
        self._open_for_today()

    def _path_for(self, date_str: str) -> str:
        return os.path.join(self.log_dir, f"{date_str}.log")

    def _open_for_today(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._current_date:
            if self._stream:
                self._stream.close()
            self._current_date = today
            self._stream = open(self._path_for(today), "a", encoding=self.encoding)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            with self._lock2:
                self._open_for_today()  # re-check every write so a long-running
                                         # process rolls over at midnight on its own
                msg = self.format(record)
                self._stream.write(msg + "\n")
                self._stream.flush()  # flushed immediately so `qmbotctl logs -f` is live, not buffered
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        with self._lock2:
            if self._stream:
                self._stream.close()
        super().close()


def setup_logging(log_dir: str = "logs", level: int = logging.INFO, console: bool = True) -> DailyFileHandler:
    """Configure the root logger once. Safe to call more than once — clears
    any handlers from a prior call first so logs don't get duplicated."""
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    file_handler = DailyFileHandler(log_dir)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    if console:
        # stdout, not the logging default of stderr: qmbotctl redirects the
        # child process's stderr into qmbot.crash.log as a last-resort net for
        # genuine uncaught crashes, and that file would otherwise fill up with
        # a duplicate of every line already written to the daily log file.
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(fmt)
        root.addHandler(console_handler)

    return file_handler
