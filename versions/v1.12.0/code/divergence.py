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
"""

from __future__ import annotations

from dataclasses import dataclass

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


def last_swing_momentum(signal, rsi_series: pd.Series) -> float | None:
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
    head, trig = r[signal.head_idx], r[signal.trigger_idx]
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
    required: bool = True,
    ls_grade_a: float = 5.0,
    ls_grade_b: float = 0.0,
    ls_min_diff: float | None = None,
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

        # Last-swing momentum is attached to every signal regardless of the
        # gate above, so a caller can grade or filter on it separately.
        s.ls_diff = last_swing_momentum(s, rsi_series)
        s.ls_grade = grade_last_swing(s.ls_diff, ls_grade_a, ls_grade_b)

        if not (result.confirmed or not required):
            continue
        if ls_min_diff is not None and (s.ls_diff is None or s.ls_diff <= ls_min_diff):
            continue
        kept.append(s)
    return kept
