# OKX BTC/USDT Demo Bot

Paper (demo) spot bot for **BTC/USDT** on OKX using `ccxt`.

- Strategy: SMA **10 / 30** crossover on **closed 15m** candles
- Capital model: **virtual $200 USDT** sub-ledger (JSON); ledger is source of truth for size / PnL
- Fills: real **OKX Demo Trading** market orders (`set_sandbox_mode(True)` → `x-simulated-trading: 1`)
- Risk: ~**50%** of virtual USDT per entry (configurable); BUY only when flat; SELL exits full virtual BTC

## Setup

1. On [OKX](https://www.okx.com/), open **Demo Trading** and create a **demo** API key (not live).
2. Install deps:

```bash
cd okx-demo-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. Credentials (never commit secrets). Either export env vars:

```bash
export OKX_API_KEY="your-demo-key"
export OKX_API_SECRET="your-demo-secret"
export OKX_API_PASSPHRASE="your-demo-passphrase"
```

Or copy `.env.example` → `.env` and fill in the three values. `bot.py` calls `load_dotenv()` on the bot directory’s gitignored `.env` before reading `OKX_*` (handy for Mac/agent smoke without exporting vars in the shell).

## Run

One cycle (default):

```bash
python bot.py --once
```

Signal / sizing only (still needs keys for market data + demo header check; no orders):

```bash
python bot.py --once --dry-run
```

Loop every 60s:

```bash
python bot.py --loop --sleep 60
```

Useful flags: `--allocation-pct 0.5`, `--fast 10`, `--slow 30`, `-v`.

## SMA snapshot + historical replay

Offline lookback defaults to **14 days** (≈ **1,344** closed 15m bars; OKX OHLCV is paginated). Public market data works without API keys; demo keys are only required for `--demo-orders`.

```bash
python replay.py
python replay.py --days 7          # override lookback
python replay.py --hours 48        # or hours
python replay.py --md-out /tmp/replay-14d.md
python replay.py --json-out /tmp/replay.json
```

Optional controlled demo BUY then SELL (updates `virtual_ledger_200.json`; backs up first). **Do not** enable in CI/cloud without demo keys — historical crosses are never sent as live orders.

```bash
python replay.py --demo-orders
```

`replay.py` reuses `compute_signal` / demo client helpers from `bot.py`. Historical fills are virtual at bar close. After the replay it classifies three market regimes (sustained uptrend / sustained downtrend / narrow-range oscillation) and lists which golden/death crosses fell in each.

## Ledger

On first run the bot creates `virtual_ledger_200.json` next to `bot.py`:

```json
{
  "initial_usdt": 200.0,
  "virtual_usdt": 200.0,
  "virtual_btc": 0.0,
  "last_traded_ts": null
}
```

`last_traded_ts` is the closed-candle timestamp already traded so the bot does **at most one trade per closed 15m bar**. Delete the file to reset the $200 sim. Demo exchange balances are separate; the bot sizes from the ledger, not from OKX free balance.

## V1–V4 90-day research benchmark (offline)

Fee-aware offline matrix under `research/` (does **not** touch the live demo loop or `virtual_ledger_200.json`):

```bash
python -m research.run_benchmark           # fetch/cache public OHLCV + run V1–V4
python -m research.run_benchmark --refresh # force re-fetch
python -m pytest tests/ -q
```

Report: `reports/v1-v4-90d-benchmark.md`. OHLCV caches live in gitignored `data/`.

## Smoke check (no API keys)

```bash
python -c "from bot import compute_signal, load_ledger; import pandas as pd; print('import ok')"
python -m py_compile bot.py
```

Live smoke against OKX demo requires the three env vars above.
