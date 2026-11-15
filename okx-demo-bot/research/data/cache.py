"""Disk cache for the frozen 90d benchmark dataset."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from research.config import (
    CACHE_15M,
    CACHE_1D,
    CACHE_FUNDING,
    CACHE_META,
    DAILY_WARMUP_DAYS,
    DATA_DIR,
    LOOKBACK_DAYS,
    SYMBOL_SPOT,
    SYMBOL_SWAP,
    TIMEFRAME_15M,
    TIMEFRAME_1D,
)
from research.data.fetch import create_public_okx, fetch_funding_history, fetch_ohlcv_paginated

LOGGER = logging.getLogger("research.cache")


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def load_cached_frames(
    data_dir: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    data_dir = data_dir or DATA_DIR
    meta_path = data_dir / CACHE_META
    if not meta_path.exists():
        raise FileNotFoundError(f"Missing cache meta at {meta_path}; run ensure_cached_dataset()")
    meta = json.loads(meta_path.read_text())
    bars_15m = _read_csv(data_dir / CACHE_15M)
    daily = _read_csv(data_dir / CACHE_1D)
    funding_path = data_dir / CACHE_FUNDING
    if funding_path.exists() and funding_path.stat().st_size > 0:
        funding = _read_csv(funding_path)
    else:
        funding = pd.DataFrame(columns=["ts", "funding_rate"])
    return bars_15m, daily, funding, meta


def ensure_cached_dataset(
    *,
    data_dir: Path | None = None,
    force_refresh: bool = False,
    end_ms: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Load frozen CSV cache or fetch from public OKX and persist it."""
    data_dir = data_dir or DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)
    meta_path = data_dir / CACHE_META
    have = (
        (data_dir / CACHE_15M).exists()
        and (data_dir / CACHE_1D).exists()
        and meta_path.exists()
    )
    if have and not force_refresh:
        LOGGER.info("Using cached dataset under %s", data_dir)
        return load_cached_frames(data_dir)

    end = end_ms or int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    end_dt = datetime.fromtimestamp(end / 1000.0, tz=timezone.utc)
    start_15m = end_dt - timedelta(days=LOOKBACK_DAYS + 2)
    start_1d = end_dt - timedelta(days=LOOKBACK_DAYS + DAILY_WARMUP_DAYS)
    since_15m = int(start_15m.timestamp() * 1000)
    since_1d = int(start_1d.timestamp() * 1000)

    LOGGER.info("Fetching public OKX OHLCV (15m + 1d) into %s …", data_dir)
    spot = create_public_okx(default_type="spot")
    bars_15m = fetch_ohlcv_paginated(
        spot, SYMBOL_SPOT, TIMEFRAME_15M, since_15m, until_ms=end
    )
    daily = fetch_ohlcv_paginated(
        spot, SYMBOL_SPOT, TIMEFRAME_1D, since_1d, until_ms=end
    )

    funding = pd.DataFrame(columns=["ts", "funding_rate"])
    funding_source = "proxy"
    try:
        swap = create_public_okx(default_type="swap")
        swap.load_markets()
        funding = fetch_funding_history(
            swap, SYMBOL_SWAP, since_15m, until_ms=end
        )
        if not funding.empty:
            funding_source = "historical"
            LOGGER.info("Fetched %s funding snapshots", len(funding))
        else:
            LOGGER.warning("Funding history empty; benchmark will use constant proxy")
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Funding fetch failed (%s); using constant proxy", exc)

    _write_csv(bars_15m, data_dir / CACHE_15M)
    _write_csv(daily, data_dir / CACHE_1D)
    _write_csv(funding, data_dir / CACHE_FUNDING)

    meta: dict[str, Any] = {
        "symbol_spot": SYMBOL_SPOT,
        "symbol_swap": SYMBOL_SWAP,
        "lookback_days": LOOKBACK_DAYS,
        "end_ms": end,
        "end_utc": end_dt.isoformat(),
        "bars_15m": len(bars_15m),
        "bars_1d": len(daily),
        "funding_rows": len(funding),
        "funding_source": funding_source,
        "fetched_at_utc": datetime.now(tz=timezone.utc).isoformat(),
    }
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    LOGGER.info(
        "Cached %s 15m bars, %s daily bars, funding=%s",
        len(bars_15m),
        len(daily),
        funding_source,
    )
    return bars_15m, daily, funding, meta
