"""Ledger integrity: caps, fees, atomic writes, reset, unparseable files."""

from __future__ import annotations

import json

import pytest

from ledger import (
    FeeUnconverted,
    FillRejected,
    LedgerError,
    ParsedFill,
    apply_buy_fill,
    apply_sell_fill,
    commit_fill,
    fills_path_for,
    fresh_ledger,
    load_ledger,
    parse_ccxt_order,
    reset_ledger,
    save_ledger,
)


def _state(**overrides):
    state = fresh_ledger(200.0, "spec_v1")
    state.update(overrides)
    return state


def test_buy_scales_btc_when_cost_exceeds_cash():
    parsed = parse_ccxt_order(
        {"id": "1", "filled": 0.01, "cost": 500.0, "average": 50000.0, "status": "closed"}
    )
    new, event = apply_buy_fill( _state(), parsed, base="BTC", quote="USDT", mark_price=50000.0)
    assert event["capped"] is True
    assert event["scale"] == pytest.approx(0.4)
    assert new["virtual_btc"] == pytest.approx(0.004)
    assert new["virtual_usdt"] == pytest.approx(0.0)
    # The old bug credited the full 0.01 BTC while only spending 200 USDT.
    assert new["virtual_btc"] < parsed.filled_base


def test_buy_subtracts_quote_fee():
    parsed = parse_ccxt_order(
        {
            "id": "1",
            "filled": 0.01,
            "cost": 100.0,
            "average": 10000.0,
            "status": "closed",
            "fee": {"cost": 1.0, "currency": "USDT"},
        }
    )
    new, event = apply_buy_fill(_state(), parsed, base="BTC", quote="USDT", mark_price=10000.0)
    assert event["capped"] is False
    assert event["fee_cost"] == pytest.approx(1.0)
    assert event["spent_usdt"] == pytest.approx(101.0)
    assert new["virtual_usdt"] == pytest.approx(99.0)
    assert new["virtual_btc"] == pytest.approx(0.01)


def test_buy_subtracts_base_fee_and_does_not_double_count_fees_list():
    parsed = parse_ccxt_order(
        {
            "id": "1",
            "filled": 0.01,
            "cost": 100.0,
            "average": 10000.0,
            "status": "closed",
            "fee": {"cost": 0.0001, "currency": "BTC"},
            "fees": [{"cost": 0.0001, "currency": "BTC"}],
        }
    )
    assert parsed.fee_cost == pytest.approx(0.0001)
    new, event = apply_buy_fill(_state(), parsed, base="BTC", quote="USDT", mark_price=10000.0)
    assert new["virtual_btc"] == pytest.approx(0.0099)
    assert new["virtual_usdt"] == pytest.approx(100.0)
    assert event["credited_base"] == pytest.approx(0.0099)


def test_sell_caps_proceeds_to_btc_held_and_subtracts_fee():
    parsed = parse_ccxt_order(
        {
            "id": "2",
            "filled": 0.02,
            "cost": 1000.0,
            "average": 50000.0,
            "status": "closed",
            "fee": {"cost": 1.0, "currency": "USDT"},
        }
    )
    new, event = apply_sell_fill(
        _state(virtual_btc=0.01, virtual_usdt=0.0),
        parsed,
        base="BTC",
        quote="USDT",
        mark_price=50000.0,
    )
    assert event["capped"] is True
    assert event["scale"] == pytest.approx(0.5)
    assert event["proceeds_usdt"] == pytest.approx(499.5)
    assert new["virtual_btc"] == pytest.approx(0.0)
    assert new["virtual_usdt"] == pytest.approx(499.5)


def test_partial_sell_keeps_residual_btc():
    parsed = ParsedFill(0.005, 250.0, 0.0, None, 50000.0, "closed", "3")
    new, _event = apply_sell_fill(
        _state(virtual_btc=0.02, virtual_usdt=10.0),
        parsed,
        base="BTC",
        quote="USDT",
    )
    assert new["virtual_btc"] == pytest.approx(0.015)
    assert new["virtual_usdt"] == pytest.approx(260.0)


def test_empty_buy_is_rejected():
    parsed = parse_ccxt_order({"filled": 0, "cost": 0, "status": "closed"})
    with pytest.raises(FillRejected):
        apply_buy_fill(_state(), parsed, base="BTC", quote="USDT")


def test_atomic_replace_keeps_previous_file_when_replace_fails(tmp_path, monkeypatch):
    path = tmp_path / "ledger_spec_v1.json"
    save_ledger(_state(), path)
    original = path.read_text()

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("ledger.os.replace", boom)
    with pytest.raises(OSError):
        save_ledger(_state(virtual_usdt=1.0), path)
    assert path.read_text() == original
    assert list(tmp_path.glob("*.tmp.*")) == []


def test_unparseable_ledger_refuses_to_load(tmp_path):
    path = tmp_path / "ledger_spec_v1.json"
    path.write_text("{not json")
    with pytest.raises(LedgerError, match="unparseable"):
        load_ledger(path, strategy_id="spec_v1")


def test_reset_ledger_starts_at_200(tmp_path):
    path = tmp_path / "ledger_spec_v1.json"
    save_ledger(_state(virtual_usdt=12.5, virtual_btc=0.2), path)
    fills = fills_path_for(path)
    fills.write_text('{"side":"buy"}\n')
    fresh = reset_ledger(path, initial_usdt=200.0, strategy_id="spec_v1")
    assert fresh["virtual_usdt"] == 200.0
    assert fresh["virtual_btc"] == 0.0
    assert fresh["pending_order"] is None
    assert json.loads(path.read_text())["virtual_usdt"] == 200.0
    assert not fills.exists()
    assert list(tmp_path.glob("*.backup.*"))


def test_commit_fill_appends_jsonl(tmp_path):
    path = tmp_path / "ledger_spec_v1.json"
    state = _state(virtual_usdt=150.0, virtual_btc=0.001)
    commit_fill(state, {"side": "buy", "credited_base": 0.001}, path)
    lines = fills_path_for(path).read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["side"] == "buy"
    assert json.loads(path.read_text())["virtual_usdt"] == 150.0


def test_cancelled_order_does_not_use_requested_quantity():
    parsed = parse_ccxt_order(
        {"id": "1", "status": "canceled", "filled": None, "cost": None},
        fallback_amount=0.01,
        fallback_price=50_000.0,
    )
    assert parsed.filled_base == 0.0
    before = _state()
    with pytest.raises(FillRejected):
        apply_buy_fill(before, parsed, base="BTC", quote="USDT", mark_price=50_000.0)
    assert before["virtual_usdt"] == 200.0
    assert before["virtual_btc"] == 0.0


def test_rejected_and_expired_null_fills_stay_zero():
    for status in ("rejected", "expired", "cancelled"):
        parsed = parse_ccxt_order(
            {"status": status, "filled": None, "cost": None},
            fallback_amount=1.0,
            fallback_price=100.0,
        )
        assert parsed.filled_base == 0.0


def test_partial_cancel_keeps_reported_size_only():
    parsed = parse_ccxt_order(
        {"status": "canceled", "filled": 0.004, "cost": 40.0, "average": 10_000.0},
        fallback_amount=1.0,
        fallback_price=10_000.0,
    )
    assert parsed.filled_base == pytest.approx(0.004)
    new, _event = apply_buy_fill(_state(), parsed, base="BTC", quote="USDT")
    assert new["virtual_btc"] == pytest.approx(0.004)
    assert new["virtual_usdt"] == pytest.approx(160.0)


def test_third_currency_fee_is_not_treated_as_zero():
    parsed = ParsedFill(0.01, 100.0, 0.5, "OKB", 10_000.0, "closed", "1")
    with pytest.raises(FeeUnconverted) as caught:
        apply_buy_fill(_state(), parsed, base="BTC", quote="USDT")
    assert caught.value.currency == "OKB"
    assert caught.value.cost == pytest.approx(0.5)
