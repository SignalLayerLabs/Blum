from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from math import sqrt
from typing import Sequence

from app.services.market_clock import utc_naive


@dataclass(frozen=True)
class ExecutionOrderRequest:
    order_key: str
    ticker: str
    side: str
    order_type: str
    decision_timestamp: datetime
    theoretical_price: float
    quantity: float
    limit_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    max_participation_rate: float = 0.05
    commission_bps: float = 0.0
    latency_bars: int = 0
    currency: str = "USD"
    account_currency: str = "USD"
    fx_rate: float | None = 1.0
    fx_spread_bps: float = 0.0
    liquidity_score: float = 100.0
    liquidity_basis: str = "reported_volume"
    quote_capacity_units: float | None = None
    allowed_sessions: tuple[str, ...] = ("regular",)
    borrow_rate_bps: float | None = None
    expected_holding_days: float = 0.0
    stop_activated_at: datetime | None = None
    last_observation_at: datetime | None = None


@dataclass(frozen=True)
class ExecutionMarketBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    spread_bps: float
    volatility_bps: float
    session: str = "regular"
    is_halted: bool = False
    available_at: datetime | None = None


@dataclass(frozen=True)
class ExecutionFill:
    timestamp: datetime
    quantity: float
    reference_price: float
    executed_price: float
    spread_bps: float
    slippage_bps: float
    commission_bps: float
    participation_rate: float


@dataclass(frozen=True)
class ExecutionCostBreakdown:
    spread_cost: float = 0.0
    slippage_cost: float = 0.0
    commission_cost: float = 0.0
    fx_cost: float = 0.0
    borrow_cost: float = 0.0
    gap_cost: float = 0.0

    @property
    def total_cost(self) -> float:
        return round(self.spread_cost + self.slippage_cost + self.commission_cost + self.fx_cost + self.borrow_cost + self.gap_cost, 8)


@dataclass(frozen=True)
class ExecutionDecision:
    status: str
    reason: str
    theoretical_price: float
    average_fill_price: float | None
    filled_quantity: float
    remaining_quantity: float
    fills: tuple[ExecutionFill, ...]
    costs: ExecutionCostBreakdown
    stop_activated_at: datetime | None = None
    last_observation_at: datetime | None = None
    latency_bars_remaining: int = 0


class RealisticExecutionEngine:
    def evaluate(
        self, request: ExecutionOrderRequest, bars: Sequence[ExecutionMarketBar]
    ) -> ExecutionDecision:
        request = replace(
            request,
            decision_timestamp=utc_naive(request.decision_timestamp),
            last_observation_at=(
                utc_naive(request.last_observation_at)
                if request.last_observation_at
                else None
            ),
            stop_activated_at=(
                utc_naive(request.stop_activated_at)
                if request.stop_activated_at
                else None
            ),
        )
        bars = [replace(bar, timestamp=utc_naive(bar.timestamp)) for bar in bars]
        if request.quantity <= 0 or request.theoretical_price <= 0:
            return self._empty(request, "REJECTED", "INVALID_ORDER")
        if request.currency != request.account_currency and (
            request.fx_rate is None or request.fx_rate <= 0
        ):
            return self._empty(request, "REJECTED", "FX_RATE_UNAVAILABLE")
        if (
            request.side.upper() in {"SHORT", "SELL_SHORT"}
            and request.borrow_rate_bps is None
        ):
            return self._empty(request, "REJECTED", "BORROW_RATE_UNAVAILABLE")
        later = [
            bar
            for bar in sorted(bars, key=lambda item: item.timestamp)
            if bar.timestamp
            > max(
                request.decision_timestamp,
                request.last_observation_at or request.decision_timestamp,
            )
        ]
        latency = max(0, int(request.latency_bars))
        activation = request.stop_activated_at
        last_observation = request.last_observation_at
        allowed_sessions = {
            str(session).lower() for session in request.allowed_sessions
        }
        eligible = [
            bar
            for bar in later
            if not bar.is_halted and str(bar.session).lower() in allowed_sessions
        ]
        if not eligible:
            reason = (
                "MARKET_HALTED"
                if later and all(bar.is_halted for bar in later)
                else "NO_ALLOWED_SESSION_BAR" if later else "NO_LATER_EXECUTABLE_BAR"
            )
            return replace(
                self._empty(request, "SUBMITTED", reason),
                stop_activated_at=activation,
                last_observation_at=max(
                    (bar.timestamp for bar in later), default=last_observation
                ),
                latency_bars_remaining=latency,
            )

        remaining = float(request.quantity)
        fills: list[ExecutionFill] = []
        for market_bar in eligible:
            if remaining <= 1e-9:
                break
            last_observation = market_bar.timestamp
            if latency:
                latency -= 1
                continue
            if request.order_type.upper() == "STOP_LIMIT":
                if activation is None:
                    if not self._is_triggered(request, market_bar):
                        continue
                    activation = market_bar.timestamp
                    # OHLC cannot establish whether the limit crossed after activation.
                    # Only an already-triggered open establishes ordering on this bar.
                    opens_triggered = (
                        market_bar.open >= float(request.stop_price)
                        if request.side.upper() == "BUY"
                        else market_bar.open <= float(request.stop_price)
                    )
                    if not opens_triggered:
                        continue
                if request.limit_price is None or not self._is_triggered(
                    replace(request, order_type="LIMIT"), market_bar
                ):
                    continue
            elif not self._is_triggered(request, market_bar):
                continue
            liquidity_capacity = max(
                0.05, min(1.0, float(request.liquidity_score) / 100.0)
            )
            reported_volume = max(0.0, float(market_bar.volume))
            capacity_base = reported_volume
            if (
                request.liquidity_basis == "otc_quote_capacity"
                and reported_volume <= 0
                and float(request.quote_capacity_units or 0.0) > 0
            ):
                capacity_base = float(request.quote_capacity_units or 0.0)
            capacity = (
                capacity_base
                * max(0.0, min(0.25, float(request.max_participation_rate)))
                * liquidity_capacity
            )
            quantity = min(remaining, capacity)
            if quantity <= 0:
                continue
            participation = quantity / max(1.0, capacity_base)
            slippage_bps = self.dynamic_slippage_bps(
                market_bar.volatility_bps, participation, request.liquidity_score
            )
            reference = self._reference_price(request, market_bar)
            adverse_bps = max(0.0, float(market_bar.spread_bps)) / 2.0 + slippage_bps
            direction = 1.0 if request.side.upper() == "BUY" else -1.0
            executed = reference * (1.0 + direction * adverse_bps / 10_000.0)
            if (
                request.order_type.upper() in {"LIMIT", "STOP_LIMIT"}
                and request.limit_price is not None
            ):
                executed = (
                    min(executed, request.limit_price)
                    if direction > 0
                    else max(executed, request.limit_price)
                )
            fills.append(
                ExecutionFill(
                    timestamp=market_bar.timestamp,
                    quantity=round(quantity, 8),
                    reference_price=round(reference, 8),
                    executed_price=round(executed, 8),
                    spread_bps=round(float(market_bar.spread_bps), 8),
                    slippage_bps=round(slippage_bps, 8),
                    commission_bps=round(max(0.0, request.commission_bps), 8),
                    participation_rate=round(participation, 8),
                )
            )
            remaining -= quantity

        if not fills:
            return replace(
                self._empty(request, "SUBMITTED", "ORDER_NOT_FILLED"),
                stop_activated_at=activation,
                last_observation_at=last_observation,
                latency_bars_remaining=latency,
            )
        filled = sum(fill.quantity for fill in fills)
        average = sum(fill.executed_price * fill.quantity for fill in fills) / filled
        costs = self._costs(fills, request)
        status = "FILLED" if remaining <= 1e-9 else "PARTIALLY_FILLED"
        return ExecutionDecision(
            status,
            status,
            request.theoretical_price,
            round(average, 8),
            round(filled, 8),
            round(max(0.0, remaining), 8),
            tuple(fills),
            costs,
            activation,
            last_observation,
            latency,
        )

    def evaluate_exit(
        self,
        *,
        side: str,
        quantity: float,
        entry_price: float,
        stop_price: float,
        target_price: float,
        decision_timestamp: datetime,
        bars: Sequence[ExecutionMarketBar],
        commission_bps: float = 0.0,
    ) -> ExecutionDecision:
        for market_bar in sorted(bars, key=lambda item: item.timestamp):
            if market_bar.timestamp <= decision_timestamp or market_bar.is_halted:
                continue
            is_long = side.upper() == "LONG"
            stop_hit = market_bar.low <= stop_price if is_long else market_bar.high >= stop_price
            target_hit = market_bar.high >= target_price if is_long else market_bar.low <= target_price
            if not stop_hit and not target_hit:
                continue
            reason = "STOP_HIT" if stop_hit else "TARGET_HIT"
            trigger = stop_price if stop_hit else target_price
            if stop_hit and ((is_long and market_bar.open < stop_price) or (not is_long and market_bar.open > stop_price)):
                trigger = market_bar.open
            exit_side = "SELL" if is_long else "BUY"
            request = ExecutionOrderRequest(
                order_key=f"exit:{decision_timestamp.isoformat()}",
                ticker="position",
                side=exit_side,
                order_type="MARKET",
                decision_timestamp=decision_timestamp,
                theoretical_price=trigger,
                quantity=quantity,
                max_participation_rate=1.0,
                commission_bps=commission_bps,
            )
            reference = float(trigger)
            participation = min(1.0, quantity / max(1.0, market_bar.volume))
            slippage = self.dynamic_slippage_bps(market_bar.volatility_bps, participation)
            adverse = market_bar.spread_bps / 2.0 + slippage
            direction = 1.0 if exit_side == "BUY" else -1.0
            executed = reference * (1.0 + direction * adverse / 10_000.0)
            fill = ExecutionFill(market_bar.timestamp, quantity, reference, executed, market_bar.spread_bps, slippage, commission_bps, participation)
            costs = self._costs([fill], request)
            gap_cost = abs(float(stop_price) - float(trigger)) * float(quantity) if stop_hit and trigger != stop_price else 0.0
            costs = ExecutionCostBreakdown(
                spread_cost=costs.spread_cost,
                slippage_cost=costs.slippage_cost,
                commission_cost=costs.commission_cost,
                fx_cost=costs.fx_cost,
                borrow_cost=costs.borrow_cost,
                gap_cost=round(gap_cost, 8),
            )
            return ExecutionDecision("CLOSED", reason, entry_price, round(executed, 8), quantity, 0.0, (fill,), costs)
        request = ExecutionOrderRequest("exit", "position", "SELL", "MARKET", decision_timestamp, entry_price, quantity)
        return self._empty(request, "OPEN", "NO_EXIT_TRIGGER")

    @staticmethod
    def dynamic_slippage_bps(volatility_bps: float, participation_rate: float, liquidity_score: float = 100.0) -> float:
        participation = max(0.0, min(1.0, float(participation_rate)))
        liquidity_penalty = max(0.0, 100.0 - max(0.0, min(100.0, float(liquidity_score)))) * 0.04
        return round(max(0.25, max(0.0, float(volatility_bps)) * sqrt(participation) * 0.12 + participation * 8.0 + liquidity_penalty), 8)

    @staticmethod
    def _is_triggered(request: ExecutionOrderRequest, market_bar: ExecutionMarketBar) -> bool:
        order_type = request.order_type.upper()
        if order_type == "MARKET":
            return True
        if order_type == "LIMIT" and request.limit_price is not None:
            return market_bar.low <= request.limit_price if request.side.upper() == "BUY" else market_bar.high >= request.limit_price
        if order_type in {"STOP", "STOP_LIMIT"} and request.stop_price is not None:
            return market_bar.high >= request.stop_price if request.side.upper() == "BUY" else market_bar.low <= request.stop_price
        return False

    @staticmethod
    def _reference_price(
        request: ExecutionOrderRequest, market_bar: ExecutionMarketBar
    ) -> float:
        order_type = request.order_type.upper()
        if order_type == "MARKET":
            return float(market_bar.open)
        if order_type in {"LIMIT", "STOP_LIMIT"} and request.limit_price is not None:
            if request.side.upper() == "BUY":
                return min(float(request.limit_price), float(market_bar.open))
            return max(float(request.limit_price), float(market_bar.open))
        if order_type == "STOP" and request.stop_price is not None:
            return (
                max(float(request.stop_price), float(market_bar.open))
                if request.side.upper() == "BUY"
                else min(float(request.stop_price), float(market_bar.open))
            )
        return float(market_bar.open)

    @staticmethod
    def _costs(fills: Sequence[ExecutionFill], request: ExecutionOrderRequest) -> ExecutionCostBreakdown:
        spread = slippage = commission = fx_cost = borrow_cost = 0.0
        fx_rate = float(request.fx_rate or 1.0)
        for fill in fills:
            notional = abs(fill.executed_price * fill.quantity) / fx_rate
            spread += notional * fill.spread_bps / 20_000.0
            slippage += notional * fill.slippage_bps / 10_000.0
            commission += notional * fill.commission_bps / 10_000.0
            if request.currency != request.account_currency:
                fx_cost += notional * max(0.0, request.fx_spread_bps) / 10_000.0
            if request.side.upper() in {"SHORT", "SELL_SHORT"}:
                borrow_cost += notional * max(0.0, float(request.borrow_rate_bps or 0.0)) / 10_000.0 * max(0.0, request.expected_holding_days) / 365.0
        return ExecutionCostBreakdown(
            spread_cost=round(spread, 8),
            slippage_cost=round(slippage, 8),
            commission_cost=round(commission, 8),
            fx_cost=round(fx_cost, 8),
            borrow_cost=round(borrow_cost, 8),
        )

    @staticmethod
    def _empty(request: ExecutionOrderRequest, status: str, reason: str) -> ExecutionDecision:
        return ExecutionDecision(status, reason, request.theoretical_price, None, 0.0, max(0.0, request.quantity), (), ExecutionCostBreakdown())
