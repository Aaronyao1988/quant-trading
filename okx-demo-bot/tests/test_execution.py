"""Execution: one order per bar, reconciliation, halt, sandbox header."""

from __future__ import annotations

import ccxt
import pytest

from execution import (
    backoff_seconds,
    execute_cycle,
    fetch_ohlcv_paginated,
    plan_wake,
    run_loop,
    spot_market_order_params,
)
from ledger import fresh_ledger, ledger_path, save_ledger
from strategy import STRATEGIES, Strategy

START = 1_700_006_400_000
TF_MS = 14_400_000

SHORT = Strategy(
    id="short_cross",
    timeframe="4h",
    fast=3,
    slow=8,
    fast_kind="ema",
    slow_kind="sma",
    allocation=1.0,
    vol_target=None,
    buy_and_hold=False,
    min_closed=9,
    description="test",
)


def _closes() -> list[float]:
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


def _rows(n: int | None = None) -> list[list[float]]:
    closes = _closes() if n is None else _closes()[:n]
    rows = []
    for i, close in enumerate(closes):
        ts = START + i * TF_MS
        open_px = close - 1.0
        rows.append([ts, open_px, max(open_px, close) + 2.0, min(open_px, close) - 2.0, close, 1.0])
    return rows


class FakeExchange:
    def __init__(self, rows: list[list[float]], *, mark: float | None = None):
        self.rows = rows
        self.headers = {"x-simulated-trading": "1"}
        self.created: list[dict] = []
        self.mark = mark if mark is not None else float(rows[-1][4])
        self.order: dict | None = None
        self.fail_network = False
        self.not_found = False
        self.fetch_calls = 0

    def milliseconds(self) -> int:
        return int(self.rows[-1][0] + TF_MS)

    def market(self, _symbol: str) -> dict:
        return {"limits": {"amount": {"min": 0.00001}, "cost": {"min": 5}}}

    def amount_to_precision(self, _symbol: str, amount: float) -> str:
        return f"{float(amount):.8f}"

    def fetch_ohlcv(self, _symbol, _timeframe, since=None, limit=100):
        data = [row for row in self.rows if since is None or row[0] >= since]
        return data[:limit]

    def fetch_ticker(self, _symbol):
        return {"last": self.mark}

    def fetch_order(self, _order_id, _symbol, params=None):
        self.fetch_calls += 1
        if self.not_found or self.order is None:
            raise ccxt.OrderNotFound("missing")
        assert params and params.get("clientOrderId")
        return self.order

    def create_order(self, symbol, order_type, side, amount, price, params):
        self.created.append(
            {"symbol": symbol, "type": order_type, "side": side, "amount": amount, "params": params}
        )
        if self.fail_network:
            raise ccxt.NetworkError("timeout")
        cost = float(amount) * self.mark
        self.order = {
            "id": "ex-1",
            "filled": float(amount),
            "cost": cost,
            "average": self.mark,
            "status": "closed",
            "side": side,
            "fee": {"cost": cost * 0.001, "currency": "USDT"},
        }
        return self.order


def test_order_params_force_base_currency():
    params = spot_market_order_params("abc123")
    assert params["tgtCcy"] == "base_ccy"
    assert params["clientOrderId"] == "abc123"


def test_plan_wake_runs_only_near_the_close():
    closed_open = START - TF_MS
    just_after = START / 1000 + 5
    wake = plan_wake(just_after, TF_MS, 2.0, 30.0, None)
    assert wake.action == "run"
    assert wake.closed_open_ms == closed_open
    early = plan_wake(START / 1000 + 1, TF_MS, 2.0, 30.0, None)
    assert early.action == "sleep"
    assert early.delay_sec == pytest.approx(1.0)
    stale = plan_wake(START / 1000 + 100, TF_MS, 2.0, 30.0, None)
    assert stale.action == "skip_stale"
    again = plan_wake(just_after, TF_MS, 2.0, 30.0, closed_open)
    assert again.action == "sleep"


def test_pagination_collects_at_least_231_bars():
    rows = []
    for i in range(260):
        ts = START + i * TF_MS
        rows.append([ts, 100.0, 101.0, 99.0, 100.0, 1.0])
    now_ms = rows[-1][0] + TF_MS
    got = fetch_ohlcv_paginated(FakeExchange(rows), "BTC/USDT", "4h", 240, now_ms, limit=100)
    assert len(got) >= 240
    assert got == sorted(got, key=lambda row: row[0])


def test_sandbox_header_is_required(tmp_path):
    ex = FakeExchange(_rows(42))
    ex.headers = {}
    with pytest.raises(RuntimeError, match="sandbox"):
        execute_cycle(ex, SHORT, now_ms=ex.milliseconds(), directory=tmp_path, sleep_fn=lambda _s: None)


def test_already_long_does_not_buy(tmp_path):
    rows = _rows(42)
    ex = FakeExchange(rows)
    path = ledger_path(SHORT.id, tmp_path)
    save_ledger(fresh_ledger(200.0, SHORT.id) | {"virtual_btc": 1.0, "virtual_usdt": 50.0}, path)
    result = execute_cycle(ex, SHORT, now_ms=ex.milliseconds(), directory=tmp_path, sleep_fn=lambda _s: None)
    assert result["action"] == "skip_already_long"
    assert ex.created == []


def test_already_flat_does_not_sell(tmp_path):
    ex = FakeExchange(_rows(73))
    result = execute_cycle(ex, SHORT, now_ms=ex.milliseconds(), directory=tmp_path, sleep_fn=lambda _s: None)
    assert result["action"] == "skip_already_flat"
    assert ex.created == []


def test_halt_blocks_buy_and_allows_sell(tmp_path):
    buy_ex = FakeExchange(_rows(42))
    path = ledger_path(SHORT.id, tmp_path)
    save_ledger(fresh_ledger(200.0, SHORT.id) | {"virtual_usdt": 150.0}, path)
    blocked = execute_cycle(
        buy_ex, SHORT, now_ms=buy_ex.milliseconds(), directory=tmp_path, sleep_fn=lambda _s: None
    )
    assert blocked["action"] == "skip_halt"
    assert buy_ex.created == []

    sell_ex = FakeExchange(_rows(73), mark=100.0)
    save_ledger(
        fresh_ledger(200.0, SHORT.id) | {"virtual_usdt": 10.0, "virtual_btc": 0.01},
        path,
    )
    sold = execute_cycle(
        sell_ex, SHORT, now_ms=sell_ex.milliseconds(), directory=tmp_path, sleep_fn=lambda _s: None
    )
    assert sold["action"] == "sell"
    assert len(sell_ex.created) == 1
    assert sell_ex.created[0]["side"] == "sell"
    assert sell_ex.created[0]["params"]["tgtCcy"] == "base_ccy"


def test_reconcile_does_not_send_a_second_order(tmp_path):
    rows = _rows(42)
    bar_ts = int(rows[-1][0])
    ex = FakeExchange(rows, mark=10000.0)
    ex.order = {
        "id": "ex-9",
        "filled": 0.01,
        "cost": 100.0,
        "average": 10000.0,
        "status": "closed",
        "side": "buy",
        "fee": {"cost": 0.5, "currency": "USDT"},
    }

    def _boom(*_args, **_kwargs):
        raise AssertionError("duplicate order")

    ex.create_order = _boom  # type: ignore[method-assign]
    path = ledger_path(SHORT.id, tmp_path)
    state = fresh_ledger(200.0, SHORT.id)
    state["pending_order"] = {
        "client_order_id": "abc123",
        "side": "buy",
        "signal_ts": bar_ts,
        "requested_qty": 0.01,
        "weight": 1.0,
        "symbol": "BTC/USDT",
        "mark_price": 10000.0,
    }
    state["last_attempt_ts"] = bar_ts
    save_ledger(state, path)
    result = execute_cycle(ex, SHORT, now_ms=ex.milliseconds(), directory=tmp_path, sleep_fn=lambda _s: None)
    assert result["action"] == "already_acted"
    booked = __import__("json").loads(path.read_text())
    assert booked["pending_order"] is None
    assert booked["virtual_btc"] == pytest.approx(0.01)
    assert booked["virtual_usdt"] == pytest.approx(99.5)
    assert booked["last_traded_ts"] == bar_ts


def test_network_error_does_not_retry_the_same_bar(tmp_path):
    rows = _rows(42)
    ex = FakeExchange(rows)
    ex.fail_network = True
    first = execute_cycle(ex, SHORT, now_ms=ex.milliseconds(), directory=tmp_path, sleep_fn=lambda _s: None)
    assert first["action"] == "buy_unknown"
    assert len(ex.created) == 1
    ex.fail_network = False
    ex.not_found = True
    second = execute_cycle(ex, SHORT, now_ms=ex.milliseconds(), directory=tmp_path, sleep_fn=lambda _s: None)
    assert second["action"] == "already_acted"
    assert len(ex.created) == 1
    booked = __import__("json").loads(ledger_path(SHORT.id, tmp_path).read_text())
    assert booked["pending_order"] is None
    assert booked["virtual_btc"] == 0.0


def test_loop_survives_an_exception_and_backs_off(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_cycle(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ccxt.ExchangeError("temporary")
        return {"action": "hold"}

    monkeypatch.setattr("execution.execute_cycle", fake_cycle)
    sleeps: list[float] = []
    ex = FakeExchange(_rows(2))
    run_loop(
        ex,
        [STRATEGIES["buy_and_hold"]],
        sleep_fn=sleeps.append,
        now_fn=lambda: START / 1000 + 5,
        max_cycles=1,
        directory=tmp_path,
    )
    assert calls["n"] == 2
    assert sleeps[0] == pytest.approx(backoff_seconds(1))
