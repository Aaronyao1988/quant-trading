# OKX demo paper bot — technical notes

Paper / sandbox only. Branch work that replaced the 15m SMA loop with separate ledgers, a close-aligned execution cycle, and the three 4h books from the 2026-11-16 research. Live trading is not implemented: `create_okx_demo_exchange` calls `set_sandbox_mode(True)`, refuses `OKX_LIVE`, and `assert_sandbox` rejects any client whose `x-simulated-trading` header is not `1`.

## 1. Process

One Python process, one ccxt OKX demo client.

```
bot.py            CLI, credentials, sandbox client, --check-order-size
execution.py      sleep until candle close, one order per closed bar
strategy.py       indicators and signals (closed bars only)
ledger.py         virtual cash / BTC, atomic save, JSONL fills
replay.py         same rules offline, no orders
```

Each book has `ledger_<id>.json` and `fills_<id>.jsonl` next to the code. The legacy file `virtual_ledger_200.json` is no longer read.

Default book is `spec_v1`. `--all-books` runs `spec_v1`, `ema_50_200`, and `buy_and_hold`. Those three share the 4h clock. `sma_10_30` is 15m and stays on its own loop.

## 2. Strategies

Signals are computed on closed candles. The in-progress bar is dropped (`ts + timeframe > now`).

**Cross.** Golden cross: previous fast ≤ previous slow and fast > slow, all four values finite. Death cross is the mirror. Same definition the old `compute_signal` used.

**EMA.** `ewm(span, adjust=False)`, then the first `span - 1` outputs set to NaN. EMA(10) is first valid on the 10th close.

**SMA.** Rolling mean, undefined until `window` closes exist. SMA(230) needs 231 closed bars before a cross can fire (current bar plus the previous bar).

**ATR.** Wilder ATR(14). True range uses the previous close. The seed is the SMA of the first 14 true ranges after bar 0, so the first finite value is at index 14. The research grid used pandas `ewm(alpha=1/14)` instead. The two match long before the first SMA(230) cross; they are not bit-identical on the first few dozen bars.

**SPEC v1 weight**, on the signal bar only:

```
sigma = (ATR(14) / close) * sqrt(bars_per_year)
w     = min(1, 0.15 / sigma)
```

For 4h, `bars_per_year` is `365.25 * 6`. Missing or non-positive sigma skips that entry. Spend is `virtual_usdt * w` at the fill. No adds while in the trade. No leverage. A cross while already long is ignored; a death cross while flat is ignored.

**EMA 50/200** uses the same cross and spends 100% of virtual USDT.

**Buy-and-hold** buys 100% once and never emits a sell. The halt rule can block that first buy. It does not force an exit.

**Legacy SMA 10/30** spends 50% of virtual USDT on 15m bars.

`entry_weight` returns `None` when vol is undefined. The cycle records `last_attempt_ts` and does not retry that bar.

## 3. Ledger

Required fields: `initial_usdt`, `virtual_usdt`, `virtual_btc`, `last_traded_ts`. Optional: `last_attempt_ts`, `pending_order`, `unbooked_order`, `strategy`.

`load_ledger` raises `LedgerError` on invalid JSON, a non-object, missing fields, or a negative balance. The CLI turns that into exit code 2. `--reset-ledger` moves the JSON and the JSONL aside (`*.backup.<epoch>.*`) and writes a new $200 book (or `--initial-usdt`).

Saves go to `name.tmp.<pid>` in the same directory and then `os.replace`. A failed replace deletes the temp file and leaves the previous ledger.

### Buys

ccxt `filled` is treated as gross base. ccxt `cost` is quote notional and does **not** include the fee. The fee is read from `order["fee"]` (the `fees` list is used only when `fee` is absent, so the same fee is not applied twice).

- Base fee (BTC): credited BTC = filled − fee.
- Quote fee (USDT): USDT outlay = cost + fee.
- A positive fee with no currency is rejected and not booked.
- If the outlay is greater than `virtual_usdt`, credited BTC is multiplied by `virtual_usdt / outlay` and cash goes to zero. The old code capped cash and still credited the full BTC.
- A zero fill, a fee that consumes the whole base fill, or a non-finite number leaves balances unchanged.

### Sells

Proceeds = quote notional − quote fee. If the exchange reports more base than the ledger holds, proceeds are multiplied by `held / filled` and the ledger BTC goes to zero. A smaller fill leaves the residual BTC in the ledger. Dust is not deleted.

`commit_fill` replaces the JSON first, then appends one JSON line to the fill log (`O_APPEND`, one write).

## 4. Execution

`--loop` does not sleep a fixed 60s.

1. On startup, any `pending_order` is reconciled immediately, even mid-bar.
2. `plan_wake` sleeps until the candle boundary plus `--buffer-sec` (default 2). A bar whose close is already older than `--act-window-sec` (default 30) is skipped, including `--once`. `--allow-stale` is the explicit override. Sending later than that window is not the next open.
3. Candles are paged (`limit=100`) until `min_closed + 2` rows are in hand. The forming bar is dropped. If the just-closed open is missing, the fetch is retried a few times with a short sleep.
4. One action per closed-bar timestamp. `last_attempt_ts` is set when an order is about to be sent, or when the order is rejected, or when size is below the minimum. A failure does not send again on that bar.
5. The client order id (32 hex chars, OKX `clOrdId`) is written into `pending_order` and the ledger is replaced **before** `create_order`.
6. Every order sends `tgtCcy=base_ccy`. See §6.
7. A returned payload is booked only when status is `closed` or `filled` and `filled > 0`, or when a cancelled/rejected/expired order reports `filled > 0` (that partial size only). `filled is None` is never replaced with the requested quantity. An unclear payload is refreshed with `fetch_order` before any booking.
8. Network errors and `OrderNotFound` leave `pending_order` in place. Later cycles and the next startup call `fetch_order` on that client id before they will send anything else. The search lasts 30 minutes from `since_ms`. After that the book sets `entries_halted` and stores `unresolved_order` so a late fill cannot be doubled by a new entry.
9. A fee in a third currency (for example OKB) is converted with the `CCY/USDT` ticker and subtracted. If that ticker is missing, the reported base size is still recorded and `entries_halted` is set. The fee is not booked as zero, and a later bar cannot open a second position.
10. Other exceptions in the loop are logged. Backoff is `min(300, 5 * 2^(n-1))` seconds. `LedgerError` and `KeyboardInterrupt` still stop the process.
11. Halt: if `virtual_usdt + virtual_btc * mark < 0.80 * initial_usdt`, or `entries_halted` is set, buys are skipped. Sells are not.

Mark price is the ticker last, or the last closed close if the ticker call fails. The signal itself does not use the ticker.

## 5. Replay

`replay.py` uses the same `prepare_frame` / vol weight as the live signal. Fills are at the next bar's open. Buy quantity is `(spend / (open * (1+slip))) * (1-fee)`. Sell proceeds are `qty * open * (1-slip) * (1-fee)`. Defaults are 0.10% and 0.05%. Buy-and-hold buys at the first open and is marked to the last close (no exit fee), matching the research benchmark. Data is public OKX OHLCV with no API key and no `create_order`.

That cost model is the research assumption. The live ledger uses the fee the demo fill actually reports, which may not be 10 bps.

## 6. `tgtCcy` (unconfirmed on this account)

OKX spot market **buys** default `sz` to quote currency (`tgtCcy=quote_ccy`). Market sells default to base. ccxt 4.5's `create_order_request` defaults the `tgtCcy` option to `base_ccy` and forwards it, but a client that omits the field follows the venue. This bot sets the option and also passes `tgtCcy=base_ccy` on every order (`execution.spot_market_order_params`).

`--check-order-size` prints the base quantity, the estimated quote, and the params. `--send-demo-check` places a minimum demo buy and an offsetting sell and compares filled base to the requested BTC quantity. It does not update a strategy ledger. That round trip has not been run in this change; the interpretation is still something to confirm on the demo account.

## 7. Tests

`python -m pytest` covers the ledger and replay cases plus execution regressions: a cancelled order with `filled` null does not spend the book, a partial cancel books only the reported size, `OrderNotFound` keeps the pending id until a later fill or the 30 minute halt, an OKB fee is converted or the book is halted with the position recorded, and `--once` skips a stale bar unless `--allow-stale` is set.

`python -m unittest smoke_test.py` still checks SMA warmup, a 3/5 cross, and `extract_fill` fallbacks.

## 8. Limits

- If `fetch_order` still cannot see a client id after 30 minutes, new entries halt and the id stays on `unresolved_order`. A fill that shows up on a later startup is booked before any new order. Check the demo UI when `entries_halted` is set.
- The assumption “`filled` is gross base and `fee` is not already removed” is what the tests lock in. If a future ccxt build reports net filled, BTC fees would be subtracted twice. The fill log stores both numbers so a bad print is visible.
- Research numbers in `RESEARCH_SUMMARY.md` used Binance candles. This bot trades OKX demo prints.
- SPEC v1 is a frozen paper rule, not evidence of a durable edge. Run it next to the other two books.
- No short, no perp, no ADX filter, no kill of an open buy-and-hold position other than a later manual sell. The halt does not flatten; it only blocks entries.
