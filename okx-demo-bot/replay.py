#!/usr/bin/env python3
"""SMA snapshot + offline historical crossover replay for the OKX demo bot.

Reuses compute_signal / ledger helpers from bot.py (no strategy drift).
Default offline lookback is 14 days (~1,344 closed 15m bars). Historical
fills are virtual at bar close. --demo-orders places a short live demo
BUY then SELL to prove the sandbox path; do not spam historical crosses
as live orders.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import ccxt
import numpy as np
import pandas as pd

from bot import (
    DEFAULT_ALLOCATION_PCT,
    DEFAULT_FAST,
    DEFAULT_INITIAL_USDT,
    DEFAULT_SLOW,
    DEFAULT_SYMBOL,
    DEFAULT_TIMEFRAME,
    BOT_DIR,
    compute_signal,
    create_okx_demo_exchange,
    ensure_order_fill,
    ledger_path,
    load_ledger,
    min_amount,
    min_notional,
    save_ledger,
)

LOGGER = logging.getLogger("okx-replay")
SHANGHAI = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc

# 14 days × 24h × 4 bars/hour = 1,344 closed 15m candles.
DEFAULT_LOOKBACK_DAYS = 14
DEFAULT_LOOKBACK_BARS_15M = 14 * 24 * 4  # 1344
BARS_PER_DAY_15M = 24 * 4

# Regime heuristics (15m): rolling return / ADX-ish / short-range vs ATR.
REGIME_WINDOW = 96  # ~1 day of 15m bars for trend return
OSC_RANGE_WINDOW = 16  # ~4h span for "narrow range"
UPTREND_RET = 0.015  # +1.5% over window
DOWNTREND_RET = -0.015
ADX_TREND_MIN = 22.0
OSC_ADX_MAX = 20.0
OSC_RET_ABS_MAX = 0.01  # |1d return| ≤ 1%
OSC_RANGE_ATR_MAX = 6.0  # 4h high-low / ATR — BTC 15m floors ~4.5 on full-day spans


def fmt_ts(ms: int) -> tuple[str, str]:
    """Return (Asia/Shanghai local, UTC) strings for a candle open ms."""
    dt_utc = datetime.fromtimestamp(ms / 1000.0, tz=UTC)
    dt_local = dt_utc.astimezone(SHANGHAI)
    return (
        dt_local.strftime("%Y-%m-%d %H:%M:%S %Z"),
        dt_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
    )


def create_okx_public_exchange() -> ccxt.okx:
    """Public market-data client (no API keys) for offline OHLCV replay."""
    return ccxt.okx(
        {
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }
    )


def resolve_exchange(*, need_trading: bool) -> tuple[ccxt.okx, str]:
    """Prefer public OHLCV; require demo keys only for --demo-orders."""
    keys_present = all(
        os.environ.get(k, "").strip()
        for k in ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE")
    )
    if need_trading:
        if not keys_present:
            raise SystemExit(
                "--demo-orders requires OKX_API_KEY / OKX_API_SECRET / "
                "OKX_API_PASSPHRASE (demo sandbox). Offline replay does not."
            )
        ex = create_okx_demo_exchange()
        return ex, "demo"
    if keys_present:
        try:
            ex = create_okx_demo_exchange()
            return ex, "demo"
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Demo client failed (%s); falling back to public OHLCV.", exc)
    return create_okx_public_exchange(), "public"


def fetch_ohlcv_since(
    exchange: ccxt.Exchange,
    symbol: str,
    timeframe: str,
    since_ms: int,
    *,
    until_ms: int | None = None,
) -> pd.DataFrame:
    """Paginate OHLCV from since_ms until now (or until_ms), closed bars only."""
    tf_ms = int(exchange.parse_timeframe(timeframe) * 1000)
    end = until_ms or int(time.time() * 1000)
    all_rows: list[list[float]] = []
    cursor = since_ms
    # OKX typically returns ≤100 candles per fetch_ohlcv; page forward.
    while cursor < end:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=100)
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
        time.sleep(exchange.rateLimit / 1000.0 if exchange.rateLimit else 0.05)

    if not all_rows:
        raise RuntimeError("No OHLCV returned from OKX.")

    df = pd.DataFrame(all_rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    now_ms = int(time.time() * 1000)
    closed = df[df["ts"] + tf_ms <= now_ms].copy().reset_index(drop=True)
    return closed


def annotate_smas(df: pd.DataFrame, fast: int, slow: int) -> pd.DataFrame:
    work = df.copy()
    work["sma_fast"] = work["close"].rolling(fast).mean()
    work["sma_slow"] = work["close"].rolling(slow).mean()
    work["gap"] = work["sma_fast"] - work["sma_slow"]
    return work


def detect_cross_on_bar(work: pd.DataFrame, i: int) -> str | None:
    """Return 'golden' / 'death' / None using the same rules as compute_signal."""
    if i < 1:
        return None
    window = work.iloc[: i + 1]
    signal = compute_signal(window)
    if signal == "BUY":
        return "golden"
    if signal == "SELL":
        return "death"
    return None


def sma_snapshot_table(work: pd.DataFrame, n: int = 5) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    tail = work.iloc[-n:]
    start_i = len(work) - n
    for offset, (_, bar) in enumerate(tail.iterrows()):
        i = start_i + offset
        local, utc = fmt_ts(int(bar["ts"]))
        cross = detect_cross_on_bar(work, i)
        note = ""
        if cross == "golden":
            note = "GOLDEN CROSS (fast above slow)"
        elif cross == "death":
            note = "DEATH CROSS (fast below slow)"
        rows.append(
            {
                "ts_ms": int(bar["ts"]),
                "local": local,
                "utc": utc,
                "close": float(bar["close"]),
                "sma10": float(bar["sma_fast"]) if pd.notna(bar["sma_fast"]) else None,
                "sma30": float(bar["sma_slow"]) if pd.notna(bar["sma_slow"]) else None,
                "gap": float(bar["gap"]) if pd.notna(bar["gap"]) else None,
                "note": note,
            }
        )
    return rows


def imminent_crossover(work: pd.DataFrame, lookback: int = 4) -> dict[str, Any]:
    """Heuristic: gap shrinking toward zero over recent closed bars."""
    recent = work.dropna(subset=["gap"]).iloc[-lookback:]
    if len(recent) < 2:
        return {"imminent": False, "reason": "not enough gap history"}
    gaps = recent["gap"].tolist()
    abs_gaps = [abs(g) for g in gaps]
    last = gaps[-1]
    shrinking = all(abs_gaps[i] >= abs_gaps[i + 1] for i in range(len(abs_gaps) - 1))
    approaching = abs(last) < abs(gaps[0]) and abs(last) < abs(gaps[-2]) * 1.25
    sign_flip_near = abs(last) < abs(gaps[0]) * 0.5 if gaps[0] != 0 else abs(last) < 1.0
    imminent = shrinking and approaching and abs(last) > 0
    if last == 0:
        reason = "gap is already ~0 on last closed bar"
    elif imminent or (shrinking and sign_flip_near):
        direction = (
            "up through zero (possible golden)" if last < 0 else "down through zero (possible death)"
        )
        reason = (
            f"gap shrinking toward zero over last {len(gaps)} bars "
            f"(abs gaps={[round(a, 2) for a in abs_gaps]}); approaching {direction}"
        )
        imminent = True
    else:
        reason = (
            f"gap not clearly compressing to zero "
            f"(last gap={last:.4f}, abs gaps={[round(a, 2) for a in abs_gaps]})"
        )
    return {
        "imminent": imminent,
        "last_gap": float(last),
        "abs_gaps": [float(a) for a in abs_gaps],
        "reason": reason,
    }


def wilder_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ADX-ish Wilder average directional index (no external TA lib)."""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr = pd.Series(tr, index=df.index).ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean()


def annotate_regimes(work: pd.DataFrame, window: int = REGIME_WINDOW) -> pd.DataFrame:
    """Label each bar as uptrend / downtrend / oscillation / mixed."""
    out = work.copy()
    close = out["close"].astype(float)
    out["ret_w"] = close / close.shift(window) - 1.0
    out["atr14"] = (
        pd.concat(
            [
                (out["high"] - out["low"]).abs(),
                (out["high"] - close.shift(1)).abs(),
                (out["low"] - close.shift(1)).abs(),
            ],
            axis=1,
        )
        .max(axis=1)
        .ewm(alpha=1 / 14, adjust=False)
        .mean()
    )
    out["adx"] = wilder_adx(out)
    # Short-horizon high-low span / ATR (full-day BTC span is almost never "narrow").
    roll_high = out["high"].rolling(OSC_RANGE_WINDOW).max()
    roll_low = out["low"].rolling(OSC_RANGE_WINDOW).min()
    out["range_atr"] = (roll_high - roll_low) / out["atr14"].replace(0, np.nan)

    regimes: list[str] = []
    for i in range(len(out)):
        ret = out.iloc[i]["ret_w"]
        adx = out.iloc[i]["adx"]
        ra = out.iloc[i]["range_atr"]
        if pd.isna(ret) or pd.isna(adx):
            regimes.append("warmup")
            continue
        if ret >= UPTREND_RET and adx >= ADX_TREND_MIN:
            regimes.append("sustained_uptrend")
        elif ret <= DOWNTREND_RET and adx >= ADX_TREND_MIN:
            regimes.append("sustained_downtrend")
        elif (
            abs(ret) <= OSC_RET_ABS_MAX
            and adx <= OSC_ADX_MAX
            and (pd.isna(ra) or ra <= OSC_RANGE_ATR_MAX)
        ):
            regimes.append("narrow_range_oscillation")
        else:
            regimes.append("mixed")
    out["regime"] = regimes
    return out


def collect_crosses(
    work: pd.DataFrame,
    window_start_ms: int,
) -> list[dict[str, Any]]:
    crosses: list[dict[str, Any]] = []
    for i in range(1, len(work)):
        if int(work.iloc[i]["ts"]) < window_start_ms:
            continue
        kind = detect_cross_on_bar(work, i)
        if not kind:
            continue
        bar = work.iloc[i]
        local, utc = fmt_ts(int(bar["ts"]))
        crosses.append(
            {
                "kind": kind,
                "ts_ms": int(bar["ts"]),
                "local": local,
                "utc": utc,
                "close": float(bar["close"]),
                "sma10": float(bar["sma_fast"]),
                "sma30": float(bar["sma_slow"]),
                "gap": float(bar["gap"]),
                "regime": str(bar.get("regime", "mixed")),
            }
        )
    return crosses


def classify_regime_coverage(
    work: pd.DataFrame,
    crosses: list[dict[str, Any]],
    window_start_ms: int,
) -> dict[str, Any]:
    """Summarize three target regimes and which crosses fell in each."""
    trading = work[work["ts"] >= window_start_ms].copy()
    labels = (
        "sustained_uptrend",
        "sustained_downtrend",
        "narrow_range_oscillation",
    )
    coverage: dict[str, Any] = {}
    for label in labels:
        bars = trading[trading["regime"] == label]
        bar_crosses = [c for c in crosses if c.get("regime") == label]
        first_ts = int(bars.iloc[0]["ts"]) if len(bars) else None
        last_ts = int(bars.iloc[-1]["ts"]) if len(bars) else None
        coverage[label] = {
            "bar_count": int(len(bars)),
            "pct_of_window": round(100.0 * len(bars) / max(len(trading), 1), 2),
            "first_bar_local": fmt_ts(first_ts)[0] if first_ts else None,
            "last_bar_local": fmt_ts(last_ts)[0] if last_ts else None,
            "price_regime_present": len(bars) > 0,
            "golden_crosses": [c for c in bar_crosses if c["kind"] == "golden"],
            "death_crosses": [c for c in bar_crosses if c["kind"] == "death"],
            "cross_count": len(bar_crosses),
        }
    mixed_bars = int((trading["regime"] == "mixed").sum()) if len(trading) else 0
    coverage["_meta"] = {
        "window_bars": int(len(trading)),
        "mixed_bars": mixed_bars,
        "warmup_bars": int((trading["regime"] == "warmup").sum()) if len(trading) else 0,
        "heuristic": {
            "window_bars": REGIME_WINDOW,
            "osc_range_window": OSC_RANGE_WINDOW,
            "uptrend_ret": UPTREND_RET,
            "downtrend_ret": DOWNTREND_RET,
            "adx_trend_min": ADX_TREND_MIN,
            "osc_adx_max": OSC_ADX_MAX,
            "osc_ret_abs_max": OSC_RET_ABS_MAX,
            "osc_range_atr_max": OSC_RANGE_ATR_MAX,
        },
    }
    return coverage


def load_history(
    exchange: ccxt.Exchange,
    symbol: str,
    timeframe: str,
    fast: int,
    slow: int,
    lookback_hours: int,
) -> tuple[pd.DataFrame, int, list[dict[str, Any]], dict[str, Any]]:
    """Fetch lookback window (+ SMA warmup), annotate regimes, list crosses."""
    now_ms = int(time.time() * 1000)
    tf_ms = int(exchange.parse_timeframe(timeframe) * 1000)
    warmup_ms = (slow + 5 + REGIME_WINDOW) * tf_ms
    window_start = now_ms - lookback_hours * 3600 * 1000
    since = window_start - warmup_ms
    df = fetch_ohlcv_since(exchange, symbol, timeframe, since)
    work = annotate_smas(df, fast, slow)
    work = annotate_regimes(work)
    keep_from = window_start - warmup_ms
    trimmed = work[work["ts"] >= keep_from].copy().reset_index(drop=True)
    crosses = collect_crosses(trimmed, window_start)
    regimes = classify_regime_coverage(trimmed, crosses, window_start)
    LOGGER.info(
        "Lookback %dh: %d closed bars in frame, %d trading-window bars, "
        "%d golden, %d death",
        lookback_hours,
        len(trimmed),
        int(regimes["_meta"]["window_bars"]),
        sum(1 for c in crosses if c["kind"] == "golden"),
        sum(1 for c in crosses if c["kind"] == "death"),
    )
    return trimmed, lookback_hours, crosses, regimes


def replay_virtual(
    work: pd.DataFrame,
    window_start_ms: int,
    *,
    allocation_pct: float = DEFAULT_ALLOCATION_PCT,
    initial_usdt: float = DEFAULT_INITIAL_USDT,
) -> dict[str, Any]:
    """Walk closed candles; trade at close on golden/death with virtual ledger."""
    ledger = {
        "initial_usdt": float(initial_usdt),
        "virtual_usdt": float(initial_usdt),
        "virtual_btc": 0.0,
        "last_traded_ts": None,
    }
    trades: list[dict[str, Any]] = []
    flat = True

    for i in range(1, len(work)):
        bar = work.iloc[i]
        ts = int(bar["ts"])
        if ts < window_start_ms:
            continue
        kind = detect_cross_on_bar(work, i)
        if not kind:
            continue
        if ledger["last_traded_ts"] == ts:
            continue

        price = float(bar["close"])
        local, utc = fmt_ts(ts)
        regime = str(bar.get("regime", "mixed"))

        if kind == "golden":
            if not flat:
                continue
            spend = ledger["virtual_usdt"] * allocation_pct
            if spend <= 0 or price <= 0:
                continue
            qty = spend / price
            ledger["virtual_usdt"] = round(ledger["virtual_usdt"] - spend, 6)
            ledger["virtual_btc"] = round(ledger["virtual_btc"] + qty, 8)
            ledger["last_traded_ts"] = ts
            flat = False
            trades.append(
                {
                    "type": "BUY",
                    "cross": "golden",
                    "ts_ms": ts,
                    "local": local,
                    "utc": utc,
                    "price": price,
                    "qty": qty,
                    "usdt_after": ledger["virtual_usdt"],
                    "btc_after": ledger["virtual_btc"],
                    "equity_at_close": round(
                        ledger["virtual_usdt"] + ledger["virtual_btc"] * price, 4
                    ),
                    "regime": regime,
                }
            )
        elif kind == "death":
            if flat:
                continue
            qty = ledger["virtual_btc"]
            proceeds = qty * price
            ledger["virtual_usdt"] = round(ledger["virtual_usdt"] + proceeds, 6)
            ledger["virtual_btc"] = 0.0
            ledger["last_traded_ts"] = ts
            flat = True
            trades.append(
                {
                    "type": "SELL",
                    "cross": "death",
                    "ts_ms": ts,
                    "local": local,
                    "utc": utc,
                    "price": price,
                    "qty": qty,
                    "usdt_after": ledger["virtual_usdt"],
                    "btc_after": ledger["virtual_btc"],
                    "equity_at_close": round(ledger["virtual_usdt"], 4),
                    "regime": regime,
                }
            )

    mark = float(work.iloc[-1]["close"])
    final_equity = ledger["virtual_usdt"] + ledger["virtual_btc"] * mark
    pnl = final_equity - initial_usdt
    pnl_pct = (final_equity / initial_usdt - 1.0) * 100.0
    return {
        "trades": trades,
        "final_ledger": ledger,
        "mark_price": mark,
        "final_equity": final_equity,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
    }


def demo_order_proof(
    exchange: ccxt.Exchange,
    symbol: str,
    *,
    allocation_pct: float = DEFAULT_ALLOCATION_PCT,
) -> dict[str, Any]:
    """Controlled live demo BUY then SELL; backup ledger first."""
    path = ledger_path()
    if not path.exists():
        save_ledger(load_ledger())
    backup = BOT_DIR / f"virtual_ledger_200.backup.{int(time.time())}.json"
    shutil.copy2(path, backup)
    LOGGER.info("Ledger backup → %s", backup.name)

    before = load_ledger()
    before_snap = deepcopy(before)
    exchange.load_markets()
    market = exchange.market(symbol)
    amt_min = min_amount(market)
    cost_min = min_notional(market)

    ticker = exchange.fetch_ticker(symbol)
    mark = float(ticker["last"] or ticker["close"])
    header = exchange.headers.get("x-simulated-trading")
    if str(header) != "1":
        raise RuntimeError(f"Refusing non-demo trading; header={header!r}")

    result: dict[str, Any] = {
        "backup_path": str(backup),
        "sandbox_header": str(header),
        "mark_price": mark,
        "ledger_before": before_snap,
        "orders": [],
        "ledger_after_buy": None,
        "ledger_after_sell": None,
        "ledger_final": None,
        "restored": False,
    }

    state = load_ledger()
    flat = state["virtual_btc"] < amt_min

    def place_buy(st: dict) -> dict:
        spend = st["virtual_usdt"] * allocation_pct
        if spend < cost_min:
            raise RuntimeError(f"BUY allocation {spend:.4f} below min notional {cost_min}")
        raw_qty = spend / mark
        btc_qty = float(exchange.amount_to_precision(symbol, raw_qty))
        if btc_qty < amt_min:
            raise RuntimeError(f"BUY qty {btc_qty} below min {amt_min}")
        order = exchange.create_market_buy_order(symbol, btc_qty)
        filled_btc, spent_usdt = ensure_order_fill(exchange, symbol, order, btc_qty, mark)
        if filled_btc <= 0:
            raise RuntimeError("BUY zero fill")
        spent_usdt = min(spent_usdt, st["virtual_usdt"])
        st["virtual_usdt"] = round(st["virtual_usdt"] - spent_usdt, 6)
        st["virtual_btc"] = round(st["virtual_btc"] + filled_btc, 8)
        st["last_traded_ts"] = int(time.time() * 1000)
        save_ledger(st)
        summary = {
            "side": "buy",
            "id": order.get("id"),
            "requested_qty": btc_qty,
            "filled": filled_btc,
            "cost": spent_usdt,
            "status": order.get("status"),
            "average": order.get("average") or order.get("price"),
        }
        result["orders"].append(summary)
        LOGGER.info("DEMO BUY id=%s filled=%.8f cost=%.4f", summary["id"], filled_btc, spent_usdt)
        return st

    def place_sell(st: dict) -> dict:
        btc_qty = float(exchange.amount_to_precision(symbol, st["virtual_btc"]))
        if btc_qty < amt_min:
            raise RuntimeError(f"SELL qty {btc_qty} below min {amt_min}")
        order = exchange.create_market_sell_order(symbol, btc_qty)
        sold_btc, received_usdt = ensure_order_fill(exchange, symbol, order, btc_qty, mark)
        if sold_btc <= 0:
            raise RuntimeError("SELL zero fill")
        remaining = max(0.0, st["virtual_btc"] - sold_btc)
        st["virtual_btc"] = round(remaining if remaining >= amt_min else 0.0, 8)
        st["virtual_usdt"] = round(st["virtual_usdt"] + received_usdt, 6)
        st["last_traded_ts"] = int(time.time() * 1000)
        save_ledger(st)
        summary = {
            "side": "sell",
            "id": order.get("id"),
            "requested_qty": btc_qty,
            "filled": sold_btc,
            "cost": received_usdt,
            "status": order.get("status"),
            "average": order.get("average") or order.get("price"),
        }
        result["orders"].append(summary)
        LOGGER.info(
            "DEMO SELL id=%s filled=%.8f proceeds=%.4f", summary["id"], sold_btc, received_usdt
        )
        return st

    if not flat:
        LOGGER.info("Ledger already long; SELL first.")
        state = place_sell(state)
        result["ledger_after_sell"] = deepcopy(state)

    state = place_buy(state)
    result["ledger_after_buy"] = deepcopy(state)
    state = place_sell(state)
    result["ledger_after_sell"] = deepcopy(state)
    result["ledger_final"] = deepcopy(state)
    result["note"] = (
        f"Post-test ledger left as-is after BUY+SELL cycle. "
        f"Backup at {backup.name}; restore with: "
        f"cp {backup.name} {path.name}"
    )
    return result


def print_snapshot(rows: list[dict[str, Any]], imminent: dict[str, Any]) -> None:
    print("\n=== SMA snapshot (last 5 completed 15m candles) ===")
    hdr = (
        f"{'Local (Asia/Shanghai)':<28} {'UTC':<24} {'Close':>10} "
        f"{'SMA10':>10} {'SMA30':>10} {'Gap':>10}  Note"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        sma10 = f"{r['sma10']:.2f}" if r["sma10"] is not None else "n/a"
        sma30 = f"{r['sma30']:.2f}" if r["sma30"] is not None else "n/a"
        gap = f"{r['gap']:+.2f}" if r["gap"] is not None else "n/a"
        print(
            f"{r['local']:<28} {r['utc']:<24} {r['close']:10.2f} "
            f"{sma10:>10} {sma30:>10} {gap:>10}  {r['note']}"
        )
    print(f"\nImminent crossover? {imminent['imminent']} — {imminent['reason']}")


def print_regimes(coverage: dict[str, Any]) -> None:
    print("\n=== Market regime coverage (heuristic) ===")
    meta = coverage.get("_meta", {})
    print(
        f"Window bars={meta.get('window_bars')} | mixed={meta.get('mixed_bars')} | "
        f"warmup={meta.get('warmup_bars')}"
    )
    labels = (
        ("sustained_uptrend", "Sustained uptrend"),
        ("sustained_downtrend", "Sustained downtrend"),
        ("narrow_range_oscillation", "Narrow-range oscillation"),
    )
    for key, title in labels:
        block = coverage[key]
        present = "yes" if block["price_regime_present"] else "no"
        print(
            f"\n{title}: present={present} bars={block['bar_count']} "
            f"({block['pct_of_window']}% of window) crosses={block['cross_count']}"
        )
        if block["first_bar_local"]:
            print(f"  span: {block['first_bar_local']} → {block['last_bar_local']}")
        goldens = block["golden_crosses"]
        deaths = block["death_crosses"]
        if not goldens and not deaths:
            print("  crosses: none in this regime (price regime still documented)")
            continue
        for c in goldens:
            print(f"  GOLDEN {c['local']} close={c['close']:.2f} gap={c['gap']:+.2f}")
        for c in deaths:
            print(f"  DEATH  {c['local']} close={c['close']:.2f} gap={c['gap']:+.2f}")


def render_markdown_report(payload: dict[str, Any]) -> str:
    """Optional markdown summary for Project internal/ reports."""
    hours = payload["lookback_hours"]
    days = payload.get("lookback_days")
    crosses = payload["crosses"]
    goldens = [c for c in crosses if c["kind"] == "golden"]
    deaths = [c for c in crosses if c["kind"] == "death"]
    replay = payload["replay"]
    lines = [
        f"# OKX demo SMA replay ({days}d / {hours}h)",
        "",
        f"Generated: {payload['generated_at_utc']}",
        f"Client: `{payload.get('exchange_mode')}` | symbol `{payload['symbol']}` "
        f"`{payload['timeframe']}` SMA{payload['fast']}/{payload['slow']}",
        f"Target closed bars ≈ {payload.get('target_closed_bars')} "
        f"(fetched trading-window bars: {payload['regimes']['_meta']['window_bars']})",
        "",
        "## Crosses",
        f"Golden: **{len(goldens)}** | Death: **{len(deaths)}**",
        "",
    ]
    for c in crosses:
        lines.append(
            f"- **{c['kind'].upper()}** {c['local']} / {c['utc']} "
            f"close={c['close']:.2f} gap={c['gap']:+.2f} regime=`{c.get('regime')}`"
        )
    lines += [
        "",
        "## Offline virtual ledger",
        f"Start $200 → final **${replay['final_equity']:.4f}** "
        f"(PnL ${replay['pnl']:+.4f} / {replay['pnl_pct']:+.2f}%) | "
        f"trades={len(replay['trades'])}",
        "",
        "## Regime coverage",
    ]
    for key, title in (
        ("sustained_uptrend", "Sustained uptrend"),
        ("sustained_downtrend", "Sustained downtrend"),
        ("narrow_range_oscillation", "Narrow-range oscillation"),
    ):
        b = payload["regimes"][key]
        lines.append(
            f"### {title}\n"
            f"- present: {b['price_regime_present']} | bars={b['bar_count']} "
            f"({b['pct_of_window']}%) | crosses={b['cross_count']}"
        )
        if not b["golden_crosses"] and not b["death_crosses"]:
            lines.append("- crosses: none (regime still documented if present)")
        for c in b["golden_crosses"]:
            lines.append(f"- GOLDEN {c['local']} @ {c['close']:.2f}")
        for c in b["death_crosses"]:
            lines.append(f"- DEATH {c['local']} @ {c['close']:.2f}")
        lines.append("")
    if payload.get("demo_orders") is None:
        lines += [
            "## Demo orders",
            "Not run (use `--demo-orders` with demo API keys; do not enable in CI).",
            "",
        ]
    return "\n".join(lines)


def resolve_lookback_hours(args: argparse.Namespace) -> tuple[int, float, int]:
    """Return (hours, days, target_closed_15m_bars)."""
    if args.hours is not None and args.days is not None:
        raise SystemExit("Pass only one of --hours or --days.")
    if args.hours is not None:
        hours = int(args.hours)
    elif args.days is not None:
        hours = int(round(float(args.days) * 24))
    else:
        hours = DEFAULT_LOOKBACK_DAYS * 24
    if hours < 1:
        raise SystemExit("Lookback must be ≥ 1 hour.")
    days = hours / 24.0
    # For non-15m timeframes, scale target bar count from wall-clock hours.
    # Default 15m → 1344 bars for 14d.
    target_bars = int(round(hours * 60 / 15)) if args.timeframe == "15m" else None
    if args.timeframe == "15m":
        target_bars = hours * 4  # 4 bars per hour
    return hours, days, int(target_bars or 0)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "OKX demo SMA snapshot + offline historical replay "
            f"(default {DEFAULT_LOOKBACK_DAYS}d ≈ {DEFAULT_LOOKBACK_BARS_15M} × 15m bars)."
        )
    )
    p.add_argument("--symbol", default=DEFAULT_SYMBOL)
    p.add_argument("--timeframe", default=DEFAULT_TIMEFRAME)
    p.add_argument("--fast", type=int, default=DEFAULT_FAST)
    p.add_argument("--slow", type=int, default=DEFAULT_SLOW)
    p.add_argument("--allocation-pct", type=float, default=DEFAULT_ALLOCATION_PCT)
    p.add_argument(
        "--days",
        type=float,
        default=None,
        help=f"Offline lookback in days (default {DEFAULT_LOOKBACK_DAYS}).",
    )
    p.add_argument(
        "--hours",
        type=int,
        default=None,
        help="Offline lookback in hours (overrides --days / default).",
    )
    p.add_argument(
        "--demo-orders",
        action="store_true",
        help="Place a controlled live demo BUY then SELL (sandbox only; needs keys).",
    )
    p.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Write machine-readable results JSON (no secrets).",
    )
    p.add_argument(
        "--md-out",
        type=Path,
        default=None,
        help="Write markdown regime/replay summary (e.g. Project internal/).",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    lookback_hours, lookback_days, target_bars = resolve_lookback_hours(args)

    exchange, mode = resolve_exchange(need_trading=args.demo_orders)
    LOGGER.info(
        "OKX client mode=%s (x-simulated-trading=%s).",
        mode,
        exchange.headers.get("x-simulated-trading"),
    )
    try:
        exchange.load_markets()
    except ccxt.BaseError as exc:
        LOGGER.warning("load_markets failed (%s); continuing for public OHLCV.", exc)

    # --- 1) Live SMA snapshot ---
    snap_since = int(time.time() * 1000) - (args.slow + 40) * int(
        exchange.parse_timeframe(args.timeframe) * 1000
    )
    snap_df = fetch_ohlcv_since(exchange, args.symbol, args.timeframe, snap_since)
    snap_work = annotate_smas(snap_df, args.fast, args.slow)
    snap_rows = sma_snapshot_table(snap_work, n=5)
    imminent = imminent_crossover(snap_work)
    print_snapshot(snap_rows, imminent)

    # --- 2) Fixed lookback historical window + virtual replay + regimes ---
    hist_df, hours, crosses, regimes = load_history(
        exchange,
        args.symbol,
        args.timeframe,
        args.fast,
        args.slow,
        lookback_hours,
    )
    now_ms = int(time.time() * 1000)
    window_start = now_ms - hours * 3600 * 1000
    goldens = [c for c in crosses if c["kind"] == "golden"]
    deaths = [c for c in crosses if c["kind"] == "death"]
    window_bars = regimes["_meta"]["window_bars"]
    print(
        f"\n=== Historical crosses (window={hours}h / {lookback_days:g}d, "
        f"~{target_bars or window_bars} × {args.timeframe} target, "
        f"got {window_bars} trading bars) ==="
    )
    print(f"Golden: {len(goldens)} | Death: {len(deaths)}")
    for c in crosses:
        print(
            f"  {c['kind'].upper():6} {c['local']} / {c['utc']} "
            f"close={c['close']:.2f} gap={c['gap']:+.2f} regime={c.get('regime')}"
        )

    replay = replay_virtual(
        hist_df,
        window_start,
        allocation_pct=args.allocation_pct,
    )
    print(f"\n=== Offline virtual replay ({hours}h / {lookback_days:g}d) ===")
    print(f"Trades: {len(replay['trades'])}")
    for t in replay["trades"]:
        print(
            f"  {t['type']:4} {t['local']} @ {t['price']:.2f} qty={t['qty']:.8f} "
            f"→ USDT={t['usdt_after']:.4f} BTC={t['btc_after']:.8f} "
            f"equity≈{t['equity_at_close']:.2f} regime={t.get('regime')}"
        )
    print(
        f"Final equity ${replay['final_equity']:.4f} vs $200 "
        f"(PnL ${replay['pnl']:+.4f} / {replay['pnl_pct']:+.2f}%) "
        f"mark={replay['mark_price']:.2f}"
    )
    print(f"Final ledger: {json.dumps(replay['final_ledger'])}")

    print_regimes(regimes)

    demo: dict[str, Any] | None = None
    if args.demo_orders:
        print("\n=== Live demo order proof (sandbox) ===")
        demo = demo_order_proof(exchange, args.symbol, allocation_pct=args.allocation_pct)
        print(f"Ledger before: {json.dumps(demo['ledger_before'])}")
        for o in demo["orders"]:
            print(
                f"  {o['side'].upper()} id={o['id']} filled={o['filled']} "
                f"cost/proceeds={o['cost']} avg={o['average']} status={o['status']}"
            )
        print(f"After BUY:  {json.dumps(demo['ledger_after_buy'])}")
        print(f"After SELL: {json.dumps(demo['ledger_after_sell'])}")
        print(f"Final:      {json.dumps(demo['ledger_final'])}")
        print(demo["note"])
    else:
        print(
            "\n(demo orders skipped — pass --demo-orders with OKX demo keys; "
            "not for CI/cloud without secrets)"
        )

    payload = {
        "generated_at_utc": datetime.now(tz=UTC).isoformat(),
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "fast": args.fast,
        "slow": args.slow,
        "exchange_mode": mode,
        "lookback_hours": hours,
        "lookback_days": lookback_days,
        "target_closed_bars": target_bars,
        "snapshot": snap_rows,
        "imminent": imminent,
        "crosses": crosses,
        "regimes": regimes,
        "replay": replay,
        "demo_orders": demo,
    }
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n")
        LOGGER.info("Wrote %s", args.json_out)

    local_out = BOT_DIR / "replay_last_run.json"
    local_out.write_text(json.dumps(payload, indent=2) + "\n")
    LOGGER.info("Wrote %s", local_out)

    if args.md_out:
        args.md_out.parent.mkdir(parents=True, exist_ok=True)
        args.md_out.write_text(render_markdown_report(payload) + "\n")
        LOGGER.info("Wrote %s", args.md_out)

    return 0


if __name__ == "__main__":
    sys.exit(main())
