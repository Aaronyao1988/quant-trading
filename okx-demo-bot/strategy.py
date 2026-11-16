#!/usr/bin/env python3
"""Paper strategies. Signals use closed bars only.

SPEC v1 is the pre-registered 4h EMA(10) / SMA(230) long-only cross with a
15% ATR vol target capped at 100%. EMA 50/200 at 100% and buy-and-hold are
benchmarks. SMA 10/30 on 15m is the previous bot, kept available and not
the default.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

# 4h bars per year. SPEC vol formula: ATR/close * sqrt(365.25 * 6).
BARS_PER_YEAR_4H = 365.25 * 6.0
HALT_EQUITY_FRACTION = 0.80
ATR_PERIOD = 14


@dataclass(frozen=True)
class Strategy:
    id: str
    timeframe: str
    fast: int
    slow: int
    fast_kind: str
    slow_kind: str
    allocation: float | None
    vol_target: float | None
    buy_and_hold: bool
    min_closed: int
    description: str


STRATEGIES: dict[str, Strategy] = {
    "spec_v1": Strategy(
        id="spec_v1",
        timeframe="4h",
        fast=10,
        slow=230,
        fast_kind="ema",
        slow_kind="sma",
        allocation=None,
        vol_target=0.15,
        buy_and_hold=False,
        min_closed=231,
        description="4h EMA 10 / SMA 230 crossover, 15% vol target, cap 100%, long-only",
    ),
    "ema_50_200": Strategy(
        id="ema_50_200",
        timeframe="4h",
        fast=50,
        slow=200,
        fast_kind="ema",
        slow_kind="ema",
        allocation=1.0,
        vol_target=None,
        buy_and_hold=False,
        min_closed=201,
        description="4h EMA 50 / EMA 200 crossover, 100% of cash, long-only benchmark",
    ),
    "buy_and_hold": Strategy(
        id="buy_and_hold",
        timeframe="4h",
        fast=1,
        slow=1,
        fast_kind="sma",
        slow_kind="sma",
        allocation=1.0,
        vol_target=None,
        buy_and_hold=True,
        min_closed=1,
        description="Buy 100% once and hold. Benchmark, not a timing rule.",
    ),
    "sma_10_30": Strategy(
        id="sma_10_30",
        timeframe="15m",
        fast=10,
        slow=30,
        fast_kind="sma",
        slow_kind="sma",
        allocation=0.50,
        vol_target=None,
        buy_and_hold=False,
        min_closed=31,
        description="Legacy 15m SMA 10/30, 50% of cash. Not the default.",
    ),
}

PAPER_BOOKS: tuple[str, ...] = ("spec_v1", "ema_50_200", "buy_and_hold")


def timeframe_to_ms(timeframe: str) -> int:
    if len(timeframe) < 2:
        raise ValueError(f"Bad timeframe {timeframe!r}")
    unit = timeframe[-1]
    try:
        count = int(timeframe[:-1])
    except ValueError as exc:
        raise ValueError(f"Bad timeframe {timeframe!r}") from exc
    mult = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}.get(unit)
    if mult is None or count <= 0:
        raise ValueError(f"Bad timeframe {timeframe!r}")
    return count * mult


def bars_per_year(timeframe: str) -> float:
    return 365.25 * 86_400_000 / timeframe_to_ms(timeframe)


def ema(series: pd.Series, span: int) -> pd.Series:
    """EMA with adjust=False. The first span-1 values are NaN (not a mature average)."""
    out = series.ewm(span=span, adjust=False).mean().copy()
    if span > 1:
        out.iloc[: span - 1] = np.nan
    return out


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).mean()


def moving_average(series: pd.Series, kind: str, window: int) -> pd.Series:
    if kind == "ema":
        return ema(series, window)
    if kind == "sma":
        return sma(series, window)
    raise ValueError(f"Unknown average {kind!r}")


def wilder_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    """Wilder ATR. Seed is the SMA of the first `period` true ranges after bar 0.

    Bar 0 has no previous close, so it is not part of the seed. The first
    finite ATR is at index `period`.
    """
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev).abs(), (low - prev).abs()],
        axis=1,
    ).max(axis=1)
    values = tr.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    if len(values) > period:
        window = values[1 : period + 1]
        if window.size == period and np.all(np.isfinite(window)):
            out[period] = float(window.mean())
            for i in range(period + 1, len(values)):
                if np.isfinite(values[i]) and np.isfinite(out[i - 1]):
                    out[i] = (out[i - 1] * (period - 1) + values[i]) / period
    return pd.Series(out, index=df.index)


def prepare_frame(df: pd.DataFrame, spec: Strategy) -> pd.DataFrame:
    """Add fast, slow, atr, and signal columns. Averages look backward only."""
    out = df.copy()
    close = out["close"].astype(float)
    out["atr"] = wilder_atr(out)
    if spec.buy_and_hold:
        out["fast"] = close
        out["slow"] = close
        out["signal"] = "BUY" if len(out) else "HOLD"
        return out
    out["fast"] = moving_average(close, spec.fast_kind, spec.fast)
    out["slow"] = moving_average(close, spec.slow_kind, spec.slow)
    prev_f = out["fast"].shift(1)
    prev_s = out["slow"].shift(1)
    buy = (
        (prev_f <= prev_s) & (out["fast"] > out["slow"]) & prev_f.notna() & prev_s.notna()
    ).fillna(False)
    sell = (
        (prev_f >= prev_s) & (out["fast"] < out["slow"]) & prev_f.notna() & prev_s.notna()
    ).fillna(False)
    out["signal"] = "HOLD"
    out.loc[buy, "signal"] = "BUY"
    out.loc[sell, "signal"] = "SELL"
    return out


def latest_signal(df: pd.DataFrame, spec: Strategy) -> str:
    """BUY / SELL / HOLD on the last closed bar."""
    if df is None or len(df) == 0:
        return "HOLD"
    if spec.buy_and_hold:
        return "BUY"
    if len(df) < spec.slow + 1:
        return "HOLD"
    prepared = prepare_frame(df, spec)
    signal = prepared.iloc[-1]["signal"]
    if signal not in ("BUY", "SELL", "HOLD"):
        return "HOLD"
    return str(signal)


def compute_signal(df: pd.DataFrame, fast: int = 10, slow: int = 30) -> str:
    """SMA crossover used by the legacy smoke checks."""
    spec = Strategy(
        id="adhoc_sma",
        timeframe="15m",
        fast=fast,
        slow=slow,
        fast_kind="sma",
        slow_kind="sma",
        allocation=0.5,
        vol_target=None,
        buy_and_hold=False,
        min_closed=slow + 1,
        description="adhoc",
    )
    return latest_signal(df, spec)


def entry_weight(df: pd.DataFrame, spec: Strategy) -> float | None:
    """Fraction of virtual USDT to spend. None means skip the entry.

    Vol target (SPEC v1), evaluated on the signal bar::

        sigma = (ATR(14) / close) * sqrt(bars_per_year)
        w = min(1, target / sigma)

    For 4h, bars_per_year is 365.25 * 6. There is no leverage.
    """
    if spec.buy_and_hold:
        return 1.0
    if spec.vol_target is None:
        if spec.allocation is None:
            return None
        return float(spec.allocation)
    if len(df) == 0:
        return None
    prepared = prepare_frame(df, spec)
    row = prepared.iloc[-1]
    if pd.isna(row["atr"]) or pd.isna(row["close"]):
        return None
    atr = float(row["atr"])
    close = float(row["close"])
    if not math.isfinite(atr) or not math.isfinite(close) or atr <= 0 or close <= 0:
        return None
    sigma = (atr / close) * math.sqrt(bars_per_year(spec.timeframe))
    if not math.isfinite(sigma) or sigma <= 0:
        return None
    return min(1.0, float(spec.vol_target) / sigma)


def weight_series(prepared: pd.DataFrame, spec: Strategy) -> np.ndarray:
    """Per-bar entry weight aligned to ``prepared``. NaN means skip."""
    n = len(prepared)
    if spec.buy_and_hold:
        return np.ones(n)
    if spec.vol_target is None:
        value = 1.0 if spec.allocation is None else float(spec.allocation)
        return np.full(n, value)
    atr = prepared["atr"].to_numpy(dtype=float)
    close = prepared["close"].to_numpy(dtype=float)
    scale = math.sqrt(bars_per_year(spec.timeframe))
    out = np.full(n, np.nan)
    for i in range(n):
        a, c = atr[i], close[i]
        if np.isfinite(a) and np.isfinite(c) and a > 0 and c > 0:
            sigma = (a / c) * scale
            if sigma > 0 and np.isfinite(sigma):
                out[i] = min(1.0, float(spec.vol_target) / sigma)
    return out


def halted(equity: float, initial_usdt: float, fraction: float = HALT_EQUITY_FRACTION) -> bool:
    """True when marked equity is below ``fraction`` of starting equity."""
    if initial_usdt <= 0 or not math.isfinite(equity):
        return True
    return equity < fraction * initial_usdt


def decide(signal: str, *, flat: bool, halted_now: bool) -> str:
    """Map a signal to an action. Halt blocks entries and still allows exits."""
    if signal == "BUY":
        if not flat:
            return "skip_already_long"
        if halted_now:
            return "skip_halt"
        return "buy"
    if signal == "SELL":
        if flat:
            return "skip_already_flat"
        return "sell"
    return "hold"
