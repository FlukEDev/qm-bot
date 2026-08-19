"""
Bangkok-time display helper — the ONE place timezone conversion happens.

Detection/data logic (qm_detector.py, divergence.py, bot.py's OHLCV fetch)
stays UTC throughout on purpose, per the skill's own guidance: converting
timezone at the data layer shifts bar boundaries (a "1h" candle starting at
07:00 ICT is a different bar than one starting at 00:00 UTC) and would
silently desync backtests from live behavior. Conversion happens only here,
at the final display step — LINE messages and chart axis labels.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

BANGKOK = ZoneInfo("Asia/Bangkok")
UTC = ZoneInfo("UTC")


def format_bangkok(ts: str | datetime, fmt: str = "%d/%m %H:%M") -> str:
    """Parse a UTC(-ish) timestamp — string or datetime, naive or aware —
    and format it in Bangkok local time. Used for anything a human reads:
    the LINE Flex bubble's Time row, the plain-text fallback message, etc.
    """
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(BANGKOK).strftime(fmt)
