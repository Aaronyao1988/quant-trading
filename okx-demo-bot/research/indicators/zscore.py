"""Rolling Z-score on close prices."""

from __future__ import annotations

import pandas as pd


def zscore(close: pd.Series, window: int = 20) -> pd.Series:
    series = close.astype(float)
    mean = series.rolling(window).mean()
    std = series.rolling(window).std(ddof=0)
    return (series - mean) / std.replace(0, pd.NA)
