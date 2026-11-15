"""Experiment portfolio schema (separate from live virtual_ledger_200.json)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Side = Literal["flat", "long", "short"]
EntryStrategy = Literal["sma", "zscore", "macro", ""]


@dataclass
class Intent:
    """Strategy output consumed by the matching engine."""

    action: Literal["enter_long", "exit_long", "enter_short", "exit_short", "flat"]
    reason: str
    entry_strategy: EntryStrategy = ""
    # Optional explicit stop override; engine still enforces STOP_PCT by default.
    stop_pct: float | None = None


@dataclass
class TradeFill:
    ts: int
    action: str
    side: Side
    price: float
    qty: float  # BTC for spot; contracts for swap
    notional: float
    fee: float
    funding: float
    entry_strategy: str
    reason: str
    cash_after: float
    equity_after: float


@dataclass
class BacktestLedger:
    """Offline experiment ledger with position metadata required by V2–V4."""

    initial_usdt: float
    cash: float
    # Spot: BTC amount. Swap: number of contracts (each CT_VAL_BTC BTC).
    position_qty: float = 0.0
    side: Side = "flat"
    entry_price: float | None = None
    entry_ts: int | None = None
    entry_strategy: EntryStrategy = ""
    last_processed_ts: int | None = None
    cumulative_fees: float = 0.0
    cumulative_funding: float = 0.0
    realized_pnl: float = 0.0
    trades: list[TradeFill] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    instrument: Literal["spot", "swap"] = "spot"
    intended_notional_log: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def blank(cls, initial_usdt: float, *, instrument: Literal["spot", "swap"] = "spot") -> BacktestLedger:
        return cls(initial_usdt=initial_usdt, cash=initial_usdt, instrument=instrument)

    def is_flat(self) -> bool:
        return self.side == "flat" or abs(self.position_qty) < 1e-12

    def mark_equity(self, mark_price: float, *, ct_val: float = 0.01) -> float:
        if self.is_flat():
            return self.cash
        if self.instrument == "spot":
            return self.cash + self.position_qty * mark_price
        # 1x swap: cash holds margin residual; unrealized on contracts.
        direction = 1.0 if self.side == "long" else -1.0
        entry = float(self.entry_price or mark_price)
        btc = abs(self.position_qty) * ct_val
        unrealized = direction * btc * (mark_price - entry)
        return self.cash + unrealized

    def stop_hit_price(self, stop_pct: float) -> float | None:
        if self.is_flat() or self.entry_price is None:
            return None
        if self.side == "long":
            return float(self.entry_price) * (1.0 - stop_pct)
        if self.side == "short":
            return float(self.entry_price) * (1.0 + stop_pct)
        return None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["trades"] = [asdict(t) for t in self.trades]
        return d
