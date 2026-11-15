"""V3: V2 + daily SMA(30) macro filter on new longs.

Macro policy (pinned)
---------------------
- New longs only if close > prior-day daily SMA30 (as-of join).
- All V2 exits remain active when price is below the macro filter
  (no forced flatten on macro break — closes still allowed via death / Z / stop).
"""

from __future__ import annotations

import pandas as pd

from research.portfolio.ledger import BacktestLedger, Intent
from research.strategy.v2 import V2AdxZSpot


class V3MacroFilter:
    name = "V3"

    def __init__(self) -> None:
        self._inner = V2AdxZSpot()

    def on_bar(
        self,
        i: int,
        bars: pd.DataFrame,
        ledger: BacktestLedger,
    ) -> list[Intent]:
        intents = self._inner.on_bar(i, bars, ledger)
        if not intents:
            return intents

        row = bars.iloc[i]
        filtered: list[Intent] = []
        for intent in intents:
            if intent.action == "enter_long":
                sma = row.get("daily_sma30")
                close = float(row["close"])
                if pd.isna(sma) or close <= float(sma):
                    # Block entry; exits were already returned alone by V2 when needed.
                    continue
            filtered.append(intent)
        return filtered
