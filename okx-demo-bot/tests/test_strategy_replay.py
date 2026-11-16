"""Signals, warmup, and the next-open replay used by the three paper books."""

from __future__ import annotations

import pandas as pd
import pytest

from replay import simulate, replay_books
from strategy import STRATEGIES, decide, ema, latest_signal, prepare_frame

START = 1_700_006_400_000
TF_MS = 14_400_000


def _frame(closes: list[float]) -> pd.DataFrame:
    rows = []
    for i, close in enumerate(closes):
        open_px = close - 1.0
        rows.append(
            {
                "ts": START + i * TF_MS,
                "open": open_px,
                "high": max(open_px, close) + 2.0,
                "low": min(open_px, close) - 2.0,
                "close": close,
                "volume": 1.0,
            }
        )
    return pd.DataFrame(rows)


def _path() -> list[float]:
    price = 100.0
    closes: list[float] = []
    for _ in range(40):
        closes.append(price)
        price *= 0.99
    for _ in range(30):
        price *= 1.03
        closes.append(price)
    for _ in range(20):
        price *= 0.96
        closes.append(price)
    return closes


def test_ema_warmup_is_nan_until_span():
    series = pd.Series([float(i) for i in range(1, 16)])
    out = ema(series, 10)
    assert out.iloc[:9].isna().all()
    assert out.iloc[9] == pytest.approx(6.239368480121215)
    assert out.iloc[9:].notna().all()


def test_spec_v1_sma_and_ema_warmup():
    closes = [100.0 + i * 0.01 for i in range(231)]
    prepared = prepare_frame(_frame(closes), STRATEGIES["spec_v1"])
    assert prepared["fast"].iloc[:9].isna().all()
    assert prepared["fast"].iloc[9:].notna().all()
    assert prepared["slow"].iloc[:229].isna().all()
    assert pd.notna(prepared["slow"].iloc[229])
    assert pd.isna(prepared["atr"].iloc[13])
    assert pd.notna(prepared["atr"].iloc[14])


def test_already_long_and_already_flat_and_halt():
    assert decide("BUY", flat=False, halted_now=False) == "skip_already_long"
    assert decide("SELL", flat=True, halted_now=False) == "skip_already_flat"
    assert decide("BUY", flat=True, halted_now=True) == "skip_halt"
    assert decide("SELL", flat=False, halted_now=True) == "sell"
    assert decide("HOLD", flat=True, halted_now=False) == "hold"


def test_short_cross_signal_on_last_bar():
    from strategy import Strategy

    spec = Strategy("t", "4h", 3, 8, "ema", "sma", 1.0, None, False, 9, "t")
    closes = _path()
    assert latest_signal(_frame(closes[:42]), spec) == "BUY"
    assert latest_signal(_frame(closes[:73]), spec) == "SELL"


def test_replay_fees_on_and_off_and_next_open():
    from strategy import Strategy

    spec = Strategy("t", "4h", 3, 8, "ema", "sma", 1.0, None, False, 9, "t")
    frame = _frame(_path())
    plain = simulate(frame, spec, fee=0.0, slip=0.0)
    costly = simulate(frame, spec, fee=0.001, slip=0.0005)
    assert plain["metrics"]["trades"] >= 2
    assert costly["metrics"]["trades"] == plain["metrics"]["trades"]
    assert costly["metrics"]["final_equity"] < plain["metrics"]["final_equity"]
    buy = plain["trades"][0]
    assert buy["type"] == "BUY"
    assert buy["signal_ts"] == int(frame.iloc[41]["ts"])
    assert buy["ts"] == int(frame.iloc[42]["ts"])
    assert buy["price"] == pytest.approx(float(frame.iloc[42]["open"]))
    assert buy["price"] != pytest.approx(float(frame.iloc[41]["close"]))


def test_vol_weight_spends_less_than_full_cash():
    from strategy import Strategy

    spec = Strategy("t", "4h", 3, 8, "ema", "sma", None, 0.15, False, 9, "t")
    result = simulate(_frame(_path()), spec, fee=0.001, slip=0.0005)
    buy = result["trades"][0]
    assert buy["weight"] < 1.0
    assert buy["spend"] < 200.0


def test_three_books_run_side_by_side():
    results = replay_books(_frame(_path()), fee=0.001, slip=0.0005)
    assert set(results) == {"spec_v1", "ema_50_200", "buy_and_hold"}
    held = results["buy_and_hold"]
    assert held["metrics"]["trades"] == 1
    assert held["trades"][0]["type"] == "BUY"
    assert held["trades"][0]["weight"] == 1.0
    assert held["metrics"]["final_equity"] != pytest.approx(200.0)
