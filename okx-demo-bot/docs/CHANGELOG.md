# Changelog

## 2026-11-16

Paper-only rebuild of `okx-demo-bot`. Sandbox mode stays mandatory. No live path.

- Ledger: scale BTC when a buy costs more than virtual cash; subtract the ccxt fee (`fee`, otherwise `fees`); cap sell proceeds at BTC the ledger holds; keep residual dust; atomic `os.replace`; append-only `fills_<book>.jsonl`; refuse an unparseable file; `--reset-ledger` starts a fresh $200 book.
- Execution: one order per closed bar; sleep until the candle close plus a short buffer; page candles (SPEC needs 231 closed 4h bars); store the client order id before `create_order`; reconcile with `fetch_order` on startup and after a network error; do not retry a failed bar; backoff on other exceptions so the loop stays up.
- Books: `spec_v1` (4h EMA 10 / SMA 230, 15% vol target, cap 1), `ema_50_200` at 100%, and `buy_and_hold`, each with its own ledger. `--all-books` runs the three. `sma_10_30` remains available and is not the default.
- Halt: no new buys when marked equity is below 80% of that book's starting equity. Sells still run.
- Replay: next-open fills, 0.10% fee, 0.05% slippage, vol weight, three books side by side. No orders.
- Orders always send `tgtCcy=base_ccy`. `--check-order-size` prints the demo market-buy size; `--send-demo-check` does a minimum demo round trip without touching a strategy ledger. That round trip was not executed in this change.
- Tests: `python -m pytest` (ledger, signals, replay, execution) and the existing unittest smoke checks.
