"""
RSI regular-divergence confirmation for QM signals.

Kept separate from qm_detector.py on purpose — the detector stays a pure
function of OHLCV with no notion of "confirmation filters" (see its own
docstring). Divergence is one more gate applied after detect_qm(), the same
way the RR gate is applied inside it, and the caller decides whether to
require it or just tag signals with it.

Regular divergence is checked between the LS and HEAD pivots — the same two
swing points that define the QM's liquidity sweep:

  bearish QM: price makes a HIGHER high (head > ls, already guaranteed by the
              detector's sweep check) while RSI makes a LOWER high
              -> momentum did not confirm the new high -> bearish divergence.
  bullish QM: mirror — price LOWER low while RSI makes a HIGHER low.

If either pivot falls inside the RSI warm-up window (NaN), divergence cannot
be evaluated and the signal is treated as unconfirmed rather than guessed at.

DRAWING vs MEASURING — deliberately two different things
--------------------------------------------------------
A divergence line must join peaks of the oscillator itself, so the chart
anchors its endpoints to the RSI extremum near each price pivot (draw_win).
That fixed lines cutting through the RSI curve on 75% of signals.

The GATE keeps reading RSI at the price pivot bar (win=0). Backtested on 99
symbols at matched trade counts, anchoring the measurement made results
worse out-of-sample (+0.407R vs +0.634R): taking the max inside a window is
a biased estimator that always shifts the value up, and how far RSI's turn
lags price appears to carry information that snapping to the peak discards.

So: anchored points for the picture, raw pivot-bar values for the decision.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class DivergenceResult:
    confirmed: bool
    rsi_ls: float | None
    rsi_head: float | None
    rsi_diff: float | None  # signed so the direction of the divergence is visible in logs


def rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's RSI, aligned to df.index. Same EWM smoothing style as qm_detector.atr()."""
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def check_divergence(
    signal,
    rsi_series: pd.Series,
    min_rsi_diff: float = 2.0,
) -> DivergenceResult:
    """Evaluate regular RSI divergence between signal.ls_idx and signal.head_idx.

    `min_rsi_diff` is a floor on how far apart the two RSI readings must be —
    without it, a 0.1-point wiggle would count as "divergence" on pure noise.
    """
    rsi_vals = rsi_series.to_numpy()
    if signal.ls_idx >= len(rsi_vals) or signal.head_idx >= len(rsi_vals):
        return DivergenceResult(False, None, None, None)

    r_ls = float(rsi_vals[signal.ls_idx])
    r_head = float(rsi_vals[signal.head_idx])
    if pd.isna(r_ls) or pd.isna(r_head):
        return DivergenceResult(False, None, None, None)

    if signal.direction == "bearish":
        diff = r_ls - r_head  # positive means RSI made a lower high, as required
        confirmed = diff >= min_rsi_diff
    else:
        diff = r_head - r_ls  # positive means RSI made a higher low, as required
        confirmed = diff >= min_rsi_diff

    return DivergenceResult(confirmed, round(r_ls, 2), round(r_head, 2), round(diff, 2))


def rsi_anchor(r, idx: int, want_high: bool, back: int = 3, fwd: int = 3,
               limit: int | None = None) -> int:
    """Index of the RSI peak (or trough) that belongs to a price pivot at `idx`.

    A divergence line has to join two peaks of the oscillator itself. Reading
    RSI at the price pivot's own bar does not do that: RSI usually turns a
    bar or two away from price, so the endpoints sit on the slope instead of
    the peak and the connecting line saws straight through the RSI curve.
    Measured over 1362 signals, that happened on 75% of them, by 7 RSI points
    on average — which is also why the drawn line looked wrong.

    `fwd=0` is required for the trigger/RS end. Bars after the trigger do not
    exist when the signal fires, so searching forward there would pick a peak
    out of the future and quietly inflate every backtest that used it.
    `limit` clamps the window so an anchor can never reach past the trigger.
    """
    lo = max(0, idx - back)
    hi = min(len(r) - 1, idx + fwd)
    if limit is not None:
        hi = min(hi, limit)
    if hi < lo:
        return idx
    seg = r[lo:hi + 1]
    if np.all(np.isnan(seg)):
        return idx
    off = int(np.nanargmax(seg) if want_high else np.nanargmin(seg))
    return lo + off


def bos_rs_momentum(signal, rsi_series: pd.Series, win: int = 0,
                    draw_win: int = 3) -> float | None:
    """Strength of the counter-move on the QM's final leg, BOS -> RS.

    This is the bot's primary confirmation. The LS->HEAD reading it replaced
    spans the whole pattern — often days — and by the time price is back at
    the QML it says little about whether the retest itself has any force
    behind it. This leg is the retest.

    For a short: price rallies off the BOS low back up to the QML, and the
    value is how much RSI the rally regained. Small means the bounce is
    limp and the level is likely to hold. For a long it is the mirror, so
    lower is always better regardless of direction.
    """
    r = rsi_series.to_numpy()
    if signal.l2_idx >= len(r) or signal.trigger_idx >= len(r):
        return None
    # BOS เป็นจุดต่ำของราคา (ขาลง) -> ยึดก้น RSI ; RS เป็นจุดสูง -> ยึดยอด RSI
    bos_high = signal.direction == "bullish"
    # จุดสำหรับ "วาด" กับจุดสำหรับ "วัด" แยกกัน — ดู module docstring
    signal.i_bos_rsi = rsi_anchor(r, signal.l2_idx, bos_high, draw_win, draw_win,
                                  limit=signal.trigger_idx)
    signal.i_rs_rsi = rsi_anchor(r, signal.trigger_idx, not bos_high, draw_win, 0)
    i_bos = rsi_anchor(r, signal.l2_idx, bos_high, win, win, limit=signal.trigger_idx)
    i_rs = rsi_anchor(r, signal.trigger_idx, not bos_high, win, 0)
    bos, trig = r[i_bos], r[i_rs]
    if pd.isna(bos) or pd.isna(trig):
        return None
    return float(trig - bos) if signal.direction == "bearish" else float(bos - trig)


def last_swing_momentum(signal, rsi_series: pd.Series, win: int = 0,
                        draw_win: int = 3) -> float | None:
    """How much momentum faded on the QM's FINAL leg (BOS -> RS), in RSI points.

    The existing divergence check compares LS against HEAD — the two swings
    that form the liquidity sweep. This looks at the last swing instead: price
    rallies off the BOS low back up to the QML, and the question is whether
    that rally has any strength behind it.

    Positive = the retest arrived with weaker momentum than the head, i.e. the
    bounce is exhausted and the reversal has a better chance of holding.
    Negative = momentum is stronger at the retest than at the head.

    Backtested over 830k 1H bars, this separates outcomes sharply — see
    grade_last_swing() for the bands.
    """
    r = rsi_series.to_numpy()
    if signal.head_idx >= len(r) or signal.trigger_idx >= len(r):
        return None
    # HEAD กับ RS เป็นจุดสุดขั้วชนิดเดียวกัน (ยอดคู่ยอด / ก้นคู่ก้น)
    # จึงเป็นการเทียบ divergence ที่ถูกต้องตามตำรา
    want_high = signal.direction == "bearish"
    signal.i_head_rsi = rsi_anchor(r, signal.head_idx, want_high, draw_win, draw_win,
                                   limit=signal.trigger_idx)
    signal.i_trig_rsi = rsi_anchor(r, signal.trigger_idx, want_high, draw_win, 0)
    i_head = rsi_anchor(r, signal.head_idx, want_high, win, win, limit=signal.trigger_idx)
    i_trig = rsi_anchor(r, signal.trigger_idx, want_high, win, 0)
    head, trig = r[i_head], r[i_trig]
    if pd.isna(head) or pd.isna(trig):
        return None
    # For a short, momentum fading means RSI lower at the retest than at the
    # head; for a long it is the mirror. Sign is normalised so that positive
    # always means "fading in the direction we want to trade".
    return float(head - trig) if signal.direction == "bearish" else float(trig - head)


def grade_last_swing(diff: float | None, a_min: float = 5.0, b_min: float = 0.0) -> str:
    """Bucket the last-swing momentum into A / B / C.

    Measured out-of-sample (2024-2026, 830k-bar dataset, both live profiles):
        A  diff > 5      n=132   win 53.8%   +1.031R   PF 2.94
        B  0 < diff <= 5 n=113   win ~38%    +0.39R    PF ~1.5
        C  diff <= 0     n=306   win 27.5%   +0.265R   PF 1.31
    All three are still positive, which is why the default is to grade and
    send rather than to filter — the trader picks. Set
    `divergence.last_swing.min_diff` to drop the weak ones instead.
    """
    if diff is None:
        return "?"
    if diff > a_min:
        return "A"
    if diff > b_min:
        return "B"
    return "C"


def attach_divergence(
    signals: list,
    df: pd.DataFrame,
    rsi_period: int = 14,
    min_rsi_diff: float = 2.0,
    required: bool = False,
    ls_grade_a: float = 5.0,
    ls_grade_b: float = 0.0,
    ls_min_diff: float | None = None,
    bos_rs_max: float | None = 10.0,
    anchor_win: int = 0,
    draw_win: int = 3,
) -> list:
    """Compute RSI once for the whole frame, tag every signal, and — if
    `required` — drop the ones that don't confirm.

    Mutates each signal in place with `.divergence_confirmed`, `.rsi_ls`,
    `.rsi_head`, `.rsi_diff` (QMSignal is a plain dataclass, not slotted, so
    this is safe) and returns either the full tagged list or the filtered one.
    """
    if not signals:
        return signals

    rsi_series = rsi(df, rsi_period)
    kept = []
    for s in signals:
        result = check_divergence(s, rsi_series, min_rsi_diff)
        s.divergence_confirmed = result.confirmed
        s.rsi_ls = result.rsi_ls
        s.rsi_head = result.rsi_head
        s.rsi_diff = result.rsi_diff

        # Both final-leg readings are attached to every signal regardless of
        # the gates, so a caller can grade or filter on them separately.
        s.bos_rs = bos_rs_momentum(s, rsi_series, anchor_win, draw_win)
        s.ls_diff = last_swing_momentum(s, rsi_series, anchor_win, draw_win)
        s.ls_grade = grade_last_swing(s.ls_diff, ls_grade_a, ls_grade_b)

        # Primary gate: the retest leg itself must be weak.
        if bos_rs_max is not None and (s.bos_rs is None or s.bos_rs >= bos_rs_max):
            continue
        # LS<->HEAD is off by default now — kept so it can be switched back on
        # for comparison without restoring deleted code.
        if required and not result.confirmed:
            continue
        if ls_min_diff is not None and (s.ls_diff is None or s.ls_diff <= ls_min_diff):
            continue
        kept.append(s)
    return kept
