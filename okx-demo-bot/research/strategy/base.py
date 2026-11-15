"""Strategy protocol and shared feature preparation."""

from __future__ import annotations

from typing import Protocol

import pandas as pd

from research.config import ADX_PERIOD, SMA_FAST, SMA_SLOW, Z_WINDOW
from research.data.asof import align_daily_sma_asof
from research.indicators.adx import wilder_adx
from research.indicators.sma import annotate_smas
from research.indicators.zscore import zscore
from research.portfolio.ledger import BacktestLedger, Intent


class Strategy(Protocol):
    name: str

    def on_bar(
        self,
        i: int,
        bars: pd.DataFrame,
        ledger: BacktestLedger,
    ) -> list[Intent]:
        ...


def prepare_features(
    bars_15m: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    fast: int = SMA_FAST,
    slow: int = SMA_SLOW,
    adx_period: int = ADX_PERIOD,
    z_window: int = Z_WINDOW,
) -> pd.DataFrame:
    """Annotate 15m bars with SMAs, ADX, Z-score, and prior-day daily SMA30."""
    work = annotate_smas(bars_15m, fast=fast, slow=slow)
    work["adx"] = wilder_adx(work, period=adx_period)
    work["zscore"] = zscore(work["close"], window=z_window)
    work = align_daily_sma_asof(work, daily, window=30, column="daily_sma30")
    # Precompute cross vs previous bar for vectorized-ish lookups.
    crosses: list[str | None] = [None]
    for i in range(1, len(work)):
        from research.indicators.sma import detect_cross

        crosses.append(detect_cross(work.iloc[i - 1], work.iloc[i]))
    work["cross"] = crosses
    return work
