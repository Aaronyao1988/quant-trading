"""Run V1–V4 on the frozen 90d cache and write the benchmark report."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

# Allow `python -m research.run_benchmark` from okx-demo-bot/
BOT_DIR = Path(__file__).resolve().parent.parent
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

from research.config import (  # noqa: E402
    ALLOCATION_PCT,
    DATA_DIR,
    INITIAL_USDT,
    LOOKBACK_DAYS,
    REPORTS_DIR,
    SPOT_FEE_RATE,
    STOP_PCT,
    SWAP_FEE_RATE,
)
from research.data.cache import ensure_cached_dataset  # noqa: E402
from research.matching.engine import MatchingEngine  # noqa: E402
from research.metrics import regime_breakdown, summarize  # noqa: E402
from research.portfolio.ledger import BacktestLedger  # noqa: E402
from research.strategy import STRATEGIES, prepare_features  # noqa: E402

LOGGER = logging.getLogger("research.benchmark")


def _trading_window(bars: pd.DataFrame, lookback_days: int = LOOKBACK_DAYS) -> pd.DataFrame:
    if bars.empty:
        return bars
    end_ts = int(bars["ts"].iloc[-1])
    start_ts = end_ts - lookback_days * 86_400_000
    return bars[bars["ts"] >= start_ts].reset_index(drop=True)


def run_variant(
    name: str,
    features: pd.DataFrame,
    *,
    funding: pd.DataFrame,
    funding_source: str,
) -> tuple[BacktestLedger, dict[str, Any]]:
    cls = STRATEGIES[name]
    strategy = cls()
    instrument = "swap" if name == "V4" else "spot"
    ledger = BacktestLedger.blank(INITIAL_USDT, instrument=instrument)
    engine = MatchingEngine(
        instrument=instrument,
        fee_rate=SWAP_FEE_RATE if instrument == "swap" else SPOT_FEE_RATE,
        allocation_pct=ALLOCATION_PCT,
        stop_pct=STOP_PCT,
        funding_df=funding if instrument == "swap" else None,
        funding_source=funding_source if instrument == "swap" else "n/a",
    )

    # Need i>=1 for cross detection; warmup rows may still produce NaN indicators.
    for i in range(1, len(features)):
        bar = features.iloc[i]
        intents = strategy.on_bar(i, features, ledger)
        engine.process_bar(ledger, bar, intents)

    stats = summarize(ledger, label=name)
    stats["regime_segments"] = regime_breakdown(features, ledger)
    stats["instrument"] = instrument
    return ledger, stats


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"{v:.2f}%"


def render_report(
    results: dict[str, dict[str, Any]],
    *,
    meta: dict[str, Any],
    bars: int,
    daily_bars: int,
) -> str:
    lines: list[str] = []
    lines.append("# V1–V4 90-Day BTC/USDT Regime Benchmark")
    lines.append("")
    lines.append(f"**Generated (UTC):** {datetime.now(tz=timezone.utc).isoformat()}")
    lines.append(f"**Cache end:** {meta.get('end_utc', 'n/a')}")
    lines.append(
        f"**Bars:** {bars} × 15m trading window (~{LOOKBACK_DAYS}d); "
        f"{daily_bars} × 1d (warmup included in cache)."
    )
    lines.append(f"**Initial capital:** ${INITIAL_USDT:.2f} · **Allocation:** {ALLOCATION_PCT:.0%} per entry")
    lines.append(
        f"**Fees:** spot {SPOT_FEE_RATE*100:.2f}%/side · swap {SWAP_FEE_RATE*100:.2f}%/side"
    )
    lines.append(f"**Stop policy:** OHLC touch at {STOP_PCT*100:.0f}% vs entry; fill at stop price")
    funding_src = meta.get("funding_source", "unknown")
    if funding_src == "historical":
        lines.append(
            f"**Funding (V4):** historical OKX funding-rate series "
            f"({meta.get('funding_rows', 0)} snapshots)."
        )
    else:
        lines.append(
            "**Funding (V4):** historical series unavailable or empty — "
            "**ASSUMPTION:** constant proxy **+0.01% per 8h** "
            "(positive rate ⇒ longs pay shorts), flagged as `funding_proxy`."
        )
    lines.append("")
    lines.append("## Core comparison")
    lines.append("")
    lines.append(
        "| Variant | Trades | Long WR | Short WR | Fees | Funding | Max DD | Final NAV | Total return |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name in ("V1", "V2", "V3", "V4"):
        s = results[name]
        lines.append(
            "| {v} | {n} | {lw} | {sw} | ${fees:.4f} | ${fund:.4f} | {dd} | ${nav:.2f} | {ret} |".format(
                v=s["variant"],
                n=s["trades"],
                lw=_fmt_pct(s["long_win_rate_pct"]),
                sw=_fmt_pct(s["short_win_rate_pct"]),
                fees=s["cumulative_fees"],
                fund=s["cumulative_funding"],
                dd=_fmt_pct(s["max_drawdown_pct"]),
                nav=s["final_nav"],
                ret=_fmt_pct(s["total_return_pct"]),
            )
        )
    lines.append("")
    lines.append("## Strategy notes")
    lines.append("")
    lines.append("- **V1:** SMA(10)/SMA(30) golden/death, spot, 0.10%/side.")
    lines.append(
        "- **V2:** ADX(14)>25 → SMA trend; ADX<20 → Z(20) MR (entry Z<-2, exit Z≥0); "
        "[20,25] no new entries. Exits always follow `entry_strategy` (orphan policy)."
    )
    lines.append(
        "- **V3:** V2 + new longs only if close > prior-day daily SMA30; exits unrestricted."
    )
    lines.append(
        "- **V4:** 1x BTC-USDT-SWAP; long regime above daily SMA30 / short below; "
        "15m golden/death; contract step 0.01 (=0.01 BTC); 2% H/L stop."
    )
    lines.append("")
    lines.append("## Per-variant detail")
    lines.append("")
    for name in ("V1", "V2", "V3", "V4"):
        s = results[name]
        lines.append(f"### {name}")
        lines.append("")
        lines.append(f"- Instrument: `{s['instrument']}`")
        lines.append(f"- Round-trip trades: **{s['trades']}** "
                     f"(long {s['long_trades']}, short {s['short_trades']})")
        lines.append(f"- Overall win rate: {_fmt_pct(s['overall_win_rate_pct'])}")
        lines.append(f"- Cumulative fees: ${s['cumulative_fees']:.4f}")
        lines.append(f"- Cumulative funding paid(+)/received pattern: ${s['cumulative_funding']:.4f}")
        lines.append(f"- Max drawdown: {_fmt_pct(s['max_drawdown_pct'])}")
        lines.append(f"- Final NAV: ${s['final_nav']:.2f} ({_fmt_pct(s['total_return_pct'])})")
        lines.append("")
        lines.append("Regime breakdown (contiguous ADX runs on 15m, aggregated):")
        lines.append("")
        lines.append("| Regime | Bars | Runs | Sum segment return | Avg segment return |")
        lines.append("|---|---:|---:|---:|---:|")
        for seg in s.get("regime_segments") or []:
            lines.append(
                f"| {seg['regime']} | {seg['bars']} | {seg['runs']} | "
                f"{_fmt_pct(seg['sum_segment_return_pct'])} | "
                f"{_fmt_pct(seg['avg_segment_return_pct'])} |"
            )
        lines.append("")
        # Trade blotter (compact)
        trips = s.get("trips") or []
        lines.append(f"Trades (n={len(trips)}):")
        lines.append("")
        if not trips:
            lines.append("_No round-trips._")
        else:
            lines.append("| # | Side | Entry strategy | Return | Exit reason |")
            lines.append("|---:|---|---|---:|---|")
            for i, t in enumerate(trips, 1):
                lines.append(
                    f"| {i} | {t['side']} | {t['entry_strategy']} | "
                    f"{t['return_pct']:+.2f}% | {t['exit_reason']} |"
                )
        lines.append("")

    lines.append("## Reproducibility")
    lines.append("")
    lines.append("```bash")
    lines.append("cd okx-demo-bot")
    lines.append("python -m research.run_benchmark          # uses data/ cache if present")
    lines.append("python -m research.run_benchmark --refresh  # re-fetch public OHLCV")
    lines.append("python -m pytest tests/ -q")
    lines.append("```")
    lines.append("")
    lines.append(
        "Caches under `okx-demo-bot/data/` are gitignored. Commit this report; "
        "re-fetch to regenerate numbers on a new freeze date."
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="V1–V4 90d regime benchmark")
    parser.add_argument("--refresh", action="store_true", help="Force re-fetch OHLCV cache")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--report", type=Path, default=REPORTS_DIR / "v1-v4-90d-benchmark.md")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    bars_15m, daily, funding, meta = ensure_cached_dataset(
        data_dir=args.data_dir, force_refresh=args.refresh
    )
    features_full = prepare_features(bars_15m, daily)
    # Restrict evaluation to the last LOOKBACK_DAYS while keeping indicator warmup
    # from earlier rows: compute features on full cache, then slice trading window.
    window = _trading_window(features_full)
    # Re-index so strategies iterate the window, but crosses at the boundary used
    # the previous bar from features_full — splice one warmup bar.
    if not window.empty:
        first_ts = int(window.iloc[0]["ts"])
        prior = features_full[features_full["ts"] < first_ts]
        if not prior.empty:
            window = pd.concat([prior.iloc[[-1]], window], ignore_index=True)

    funding_source = meta.get("funding_source", "proxy")
    results: dict[str, dict[str, Any]] = {}
    ledgers: dict[str, BacktestLedger] = {}
    for name in ("V1", "V2", "V3", "V4"):
        LOGGER.info("Running %s …", name)
        ledger, stats = run_variant(
            name, window, funding=funding, funding_source=funding_source
        )
        results[name] = stats
        ledgers[name] = ledger
        LOGGER.info(
            "%s done: trades=%s NAV=$%.2f return=%+.2f%%",
            name,
            stats["trades"],
            stats["final_nav"],
            stats["total_return_pct"],
        )

    report = render_report(
        results, meta=meta, bars=len(window), daily_bars=len(daily)
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report)
    LOGGER.info("Wrote report %s", args.report)

    summary_json = args.report.with_suffix(".json")
    payload = {k: {kk: vv for kk, vv in v.items() if kk != "trips"} | {
        "trips": v.get("trips", [])
    } for k, v in results.items()}
    summary_json.write_text(json.dumps({"meta": meta, "results": payload}, indent=2) + "\n")
    # Print comparison table only (full blotter is in the markdown report).
    for line in report.splitlines():
        print(line)
        if line.startswith("## Strategy notes"):
            break
    print(f"\nFull report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
