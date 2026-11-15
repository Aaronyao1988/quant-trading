#!/usr/bin/env python3
"""OKX BTC/USDT spot demo bot: SMA 10/30 crossover on 15m candles.

Virtual $200 USDT sub-ledger is the source of truth for sizing / PnL.
Orders still go to OKX demo trading (paper fills via x-simulated-trading).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import ccxt
import pandas as pd

LOGGER = logging.getLogger("okx-demo-bot")

DEFAULT_SYMBOL = "BTC/USDT"
DEFAULT_TIMEFRAME = "15m"
DEFAULT_FAST = 10
DEFAULT_SLOW = 30
DEFAULT_ALLOCATION_PCT = 0.50
DEFAULT_INITIAL_USDT = 200.0
DEFAULT_SLEEP_SEC = 60
LEDGER_FILENAME = "virtual_ledger_200.json"
# OKX spot BTC/USDT min notional is typically ~5 USDT; keep as floor fallback.
DEFAULT_MIN_NOTIONAL_USDT = 5.0


def ledger_path() -> Path:
    """Persist ledger next to this script so cwd does not matter."""
    return Path(__file__).resolve().parent / LEDGER_FILENAME


def load_ledger(initial_usdt: float = DEFAULT_INITIAL_USDT, path: Path | None = None) -> dict:
    """Load persisted virtual sub-ledger or initialize a new one."""
    path = path or ledger_path()
    if path.exists():
        state = json.loads(path.read_text())
        for key in ("initial_usdt", "virtual_usdt", "virtual_btc", "last_traded_ts"):
            if key not in state:
                raise ValueError(f"Ledger missing required key: {key}")
        return state

    state = {
        "initial_usdt": float(initial_usdt),
        "virtual_usdt": float(initial_usdt),
        "virtual_btc": 0.0,
        "last_traded_ts": None,
    }
    save_ledger(state, path=path)
    return state


def save_ledger(state: dict, path: Path | None = None) -> None:
    path = path or ledger_path()
    path.write_text(json.dumps(state, indent=2) + "\n")


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(
            f"Missing required env var {name}. "
            "Create OKX Demo Trading API keys and export "
            "OKX_API_KEY, OKX_API_SECRET, OKX_API_PASSPHRASE."
        )
    return value


def create_okx_demo_exchange() -> ccxt.okx:
    """Build a ccxt OKX client locked to demo/sandbox trading."""
    exchange = ccxt.okx(
        {
            "apiKey": require_env("OKX_API_KEY"),
            "secret": require_env("OKX_API_SECRET"),
            "password": require_env("OKX_API_PASSPHRASE"),
            "enableRateLimit": True,
            "options": {
                "defaultType": "spot",
            },
        }
    )
    # Critical: attaches x-simulated-trading: 1 so requests stay on demo paper funds.
    exchange.set_sandbox_mode(True)
    header = exchange.headers.get("x-simulated-trading")
    if str(header) != "1":
        raise RuntimeError(
            "OKX demo header missing after set_sandbox_mode(True); "
            f"got x-simulated-trading={header!r}. Refusing to trade."
        )
    return exchange


def fetch_closed_candles(
    exchange: ccxt.Exchange,
    symbol: str,
    timeframe: str,
    slow: int,
) -> pd.DataFrame:
    """Fetch OHLCV and drop the still-forming candle."""
    limit = max(slow + 10, 50)
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    if not ohlcv or len(ohlcv) < slow + 2:
        raise RuntimeError(
            f"Not enough candles for SMA({slow}): got {0 if not ohlcv else len(ohlcv)}"
        )
    df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
    # Last row is the in-progress candle; strategy uses only closed bars.
    return df.iloc[:-1].copy().reset_index(drop=True)


def compute_signal(
    df: pd.DataFrame,
    fast: int = DEFAULT_FAST,
    slow: int = DEFAULT_SLOW,
) -> str:
    """SMA crossover on the two most recent *closed* candles.

    Returns BUY / SELL / HOLD. HOLD when SMAs are still NaN (warmup).
    """
    if len(df) < slow + 1:
        return "HOLD"

    work = df.copy()
    work["sma_fast"] = work["close"].rolling(fast).mean()
    work["sma_slow"] = work["close"].rolling(slow).mean()

    prev, last_closed = work.iloc[-2], work.iloc[-1]
    values = [
        prev["sma_fast"],
        prev["sma_slow"],
        last_closed["sma_fast"],
        last_closed["sma_slow"],
    ]
    if any(pd.isna(v) for v in values):
        return "HOLD"

    if prev["sma_fast"] <= prev["sma_slow"] and last_closed["sma_fast"] > last_closed["sma_slow"]:
        return "BUY"
    if prev["sma_fast"] >= prev["sma_slow"] and last_closed["sma_fast"] < last_closed["sma_slow"]:
        return "SELL"
    return "HOLD"


def min_amount(market: dict) -> float:
    limits = (market.get("limits") or {}).get("amount") or {}
    raw = limits.get("min")
    return float(raw) if raw is not None else 0.00001


def min_notional(market: dict) -> float:
    limits = (market.get("limits") or {}).get("cost") or {}
    raw = limits.get("min")
    if raw is not None:
        return float(raw)
    return DEFAULT_MIN_NOTIONAL_USDT


def extract_fill(order: dict, fallback_amount: float, fallback_price: float) -> tuple[float, float]:
    """Prefer exchange-reported filled amount and cost over estimates.

    Missing ``filled``/``cost`` fall back to requested size × mark price.
    An explicit zero fill stays zero (do not invent a fill).
    """
    filled = order.get("filled")
    cost = order.get("cost")
    average = order.get("average") or order.get("price")

    if filled is None:
        filled_amt = float(fallback_amount)
    else:
        filled_amt = float(filled)

    if cost is not None:
        filled_cost = float(cost)
    elif average is not None and filled_amt:
        filled_cost = filled_amt * float(average)
    else:
        filled_cost = filled_amt * float(fallback_price)
    return filled_amt, filled_cost


def ensure_order_fill(
    exchange: ccxt.Exchange,
    symbol: str,
    order: dict,
    fallback_amount: float,
    fallback_price: float,
) -> tuple[float, float]:
    """Refresh the order once if fill fields are missing (incomplete response)."""
    needs_refresh = order.get("filled") is None or order.get("cost") is None
    order_id = order.get("id")
    if needs_refresh and order_id:
        try:
            order = exchange.fetch_order(order_id, symbol)
            LOGGER.info(
                "Refreshed order %s: filled=%s cost=%s",
                order_id,
                order.get("filled"),
                order.get("cost"),
            )
        except ccxt.BaseError as exc:
            LOGGER.warning("Could not refresh order %s: %s; using available fields", order_id, exc)
    return extract_fill(order, fallback_amount, fallback_price)


def print_status(state: dict, mark_price: float, signal: str, last_closed_ts: int) -> None:
    equity = state["virtual_usdt"] + state["virtual_btc"] * mark_price
    pnl_pct = ((equity / state["initial_usdt"]) - 1.0) * 100.0
    LOGGER.info(
        "ts=%s price=%.2f signal=%s | virtual=%.4f USDT + %.8f BTC | equity=$%.2f (%+.2f%%) | last_traded_ts=%s",
        last_closed_ts,
        mark_price,
        signal,
        state["virtual_usdt"],
        state["virtual_btc"],
        equity,
        pnl_pct,
        state.get("last_traded_ts"),
    )


def execute_cycle(
    exchange: ccxt.Exchange,
    *,
    symbol: str = DEFAULT_SYMBOL,
    timeframe: str = DEFAULT_TIMEFRAME,
    fast: int = DEFAULT_FAST,
    slow: int = DEFAULT_SLOW,
    allocation_pct: float = DEFAULT_ALLOCATION_PCT,
    dry_run: bool = False,
) -> dict:
    """One strategy cycle: fetch candles, signal, optionally place demo order."""
    state = load_ledger()
    closed = fetch_closed_candles(exchange, symbol, timeframe, slow)
    last_closed_ts = int(closed.iloc[-1]["ts"])
    mark_price = float(closed.iloc[-1]["close"])

    # Prefer live ticker for sizing mark if available; fall back to last close.
    try:
        ticker = exchange.fetch_ticker(symbol)
        if ticker.get("last"):
            mark_price = float(ticker["last"])
    except ccxt.BaseError as exc:
        LOGGER.warning("fetch_ticker failed (%s); using last closed close", exc)

    signal = compute_signal(closed, fast=fast, slow=slow)
    print_status(state, mark_price, signal, last_closed_ts)

    if state.get("last_traded_ts") == last_closed_ts:
        LOGGER.info("Already acted on closed candle %s; skipping (idempotent).", last_closed_ts)
        return state

    market = exchange.market(symbol)
    amt_min = min_amount(market)
    cost_min = min_notional(market)
    flat = state["virtual_btc"] < amt_min

    if signal == "BUY":
        if not flat:
            LOGGER.info("BUY signal ignored: already long (virtual_btc=%.8f).", state["virtual_btc"])
            return state

        spend_usdt = state["virtual_usdt"] * allocation_pct
        if spend_usdt < cost_min:
            LOGGER.warning(
                "BUY skipped: allocation %.4f USDT below min notional %.4f.",
                spend_usdt,
                cost_min,
            )
            return state

        raw_qty = spend_usdt / mark_price
        btc_qty = float(exchange.amount_to_precision(symbol, raw_qty))
        if btc_qty < amt_min:
            LOGGER.warning(
                "BUY skipped: qty %s below min amount %s.",
                btc_qty,
                amt_min,
            )
            return state

        estimated_cost = btc_qty * mark_price
        if estimated_cost < cost_min:
            LOGGER.warning(
                "BUY skipped: estimated cost %.4f below min notional %.4f.",
                estimated_cost,
                cost_min,
            )
            return state

        if dry_run:
            LOGGER.info("DRY-RUN BUY %s BTC (~%.2f USDT) — no order sent.", btc_qty, estimated_cost)
            return state

        try:
            order = exchange.create_market_buy_order(symbol, btc_qty)
            filled_btc, spent_usdt = ensure_order_fill(
                exchange, symbol, order, btc_qty, mark_price
            )
            if filled_btc <= 0:
                LOGGER.error("BUY returned zero fill; leaving ledger unchanged.")
                return state

            # Cap spend to available virtual USDT so ledger cannot go deeply negative
            # if demo fill cost exceeds our simulated budget (exchange has its own balance).
            spent_usdt = min(spent_usdt, state["virtual_usdt"])
            state["virtual_usdt"] = round(state["virtual_usdt"] - spent_usdt, 6)
            state["virtual_btc"] = round(state["virtual_btc"] + filled_btc, 8)
            state["last_traded_ts"] = last_closed_ts
            save_ledger(state)
            LOGGER.info("DEMO BUY filled: +%.8f BTC for -%.4f USDT", filled_btc, spent_usdt)
        except ccxt.InsufficientFunds as exc:
            LOGGER.error("BUY failed: insufficient demo funds on OKX: %s", exc)
        except ccxt.InvalidOrder as exc:
            LOGGER.error("BUY failed: invalid order (min size/notional?): %s", exc)
        except ccxt.BaseError as exc:
            LOGGER.error("BUY failed: %s", exc)
        return state

    if signal == "SELL":
        if flat:
            LOGGER.info("SELL signal ignored: flat.")
            return state

        btc_qty = float(exchange.amount_to_precision(symbol, state["virtual_btc"]))
        if btc_qty < amt_min:
            LOGGER.warning("SELL skipped: position %.8f below min amount %s.", btc_qty, amt_min)
            return state

        if dry_run:
            LOGGER.info("DRY-RUN SELL %.8f BTC — no order sent.", btc_qty)
            return state

        try:
            order = exchange.create_market_sell_order(symbol, btc_qty)
            sold_btc, received_usdt = ensure_order_fill(
                exchange, symbol, order, btc_qty, mark_price
            )
            if sold_btc <= 0:
                LOGGER.error("SELL returned zero fill; leaving ledger unchanged.")
                return state

            # Incomplete fills: only reduce by what actually sold.
            remaining = max(0.0, state["virtual_btc"] - sold_btc)
            state["virtual_btc"] = round(remaining if remaining >= amt_min else 0.0, 8)
            state["virtual_usdt"] = round(state["virtual_usdt"] + received_usdt, 6)
            state["last_traded_ts"] = last_closed_ts
            save_ledger(state)
            LOGGER.info("DEMO SELL filled: -%.8f BTC for +%.4f USDT", sold_btc, received_usdt)
            if remaining >= amt_min:
                LOGGER.warning(
                    "Partial sell: %.8f BTC still on virtual ledger (incomplete fill).",
                    remaining,
                )
        except ccxt.InsufficientFunds as exc:
            LOGGER.error("SELL failed: insufficient demo BTC on OKX: %s", exc)
        except ccxt.InvalidOrder as exc:
            LOGGER.error("SELL failed: invalid order: %s", exc)
        except ccxt.BaseError as exc:
            LOGGER.error("SELL failed: %s", exc)
        return state

    LOGGER.info("HOLD — no trade.")
    return state


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OKX BTC/USDT spot demo bot (SMA 10/30 on 15m, $200 virtual ledger)."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single cycle and exit (default unless --loop).",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Poll forever, sleeping between cycles.",
    )
    parser.add_argument(
        "--sleep",
        type=int,
        default=DEFAULT_SLEEP_SEC,
        help=f"Seconds between loop cycles (default {DEFAULT_SLEEP_SEC}).",
    )
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--timeframe", default=DEFAULT_TIMEFRAME)
    parser.add_argument("--fast", type=int, default=DEFAULT_FAST)
    parser.add_argument("--slow", type=int, default=DEFAULT_SLOW)
    parser.add_argument(
        "--allocation-pct",
        type=float,
        default=DEFAULT_ALLOCATION_PCT,
        help="Fraction of virtual USDT to deploy per BUY (default 0.50).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute signal and size orders but do not place them.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Debug logging.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if not 0 < args.allocation_pct <= 1:
        LOGGER.error("--allocation-pct must be in (0, 1].")
        return 2
    if args.fast < 1 or args.slow <= args.fast:
        LOGGER.error("--slow must be greater than --fast, and both >= 1.")
        return 2

    try:
        exchange = create_okx_demo_exchange()
        LOGGER.info(
            "OKX demo mode ON (x-simulated-trading=%s).",
            exchange.headers.get("x-simulated-trading"),
        )
        exchange.load_markets()
        if args.symbol not in exchange.markets:
            LOGGER.error("Symbol %s not found on OKX spot markets.", args.symbol)
            return 1
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — top-level startup errors
        LOGGER.error("Failed to initialize OKX client: %s", exc)
        return 1

    cycle_kwargs: dict[str, Any] = {
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "fast": args.fast,
        "slow": args.slow,
        "allocation_pct": args.allocation_pct,
        "dry_run": args.dry_run,
    }

    try:
        if args.loop:
            LOGGER.info("Entering loop (sleep=%ss). Ctrl+C to stop.", args.sleep)
            while True:
                try:
                    execute_cycle(exchange, **cycle_kwargs)
                except ccxt.NetworkError as exc:
                    LOGGER.warning("Network error this cycle: %s", exc)
                except ccxt.ExchangeError as exc:
                    LOGGER.error("Exchange error this cycle: %s", exc)
                time.sleep(max(1, args.sleep))
        else:
            execute_cycle(exchange, **cycle_kwargs)
    except KeyboardInterrupt:
        LOGGER.info("Stopped by user.")
        return 0
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("Fatal error: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
