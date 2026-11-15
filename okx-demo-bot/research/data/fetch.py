"""Public OKX OHLCV / funding pagination with retries."""

from __future__ import annotations

import logging
import time
from typing import Any

import ccxt
import pandas as pd

LOGGER = logging.getLogger("research.fetch")


def create_public_okx(*, default_type: str = "spot") -> ccxt.okx:
    exchange = ccxt.okx(
        {
            "enableRateLimit": True,
            "options": {"defaultType": default_type},
        }
    )
    return exchange


def _sleep(exchange: ccxt.Exchange) -> None:
    time.sleep(exchange.rateLimit / 1000.0 if exchange.rateLimit else 0.05)


def fetch_ohlcv_paginated(
    exchange: ccxt.Exchange,
    symbol: str,
    timeframe: str,
    since_ms: int,
    *,
    until_ms: int | None = None,
    max_retries: int = 5,
) -> pd.DataFrame:
    """Paginate closed OHLCV bars with retry/resume on transient errors."""
    tf_ms = int(exchange.parse_timeframe(timeframe) * 1000)
    end = until_ms or int(time.time() * 1000)
    all_rows: list[list[float]] = []
    cursor = since_ms
    while cursor < end:
        batch: list[Any] | None = None
        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                batch = exchange.fetch_ohlcv(
                    symbol, timeframe=timeframe, since=cursor, limit=100
                )
                last_err = None
                break
            except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as exc:
                last_err = exc
                wait = min(2**attempt, 16)
                LOGGER.warning(
                    "OHLCV fetch retry %s/%s after %s (sleep %ss)",
                    attempt + 1,
                    max_retries,
                    exc,
                    wait,
                )
                time.sleep(wait)
        if last_err is not None:
            raise RuntimeError(f"OHLCV fetch failed after retries: {last_err}") from last_err
        if not batch:
            break
        all_rows.extend(batch)
        last_ts = int(batch[-1][0])
        next_cursor = last_ts + tf_ms
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(batch) < 100:
            break
        _sleep(exchange)

    if not all_rows:
        raise RuntimeError(f"No OHLCV for {symbol} {timeframe}")

    df = pd.DataFrame(all_rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    now_ms = int(time.time() * 1000)
    closed = df[df["ts"] + tf_ms <= now_ms].copy().reset_index(drop=True)
    if until_ms is not None:
        closed = closed[closed["ts"] + tf_ms <= until_ms].reset_index(drop=True)
    return closed


def fetch_funding_history(
    exchange: ccxt.Exchange,
    symbol: str,
    since_ms: int,
    *,
    until_ms: int | None = None,
    max_retries: int = 5,
) -> pd.DataFrame:
    """Fetch historical funding rates if the exchange supports it.

    Returns empty DataFrame on unsupported/empty responses so callers can
    fall back to a documented constant proxy.
    """
    end = until_ms or int(time.time() * 1000)
    if not hasattr(exchange, "fetch_funding_rate_history"):
        return pd.DataFrame(columns=["ts", "funding_rate"])

    all_rows: list[dict[str, Any]] = []
    cursor = since_ms
    while cursor < end:
        batch: list[dict[str, Any]] | None = None
        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                batch = exchange.fetch_funding_rate_history(
                    symbol, since=cursor, limit=100
                )
                last_err = None
                break
            except ccxt.NotSupported:
                return pd.DataFrame(columns=["ts", "funding_rate"])
            except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as exc:
                last_err = exc
                time.sleep(min(2**attempt, 16))
            except ccxt.BaseError as exc:
                LOGGER.warning("Funding history unavailable: %s", exc)
                return pd.DataFrame(columns=["ts", "funding_rate"])
        if last_err is not None:
            LOGGER.warning("Funding fetch failed after retries: %s", last_err)
            break
        if not batch:
            break
        all_rows.extend(batch)
        last_ts = int(batch[-1].get("timestamp") or 0)
        if last_ts <= cursor:
            break
        cursor = last_ts + 1
        if len(batch) < 100:
            break
        _sleep(exchange)

    if not all_rows:
        return pd.DataFrame(columns=["ts", "funding_rate"])

    rows = []
    for item in all_rows:
        ts = item.get("timestamp")
        rate = item.get("fundingRate")
        if ts is None or rate is None:
            continue
        rows.append({"ts": int(ts), "funding_rate": float(rate)})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.drop_duplicates(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    df = df[(df["ts"] >= since_ms) & (df["ts"] <= end)].reset_index(drop=True)
    return df
