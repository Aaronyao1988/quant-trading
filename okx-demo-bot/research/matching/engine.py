"""Unified order matching, fees, stops, and funding for V1–V4."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from research.config import (
    ALLOCATION_PCT,
    CONTRACT_STEP,
    CT_VAL_BTC,
    FUNDING_INTERVAL_MS,
    FUNDING_PROXY_8H,
    SPOT_FEE_RATE,
    STOP_PCT,
    SWAP_FEE_RATE,
)
from research.portfolio.ledger import BacktestLedger, Intent, TradeFill


def _round_contracts(raw: float) -> float:
    """Round down to CONTRACT_STEP (0.01)."""
    if raw <= 0:
        return 0.0
    steps = math.floor(raw / CONTRACT_STEP + 1e-12)
    return round(steps * CONTRACT_STEP, 8)


class MatchingEngine:
    """Apply strategy intents + independent stop/funding rules to a ledger.

    Stop policy (pinned): OHLC touch — if bar high/low crosses the stop level,
    fill at the stop price (conservative path assumption). Stops are evaluated
    **before** strategy intents on each bar.
    """

    def __init__(
        self,
        *,
        instrument: str = "spot",
        fee_rate: float | None = None,
        allocation_pct: float = ALLOCATION_PCT,
        stop_pct: float = STOP_PCT,
        ct_val: float = CT_VAL_BTC,
        funding_df: pd.DataFrame | None = None,
        funding_proxy_8h: float = FUNDING_PROXY_8H,
        funding_source: str = "proxy",
    ) -> None:
        self.instrument = instrument
        self.fee_rate = fee_rate if fee_rate is not None else (
            SWAP_FEE_RATE if instrument == "swap" else SPOT_FEE_RATE
        )
        self.allocation_pct = allocation_pct
        self.stop_pct = stop_pct
        self.ct_val = ct_val
        self.funding_df = funding_df if funding_df is not None else pd.DataFrame(
            columns=["ts", "funding_rate"]
        )
        self.funding_proxy_8h = funding_proxy_8h
        self.funding_source = funding_source
        self._funding_idx = 0
        self._next_proxy_ts: int | None = None

    def process_bar(
        self,
        ledger: BacktestLedger,
        bar: pd.Series,
        intents: list[Intent],
    ) -> BacktestLedger:
        ts = int(bar["ts"])
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])

        # 1) Funding on open positions (swap only), using events with ts in (prev, bar_ts].
        if self.instrument == "swap" and not ledger.is_flat():
            self._apply_funding(ledger, ts, close)

        # 2) Hard stop on H/L — always first, independent of strategy.
        if not ledger.is_flat():
            stop_price = ledger.stop_hit_price(self.stop_pct)
            if stop_price is not None:
                hit = False
                if ledger.side == "long" and low <= stop_price:
                    hit = True
                elif ledger.side == "short" and high >= stop_price:
                    hit = True
                if hit:
                    self._close_position(
                        ledger,
                        ts=ts,
                        price=stop_price,
                        reason="hard_stop_2pct",
                        entry_strategy=ledger.entry_strategy or "",
                    )
                    ledger.last_processed_ts = ts
                    self._record_equity(ledger, ts, close)
                    return ledger

        # 3) Strategy intents (at most one ledger-mutating fill per bar).
        for intent in intents:
            acted = self._apply_intent(ledger, intent, ts=ts, price=close)
            if acted:
                break

        ledger.last_processed_ts = ts
        self._record_equity(ledger, ts, close)
        return ledger

    def _record_equity(self, ledger: BacktestLedger, ts: int, mark: float) -> None:
        eq = ledger.mark_equity(mark, ct_val=self.ct_val)
        ledger.equity_curve.append({"ts": ts, "equity": eq, "mark": mark})

    def _apply_funding(self, ledger: BacktestLedger, bar_ts: int, mark: float) -> None:
        if self.funding_source == "historical" and not self.funding_df.empty:
            while self._funding_idx < len(self.funding_df):
                row = self.funding_df.iloc[self._funding_idx]
                fts = int(row["ts"])
                if fts > bar_ts:
                    break
                prev = ledger.last_processed_ts or -1
                if fts > prev:
                    rate = float(row["funding_rate"])
                    self._charge_funding(ledger, bar_ts, mark, rate, reason="funding_hist")
                self._funding_idx += 1
            return

        # Proxy: apply constant every 8h while a position is open.
        if self._next_proxy_ts is None:
            # Align to next 8h boundary after position entry.
            entry = ledger.entry_ts or bar_ts
            self._next_proxy_ts = entry + FUNDING_INTERVAL_MS
        while self._next_proxy_ts is not None and self._next_proxy_ts <= bar_ts:
            self._charge_funding(
                ledger, bar_ts, mark, self.funding_proxy_8h, reason="funding_proxy"
            )
            self._next_proxy_ts += FUNDING_INTERVAL_MS

    def _charge_funding(
        self,
        ledger: BacktestLedger,
        ts: int,
        mark: float,
        rate: float,
        *,
        reason: str,
    ) -> None:
        """Positive rate: longs pay shorts (cash decreases for longs)."""
        if ledger.is_flat():
            return
        btc = abs(ledger.position_qty) * self.ct_val
        notional = btc * mark
        # Long pays +rate; short receives +rate (cash += -side_sign * rate * notional)
        side_sign = 1.0 if ledger.side == "long" else -1.0
        payment = side_sign * rate * notional
        ledger.cash -= payment
        ledger.cumulative_funding += payment
        # Record as zero-qty fill for audit trail.
        ledger.trades.append(
            TradeFill(
                ts=ts,
                action="funding",
                side=ledger.side,
                price=mark,
                qty=0.0,
                notional=notional,
                fee=0.0,
                funding=payment,
                entry_strategy=ledger.entry_strategy or "",
                reason=reason,
                cash_after=ledger.cash,
                equity_after=ledger.mark_equity(mark, ct_val=self.ct_val),
            )
        )

    def _apply_intent(
        self,
        ledger: BacktestLedger,
        intent: Intent,
        *,
        ts: int,
        price: float,
    ) -> bool:
        if intent.action == "enter_long":
            if not ledger.is_flat():
                return False
            return self._open_long(ledger, ts, price, intent)
        if intent.action == "exit_long":
            if ledger.side != "long":
                return False
            self._close_position(
                ledger,
                ts=ts,
                price=price,
                reason=intent.reason,
                entry_strategy=intent.entry_strategy or ledger.entry_strategy or "",
            )
            return True
        if intent.action == "enter_short":
            if self.instrument != "swap":
                return False
            if not ledger.is_flat():
                return False
            return self._open_short(ledger, ts, price, intent)
        if intent.action == "exit_short":
            if ledger.side != "short":
                return False
            self._close_position(
                ledger,
                ts=ts,
                price=price,
                reason=intent.reason,
                entry_strategy=intent.entry_strategy or ledger.entry_strategy or "",
            )
            return True
        return False

    def _open_long(
        self, ledger: BacktestLedger, ts: int, price: float, intent: Intent
    ) -> bool:
        spend = ledger.cash * self.allocation_pct
        if spend <= 0 or price <= 0:
            return False

        if self.instrument == "spot":
            gross_btc = spend / price
            fee = spend * self.fee_rate
            # Fee comes from cash; BTC bought with (spend - fee) conceptually,
            # but we model fee on notional and reduce cash by spend+fee? Spec:
            # fee per side on notional. Use: buy btc = spend/price, cash -= spend + fee
            # with fee = spend * fee_rate, capped so cash stays non-negative.
            fee = spend * self.fee_rate
            total_debit = spend + fee
            if total_debit > ledger.cash:
                spend = ledger.cash / (1.0 + self.fee_rate)
                fee = spend * self.fee_rate
                total_debit = spend + fee
            btc = spend / price
            if btc <= 0:
                return False
            ledger.cash -= total_debit
            ledger.position_qty = btc
            ledger.side = "long"
            ledger.entry_price = price
            ledger.entry_ts = ts
            ledger.entry_strategy = intent.entry_strategy or "sma"
            ledger.cumulative_fees += fee
            self._log_fill(
                ledger, ts, "enter_long", "long", price, btc, spend, fee, 0.0, intent
            )
            return True

        # Swap: size in contracts, 1x notional ≈ allocation of cash.
        target_btc = spend / price
        raw_contracts = target_btc / self.ct_val
        contracts = _round_contracts(raw_contracts)
        ledger.intended_notional_log.append(
            {
                "ts": ts,
                "intended_usdt": spend,
                "raw_contracts": raw_contracts,
                "filled_contracts": contracts,
                "side": "long",
            }
        )
        if contracts <= 0:
            return False
        notional = contracts * self.ct_val * price
        fee = notional * self.fee_rate
        if fee > ledger.cash:
            return False
        ledger.cash -= fee
        ledger.position_qty = contracts
        ledger.side = "long"
        ledger.entry_price = price
        ledger.entry_ts = ts
        ledger.entry_strategy = intent.entry_strategy or "macro"
        ledger.cumulative_fees += fee
        self._next_proxy_ts = ts + FUNDING_INTERVAL_MS
        self._log_fill(
            ledger, ts, "enter_long", "long", price, contracts, notional, fee, 0.0, intent
        )
        return True

    def _open_short(
        self, ledger: BacktestLedger, ts: int, price: float, intent: Intent
    ) -> bool:
        spend = ledger.cash * self.allocation_pct
        if spend <= 0 or price <= 0:
            return False
        target_btc = spend / price
        raw_contracts = target_btc / self.ct_val
        contracts = _round_contracts(raw_contracts)
        ledger.intended_notional_log.append(
            {
                "ts": ts,
                "intended_usdt": spend,
                "raw_contracts": raw_contracts,
                "filled_contracts": contracts,
                "side": "short",
            }
        )
        if contracts <= 0:
            return False
        notional = contracts * self.ct_val * price
        fee = notional * self.fee_rate
        if fee > ledger.cash:
            return False
        ledger.cash -= fee
        ledger.position_qty = contracts
        ledger.side = "short"
        ledger.entry_price = price
        ledger.entry_ts = ts
        ledger.entry_strategy = intent.entry_strategy or "macro"
        ledger.cumulative_fees += fee
        self._next_proxy_ts = ts + FUNDING_INTERVAL_MS
        self._log_fill(
            ledger, ts, "enter_short", "short", price, contracts, notional, fee, 0.0, intent
        )
        return True

    def _close_position(
        self,
        ledger: BacktestLedger,
        *,
        ts: int,
        price: float,
        reason: str,
        entry_strategy: str,
    ) -> None:
        if ledger.is_flat() or ledger.entry_price is None:
            return
        side = ledger.side
        qty = ledger.position_qty
        entry = float(ledger.entry_price)

        if self.instrument == "spot":
            notional = qty * price
            fee = notional * self.fee_rate
            proceeds = notional - fee
            # Cost basis approximates entry * qty (fees already paid on entry).
            ledger.realized_pnl += (price - entry) * qty - fee
            ledger.cash += proceeds
            ledger.cumulative_fees += fee
            self._log_fill_raw(
                ledger,
                ts=ts,
                action="exit_long",
                side="flat",
                price=price,
                qty=qty,
                notional=notional,
                fee=fee,
                funding=0.0,
                entry_strategy=entry_strategy,
                reason=reason,
            )
        else:
            notional = qty * self.ct_val * price
            fee = notional * self.fee_rate
            direction = 1.0 if side == "long" else -1.0
            btc = qty * self.ct_val
            pnl = direction * btc * (price - entry)
            ledger.realized_pnl += pnl - fee
            ledger.cash += pnl - fee
            ledger.cumulative_fees += fee
            action = "exit_long" if side == "long" else "exit_short"
            self._log_fill_raw(
                ledger,
                ts=ts,
                action=action,
                side="flat",
                price=price,
                qty=qty,
                notional=notional,
                fee=fee,
                funding=0.0,
                entry_strategy=entry_strategy,
                reason=reason,
            )

        ledger.position_qty = 0.0
        ledger.side = "flat"
        ledger.entry_price = None
        ledger.entry_ts = None
        ledger.entry_strategy = ""
        self._next_proxy_ts = None

    def _log_fill(
        self,
        ledger: BacktestLedger,
        ts: int,
        action: str,
        side: str,
        price: float,
        qty: float,
        notional: float,
        fee: float,
        funding: float,
        intent: Intent,
    ) -> None:
        self._log_fill_raw(
            ledger,
            ts=ts,
            action=action,
            side=side,  # type: ignore[arg-type]
            price=price,
            qty=qty,
            notional=notional,
            fee=fee,
            funding=funding,
            entry_strategy=intent.entry_strategy or "",
            reason=intent.reason,
        )

    def _log_fill_raw(
        self,
        ledger: BacktestLedger,
        *,
        ts: int,
        action: str,
        side: Any,
        price: float,
        qty: float,
        notional: float,
        fee: float,
        funding: float,
        entry_strategy: str,
        reason: str,
    ) -> None:
        ledger.trades.append(
            TradeFill(
                ts=ts,
                action=action,
                side=side,
                price=price,
                qty=qty,
                notional=notional,
                fee=fee,
                funding=funding,
                entry_strategy=entry_strategy,
                reason=reason,
                cash_after=ledger.cash,
                equity_after=ledger.mark_equity(price, ct_val=self.ct_val),
            )
        )
