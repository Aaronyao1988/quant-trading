"""V4: 1x bidirectional BTC-USDT-SWAP simulation.

Priority table
--------------
1. MatchingEngine 2% hard stop on H/L (always first).
2. Macro regime from prior-day daily SMA30:
   - close > daily_sma30 → long regime
   - close < daily_sma30 → short regime
   - equal / NaN → no new entries; exits still allowed
3. Within long regime: golden → enter/flip to long; death → exit long.
4. Within short regime: death → enter/flip to short; golden → exit short.
5. Regime flip while in a position that contradicts the new regime:
   flatten on the opposing cross (death exits long; golden exits short),
   then allow the same bar's cross to open the new side only if still flat
   after the engine processes one intent — so we emit exit then enter as
   ordered list; engine takes the first actionable intent per bar.
   Practical rule: on regime-conflict, prefer exit this bar; enter next cross.
"""

from __future__ import annotations

import pandas as pd

from research.portfolio.ledger import BacktestLedger, Intent


class V4SwapBidirectional:
    name = "V4"

    def on_bar(
        self,
        i: int,
        bars: pd.DataFrame,
        ledger: BacktestLedger,
    ) -> list[Intent]:
        row = bars.iloc[i]
        cross = row.get("cross")
        close = float(row["close"])
        sma = row.get("daily_sma30")

        if pd.isna(sma):
            # Still allow protective exits.
            if ledger.side == "long" and cross == "death":
                return [Intent(action="exit_long", reason="death_warmup", entry_strategy="macro")]
            if ledger.side == "short" and cross == "golden":
                return [Intent(action="exit_short", reason="golden_warmup", entry_strategy="macro")]
            return []

        long_regime = close > float(sma)
        short_regime = close < float(sma)

        # Exits / flips driven by crosses.
        if ledger.side == "long":
            if cross == "death":
                # Exit long; if short regime, engine will only take first intent —
                # schedule enter_short only when already flat path.
                return [Intent(action="exit_long", reason="death_exit_long", entry_strategy="macro")]
            if short_regime and cross == "golden":
                # Odd combo; hold.
                return []
            return []

        if ledger.side == "short":
            if cross == "golden":
                return [Intent(action="exit_short", reason="golden_exit_short", entry_strategy="macro")]
            return []

        # Flat: entries gated by macro regime + cross.
        if long_regime and cross == "golden":
            return [Intent(action="enter_long", reason="macro_long_golden", entry_strategy="macro")]
        if short_regime and cross == "death":
            return [Intent(action="enter_short", reason="macro_short_death", entry_strategy="macro")]
        return []
