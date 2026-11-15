"""Lookahead-safe daily → 15m as-of joins (previous closed day only)."""

from __future__ import annotations

import pandas as pd


def _utc_day_start_ms(ts_ms: int) -> int:
    """Floor candle open timestamp to UTC midnight (ms)."""
    return int(ts_ms) - (int(ts_ms) % 86_400_000)


def daily_sma(daily: pd.DataFrame, window: int = 30) -> pd.DataFrame:
    """Compute SMA on closed daily bars. ``ts`` is the daily candle open ms."""
    out = daily.copy()
    out["sma"] = out["close"].astype(float).rolling(window).mean()
    # Close time of a 1d bar that opened at ts is ts + 1d.
    out["close_ts"] = out["ts"].astype("int64") + 86_400_000
    return out


def align_daily_sma_asof(
    bars_15m: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    window: int = 30,
    column: str = "daily_sma30",
) -> pd.DataFrame:
    """Attach prior-day-only daily SMA(window) onto each 15m bar.

    Rule: for a 15m bar with open ``t``, use the SMA computed from daily
    candles whose **close time ≤ start_of_current_UTC_day(t)**. Equivalently
    the last fully closed UTC day strictly before the unfinished day that
    contains ``t``. A bar at 12:00 on day D never sees day D's close.
    """
    if bars_15m.empty:
        out = bars_15m.copy()
        out[column] = pd.Series(dtype=float)
        return out

    daily_feat = daily_sma(daily, window=window)
    daily_feat = daily_feat.dropna(subset=["sma"]).copy()
    if daily_feat.empty:
        out = bars_15m.copy()
        out[column] = float("nan")
        return out

    # As-of keys: daily SMA becomes available at close_ts (= next midnight).
    right = daily_feat[["close_ts", "sma"]].rename(
        columns={"close_ts": "asof_ts", "sma": column}
    )
    left = bars_15m.copy()
    left["day_start_ms"] = left["ts"].map(_utc_day_start_ms)

    merged = pd.merge_asof(
        left.sort_values("day_start_ms"),
        right.sort_values("asof_ts"),
        left_on="day_start_ms",
        right_on="asof_ts",
        direction="backward",
    )
    # Restore original 15m order.
    merged = merged.sort_values("ts").reset_index(drop=True)
    return merged.drop(columns=["day_start_ms", "asof_ts"], errors="ignore")
