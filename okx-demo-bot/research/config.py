"""Pinned parameters for the V1–V4 90-day benchmark."""

from __future__ import annotations

from pathlib import Path

RESEARCH_DIR = Path(__file__).resolve().parent
BOT_DIR = RESEARCH_DIR.parent
DATA_DIR = BOT_DIR / "data"
REPORTS_DIR = BOT_DIR / "reports"

SYMBOL_SPOT = "BTC/USDT"
SYMBOL_SWAP = "BTC/USDT:USDT"
TIMEFRAME_15M = "15m"
TIMEFRAME_1D = "1d"

LOOKBACK_DAYS = 90
# Extra closed days so SMA(30) is warm before the 90d trading window starts.
DAILY_WARMUP_DAYS = 45
# Extra 15m bars for Z(20)/ADX(14)/SMA(30) warmup inside the window edge.
INTRADAY_WARMUP_BARS = 80

INITIAL_USDT = 200.0
ALLOCATION_PCT = 0.50

SMA_FAST = 10
SMA_SLOW = 30
ADX_PERIOD = 14
ADX_TREND = 25.0
ADX_MR = 20.0
Z_WINDOW = 20
Z_ENTRY = -2.0
Z_EXIT = 0.0
STOP_PCT = 0.02

SPOT_FEE_RATE = 0.0010  # 0.10% per side
SWAP_FEE_RATE = 0.0005  # 0.05% per side

# OKX BTC-USDT-SWAP: 1 contract = 0.01 BTC; size rounds to 0.01 contracts.
CT_VAL_BTC = 0.01
CONTRACT_STEP = 0.01

# Funding proxy when historical series is unavailable (per 8h settlement).
# Flagged in the report when used.
FUNDING_PROXY_8H = 0.0001  # +0.01% per 8h (longs pay shorts when positive)
FUNDING_INTERVAL_MS = 8 * 60 * 60 * 1000

CACHE_15M = "btc_usdt_15m_90d.csv"
CACHE_1D = "btc_usdt_1d.csv"
CACHE_FUNDING = "btc_usdt_swap_funding.csv"
CACHE_META = "cache_meta.json"
