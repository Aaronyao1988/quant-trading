"""V2: ADX regime switch between SMA trend and Z-score mean-reversion.

Exit priority (must-fix — prevents orphaned inventory)
-------------------------------------------------------
1. MatchingEngine hard stop (2% on H/L) — always, before this method.
2. Exit rules always follow ``entry_strategy``, regardless of current ADX band:
   - sma entry  → death-cross exit (active in trend, dead-band, and MR).
   - zscore entry → Z ≥ 0 exit; death-cross is an additional safety flatten.
3. ADX ∈ [20, 25]: **no new entries**; exits (2) still fire.
4. ADX > 25: new longs only via SMA golden (trend mode).
5. ADX < 20: new longs only via Z < −2 (MR mode).
6. Mode changes never strip exit rights from an open ticket.
"""

from __future__ import annotations

import pandas as pd

from research.config import ADX_MR, ADX_TREND, Z_ENTRY, Z_EXIT
from research.portfolio.ledger import BacktestLedger, Intent


class V2AdxZSpot:
    name = "V2"

    def on_bar(
        self,
        i: int,
        bars: pd.DataFrame,
        ledger: BacktestLedger,
    ) -> list[Intent]:
        row = bars.iloc[i]
        adx = row.get("adx")
        z = row.get("zscore")
        cross = row.get("cross")

        intents: list[Intent] = []

        # --- Exits first (orphan policy) ---
        if ledger.side == "long":
            if ledger.entry_strategy == "sma":
                if cross == "death":
                    intents.append(
                        Intent(action="exit_long", reason="sma_death", entry_strategy="sma")
                    )
                    return intents
            elif ledger.entry_strategy == "zscore":
                if pd.notna(z) and float(z) >= Z_EXIT:
                    intents.append(
                        Intent(action="exit_long", reason="z_exit_ge_0", entry_strategy="zscore")
                    )
                    return intents
                if cross == "death":
                    intents.append(
                        Intent(
                            action="exit_long",
                            reason="z_safety_death",
                            entry_strategy="zscore",
                        )
                    )
                    return intents
            else:
                # Unknown entry tag: flatten on death to avoid orphans.
                if cross == "death":
                    intents.append(
                        Intent(action="exit_long", reason="orphan_death", entry_strategy="")
                    )
                    return intents

        if not ledger.is_flat():
            return intents

        # --- Entries (flat only) ---
        if pd.isna(adx):
            return intents
        adx_v = float(adx)

        if ADX_MR <= adx_v <= ADX_TREND:
            # Dead band: no new entries.
            return intents

        if adx_v > ADX_TREND:
            if cross == "golden":
                intents.append(
                    Intent(action="enter_long", reason="adx_trend_golden", entry_strategy="sma")
                )
            return intents

        # adx_v < ADX_MR → mean-reversion
        if pd.notna(z) and float(z) < Z_ENTRY:
            intents.append(
                Intent(action="enter_long", reason="adx_mr_z_entry", entry_strategy="zscore")
            )
        return intents
