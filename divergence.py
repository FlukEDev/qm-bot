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


def attach_divergence(
    signals: list,
    df: pd.DataFrame,
    rsi_period: int = 14,
    min_rsi_diff: float = 2.0,
    required: bool = True,
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
        if result.confirmed or not required:
            kept.append(s)
    return kept
