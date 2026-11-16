# OKX BTC/USDT demo paper bot

Paper trading on the **OKX demo** (sandbox) account. The process refuses to run without `x-simulated-trading: 1`. There is no live-trading flag. `OKX_LIVE` in the environment aborts startup.

Three 4h paper books, each with its own ledger:

| Book | Rule | Ledger |
| --- | --- | --- |
| `spec_v1` (default) | EMA 10 / SMA 230 cross, 15% vol target, cap 100% | `ledger_spec_v1.json` |
| `ema_50_200` | EMA 50 / EMA 200 cross, 100% of cash | `ledger_ema_50_200.json` |
| `buy_and_hold` | Buy 100% once and hold | `ledger_buy_and_hold.json` |

`sma_10_30` is the old 15m SMA 10/30 book at 50% of cash. It is not the default.

Signals use closed bars. A cross on bar *t* is sent once, just after that bar closes, which is the practical stand-in for the next open. The loop does not poll every 60 seconds.

## Setup

Create a **demo** API key (Trade permission). Do not use a live key.

```bash
cd okx-demo-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill OKX_API_KEY, OKX_API_SECRET, OKX_API_PASSPHRASE
```

`.env` is gitignored. Never commit it.

## Run

One cycle of SPEC v1 (creates a fresh $200 ledger the first time). A closed bar older than 30 seconds is skipped; `--allow-stale` sends anyway:

```bash
python bot.py --once
python bot.py --once --dry-run          # signal and size only; no order
python bot.py --once --allow-stale      # act even if the close is no longer fresh
python bot.py --loop                    # sleep until each 4h close + 2s
```

All three 4h books in one process:

```bash
python bot.py --all-books --once
python bot.py --all-books --loop
```

Legacy 15m book, on its own ledger:

```bash
python bot.py --strategy sma_10_30 --loop
```

`--initial-usdt` applies when a ledger is created or reset. It does not rescale an existing book.

## Reset

Rotate the current ledger and fill log aside and start again at $200:

```bash
python bot.py --reset-ledger                      # spec_v1 only
python bot.py --all-books --reset-ledger          # the three 4h books
python bot.py --reset-ledger --once               # reset, then run one cycle
```

Backups are named `ledger_<book>.backup.<epoch>.json`. An unreadable ledger aborts the process. Delete or reset it; the bot will not trade on a partial file.

## Halt

If marked equity (virtual USDT + virtual BTC × mark) is **below 80%** of that book's `initial_usdt`, new buys are skipped. Sells still run. The same entry block is set when a fill's fee cannot be converted to USDT, or when a client order is still missing after 30 minutes. The position from a real fill stays on the ledger so the book cannot enter twice.

## Order size and `tgtCcy`

OKX spot market buys are ambiguous: without `tgtCcy`, `sz` is quote USDT for a buy and base BTC for a sell. This bot always sends `tgtCcy=base_ccy` plus a client order id that is saved **before** the request. Confirm that on the demo account before trusting size:

```bash
python bot.py --check-order-size                         # print the order, send nothing
python bot.py --check-order-size --send-demo-check       # minimum demo buy, then sell
```

The send path does not write a strategy ledger. Read the printed filled base versus the requested BTC quantity. A match means the amount was treated as BTC.

## Replay

Public 4h candles, no keys, no orders. Next-bar open, 0.10% fee, 0.05% slippage, SPEC vol weight, three books side by side. Warmup for SMA 230 is fetched on top of `--days`.

```bash
python replay.py
python replay.py --days 180
python replay.py --csv candles.csv --json-out /tmp/replay.json
```

## Tests

```bash
python -m pytest
python -m unittest smoke_test.py
```

## Files

| File | Role |
| --- | --- |
| `bot.py` | CLI, sandbox client, order-size check |
| `execution.py` | Close-aligned loop, one order per bar, reconciliation |
| `strategy.py` | SPEC v1, EMA 50/200, buy-and-hold, legacy SMA |
| `ledger.py` | Atomic JSON ledger, fill rules, JSONL log |
| `replay.py` | Offline next-open replay |
| `fills_<book>.jsonl` | Append-only fill log (gitignored) |

More detail is in `docs/TECHNICAL.md`. The research that chose these books is in `docs/RESEARCH_SUMMARY.md`.
