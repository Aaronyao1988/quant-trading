#!/usr/bin/env python3
"""Sandbox execution loop. One order per closed bar, reconciled by client id.

Live trading is not implemented. Callers must pass an exchange whose
``x-simulated-trading`` header is ``1``.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import ccxt
import pandas as pd

from ledger import (
    FillRejected,
    LedgerError,
    apply_buy_fill,
    apply_sell_fill,
    commit_fill,
    ledger_path,
    load_ledger,
    parse_ccxt_order,
    save_ledger,
)
from strategy import (
    HALT_EQUITY_FRACTION,
    Strategy,
    decide,
    entry_weight,
    halted,
    latest_signal,
    timeframe_to_ms,
)

LOGGER = logging.getLogger("okx-demo-bot")

SYMBOL = "BTC/USDT"
# Wake this long after the candle boundary so the closed bar is published.
CLOSE_BUFFER_SEC = 2.0
# A signal older than this is not a next-open fill. Skip it.
ACT_WINDOW_SEC = 30.0
FETCH_LIMIT = 100


def new_client_id() -> str:
    """OKX clOrdId: 1–32 alphanumeric characters."""
    return uuid.uuid4().hex


def spot_market_order_params(client_order_id: str) -> dict[str, str]:
    """Params for an OKX spot market order.

    OKX's own default for a spot market *buy* is ``tgtCcy=quote_ccy``, so
    ``sz`` is USDT notional. A market sell defaults to ``base_ccy`` (BTC).
    ccxt 4.5 forwards ``options['tgtCcy']`` and defaults that option to
    ``base_ccy``, but a missing ``tgtCcy`` (older ccxt, or a client that
    omits it) follows the venue and would treat a BTC quantity as USDT.

    Every order this bot sends sets ``tgtCcy=base_ccy`` and a client id that
    was already written to the ledger. Confirm the interpretation on the demo
    account with ``python bot.py --check-order-size`` before trusting size.
    """
    return {"tgtCcy": "base_ccy", "clientOrderId": client_order_id}


def assert_sandbox(exchange: Any) -> None:
    header = (getattr(exchange, "headers", None) or {}).get("x-simulated-trading")
    if str(header) != "1":
        raise RuntimeError(
            "Refusing to trade: x-simulated-trading is not '1'. "
            "This process only places OKX demo (sandbox) orders."
        )


def split_symbol(symbol: str) -> tuple[str, str]:
    base, quote = symbol.split("/")
    return base, quote


def backoff_seconds(failures: int) -> float:
    if failures < 1:
        return 0.0
    return min(300.0, 5.0 * (2 ** (failures - 1)))


def last_closed_open_ms(now_ms: int, tf_ms: int) -> int:
    """Open timestamp of the candle that has already closed."""
    boundary = (now_ms // tf_ms) * tf_ms
    return boundary - tf_ms


@dataclass
class Wake:
    action: str  # run | sleep | skip_stale
    delay_sec: float
    closed_open_ms: int


def plan_wake(
    now_sec: float,
    tf_ms: int,
    buffer_sec: float,
    act_window_sec: float,
    serviced_open_ms: int | None,
) -> Wake:
    """Decide whether to trade the bar that just closed or wait."""
    now_ms = int(now_sec * 1000)
    closed_open = last_closed_open_ms(now_ms, tf_ms)
    closed_at = (closed_open + tf_ms) / 1000.0
    elapsed = now_sec - closed_at
    next_close = closed_at + (tf_ms / 1000.0)
    if serviced_open_ms == closed_open:
        return Wake("sleep", max(0.0, next_close + buffer_sec - now_sec), closed_open)
    if elapsed > act_window_sec:
        return Wake("skip_stale", max(0.0, next_close + buffer_sec - now_sec), closed_open)
    if elapsed < buffer_sec:
        return Wake("sleep", buffer_sec - elapsed, closed_open)
    return Wake("run", 0.0, closed_open)


def fetch_ohlcv_paginated(
    exchange: Any,
    symbol: str,
    timeframe: str,
    min_bars: int,
    now_ms: int,
    *,
    limit: int = FETCH_LIMIT,
) -> list[list[float]]:
    """Page forward until ``min_bars`` candles covering ``now_ms`` are in hand."""
    tf_ms = timeframe_to_ms(timeframe)
    since = now_ms - (min_bars + 5) * tf_ms
    rows: list[list[float]] = []
    seen: set[int] = set()
    for _ in range(80):
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
        if not batch:
            break
        for row in batch:
            ts = int(row[0])
            if ts not in seen:
                seen.add(ts)
                rows.append(row)
        last = int(batch[-1][0])
        if last <= since:
            break
        since = last + 1
        reached_now = last + tf_ms >= now_ms
        if reached_now and len(rows) >= min_bars:
            break
        if len(batch) < limit and reached_now:
            break
    rows.sort(key=lambda row: int(row[0]))
    return rows


def rows_to_frame(rows: list[list[float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])


def fetch_closed_frame(
    exchange: Any,
    spec: Strategy,
    now_ms: int,
    *,
    symbol: str = SYMBOL,
    attempts: int = 5,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> pd.DataFrame:
    """Closed candles only, at least ``spec.min_closed`` of them, including the just-closed bar."""
    tf_ms = timeframe_to_ms(spec.timeframe)
    expected = last_closed_open_ms(now_ms, tf_ms)
    need = spec.min_closed + 2
    last_error = "closed bar was not published"
    for attempt in range(attempts):
        rows = fetch_ohlcv_paginated(exchange, symbol, spec.timeframe, need, now_ms)
        closed = [row for row in rows if int(row[0]) + tf_ms <= now_ms]
        if closed and int(closed[-1][0]) >= expected and len(closed) >= spec.min_closed:
            return rows_to_frame(closed)
        last_error = (
            f"have {len(closed)} closed {spec.timeframe} bars, "
            f"latest open {closed[-1][0] if closed else None}, expected {expected}"
        )
        if attempt + 1 < attempts:
            sleep_fn(1.0 + attempt)
    raise RuntimeError(f"Closed {spec.timeframe} bar not ready: {last_error}")


def market_limits(exchange: Any, symbol: str) -> tuple[float, float]:
    market = exchange.market(symbol)
    limits = market.get("limits") or {}
    amount = (limits.get("amount") or {}).get("min")
    cost = (limits.get("cost") or {}).get("min")
    return float(amount if amount is not None else 1e-5), float(cost if cost is not None else 5.0)


def _mark_price(exchange: Any, frame: pd.DataFrame, symbol: str) -> float:
    try:
        ticker = exchange.fetch_ticker(symbol)
        last = ticker.get("last")
        if last:
            return float(last)
    except ccxt.BaseError as exc:
        LOGGER.warning("fetch_ticker failed (%s); using last close", exc)
    return float(frame.iloc[-1]["close"])


def _floor_qty(exchange: Any, symbol: str, qty: float, cap: float) -> float:
    precise = float(exchange.amount_to_precision(symbol, qty))
    if precise > cap > 0:
        precise = float(exchange.amount_to_precision(symbol, cap * 0.999))
    if precise > cap:
        return 0.0
    return precise


def _fetch_client_order(
    exchange: Any,
    symbol: str,
    client_order_id: str,
    *,
    attempts: int = 3,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any] | None:
    """Fetch by clOrdId. A missing order is retried briefly before we give up.

    OKX can return not-found for an order that just landed. Treating the first
    miss as final would drop a real demo fill off the ledger.
    """
    for attempt in range(attempts):
        try:
            return exchange.fetch_order(
                client_order_id, symbol, {"clientOrderId": client_order_id}
            )
        except ccxt.OrderNotFound:
            if attempt + 1 == attempts:
                return None
            sleep_fn(0.25)
        except ccxt.NetworkError:
            if attempt + 1 == attempts:
                raise
            sleep_fn(0.25)
    return None


def _order_still_open(order: dict[str, Any]) -> bool:
    status = str(order.get("status") or "").lower()
    if status in {"closed", "filled", "canceled", "cancelled", "rejected", "expired"}:
        return False
    if status in {"open", "live"}:
        return True
    filled = order.get("filled")
    return filled in (None, 0, 0.0, "0")


def reconcile_pending(
    exchange: Any,
    state: dict[str, Any],
    spec: Strategy,
    *,
    symbol: str = SYMBOL,
    mark_price: float | None = None,
    ledger=None,
    directory: Path | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Apply a previously stored client order. Never sends a second order."""
    pending = state.get("pending_order")
    if not pending:
        return state
    path = ledger or ledger_path(spec.id, directory)
    coid = pending["client_order_id"]
    order = _fetch_client_order(
        exchange, pending.get("symbol") or symbol, coid, sleep_fn=sleep_fn
    )
    if order is None:
        LOGGER.error(
            "Client order %s was not found. Skipping that bar so it is not sent again. "
            "Check the demo account if a fill landed late.",
            coid,
        )
        state = dict(state)
        state["pending_order"] = None
        save_ledger(state, path)
        return state
    if _order_still_open(order):
        LOGGER.info("Client order %s is still open; not sending another.", coid)
        return state
    return _book_order(exchange, state, spec, order, pending, mark_price, path, symbol)


def _book_order(
    exchange: Any,
    state: dict[str, Any],
    spec: Strategy,
    order: dict[str, Any],
    pending: dict[str, Any],
    mark_price: float | None,
    path,
    symbol: str,
) -> dict[str, Any]:
    base, quote = split_symbol(symbol)
    try:
        parsed = parse_ccxt_order(
            order,
            fallback_amount=float(pending.get("requested_qty") or 0.0),
            fallback_price=float(pending.get("mark_price") or mark_price or 0.0),
        )
        if pending["side"] == "buy":
            new_state, event = apply_buy_fill(
                state,
                parsed,
                base=base,
                quote=quote,
                mark_price=mark_price,
                weight=pending.get("weight"),
                client_order_id=pending.get("client_order_id"),
                signal_ts=pending.get("signal_ts"),
            )
        else:
            new_state, event = apply_sell_fill(
                state,
                parsed,
                base=base,
                quote=quote,
                mark_price=mark_price,
                client_order_id=pending.get("client_order_id"),
                signal_ts=pending.get("signal_ts"),
            )
    except FillRejected as exc:
        LOGGER.error(
            "Fill for %s was not booked (%s). Balances unchanged; bar will not be retried.",
            pending.get("client_order_id"),
            exc,
        )
        new_state = dict(state)
        new_state["pending_order"] = None
        new_state["unbooked_order"] = {
            "client_order_id": pending.get("client_order_id"),
            "side": pending.get("side"),
            "signal_ts": pending.get("signal_ts"),
            "reason": str(exc),
        }
        save_ledger(new_state, path)
        return new_state
    new_state["pending_order"] = None
    new_state["unbooked_order"] = None
    new_state["last_traded_ts"] = pending.get("signal_ts")
    new_state["last_attempt_ts"] = pending.get("signal_ts")
    event["strategy"] = spec.id
    event["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    commit_fill(new_state, event, path)
    LOGGER.info(
        "%s %s booked: base=%s quote_spent_or_proceeds=%s equity=%s capped=%s",
        spec.id,
        event["side"],
        event.get("credited_base", event.get("sold_base")),
        event.get("spent_usdt", event.get("proceeds_usdt")),
        event.get("equity"),
        event.get("capped"),
    )
    return new_state


def _remember_attempt(state: dict[str, Any], bar_ts: int, path) -> dict[str, Any]:
    state = dict(state)
    state["last_attempt_ts"] = bar_ts
    state["pending_order"] = None
    save_ledger(state, path)
    return state


def execute_cycle(
    exchange: Any,
    spec: Strategy,
    *,
    symbol: str = SYMBOL,
    dry_run: bool = False,
    now_ms: int | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    fetch_attempts: int = 5,
    directory: Path | None = None,
    initial_usdt: float = 200.0,
) -> dict[str, Any]:
    """One closed bar for one paper book. At most one new order."""
    assert_sandbox(exchange)
    path = ledger_path(spec.id, directory)
    state = load_ledger(path, initial_usdt=initial_usdt, strategy_id=spec.id)
    if now_ms is None:
        now_ms = int(exchange.milliseconds())
    frame = fetch_closed_frame(
        exchange, spec, now_ms, symbol=symbol, attempts=fetch_attempts, sleep_fn=sleep_fn
    )
    mark = _mark_price(exchange, frame, symbol)
    if state.get("pending_order"):
        state = reconcile_pending(
            exchange,
            state,
            spec,
            symbol=symbol,
            mark_price=mark,
            ledger=path,
            sleep_fn=sleep_fn,
        )
        if state.get("pending_order"):
            return {"action": "pending", "strategy": spec.id}

    bar_ts = int(frame.iloc[-1]["ts"])
    signal = latest_signal(frame, spec)
    equity = float(state["virtual_usdt"]) + float(state["virtual_btc"]) * mark
    LOGGER.info(
        "%s ts=%s signal=%s equity=%.4f usdt=%.4f btc=%.8f",
        spec.id,
        bar_ts,
        signal,
        equity,
        state["virtual_usdt"],
        state["virtual_btc"],
    )
    if state.get("last_attempt_ts") == bar_ts or state.get("last_traded_ts") == bar_ts:
        return {"action": "already_acted", "strategy": spec.id, "signal": signal, "equity": equity}

    min_amount, min_cost = market_limits(exchange, symbol)
    flat = float(state["virtual_btc"]) < min_amount
    action = decide(signal, flat=flat, halted_now=halted(equity, float(state["initial_usdt"])))
    if action != "buy" and action != "sell":
        LOGGER.info("%s %s", spec.id, action)
        return {"action": action, "strategy": spec.id, "signal": signal, "equity": equity}

    if action == "buy":
        weight = entry_weight(frame, spec)
        if weight is None or weight <= 0:
            state = _remember_attempt(state, bar_ts, path)
            LOGGER.info("%s skipped buy: vol weight undefined", spec.id)
            return {"action": "skip_weight", "strategy": spec.id}
        spend = float(state["virtual_usdt"]) * weight
        if spend < min_cost or mark <= 0:
            state = _remember_attempt(state, bar_ts, path)
            LOGGER.info("%s skipped buy: spend %.4f below min notional", spec.id, spend)
            return {"action": "skip_min_notional", "strategy": spec.id}
        qty = _floor_qty(exchange, symbol, spend / mark, spend / mark)
        if qty < min_amount or qty * mark < min_cost:
            state = _remember_attempt(state, bar_ts, path)
            LOGGER.info("%s skipped buy: qty %s below exchange minimum", spec.id, qty)
            return {"action": "skip_min_notional", "strategy": spec.id}
        if dry_run:
            LOGGER.info("%s DRY-RUN BUY %.8f BTC weight=%.4f spend=%.4f", spec.id, qty, weight, spend)
            return {"action": "dry_run_buy", "strategy": spec.id, "qty": qty, "weight": weight, "spend": spend}
        return _send(
            exchange, state, spec, path, symbol, "buy", qty, bar_ts, mark, weight, spend
        )

    qty = _floor_qty(exchange, symbol, float(state["virtual_btc"]), float(state["virtual_btc"]))
    if qty < min_amount:
        state = _remember_attempt(state, bar_ts, path)
        LOGGER.info("%s skipped sell: qty below minimum", spec.id)
        return {"action": "skip_min_notional", "strategy": spec.id}
    if dry_run:
        LOGGER.info("%s DRY-RUN SELL %.8f BTC", spec.id, qty)
        return {"action": "dry_run_sell", "strategy": spec.id, "qty": qty}
    return _send(exchange, state, spec, path, symbol, "sell", qty, bar_ts, mark, None, None)


def _send(
    exchange: Any,
    state: dict[str, Any],
    spec: Strategy,
    path,
    symbol: str,
    side: str,
    qty: float,
    bar_ts: int,
    mark: float,
    weight: float | None,
    spend: float | None,
) -> dict[str, Any]:
    coid = new_client_id()
    pending = {
        "client_order_id": coid,
        "side": side,
        "signal_ts": bar_ts,
        "requested_qty": qty,
        "requested_spend": spend,
        "weight": weight,
        "symbol": symbol,
        "mark_price": mark,
    }
    # Persist the id before the request so a crash cannot send a second order.
    state = dict(state)
    state["pending_order"] = pending
    state["last_attempt_ts"] = bar_ts
    save_ledger(state, path)
    params = spot_market_order_params(coid)
    try:
        order = exchange.create_order(symbol, "market", side, qty, None, params)
    except ccxt.NetworkError as exc:
        LOGGER.error(
            "%s %s network error after id %s was stored (%s). "
            "Will reconcile; this bar will not be sent again.",
            spec.id,
            side,
            coid,
            exc,
        )
        return {"action": f"{side}_unknown", "strategy": spec.id, "client_order_id": coid}
    except ccxt.ExchangeError as exc:
        LOGGER.error("%s %s rejected (%s). Bar skipped.", spec.id, side, exc)
        state = dict(state)
        state["pending_order"] = None
        save_ledger(state, path)
        return {"action": f"{side}_rejected", "strategy": spec.id, "error": str(exc)}
    if _order_still_open(order):
        state = dict(state)
        state["pending_order"] = dict(pending)
        state["pending_order"]["exchange_order_id"] = order.get("id")
        save_ledger(state, path)
        LOGGER.info("%s %s %s still open; left pending for reconciliation.", spec.id, side, coid)
        return {"action": f"{side}_working", "strategy": spec.id, "client_order_id": coid}
    state = _book_order(exchange, state, spec, order, pending, mark, path, symbol)
    return {"action": side, "strategy": spec.id, "client_order_id": coid, "equity": None}


def run_loop(
    exchange: Any,
    specs: list[Strategy],
    *,
    symbol: str = SYMBOL,
    dry_run: bool = False,
    buffer_sec: float = CLOSE_BUFFER_SEC,
    act_window_sec: float = ACT_WINDOW_SEC,
    sleep_fn: Callable[[float], None] = time.sleep,
    now_fn: Callable[[], float] = time.time,
    max_cycles: int | None = None,
    directory: Path | None = None,
    initial_usdt: float = 200.0,
) -> int:
    """Sleep until each candle close, then run every book once.

    Startup reconciliation runs immediately, including mid-bar, so a crash
    after an order is booked before the next close.
    """
    assert_sandbox(exchange)
    if len({spec.timeframe for spec in specs}) != 1:
        raise LedgerError("A loop can only mix books that share a timeframe")
    tf_ms = timeframe_to_ms(specs[0].timeframe)
    for spec in specs:
        state = load_ledger(
            ledger_path(spec.id, directory),
            initial_usdt=initial_usdt,
            strategy_id=spec.id,
        )
        if state.get("pending_order"):
            reconcile_pending(
                exchange,
                state,
                spec,
                symbol=symbol,
                directory=directory,
                sleep_fn=sleep_fn,
            )
    serviced: int | None = None
    failures = 0
    cycles = 0
    while max_cycles is None or cycles < max_cycles:
        wake = plan_wake(now_fn(), tf_ms, buffer_sec, act_window_sec, serviced)
        if wake.action == "sleep":
            LOGGER.info("Sleeping %.1fs until candle close + %.1fs", wake.delay_sec, buffer_sec)
            sleep_fn(wake.delay_sec)
            continue
        if wake.action == "skip_stale":
            LOGGER.info(
                "Last closed bar is older than %.0fs; waiting for the next close.",
                act_window_sec,
            )
            serviced = wake.closed_open_ms
            sleep_fn(wake.delay_sec)
            continue
        try:
            now_ms = int(now_fn() * 1000)
            for spec in specs:
                execute_cycle(
                    exchange,
                    spec,
                    symbol=symbol,
                    dry_run=dry_run,
                    now_ms=now_ms,
                    sleep_fn=sleep_fn,
                    directory=directory,
                    initial_usdt=initial_usdt,
                )
            serviced = wake.closed_open_ms
            failures = 0
            cycles += 1
        except LedgerError:
            raise
        except Exception as exc:  # noqa: BLE001 — loop must survive a bad cycle
            failures += 1
            delay = backoff_seconds(failures)
            LOGGER.error("Cycle failed (%s). Backing off %.0fs.", exc, delay)
            sleep_fn(delay)
    return 0
