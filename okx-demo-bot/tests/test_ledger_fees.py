"""Ledger fields + fee application."""

from __future__ import annotations

import pandas as pd

from research.config import SPOT_FEE_RATE, SWAP_FEE_RATE
from research.matching.engine import MatchingEngine
from research.portfolio.ledger import BacktestLedger, Intent


def _bar(ts: int, price: float, high: float | None = None, low: float | None = None) -> pd.Series:
    return pd.Series(
        {
            "ts": ts,
            "open": price,
            "high": high if high is not None else price,
            "low": low if low is not None else price,
            "close": price,
            "volume": 1.0,
        }
    )


def test_ledger_has_required_position_fields() -> None:
    ledger = BacktestLedger.blank(200.0, instrument="spot")
    assert ledger.entry_price is None
    assert ledger.side == "flat"
    assert ledger.entry_strategy == ""
    engine = MatchingEngine(instrument="spot", fee_rate=SPOT_FEE_RATE)
    engine.process_bar(
        ledger,
        _bar(1_000, 50_000.0),
        [Intent(action="enter_long", reason="test", entry_strategy="sma")],
    )
    assert ledger.side == "long"
    assert ledger.entry_price == 50_000.0
    assert ledger.entry_strategy == "sma"
    assert ledger.entry_ts == 1_000
    assert ledger.cumulative_fees > 0


def test_spot_fee_applied_both_sides() -> None:
    ledger = BacktestLedger.blank(200.0, instrument="spot")
    engine = MatchingEngine(instrument="spot", fee_rate=0.001, allocation_pct=0.5)
    engine.process_bar(
        ledger,
        _bar(1, 100.0),
        [Intent(action="enter_long", reason="in", entry_strategy="sma")],
    )
    fee_in = ledger.cumulative_fees
    assert abs(fee_in - 100.0 * 0.001) < 1e-9  # 50% of 200 = 100 notional
    engine.process_bar(
        ledger,
        _bar(2, 110.0),
        [Intent(action="exit_long", reason="out", entry_strategy="sma")],
    )
    # Exit fee on exit notional ≈ btc * 110 * 0.001
    assert ledger.cumulative_fees > fee_in
    assert ledger.is_flat()


def test_swap_fee_and_contract_rounding() -> None:
    ledger = BacktestLedger.blank(200.0, instrument="swap")
    engine = MatchingEngine(instrument="swap", fee_rate=SWAP_FEE_RATE, allocation_pct=0.5)
    engine.process_bar(
        ledger,
        _bar(1, 50_000.0),
        [Intent(action="enter_long", reason="in", entry_strategy="macro")],
    )
    assert ledger.side == "long"
    # 100 USDT / 50000 = 0.002 BTC → 0.002/0.01 = 0.2 contracts → step 0.01 OK
    assert ledger.position_qty == 0.2
    assert ledger.intended_notional_log[-1]["filled_contracts"] == 0.2
    assert abs(ledger.cumulative_fees - (0.2 * 0.01 * 50_000 * SWAP_FEE_RATE)) < 1e-9
