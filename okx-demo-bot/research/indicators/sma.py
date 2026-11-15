"""SMA helpers aligned with bot.compute_signal cross rules."""

from __future__ import annotations

import pandas as pd


def annotate_smas(df: pd.DataFrame, fast: int = 10, slow: int = 30) -> pd.DataFrame:
    work = df.copy()
    work["sma_fast"] = work["close"].astype(float).rolling(fast).mean()
    work["sma_slow"] = work["close"].astype(float).rolling(slow).mean()
    return work


def detect_cross(row_prev: pd.Series, row_curr: pd.Series) -> str | None:
    """Return 'golden' / 'death' / None from two consecutive annotated bars."""
    vals = [
        row_prev.get("sma_fast"),
        row_prev.get("sma_slow"),
        row_curr.get("sma_fast"),
        row_curr.get("sma_slow"),
    ]
    if any(pd.isna(v) for v in vals):
        return None
    if row_prev["sma_fast"] <= row_prev["sma_slow"] and row_curr["sma_fast"] > row_curr["sma_slow"]:
        return "golden"
    if row_prev["sma_fast"] >= row_prev["sma_slow"] and row_curr["sma_fast"] < row_curr["sma_slow"]:
        return "death"
    return None
