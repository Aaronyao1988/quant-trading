#!/usr/bin/env python3
"""Virtual paper ledger for the OKX demo bot.

The JSON file is the source of truth for size and PnL. Exchange fills update
it only through the rules below. This module never talks to the network.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BOT_DIR = Path(__file__).resolve().parent
INITIAL_USDT = 200.0


class LedgerError(Exception):
    """Fatal ledger problem. The process must stop rather than trade."""


class FillRejected(Exception):
    """Fill cannot be booked. Balances are left unchanged."""


@dataclass
class ParsedFill:
    filled_base: float
    quote_notional: float
    fee_cost: float
    fee_currency: str | None
    average: float | None
    status: str | None
    order_id: str | None


def ledger_path(strategy_id: str, directory: Path | None = None) -> Path:
    return (directory or BOT_DIR) / f"ledger_{strategy_id}.json"


def fills_path_for(ledger: Path) -> Path:
    name = ledger.name
    if name.startswith("ledger_") and name.endswith(".json"):
        stem = name[len("ledger_") : -len(".json")]
        return ledger.with_name(f"fills_{stem}.jsonl")
    return ledger.with_suffix(".jsonl")


def fresh_ledger(initial_usdt: float = INITIAL_USDT, strategy_id: str | None = None) -> dict[str, Any]:
    if not math.isfinite(initial_usdt) or initial_usdt <= 0:
        raise LedgerError("initial USDT must be a positive finite number")
    return {
        "strategy": strategy_id,
        "initial_usdt": float(initial_usdt),
        "virtual_usdt": float(initial_usdt),
        "virtual_btc": 0.0,
        "last_traded_ts": None,
        "last_attempt_ts": None,
        "pending_order": None,
        "unbooked_order": None,
    }


def atomic_write_text(path: Path, text: str) -> None:
    """Write via a temp file in the same directory, then os.replace.

    A crash mid-write leaves the previous file intact. The temp file is
    removed if replace does not succeed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    try:
        tmp.write_text(text)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def save_ledger(state: dict[str, Any], path: Path) -> None:
    atomic_write_text(path, json.dumps(state, indent=2) + "\n")


def append_fill(path: Path, event: dict[str, Any]) -> None:
    """Append one JSON object as a single line. One small O_APPEND write."""
    line = json.dumps(event, separators=(",", ":"), default=str) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        os.write(fd, line.encode())
    finally:
        os.close(fd)


def _number(state: dict[str, Any], key: str, *, minimum: float = 0.0) -> float:
    if key not in state:
        raise LedgerError(f"Ledger missing required field {key}")
    try:
        value = float(state[key])
    except (TypeError, ValueError) as exc:
        raise LedgerError(f"Ledger field {key} is not a number") from exc
    if not math.isfinite(value) or value < minimum:
        raise LedgerError(f"Ledger field {key} must be a finite number >= {minimum}")
    return value


def _optional_ts(state: dict[str, Any], key: str) -> int | None:
    if key not in state or state[key] is None:
        return None
    try:
        return int(state[key])
    except (TypeError, ValueError) as exc:
        raise LedgerError(f"Ledger field {key} is not an integer timestamp") from exc


def load_ledger(
    path: Path,
    *,
    initial_usdt: float = INITIAL_USDT,
    strategy_id: str | None = None,
    create: bool = True,
) -> dict[str, Any]:
    """Load a ledger or create a fresh one. Refuses an unparseable file."""
    if not path.exists():
        if not create:
            raise LedgerError(f"Ledger does not exist: {path}")
        state = fresh_ledger(initial_usdt, strategy_id)
        save_ledger(state, path)
        return state
    try:
        raw = path.read_text()
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LedgerError(
            f"Refusing to start: ledger {path} is unparseable ({exc}). "
            "Fix the file or reset it with --reset-ledger."
        ) from exc
    except OSError as exc:
        raise LedgerError(f"Refusing to start: cannot read ledger {path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LedgerError(f"Refusing to start: ledger {path} is not a JSON object")
    state = dict(parsed)
    state["initial_usdt"] = _number(state, "initial_usdt", minimum=0.0)
    if state["initial_usdt"] <= 0:
        raise LedgerError("Ledger initial_usdt must be positive")
    state["virtual_usdt"] = _number(state, "virtual_usdt")
    state["virtual_btc"] = _number(state, "virtual_btc")
    state["last_traded_ts"] = _optional_ts(state, "last_traded_ts")
    state["last_attempt_ts"] = _optional_ts(state, "last_attempt_ts")
    pending = state.get("pending_order")
    if pending is not None and not isinstance(pending, dict):
        raise LedgerError("Ledger pending_order must be an object or null")
    state["pending_order"] = pending
    if "unbooked_order" not in state:
        state["unbooked_order"] = None
    if strategy_id is not None:
        existing = state.get("strategy")
        if existing not in (None, strategy_id):
            raise LedgerError(
                f"Ledger {path} belongs to strategy {existing}, not {strategy_id}"
            )
        state["strategy"] = strategy_id
    return state


def reset_ledger(
    path: Path,
    *,
    initial_usdt: float = INITIAL_USDT,
    strategy_id: str | None = None,
) -> dict[str, Any]:
    """Rotate the current ledger and fill log aside and write a fresh book."""
    import time

    stamp = int(time.time())
    if path.exists():
        backup = path.with_name(f"{path.stem}.backup.{stamp}{path.suffix}")
        os.replace(path, backup)
    fills = fills_path_for(path)
    if fills.exists():
        rotated = fills.with_name(f"{fills.stem}.backup.{stamp}{fills.suffix}")
        os.replace(fills, rotated)
    state = fresh_ledger(initial_usdt, strategy_id)
    save_ledger(state, path)
    return state


def _fee(order: dict[str, Any]) -> tuple[float, str | None]:
    """Read ccxt fee fields. Prefer ``fee`` so it is not added twice with ``fees``."""
    fee = order.get("fee")
    if isinstance(fee, dict) and fee.get("cost") not in (None, ""):
        return float(fee["cost"]), _ccy(fee.get("currency"))
    total = 0.0
    currency: str | None = None
    seen = False
    for item in order.get("fees") or []:
        if not isinstance(item, dict) or item.get("cost") in (None, ""):
            continue
        cost = float(item["cost"])
        ccy = _ccy(item.get("currency"))
        if seen and ccy and currency and ccy != currency:
            raise FillRejected(
                f"Order has fees in more than one currency ({currency} and {ccy})"
            )
        if ccy:
            currency = ccy
        total += cost
        seen = True
    if not seen:
        return 0.0, None
    return total, currency


def _ccy(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text.upper() if text else None


def parse_ccxt_order(
    order: dict[str, Any] | None,
    fallback_amount: float = 0.0,
    fallback_price: float = 0.0,
) -> ParsedFill:
    """Turn a ccxt order into base filled, quote notional, and fee.

    ``cost`` is the quote notional (price × base), not including the fee.
    ``filled`` is treated as the gross base amount. A positive fee in the base
    currency is removed from the credited BTC; a quote fee is added to the
    USDT outlay (buys) or taken out of proceeds (sells).
    """
    if not isinstance(order, dict):
        raise FillRejected("Order payload is not an object")
    filled = order.get("filled")
    cost = order.get("cost")
    average = order.get("average") if order.get("average") not in (None, "") else order.get("price")
    if filled is None:
        filled_amt = float(fallback_amount)
    else:
        filled_amt = float(filled)
    if cost is not None:
        quote = float(cost)
    elif average is not None and filled_amt:
        quote = filled_amt * float(average)
    else:
        quote = filled_amt * float(fallback_price)
    if not math.isfinite(filled_amt) or not math.isfinite(quote):
        raise FillRejected("Order fill fields are not finite")
    fee_cost, fee_ccy = _fee(order)
    if not math.isfinite(fee_cost):
        raise FillRejected("Order fee is not finite")
    if fee_cost > 0 and fee_ccy is None:
        raise FillRejected("Order has a positive fee with no currency; refusing to drop it")
    avg = float(average) if average not in (None, "") else None
    status = order.get("status")
    return ParsedFill(
        filled_base=filled_amt,
        quote_notional=quote,
        fee_cost=fee_cost,
        fee_currency=fee_ccy,
        average=avg,
        status=str(status).lower() if status else None,
        order_id=str(order["id"]) if order.get("id") is not None else None,
    )


def extract_fill(
    order: dict[str, Any],
    fallback_amount: float,
    fallback_price: float,
) -> tuple[float, float]:
    """Backward-compatible (filled base, quote notional) pair. Fees are separate."""
    parsed = parse_ccxt_order(order, fallback_amount, fallback_price)
    return parsed.filled_base, parsed.quote_notional


def _split_fee(parsed: ParsedFill, base: str, quote: str) -> tuple[float, float]:
    base_u, quote_u = base.upper(), quote.upper()
    if parsed.fee_cost == 0 or parsed.fee_currency is None:
        return 0.0, 0.0
    if parsed.fee_currency == base_u:
        return parsed.fee_cost, 0.0
    if parsed.fee_currency == quote_u:
        return 0.0, parsed.fee_cost
    raise FillRejected(
        f"Fee currency {parsed.fee_currency} is neither {base_u} nor {quote_u}"
    )


def _equity(usdt: float, btc: float, mark: float | None) -> float | None:
    if mark is None or not math.isfinite(mark):
        return None
    return usdt + btc * mark


def apply_buy_fill(
    state: dict[str, Any],
    parsed: ParsedFill,
    *,
    base: str,
    quote: str,
    mark_price: float | None = None,
    weight: float | None = None,
    client_order_id: str | None = None,
    signal_ts: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Book a buy. Scale BTC down when the quote outlay exceeds virtual cash.

    Returns a new state and a fill event. The input state is not mutated.
    A zero or non-positive net fill is rejected and must not change balances.
    """
    if parsed.filled_base <= 0 or parsed.quote_notional <= 0:
        raise FillRejected("Buy fill is empty; ledger unchanged")
    base_fee, quote_fee = _split_fee(parsed, base, quote)
    net_btc = parsed.filled_base - base_fee
    if net_btc <= 0:
        raise FillRejected("Base fee consumed the entire buy fill; ledger unchanged")
    quote_out = parsed.quote_notional + quote_fee
    if quote_out <= 0:
        raise FillRejected("Buy quote outlay is not positive; ledger unchanged")
    available = float(state["virtual_usdt"])
    if available <= 0:
        raise FillRejected("No virtual USDT; buy not booked")
    capped = quote_out > available + 1e-12
    if capped:
        scale = available / quote_out
        spent = available
        credited = net_btc * scale
    else:
        scale = 1.0
        spent = quote_out
        credited = net_btc
    if credited <= 0 or not math.isfinite(credited):
        raise FillRejected("Scaled BTC credit is not positive; ledger unchanged")
    new = dict(state)
    new["virtual_usdt"] = round(available - spent, 8)
    new["virtual_btc"] = round(float(state["virtual_btc"]) + credited, 8)
    event = {
        "strategy": state.get("strategy"),
        "side": "buy",
        "filled_base": parsed.filled_base,
        "credited_base": credited,
        "quote_notional": parsed.quote_notional,
        "fee_cost": parsed.fee_cost,
        "fee_currency": parsed.fee_currency,
        "spent_usdt": spent,
        "weight": weight,
        "capped": capped,
        "scale": scale,
        "average": parsed.average,
        "order_id": parsed.order_id,
        "client_order_id": client_order_id,
        "signal_ts": signal_ts,
        "virtual_usdt": new["virtual_usdt"],
        "virtual_btc": new["virtual_btc"],
        "equity": _equity(new["virtual_usdt"], new["virtual_btc"], mark_price),
        "mark_price": mark_price,
    }
    return new, event


def apply_sell_fill(
    state: dict[str, Any],
    parsed: ParsedFill,
    *,
    base: str,
    quote: str,
    mark_price: float | None = None,
    client_order_id: str | None = None,
    signal_ts: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Book a sell. Cap proceeds at the BTC the ledger actually held.

    Dust below an exchange minimum is kept. It is not deleted.
    """
    if parsed.filled_base <= 0 or parsed.quote_notional < 0:
        raise FillRejected("Sell fill is empty; ledger unchanged")
    held = float(state["virtual_btc"])
    if held <= 0:
        raise FillRejected("Ledger is flat; sell not booked")
    _base_fee, quote_fee = _split_fee(parsed, base, quote)
    net_proceeds = parsed.quote_notional - quote_fee
    capped = parsed.filled_base > held + 1e-12
    if capped:
        scale = held / parsed.filled_base
        proceeds = net_proceeds * scale
        applied = held
    else:
        scale = 1.0
        proceeds = net_proceeds
        applied = parsed.filled_base
    if not math.isfinite(proceeds):
        raise FillRejected("Sell proceeds are not finite; ledger unchanged")
    # A fee larger than the notional would invent a negative credit. Book zero
    # proceeds and keep the fee visible on the event rather than paying it twice.
    proceeds_booked = proceeds if proceeds > 0 else 0.0
    new = dict(state)
    new["virtual_btc"] = round(held - applied, 8)
    if new["virtual_btc"] < 0:
        new["virtual_btc"] = 0.0
    new["virtual_usdt"] = round(float(state["virtual_usdt"]) + proceeds_booked, 8)
    event = {
        "strategy": state.get("strategy"),
        "side": "sell",
        "filled_base": parsed.filled_base,
        "sold_base": applied,
        "quote_notional": parsed.quote_notional,
        "fee_cost": parsed.fee_cost,
        "fee_currency": parsed.fee_currency,
        "proceeds_usdt": proceeds_booked,
        "capped": capped,
        "scale": scale,
        "average": parsed.average,
        "order_id": parsed.order_id,
        "client_order_id": client_order_id,
        "signal_ts": signal_ts,
        "virtual_usdt": new["virtual_usdt"],
        "virtual_btc": new["virtual_btc"],
        "equity": _equity(new["virtual_usdt"], new["virtual_btc"], mark_price),
        "mark_price": mark_price,
    }
    return new, event


def commit_fill(state: dict[str, Any], event: dict[str, Any], ledger: Path) -> None:
    """Persist balances and append the fill. Ledger replace happens first."""
    save_ledger(state, ledger)
    append_fill(fills_path_for(ledger), event)
