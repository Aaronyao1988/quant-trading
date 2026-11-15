"""Hard stop evaluated on intra-bar high/low."""

from __future__ import annotations

import pandas as pd

from research.matching.engine import MatchingEngine
from research.portfolio.ledger import BacktestLedger, Intent


def test_long_stop_hits_on_low() -> None:
    ledger = BacktestLedger.blank(200.0, instrument="spot")
    engine = MatchingEngine(instrument="spot", fee_rate=0.0, allocation_pct=0.5, stop_pct=0.02)
    engine.process_bar(
        ledger,
        pd.Series({"ts": 1, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}),
        [Intent(action="enter_long", reason="in", entry_strategy="sma")],
    )
    assert ledger.side == "long"
    entry = ledger.entry_price
    assert entry == 100.0
    # Bar dips through 2% stop (98) but closes higher — must still stop out.
    engine.process_bar(
        ledger,
        pd.Series({"ts": 2, "open": 100, "high": 100.5, "low": 97.0, "close": 99.5, "volume": 1}),
        [],  # no strategy exit
    )
    assert ledger.is_flat()
    stop_fills = [t for t in ledger.trades if t.reason == "hard_stop_2pct"]
    assert len(stop_fills) == 1
    assert stop_fills[0].price == 98.0  # fill at stop, not at low


def test_short_stop_hits_on_high() -> None:
    ledger = BacktestLedger.blank(200.0, instrument="swap")
    engine = MatchingEngine(instrument="swap", fee_rate=0.0, allocation_pct=0.5, stop_pct=0.02)
    engine.process_bar(
        ledger,
        pd.Series({"ts": 1, "open": 100, "high": 100, "low": 100, "close": 100, "volume": 1}),
        [Intent(action="enter_short", reason="in", entry_strategy="macro")],
    )
    assert ledger.side == "short"
    engine.process_bar(
        ledger,
        pd.Series({"ts": 2, "open": 100, "high": 103.0, "low": 99.5, "close": 101.0, "volume": 1}),
        [],
    )
    assert ledger.is_flat()
    stop_fills = [t for t in ledger.trades if t.reason == "hard_stop_2pct"]
    assert stop_fills[0].price == 102.0
