"""V1: long-only SMA(10)/SMA(30) spot."""

from __future__ import annotations

import pandas as pd

from research.portfolio.ledger import BacktestLedger, Intent


class V1SMASpot:
    name = "V1"

    def on_bar(
        self,
        i: int,
        bars: pd.DataFrame,
        ledger: BacktestLedger,
    ) -> list[Intent]:
        cross = bars.iloc[i].get("cross")
        if ledger.is_flat() and cross == "golden":
            return [Intent(action="enter_long", reason="sma_golden", entry_strategy="sma")]
        if ledger.side == "long" and cross == "death":
            return [Intent(action="exit_long", reason="sma_death", entry_strategy="sma")]
        return []
