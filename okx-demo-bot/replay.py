#!/usr/bin/env python3
"""Fee-aware next-open replay of the three paper books.

Signal on closed bar t, fill at the open of bar t+1.
Default costs: 0.10% fee and 0.05% adverse slippage per side.
SPEC v1 sizes with the 15% vol target. EMA 50/200 and buy-and-hold use 100%.

This script only reads public candles. It does not place orders and does not
read API keys.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from strategy import (
    PAPER_BOOKS,
    STRATEGIES,
    Strategy,
    prepare_frame,
    timeframe_to_ms,
    weight_series,
)

FEE = 0.001
SLIP = 0.0005
INITIAL = 200.0


def simulate(
    df: pd.DataFrame,
    spec: Strategy,
    *,
    fee: float = FEE,
    slip: float = SLIP,
    initial: float = INITIAL,
) -> dict[str, Any]:
    """Walk bars. No lookahead: a cross on bar t fills at the next open."""
    if df is None or len(df) == 0:
        raise ValueError("No candles to replay")
    work = df.reset_index(drop=True)
    prepared = prepare_frame(work, spec)
    ts = work["ts"].to_numpy(dtype=np.int64)
    open_px = work["open"].astype(float).to_numpy()
    close_px = work["close"].astype(float).to_numpy()
    n = len(work)
    equity = np.full(n, np.nan)
    in_mkt = np.zeros(n, dtype=bool)
    trades: list[dict[str, Any]] = []
    usdt = float(initial)
    btc = 0.0
    entry_cost = 0.0

    if spec.buy_and_hold:
        holder = {"usdt": float(initial), "btc": 0.0, "entry_cost": 0.0}
        _buy(0, float(open_px[0]), 1.0, ts, open_px, fee, slip, trades, holder, float(initial))
        usdt = holder["usdt"]
        btc = holder["btc"]
        entry_cost = holder["entry_cost"]
        for i in range(n):
            equity[i] = usdt + btc * float(close_px[i])
            in_mkt[i] = btc > 0
        return _pack(spec, work, equity, in_mkt, trades, usdt, btc, fee, slip, initial)

    signals = prepared["signal"].tolist()
    weights = weight_series(prepared, spec)
    pending: tuple[str, float] | None = None
    for i in range(n):
        if pending is not None:
            side, weight = pending
            pending = None
            if side == "BUY" and btc <= 0 and weight > 0:
                holder = {}
                _buy(i, float(open_px[i]), weight, ts, open_px, fee, slip, trades, holder, usdt)
                usdt = holder["usdt"]
                btc = holder["btc"]
                entry_cost = holder["entry_cost"]
            elif side == "SELL" and btc > 0:
                holder = {"usdt": usdt, "btc": btc, "entry_cost": entry_cost}
                _sell(i, float(open_px[i]), ts, open_px, fee, slip, trades, holder)
                usdt = holder["usdt"]
                btc = holder["btc"]
                entry_cost = holder["entry_cost"]
        equity[i] = usdt + btc * float(close_px[i])
        in_mkt[i] = btc > 0
        if i + 1 >= n:
            continue
        signal = signals[i]
        if signal == "BUY" and btc <= 0:
            weight = float(weights[i]) if np.isfinite(weights[i]) else float("nan")
            if math.isfinite(weight) and weight > 0:
                pending = ("BUY", weight)
        elif signal == "SELL" and btc > 0:
            pending = ("SELL", 1.0)
    return _pack(spec, work, equity, in_mkt, trades, usdt, btc, fee, slip, initial)


def _buy(
    i: int,
    px: float,
    weight: float,
    ts: np.ndarray,
    open_px: np.ndarray,
    fee: float,
    slip: float,
    trades: list[dict[str, Any]],
    holder: dict[str, float],
    usdt: float | None = None,
) -> None:
    if usdt is None:
        usdt = holder.get("usdt", INITIAL)
    spend = usdt * weight
    exec_px = px * (1.0 + slip)
    qty = (spend / exec_px) * (1.0 - fee) if exec_px > 0 else 0.0
    if spend <= 0 or qty <= 0:
        holder.update(usdt=usdt, btc=holder.get("btc", 0.0), entry_cost=holder.get("entry_cost", 0.0))
        return
    signal_ts = int(ts[i - 1]) if i > 0 else int(ts[i])
    trades.append(
        {
            "type": "BUY",
            "ts": int(ts[i]),
            "signal_ts": signal_ts,
            "price": px,
            "exec_px": exec_px,
            "qty": qty,
            "spend": spend,
            "weight": weight,
            "round_trip_pnl": None,
        }
    )
    holder["usdt"] = usdt - spend
    holder["btc"] = holder.get("btc", 0.0) + qty
    holder["entry_cost"] = spend


def _sell(
    i: int,
    px: float,
    ts: np.ndarray,
    open_px: np.ndarray,
    fee: float,
    slip: float,
    trades: list[dict[str, Any]],
    holder: dict[str, float],
) -> None:
    btc = holder["btc"]
    exec_px = px * (1.0 - slip)
    proceeds = (btc * exec_px) * (1.0 - fee)
    pnl = proceeds - holder.get("entry_cost", 0.0)
    signal_ts = int(ts[i - 1]) if i > 0 else int(ts[i])
    trades.append(
        {
            "type": "SELL",
            "ts": int(ts[i]),
            "signal_ts": signal_ts,
            "price": px,
            "exec_px": exec_px,
            "qty": btc,
            "proceeds": proceeds,
            "round_trip_pnl": pnl,
        }
    )
    holder["usdt"] = holder["usdt"] + proceeds
    holder["btc"] = 0.0
    holder["entry_cost"] = 0.0


def _pack(
    spec: Strategy,
    work: pd.DataFrame,
    equity: np.ndarray,
    in_mkt: np.ndarray,
    trades: list[dict[str, Any]],
    usdt: float,
    btc: float,
    fee: float,
    slip: float,
    initial: float,
) -> dict[str, Any]:
    metrics = _metrics(work["ts"], equity, trades, in_mkt, initial)
    metrics.update(
        {
            "strategy": spec.id,
            "description": spec.description,
            "timeframe": spec.timeframe,
            "fee": fee,
            "slip": slip,
            "final_usdt": round(usdt, 8),
            "final_btc": round(btc, 8),
        }
    )
    return {"metrics": metrics, "trades": trades}


def _metrics(
    ts: pd.Series,
    equity: np.ndarray,
    trades: list[dict[str, Any]],
    in_mkt: np.ndarray,
    initial: float,
) -> dict[str, Any]:
    mask = np.isfinite(equity)
    eq = equity[mask]
    stamps = pd.to_datetime(ts.to_numpy()[mask], unit="ms", utc=True)
    start, end = stamps[0], stamps[-1]
    days = max((end - start).total_seconds() / 86400.0, 1e-9)
    final = float(eq[-1])
    total = final / initial - 1.0
    cagr = (final / initial) ** (365.25 / days) - 1.0 if final > 0 else -1.0
    peak = np.maximum.accumulate(eq)
    max_dd = float((eq / peak - 1.0).min()) if len(eq) else 0.0
    daily = pd.Series(eq, index=pd.DatetimeIndex(stamps)).resample("1D").last().dropna()
    rets = daily.pct_change().dropna()
    if len(rets) > 1 and float(rets.std(ddof=1)) > 0:
        sharpe = float(rets.mean() / rets.std(ddof=1) * math.sqrt(365.0))
    else:
        sharpe = float("nan")
    sells = [t for t in trades if t["type"] == "SELL" and t.get("round_trip_pnl") is not None]
    wins = sum(1 for t in sells if t["round_trip_pnl"] > 0)
    return {
        "start": str(start),
        "end": str(end),
        "days": round(days, 2),
        "initial": initial,
        "final_equity": round(final, 4),
        "total_return_pct": round(100.0 * total, 4),
        "cagr_pct": round(100.0 * cagr, 4),
        "max_drawdown_pct": round(100.0 * max_dd, 4),
        "sharpe": None if sharpe != sharpe else round(sharpe, 4),
        "trades": len(trades),
        "round_trips": len(sells),
        "win_rate_pct": None if not sells else round(100.0 * wins / len(sells), 2),
        "exposure_pct": round(100.0 * float(in_mkt[mask].mean()), 2),
    }


def replay_books(
    df: pd.DataFrame,
    books: tuple[str, ...] = PAPER_BOOKS,
    *,
    fee: float = FEE,
    slip: float = SLIP,
    initial: float = INITIAL,
) -> dict[str, dict[str, Any]]:
    """Run the paper books side by side on the same candles."""
    return {
        book: simulate(df, STRATEGIES[book], fee=fee, slip=slip, initial=initial) for book in books
    }


def fetch_public_ohlcv(timeframe: str, bars: int) -> pd.DataFrame:
    """Public OKX candles. No keys and no orders."""
    import ccxt

    from execution import fetch_ohlcv_paginated, rows_to_frame

    exchange = ccxt.okx({"enableRateLimit": True, "options": {"defaultType": "spot"}})
    now_ms = int(exchange.milliseconds())
    rows = fetch_ohlcv_paginated(
        exchange, "BTC/USDT", timeframe, bars, now_ms, limit=100
    )
    tf_ms = timeframe_to_ms(timeframe)
    closed = [r for r in rows if r[0] + tf_ms <= now_ms]
    if len(closed) < bars:
        raise RuntimeError(f"Only {len(closed)} closed {timeframe} bars; needed {bars}")
    return rows_to_frame(closed[-bars:])


def _print_table(results: dict[str, dict[str, Any]]) -> None:
    print(
        f"{'book':<16} {'return':>10} {'cagr':>10} {'maxDD':>10} {'sharpe':>8} "
        f"{'trades':>8} {'win':>8} {'exposure':>10} {'final':>10}"
    )
    for book, result in results.items():
        m = result["metrics"]
        sharpe = "n/a" if m["sharpe"] is None else f"{m['sharpe']:.3f}"
        win = "n/a" if m["win_rate_pct"] is None else f"{m['win_rate_pct']:.1f}%"
        print(
            f"{book:<16} {m['total_return_pct']:+9.2f}% {m['cagr_pct']:+9.2f}% "
            f"{m['max_drawdown_pct']:9.2f}% {sharpe:>8} {m['trades']:8d} {win:>8} "
            f"{m['exposure_pct']:9.1f}% {m['final_equity']:10.2f}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay the three paper books (no orders).")
    parser.add_argument("--days", type=int, default=90, help="Evaluation window after warmup.")
    parser.add_argument("--csv", type=Path, default=None, help="OHLCV csv with ts,open,high,low,close.")
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--fee", type=float, default=FEE)
    parser.add_argument("--slip", type=float, default=SLIP)
    parser.add_argument("--initial", type=float, default=INITIAL)
    args = parser.parse_args(argv)
    if args.csv:
        frame = pd.read_csv(args.csv)
    else:
        # Warmup for SMA 230 plus the evaluation window, on 4h candles.
        warmup = STRATEGIES["spec_v1"].min_closed + 5
        window = int(args.days * 24 / 4)
        frame = fetch_public_ohlcv("4h", warmup + window)
        print(
            f"Public OKX BTC/USDT 4h bars: {len(frame)} "
            f"(warmup {warmup} + about {args.days} days). No orders sent."
        )
    results = replay_books(frame, fee=args.fee, slip=args.slip, initial=args.initial)
    _print_table(results)
    if args.json_out:
        payload = {book: result["metrics"] | {"n_trades": len(result["trades"])} for book, result in results.items()}
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"Wrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
