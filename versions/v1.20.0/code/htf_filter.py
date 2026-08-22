"""
Higher-timeframe (HTF) structure alignment filter.

Confluence factor #1 per the skill's own ranking (references/qm-pattern-theory.md
§4) and the highest-value filter found in multi-timeframe research — a QM
signal that agrees with the higher timeframe's trend hits meaningfully more
often than one that fights it (research cited: ~65% hit rate for aligned
signals vs ~45% for unaligned in one study). Applied as a post-filter after
detect_qm(), the same pattern as divergence.py: qm_detector.py stays a pure
function of one timeframe's OHLCV with no notion of "what's happening on
another timeframe."
"""

from __future__ import annotations

from typing import Literal

import pandas as pd

from qm_detector import alternate, find_pivots

Structure = Literal["bullish", "bearish", "neutral"]


def htf_structure(
    df: pd.DataFrame,
    pivot_left: int = 3,
    pivot_right: int = 3,
    lookback: int = 6,
) -> Structure:
    """Read the higher-timeframe trend off its last few confirmed swing pivots.

    Bullish: the two most recent swing highs are rising AND the two most
    recent swing lows are rising (classic higher-high/higher-low structure).
    Bearish: the mirror (lower-high/lower-low). Anything else — including too
    few pivots to judge, or highs and lows disagreeing (a common sign of a
    ranging market) — is "neutral".

    Deliberately conservative: this only ever REMOVES signals that clearly
    fight an established trend. It never requires agreement it can't actually
    detect, so a genuinely undecided market doesn't get every signal blocked.
    """
    pivots = alternate(find_pivots(df, pivot_left, pivot_right))
    pivots = pivots[-lookback:] if lookback else pivots
    highs = [p for p in pivots if p.kind == "high"]
    lows = [p for p in pivots if p.kind == "low"]

    if len(highs) < 2 or len(lows) < 2:
        return "neutral"

    highs_rising = highs[-1].price > highs[-2].price
    highs_falling = highs[-1].price < highs[-2].price
    lows_rising = lows[-1].price > lows[-2].price
    lows_falling = lows[-1].price < lows[-2].price

    if highs_rising and lows_rising:
        return "bullish"
    if highs_falling and lows_falling:
        return "bearish"
    return "neutral"


def htf_allows(signal_direction: str, structure: Structure) -> bool:
    """True unless the signal direction is clearly fighting HTF structure.

    bearish QM (sell) into a bullish HTF trend -> reject (selling into a clear uptrend)
    bullish QM (buy) into a bearish HTF trend  -> reject (buying into a clear downtrend)
    Agreement, or a neutral/undetermined structure -> allow through unfiltered.
    """
    if signal_direction == "bearish" and structure == "bullish":
        return False
    if signal_direction == "bullish" and structure == "bearish":
        return False
    return True
