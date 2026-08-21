"""
Render a QM signal as an annotated PNG: candles + QM structure + Entry/SL/TP
levels, plus an RSI panel with the divergence connector between LS and HEAD.

LINE will not accept raw bytes — it fetches the image from a public HTTPS URL —
so the output of this module has to be uploaded (see chart_uploader.py) before
it is sent. See references/line-messaging-api.md in the skill for hosting options.

Pure matplotlib (no mplfinance) so it runs on a bare container.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: no display on a server
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from divergence import rsi as compute_rsi
from timeutil import BANGKOK

UP, DOWN = "#26a69a", "#ef5350"
BG, FG, GRID = "#131722", "#d1d4dc", "#2a2e39"
DIV_COLOR = "#ffd54f"
# Last-swing grade colours — deliberately distinct from DIV_COLOR so the two
# divergence lines on the RSI panel stay tellable apart at a glance.
GRADE_COLORS = {"A": "#26a69a", "B": "#ff9800", "C": "#8c8c8c"}


def _candles(ax, df: pd.DataFrame) -> None:
    x = mdates.date2num(df.index.to_pydatetime())
    width = (x[1] - x[0]) * 0.7 if len(x) > 1 else 0.02
    for xi, (o, h, l, c) in zip(x, df[["open", "high", "low", "close"]].to_numpy()):
        col = UP if c >= o else DOWN
        ax.vlines(xi, l, h, color=col, linewidth=0.8, zorder=2)
        ax.add_patch(
            plt.Rectangle(
                (xi - width / 2, min(o, c)),
                width,
                max(abs(c - o), 1e-9),
                facecolor=col,
                edgecolor=col,
                zorder=3,
            )
        )


def render_signal(
    df: pd.DataFrame,
    signal,
    out_path: str | Path = "qm_signal.png",
    padding: int = 25,
    rsi_period: int = 14,
) -> str:
    """Draw the structure (LS / HEAD / RS) plus the Entry / SL / TP levels on
    the price panel, and RSI(14) with the LS->HEAD divergence connector on a
    panel underneath.

    The point of the picture is that a human can sanity-check the bot in two
    seconds — both the QM structure AND the divergence that confirmed it need
    to be visible, not just stated in text.
    """
    lo_i = max(0, signal.ls_idx - padding)
    hi_i = min(len(df) - 1, signal.trigger_idx + padding)
    view = df.iloc[lo_i : hi_i + 1]

    rsi_series = compute_rsi(df, rsi_period)

    fig, (ax, ax_rsi) = plt.subplots(
        2, 1, figsize=(12, 8.5), dpi=110, sharex=True,
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.06},
    )
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax_rsi.set_facecolor(BG)
    _candles(ax, view)

    idx = df.index
    pts = [
        ("LS", signal.ls_idx, signal.ls_price),
        ("L1" if signal.direction == "bearish" else "H1", signal.l1_idx, signal.l1_price),
        ("HEAD", signal.head_idx, signal.head_price),
        ("BOS", signal.l2_idx, signal.l2_price),
        ("RS", signal.trigger_idx, signal.entry),
    ]
    ax.plot(
        [idx[i] for _, i, _ in pts],
        [p for _, _, p in pts],
        color="#787b86",
        linewidth=1.0,
        linestyle="--",
        zorder=4,
    )
    for label, i, price in pts:
        ax.annotate(
            label,
            (idx[i], price),
            textcoords="offset points",
            xytext=(0, 10 if label in ("LS", "HEAD", "RS") else -18),
            ha="center",
            color="#ffffff",
            fontsize=9,
            fontweight="bold",
        )

    levels = [
        ("Entry (QML)", signal.entry, "#2962ff"),
        ("SL", signal.stop_loss, "#ef5350"),
        ("TP1", signal.take_profit_1, "#26a69a"),
        ("TP2", signal.take_profit_2, "#26a69a"),
    ]
    for name, price, colour in levels:
        ax.axhline(price, color=colour, linewidth=1.2, alpha=0.9, zorder=5)
        ax.annotate(
            f"{name} {price:,.4f}".rstrip("0").rstrip("."),
            (view.index[-1], price),
            textcoords="offset points",
            xytext=(6, 0),
            va="center",
            color=colour,
            fontsize=8,
        )

    # shade the risk and reward boxes so the RR is visible, not just stated
    x0, x1 = view.index[0], view.index[-1]
    ax.fill_between([x0, x1], signal.entry, signal.stop_loss, color="#ef5350", alpha=0.10, zorder=1)
    ax.fill_between([x0, x1], signal.entry, signal.take_profit_1, color="#26a69a", alpha=0.10, zorder=1)

    confirmed = getattr(signal, "divergence_confirmed", None)
    arrow = "SELL" if signal.direction == "bearish" else "BUY"
    tag = " · Over-QM" if getattr(signal, "overshoot", False) else ""
    # The title reports the gate the signal actually passed (BOS->RS bounce).
    # It used to show the LS<->HEAD divergence tick, which now gates nothing —
    # a "✗" there made a perfectly valid signal look like it had failed
    # something.
    _b = getattr(signal, "bos_rs", None)
    div_tag = f" · bounce {_b:+.0f} RSI" if _b is not None else ""
    _g = getattr(signal, "ls_grade", None)
    grade_tag = f"  ·  Grade {_g}" if _g and _g != "?" else ""
    ax.set_title(
        f"{signal.symbol} {signal.timeframe} — QM {arrow}{tag}{div_tag}"
        f"  ·  RR {signal.risk_reward}{grade_tag}",
        color=FG,
        fontsize=13,
        fontweight="bold",
    )
    ax.grid(color=GRID, linewidth=0.5, alpha=0.6)
    ax.tick_params(colors=FG, labelsize=8, labelbottom=False)
    for spine in ax.spines.values():
        spine.set_color(GRID)

    # --- RSI panel ------------------------------------------------------- #
    rsi_view = rsi_series.reindex(view.index)
    ax_rsi.plot(view.index, rsi_view.to_numpy(), color="#b39ddb", linewidth=1.2, zorder=3)
    ax_rsi.axhline(70, color=GRID, linewidth=0.8, linestyle=":")
    ax_rsi.axhline(30, color=GRID, linewidth=0.8, linestyle=":")
    ax_rsi.set_ylim(0, 100)

    # Line 1 is the gate the signal actually had to pass: the retest leg
    # BOS -> RS. (This replaced an LS -> HEAD line, which spanned the whole
    # pattern and no longer gates anything — drawing it here would highlight
    # a reading the bot does not act on.)
    r_bos = float(rsi_series.iloc[signal.l2_idx]) if signal.l2_idx < len(rsi_series) else None
    r_head = float(rsi_series.iloc[signal.head_idx]) if signal.head_idx < len(rsi_series) else None
    r_trig0 = (float(rsi_series.iloc[signal.trigger_idx])
               if signal.trigger_idx < len(rsi_series) else None)
    bos_rs = getattr(signal, "bos_rs", None)
    if r_bos is not None and r_trig0 is not None and pd.notna(r_bos) and pd.notna(r_trig0):
        ax_rsi.plot(
            [idx[signal.l2_idx], idx[signal.trigger_idx]],
            [r_bos, r_trig0],
            color=DIV_COLOR,
            linewidth=1.6,
            linestyle="-",
            marker="o",
            markersize=3,
            zorder=4,
        )
        strength = f" ({bos_rs:+.0f} RSI)" if bos_rs is not None else ""
        # Anchored left of BOS while line 2's label sits right of RS: the two
        # points can be only a few bars apart, and both labels defaulting to
        # the right made them overlap into an unreadable smear.
        ax_rsi.annotate(
            f"1. BOS→RS bounce{strength}",
            (idx[signal.l2_idx], r_bos),
            textcoords="offset points",
            xytext=(-8, -16 if signal.direction == "bearish" else 10),
            ha="right",
            color=DIV_COLOR,
            fontsize=8,
            fontweight="bold",
        )

    # Second reading: the QM's FINAL leg, HEAD -> RS. This is the one the A/B/C
    # grade comes from, so it belongs on the picture next to the grade rather
    # than only in the message text. Drawn in the grade's own colour so the two
    # lines cannot be mistaken for each other.
    r_trig = (float(rsi_series.iloc[signal.trigger_idx])
              if signal.trigger_idx < len(rsi_series) else None)
    grade = getattr(signal, "ls_grade", None)
    ls_diff = getattr(signal, "ls_diff", None)
    if (r_head is not None and r_trig is not None
            and pd.notna(r_head) and pd.notna(r_trig) and grade and grade != "?"):
        colour = GRADE_COLORS.get(grade, "#8c8c8c")
        ax_rsi.plot(
            [idx[signal.head_idx], idx[signal.trigger_idx]],
            [r_head, r_trig],
            color=colour,
            linewidth=1.6,
            linestyle="-" if grade in ("A", "B") else "--",
            marker="o",
            markersize=3,
            zorder=5,
        )
        drop = f"{ls_diff:+.0f}" if ls_diff is not None else "?"
        ax_rsi.annotate(
            f"2. Last swing → {grade} ({drop} RSI)",
            (idx[signal.trigger_idx], r_trig),
            textcoords="offset points",
            xytext=(8, 10 if signal.direction == "bearish" else -16),
            color=colour,
            fontsize=8,
            fontweight="bold",
        )

    ax_rsi.set_ylabel("RSI(14)", color=FG, fontsize=8)
    ax_rsi.grid(color=GRID, linewidth=0.5, alpha=0.6)
    ax_rsi.tick_params(colors=FG, labelsize=8)
    for spine in ax_rsi.spines.values():
        spine.set_color(GRID)
    # tz=BANGKOK only affects how the tick labels are rendered — the
    # underlying plotted x-positions stay tied to the UTC-aware timestamps
    # in df.index, so candle positions are unaffected, only their labels.
    ax_rsi.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M", tz=BANGKOK))
    fig.autofmt_xdate()
    fig.tight_layout()

    out_path = str(out_path)
    fig.savefig(out_path, facecolor=BG)
    plt.close(fig)
    return out_path
