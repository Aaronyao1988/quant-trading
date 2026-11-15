#!/usr/bin/env python3
"""Offline smoke tests: imports, ledger, SMA NaN / crossover (no API keys)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from bot import compute_signal, extract_fill, load_ledger, save_ledger


def _ohlcv(closes: list[float], start_ts: int = 1_700_000_000_000, step_ms: int = 900_000) -> pd.DataFrame:
    rows = []
    for i, close in enumerate(closes):
        ts = start_ts + i * step_ms
        rows.append([ts, close, close, close, close, 1.0])
    return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])


class SmokeTests(unittest.TestCase):
    def test_ledger_init_and_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            state = load_ledger(initial_usdt=200.0, path=path)
            self.assertEqual(state["virtual_usdt"], 200.0)
            self.assertEqual(state["virtual_btc"], 0.0)
            self.assertIsNone(state["last_traded_ts"])
            state["virtual_usdt"] = 150.0
            state["virtual_btc"] = 0.001
            state["last_traded_ts"] = 123
            save_ledger(state, path=path)
            again = load_ledger(path=path)
            self.assertEqual(again["virtual_usdt"], 150.0)
            self.assertEqual(again["virtual_btc"], 0.001)
            self.assertEqual(again["last_traded_ts"], 123)

    def test_signal_hold_during_sma_warmup(self) -> None:
        df = _ohlcv([100.0 + i for i in range(20)])
        self.assertEqual(compute_signal(df, fast=10, slow=30), "HOLD")

    def test_signal_buy_crossover(self) -> None:
        # Build closed bars where fast crosses above slow on the last bar.
        # Bars 0..28: flat 100. Bar 29 (prev): still 100 → fast≈100, slow≈100.
        # Then drop so fast < slow, then spike so fast > slow on last bar.
        closes = [100.0] * 32
        # Depress recent prices so previous bar has fast < slow.
        for i in range(20, 31):
            closes[i] = 80.0
        closes[31] = 200.0  # last closed: lifts fast SMA across slow
        df = _ohlcv(closes)
        self.assertEqual(compute_signal(df, fast=3, slow=5), "BUY")

    def test_signal_sell_crossover(self) -> None:
        closes = [100.0] * 32
        for i in range(20, 31):
            closes[i] = 120.0
        closes[31] = 40.0
        df = _ohlcv(closes)
        self.assertEqual(compute_signal(df, fast=3, slow=5), "SELL")

    def test_extract_fill_prefers_exchange_fields(self) -> None:
        amt, cost = extract_fill(
            {"filled": 0.01, "cost": 650.0, "average": 65000.0},
            fallback_amount=0.02,
            fallback_price=64000.0,
        )
        self.assertAlmostEqual(amt, 0.01)
        self.assertAlmostEqual(cost, 650.0)

    def test_extract_fill_zero_stays_zero(self) -> None:
        amt, cost = extract_fill(
            {"filled": 0, "cost": 0},
            fallback_amount=0.02,
            fallback_price=64000.0,
        )
        self.assertEqual(amt, 0.0)
        self.assertEqual(cost, 0.0)

    def test_extract_fill_missing_uses_fallback(self) -> None:
        amt, cost = extract_fill(
            {},
            fallback_amount=0.02,
            fallback_price=64000.0,
        )
        self.assertAlmostEqual(amt, 0.02)
        self.assertAlmostEqual(cost, 1280.0)


if __name__ == "__main__":
    unittest.main()
