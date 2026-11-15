"""Performance metrics for a completed backtest ledger."""

from __future__ import annotations

from typing import Any

import pandas as pd

from research.portfolio.ledger import BacktestLedger


def _round_trips(ledger: BacktestLedger) -> list[dict[str, Any]]:
    """Pair enter_* with subsequent exit_* (ignore funding rows)."""
    trips: list[dict[str, Any]] = []
    open_trade: dict[str, Any] | None = None
    for t in ledger.trades:
        if t.action in ("enter_long", "enter_short"):
            open_trade = {
                "side": "long" if t.action == "enter_long" else "short",
                "entry_ts": t.ts,
                "entry_price": t.price,
                "entry_strategy": t.entry_strategy,
                "qty": t.qty,
            }
        elif t.action in ("exit_long", "exit_short") and open_trade is not None:
            side = open_trade["side"]
            entry = float(open_trade["entry_price"])
            exit_px = float(t.price)
            if side == "long":
                ret = (exit_px - entry) / entry
            else:
                ret = (entry - exit_px) / entry
            trips.append(
                {
                    **open_trade,
                    "exit_ts": t.ts,
                    "exit_price": exit_px,
                    "exit_reason": t.reason,
                    "return_pct": ret * 100.0,
                    "win": ret > 0,
                }
            )
            open_trade = None
    return trips


def summarize(ledger: BacktestLedger, *, label: str) -> dict[str, Any]:
    trips = _round_trips(ledger)
    longs = [t for t in trips if t["side"] == "long"]
    shorts = [t for t in trips if t["side"] == "short"]

    def win_rate(rows: list[dict[str, Any]]) -> float | None:
        if not rows:
            return None
        return 100.0 * sum(1 for r in rows if r["win"]) / len(rows)

    equity = [e["equity"] for e in ledger.equity_curve]
    if equity:
        final_nav = equity[-1]
        peak = equity[0]
        max_dd = 0.0
        for v in equity:
            peak = max(peak, v)
            if peak > 0:
                max_dd = min(max_dd, (v - peak) / peak)
    else:
        final_nav = ledger.cash
        max_dd = 0.0

    total_return = (final_nav / ledger.initial_usdt - 1.0) * 100.0
    trade_fees = sum(t.fee for t in ledger.trades)
    return {
        "variant": label,
        "trades": len(trips),
        "long_trades": len(longs),
        "short_trades": len(shorts),
        "long_win_rate_pct": win_rate(longs),
        "short_win_rate_pct": win_rate(shorts),
        "overall_win_rate_pct": win_rate(trips),
        "cumulative_fees": trade_fees,
        "cumulative_funding": ledger.cumulative_funding,
        "max_drawdown_pct": max_dd * 100.0,
        "final_nav": final_nav,
        "total_return_pct": total_return,
        "realized_pnl": ledger.realized_pnl,
        "trips": trips,
    }


def regime_breakdown(bars: pd.DataFrame, ledger: BacktestLedger) -> list[dict[str, Any]]:
    """Contiguous ADX-regime runs along the equity curve (not pooled buckets)."""
    if not ledger.equity_curve:
        return []
    eq = pd.DataFrame(ledger.equity_curve)
    merged = eq.merge(bars[["ts", "adx"]], on="ts", how="left").sort_values("ts")

    def bucket(adx: float) -> str:
        if pd.isna(adx):
            return "warmup"
        if adx > 25:
            return "trend_adx_gt_25"
        if adx < 20:
            return "mr_adx_lt_20"
        return "deadband_20_25"

    merged["regime"] = merged["adx"].map(bucket)
    rows: list[dict[str, Any]] = []
    if merged.empty:
        return rows

    run_regime = merged.iloc[0]["regime"]
    run_start_i = 0
    for i in range(1, len(merged) + 1):
        done = i == len(merged)
        cur = None if done else merged.iloc[i]["regime"]
        if done or cur != run_regime:
            g = merged.iloc[run_start_i:i]
            start, end = float(g.iloc[0]["equity"]), float(g.iloc[-1]["equity"])
            rows.append(
                {
                    "regime": run_regime,
                    "bars": len(g),
                    "start_equity": start,
                    "end_equity": end,
                    "segment_return_pct": (end / start - 1.0) * 100.0 if start else 0.0,
                }
            )
            if not done:
                run_regime = cur
                run_start_i = i

    # Aggregate by regime label for the report summary table.
    agg: dict[str, dict[str, Any]] = {}
    for seg in rows:
        a = agg.setdefault(
            seg["regime"],
            {"regime": seg["regime"], "bars": 0, "segment_return_pct_sum": 0.0, "runs": 0},
        )
        a["bars"] += seg["bars"]
        a["segment_return_pct_sum"] += seg["segment_return_pct"]
        a["runs"] += 1
    summary = []
    for regime, a in agg.items():
        summary.append(
            {
                "regime": regime,
                "bars": a["bars"],
                "runs": a["runs"],
                "sum_segment_return_pct": a["segment_return_pct_sum"],
                "avg_segment_return_pct": a["segment_return_pct_sum"] / a["runs"] if a["runs"] else 0.0,
            }
        )
    return summary
