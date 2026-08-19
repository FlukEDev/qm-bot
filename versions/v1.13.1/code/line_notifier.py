"""
LINE Messaging API sender for QM signals.

LINE Notify shut down on 2025-03-31. Anything still calling notify-api.line.me
is dead code — this module uses the Messaging API instead.

Quota note: push / broadcast / multicast all count against the plan quota and
are billed PER RECIPIENT, not per message object. Bundling the Flex bubble and
the chart image into one request (up to 5 message objects) therefore costs the
same as sending the bubble alone.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Sequence

import requests

from timeutil import format_bangkok

API_BASE = "https://api.line.me/v2/bot"
TIMEOUT = 15


class LineError(RuntimeError):
    pass


class LineNotifier:
    def __init__(self, channel_access_token: str | None = None, disclaimer: str | None = None):
        self.token = channel_access_token or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
        if not self.token:
            raise LineError("LINE_CHANNEL_ACCESS_TOKEN is not set")
        self.disclaimer = disclaimer or "สัญญาณอัตโนมัติเพื่อการศึกษา ไม่ใช่คำแนะนำการลงทุน"

    # ------------------------------------------------------------------ #
    def _post(self, path: str, payload: dict, retries: int = 3) -> None:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            # A retry key makes a repeated request idempotent, so a network
            # timeout does not turn into a duplicate alert in the user's chat.
            "X-Line-Retry-Key": str(uuid.uuid4()),
        }
        for attempt in range(retries):
            r = requests.post(f"{API_BASE}{path}", json=payload, headers=headers, timeout=TIMEOUT)
            if r.status_code == 200:
                return
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2**attempt)
                continue
            # 400 = malformed message object, 403 = quota exhausted or plan limit
            raise LineError(f"LINE {r.status_code}: {r.text}")
        raise LineError("LINE API unavailable after retries")

    def push(self, to: str, messages: Sequence[dict]) -> None:
        self._post("/message/push", {"to": to, "messages": list(messages)[:5]})

    def broadcast(self, messages: Sequence[dict]) -> None:
        self._post("/message/broadcast", {"messages": list(messages)[:5]})

    # ------------------------------------------------------------------ #
    def send_signal(
        self,
        signal,
        to: str | None = None,
        chart_url: str | None = None,
        size_text: str | None = None,
    ) -> None:
        """Send one QM signal as Flex bubble (+ chart image if hosted)."""
        messages = [flex_signal(signal, self.disclaimer, size_text)]
        if chart_url:
            if not chart_url.startswith("https://"):
                raise LineError("chart_url must be HTTPS — LINE fetches it itself")
            messages.append(
                {"type": "image", "originalContentUrl": chart_url, "previewImageUrl": chart_url}
            )
        if to:
            self.push(to, messages)
        else:
            self.broadcast(messages)


# ---------------------------------------------------------------------- #
# Flex bubble
# ---------------------------------------------------------------------- #
def _fmt(x: float) -> str:
    if abs(x) >= 100:
        return f"{x:,.2f}"
    if abs(x) >= 1:
        return f"{x:,.4f}"
    return f"{x:,.6f}"


def _row(label: str, value: str, colour: str = "#DDDDDD", bold: bool = False) -> dict:
    return {
        "type": "box",
        "layout": "horizontal",
        "contents": [
            {"type": "text", "text": label, "size": "sm", "color": "#8C8C8C", "flex": 4},
            {
                "type": "text",
                "text": value,
                "size": "sm",
                "color": colour,
                "flex": 6,
                "align": "end",
                "weight": "bold" if bold else "regular",
            },
        ],
    }


def flex_signal(signal, disclaimer: str, size_text: str | None = None) -> dict:
    """Flex bubble tuned for a trading signal.

    altText is what shows in the chat list and in the push notification, so it
    carries the three things a trader needs before opening the app: direction,
    symbol, entry.
    """
    is_sell = signal.direction == "bearish"
    accent = "#EF5350" if is_sell else "#26A69A"
    side = "SELL" if is_sell else "BUY"
    tag = "Over-QM" if getattr(signal, "overshoot", False) else "QM"

    body = [
        _row("Entry (QML)", _fmt(signal.entry), "#FFFFFF", bold=True),
        _row("Stop Loss", _fmt(signal.stop_loss), "#EF5350"),
        _row("TP1", _fmt(signal.take_profit_1), "#26A69A"),
        _row("TP2", _fmt(signal.take_profit_2), "#26A69A"),
        {"type": "separator", "margin": "md", "color": "#333333"},
        _row("R:R", f"1 : {signal.risk_reward}", "#FFD54F", bold=True),
    ]

    confirmed = getattr(signal, "divergence_confirmed", None)
    if confirmed is not None:
        rsi_ls = getattr(signal, "rsi_ls", None)
        rsi_head = getattr(signal, "rsi_head", None)
        rsi_text = f"{rsi_ls:.0f} → {rsi_head:.0f}" if rsi_ls is not None and rsi_head is not None else "-"
        body.append(
            _row(
                "Divergence",
                f"RSI {'✓' if confirmed else '✗'}  ({rsi_text})",
                "#26A69A" if confirmed else "#8C8C8C",
                bold=confirmed,
            )
        )

    grade = getattr(signal, "ls_grade", None)
    if grade and grade != "?":
        ls_diff = getattr(signal, "ls_diff", None)
        colour = {"A": "#26A69A", "B": "#FFD54F"}.get(grade, "#8C8C8C")
        level = {"A": "สูง", "B": "กลาง"}.get(grade, "ต่ำ")
        # ls_diff is already normalised so positive = momentum faded in the
        # direction being traded. Print it with its own sign rather than a
        # hardcoded minus: on a BUY the underlying RSI has to RISE for the
        # signal to be good, so a fixed "−" would state the opposite.
        detail = f" (RSI {ls_diff:+.0f})" if ls_diff is not None else ""
        body.append(_row(f"เกรด {grade}", f"{level}{detail}", colour, bold=(grade == "A")))

    structure = getattr(signal, "htf_structure", None)
    if structure is not None:
        struct_colour = {"bullish": "#26A69A", "bearish": "#EF5350"}.get(structure, "#8C8C8C")
        body.append(_row("4H Trend", structure.upper(), struct_colour))

    if size_text:
        body.append(_row("Size", size_text, "#DDDDDD"))
    body.append(_row("Time", f"{format_bangkok(signal.trigger_time)} ICT", "#8C8C8C"))

    return {
        "type": "flex",
        "altText": f"{side} {signal.symbol} {signal.timeframe} @ {_fmt(signal.entry)} (QM)",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": accent,
                "paddingAll": "12px",
                "contents": [
                    {
                        "type": "text",
                        "text": f"{side}  ·  {tag}",
                        "color": "#FFFFFF",
                        "weight": "bold",
                        "size": "lg",
                    },
                    {
                        "type": "text",
                        "text": f"{signal.symbol}   {signal.timeframe}",
                        "color": "#FFFFFF",
                        "size": "sm",
                    },
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#1E222D",
                "spacing": "sm",
                "paddingAll": "14px",
                "contents": body,
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#1E222D",
                "paddingAll": "10px",
                "contents": [
                    {
                        "type": "text",
                        "text": disclaimer,
                        "size": "xxs",
                        "color": "#6E6E6E",
                        "wrap": True,
                    }
                ],
            },
        },
    }


def text_signal(signal, disclaimer: str) -> dict:
    """Plain-text fallback — useful while debugging, or if Flex renders oddly."""
    side = "🔴 SELL" if signal.direction == "bearish" else "🟢 BUY"
    confirmed = getattr(signal, "divergence_confirmed", None)
    div_line = f"Div   : {'RSI confirmed' if confirmed else 'not confirmed'}\n" if confirmed is not None else ""
    return {
        "type": "text",
        "text": (
            f"{side}  {signal.symbol} {signal.timeframe}  [QM]\n"
            f"Entry : {_fmt(signal.entry)}\n"
            f"SL    : {_fmt(signal.stop_loss)}\n"
            f"TP1   : {_fmt(signal.take_profit_1)}\n"
            f"TP2   : {_fmt(signal.take_profit_2)}\n"
            f"R:R   : 1 : {signal.risk_reward}\n"
            f"{div_line}"
            f"{format_bangkok(signal.trigger_time)} ICT\n\n{disclaimer}"
        ),
    }
