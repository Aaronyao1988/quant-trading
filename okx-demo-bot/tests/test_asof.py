"""Unit tests: daily SMA as-of join must not leak same-day closes."""

from __future__ import annotations

import pandas as pd

from research.data.asof import align_daily_sma_asof, daily_sma


def _ms(day: int, hour: int = 0, minute: int = 0) -> int:
    """Synthetic timestamps: day 0 = 2024-01-01 00:00 UTC."""
    base = 1704067200000  # 2024-01-01 00:00:00 UTC
    return base + day * 86_400_000 + hour * 3_600_000 + minute * 60_000


def test_same_day_15m_never_sees_same_day_close() -> None:
    # Daily closes at end of day D (open at midnight D, close_ts = midnight D+1).
    # Construct rising closes so SMA is identifiable.
    daily_rows = []
    for d in range(35):
        daily_rows.append(
            {"ts": _ms(d), "open": 100 + d, "high": 101 + d, "low": 99 + d, "close": 100.0 + d, "volume": 1.0}
        )
    daily = pd.DataFrame(daily_rows)

    # 15m bars on day 34 (0-indexed day 34) at noon — must see SMA ending at day 33 close only.
    bars = pd.DataFrame(
        [
            {
                "ts": _ms(34, 12, 0),
                "open": 130,
                "high": 131,
                "low": 129,
                "close": 130.5,
                "volume": 1.0,
            },
            {
                "ts": _ms(34, 12, 15),
                "open": 130.5,
                "high": 132,
                "low": 130,
                "close": 131.0,
                "volume": 1.0,
            },
        ]
    )

    aligned = align_daily_sma_asof(bars, daily, window=30, column="daily_sma30")
    # SMA of closes for days 4..33 inclusive (30 days) when standing on day 34.
    # Available daily SMAs: after day 33 closes (at _ms(34)), SMA uses closes[4:34] = days 4..33.
    expected = daily_sma(daily, 30)
    # Last row whose close_ts <= day_start of day 34 (= _ms(34)) is the day-33 bar
    # (close_ts = _ms(34)).
    sma_day33 = float(expected.loc[expected["ts"] == _ms(33), "sma"].iloc[0])
    sma_day34 = float(expected.loc[expected["ts"] == _ms(34), "sma"].iloc[0])

    for _, row in aligned.iterrows():
        assert row["daily_sma30"] == sma_day33
        assert row["daily_sma30"] != sma_day34


def test_after_midnight_next_day_picks_up_prior_close() -> None:
    daily_rows = []
    for d in range(40):
        daily_rows.append(
            {
                "ts": _ms(d),
                "open": 100 + d,
                "high": 101 + d,
                "low": 99 + d,
                "close": 100.0 + d,
                "volume": 1.0,
            }
        )
    daily = pd.DataFrame(daily_rows)
    # First 15m of day 35 should see day-34 SMA (closed at start of day 35).
    bars = pd.DataFrame(
        [
            {
                "ts": _ms(35, 0, 0),
                "open": 135,
                "high": 136,
                "low": 134,
                "close": 135.2,
                "volume": 1.0,
            }
        ]
    )
    aligned = align_daily_sma_asof(bars, daily, window=30)
    expected = daily_sma(daily, 30)
    sma_day34 = float(expected.loc[expected["ts"] == _ms(34), "sma"].iloc[0])
    assert float(aligned.iloc[0]["daily_sma30"]) == sma_day34
