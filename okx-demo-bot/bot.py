#!/usr/bin/env python3
"""OKX BTC/USDT demo paper bot.

Sandbox only. ``set_sandbox_mode(True)`` is mandatory and a missing
``x-simulated-trading: 1`` header aborts before any order. There is no live
path. Three paper books (SPEC v1, EMA 50/200, buy-and-hold) keep separate
ledgers. The legacy 15m SMA 10/30 book is available and is not the default.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import ccxt
from dotenv import load_dotenv

from execution import (
    SYMBOL,
    assert_sandbox,
    execute_cycle,
    market_limits,
    new_client_id,
    run_loop,
    spot_market_order_params,
)
from ledger import BOT_DIR, INITIAL_USDT, LedgerError, ledger_path, reset_ledger
from strategy import PAPER_BOOKS, STRATEGIES

LOGGER = logging.getLogger("okx-demo-bot")


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(
            f"Missing {name}. Export demo OKX_API_KEY, OKX_API_SECRET, and "
            "OKX_API_PASSPHRASE, or put them in okx-demo-bot/.env (never commit it)."
        )
    return value


def create_okx_demo_exchange() -> ccxt.okx:
    """Build a ccxt client locked to OKX demo trading.

    ``OKX_LIVE`` is refused so a copied shell export cannot point this process
    at real funds. The sandbox header is checked again before every cycle.
    """
    if os.environ.get("OKX_LIVE", "").strip().lower() in {"1", "true", "yes"}:
        raise SystemExit("OKX_LIVE is set. This bot refuses live trading.")
    exchange = ccxt.okx(
        {
            "apiKey": require_env("OKX_API_KEY"),
            "secret": require_env("OKX_API_SECRET"),
            "password": require_env("OKX_API_PASSPHRASE"),
            "enableRateLimit": True,
            "options": {
                "defaultType": "spot",
                # See spot_market_order_params: we also pass tgtCcy on each order.
                "tgtCcy": "base_ccy",
            },
        }
    )
    exchange.set_sandbox_mode(True)
    assert_sandbox(exchange)
    return exchange


def _selected_specs(args: argparse.Namespace) -> list:
    if args.all_books and args.strategy:
        raise SystemExit("Pass either --all-books or --strategy, not both.")
    if args.all_books:
        return [STRATEGIES[name] for name in PAPER_BOOKS]
    name = args.strategy or "spec_v1"
    return [STRATEGIES[name]]


def check_order_size(exchange: ccxt.okx, symbol: str, send: bool) -> int:
    """Print the market-buy size we would send, and optionally do a min demo round trip.

    This does not touch a strategy ledger. It exists because OKX spot market
    buys are ambiguous between base BTC and quote USDT (``tgtCcy``).
    """
    assert_sandbox(exchange)
    exchange.load_markets()
    if symbol not in exchange.markets:
        LOGGER.error("Symbol %s is not on this OKX market list.", symbol)
        return 1
    min_amount, min_cost = market_limits(exchange, symbol)
    ticker = exchange.fetch_ticker(symbol)
    mark = float(ticker.get("last") or ticker.get("close") or 0.0)
    if mark <= 0:
        LOGGER.error("No ticker price; cannot size the check order.")
        return 1
    spend = max(min_cost * 1.05, min_cost + 1.0)
    qty = float(exchange.amount_to_precision(symbol, max(spend / mark, min_amount)))
    if qty * mark < min_cost:
        qty = float(exchange.amount_to_precision(symbol, (min_cost * 1.05) / mark))
    coid = new_client_id()
    params = spot_market_order_params(coid)
    print("OKX spot market-buy size check (demo sandbox only)")
    print(f"  ccxt {ccxt.__version__}  options.tgtCcy={exchange.options.get('tgtCcy')!r}")
    print(f"  symbol {symbol}  mark {mark:.2f}  min amount {min_amount}  min cost {min_cost}")
    print(f"  requested base qty {qty:.8f}  estimated quote {qty * mark:.4f} USDT")
    print(f"  create_order params {params}")
    print(
        "  Reading: amount is BTC because tgtCcy=base_ccy. "
        "If the venue treated it as USDT, a fill would not match this base qty."
    )
    if not send:
        print("  Dry run. Nothing sent. Add --send-demo-check to buy and sell this minimum on demo.")
        return 0
    LOGGER.warning("Sending a minimum demo buy then sell. Strategy ledgers are not updated.")
    order = exchange.create_order(symbol, "market", "buy", qty, None, params)
    filled = float(order.get("filled") or 0.0)
    cost = float(order.get("cost") or 0.0)
    if order.get("filled") is None or order.get("cost") is None:
        refreshed = exchange.fetch_order(order.get("id") or coid, symbol, {"clientOrderId": coid})
        filled = float(refreshed.get("filled") or 0.0)
        cost = float(refreshed.get("cost") or 0.0)
        order = refreshed
    implied = (cost / filled) if filled else None
    print(f"  buy id={order.get('id')} filled_base={filled:.8f} cost_quote={cost:.4f} implied={implied}")
    if filled <= 0:
        print("  INCONCLUSIVE: zero fill. No sell sent.")
        return 1
    rel = abs(filled - qty) / qty
    if rel < 0.25 and implied and implied > 1000:
        print("  OK: filled base is close to the requested BTC qty. tgtCcy=base_ccy took effect.")
    elif filled > qty * 10:
        print(
            "  WARNING: filled base is far above the requested BTC qty. "
            "The venue may have read the amount as quote USDT."
        )
    else:
        print("  INCONCLUSIVE: compare filled base, quote cost, and implied price before trusting size.")
    sell_qty = float(exchange.amount_to_precision(symbol, filled))
    sell = exchange.create_order(
        symbol, "market", "sell", sell_qty, None, spot_market_order_params(new_client_id())
    )
    print(
        f"  sell id={sell.get('id')} filled_base={sell.get('filled')} "
        f"proceeds={sell.get('cost')} (demo account round trip, ledger untouched)"
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OKX BTC/USDT demo paper bot (sandbox only, separate ledgers per book)."
    )
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit (default).")
    parser.add_argument("--loop", action="store_true", help="Wait for each candle close, then run once.")
    parser.add_argument(
        "--strategy",
        choices=sorted(STRATEGIES),
        default=None,
        help="Paper book (default spec_v1). sma_10_30 is the legacy 15m book.",
    )
    parser.add_argument(
        "--all-books",
        action="store_true",
        help="Run spec_v1, ema_50_200, and buy_and_hold as three ledgers.",
    )
    parser.add_argument(
        "--reset-ledger",
        action="store_true",
        help="Rotate the selected ledger(s) aside and start from a fresh $200 book.",
    )
    parser.add_argument("--initial-usdt", type=float, default=INITIAL_USDT)
    parser.add_argument("--symbol", default=SYMBOL)
    parser.add_argument("--dry-run", action="store_true", help="Size and log, but do not send orders.")
    parser.add_argument(
        "--check-order-size",
        action="store_true",
        help="Print the demo market-buy size and tgtCcy=base_ccy. Does not send unless --send-demo-check.",
    )
    parser.add_argument(
        "--send-demo-check",
        action="store_true",
        help="With --check-order-size, place a minimum demo buy and sell. Does not touch strategy ledgers.",
    )
    parser.add_argument("--buffer-sec", type=float, default=2.0, help="Seconds after the candle close.")
    parser.add_argument("--act-window-sec", type=float, default=30.0, help="Skip a closed bar older than this many seconds.")
    parser.add_argument(
        "--allow-stale",
        action="store_true",
        help="Send on a closed bar older than --act-window-sec. Default is to skip it.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    load_dotenv(BOT_DIR / ".env")
    LOGGER.warning("PAPER ONLY. OKX demo sandbox is required. Live trading is disabled.")
    try:
        specs = _selected_specs(args)
    except SystemExit:
        raise
    if args.once and args.loop:
        LOGGER.error("Pass either --once or --loop.")
        return 2
    if args.initial_usdt <= 0:
        LOGGER.error("--initial-usdt must be positive.")
        return 2
    if args.reset_ledger:
        for spec in specs:
            path = ledger_path(spec.id)
            state = reset_ledger(path, initial_usdt=args.initial_usdt, strategy_id=spec.id)
            LOGGER.info(
                "Reset %s to %.2f USDT (%s).",
                spec.id,
                state["virtual_usdt"],
                path.name,
            )
        if not (args.once or args.loop or args.check_order_size or args.send_demo_check):
            return 0
    if args.check_order_size or args.send_demo_check:
        try:
            exchange = create_okx_demo_exchange()
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("Failed to initialize OKX demo client: %s", exc)
            return 1
        return check_order_size(exchange, args.symbol, send=args.send_demo_check)
    try:
        exchange = create_okx_demo_exchange()
        exchange.load_markets()
        if args.symbol not in exchange.markets:
            LOGGER.error("Symbol %s is not on this OKX market list.", args.symbol)
            return 1
        LOGGER.info(
            "Sandbox on (x-simulated-trading=%s). Books: %s.",
            exchange.headers.get("x-simulated-trading"),
            ", ".join(spec.id for spec in specs),
        )
        if args.loop:
            return run_loop(
                exchange,
                specs,
                symbol=args.symbol,
                dry_run=args.dry_run,
                buffer_sec=args.buffer_sec,
                act_window_sec=args.act_window_sec,
                initial_usdt=args.initial_usdt,
            )
        for spec in specs:
            execute_cycle(
                exchange,
                spec,
                symbol=args.symbol,
                dry_run=args.dry_run,
                initial_usdt=args.initial_usdt,
                act_window_sec=args.act_window_sec,
                allow_stale=args.allow_stale,
            )
    except LedgerError as exc:
        LOGGER.error("%s", exc)
        return 2
    except KeyboardInterrupt:
        LOGGER.info("Stopped.")
        return 0
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("Fatal error: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
