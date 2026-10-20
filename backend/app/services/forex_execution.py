from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from math import floor, isfinite

from app.services.forex_broker import ForexBrokerProfile
from app.services.forex_contracts import ForexDirection, ForexOrderRequest, ForexQuote, pair_config


@dataclass(frozen=True)
class ForexExecutionResult:
    status: str
    theoretical_price: float
    bid: float
    ask: float
    requested_price: float
    fill_price: float | None
    filled_quantity_lots: float
    slippage_pips: float
    spread_pips: float
    spread_source: str
    spread_cost: float | None
    slippage_cost: float | None
    commission: float
    swap: float
    total_cost: float | None
    margin_required: float
    execution_model_version: str
    rejection_reason: str | None = None
    state_history: tuple[str, ...] = ()
    execution_latency_ms: int = 0
    account_fx_rate: float | None = None
    fx_rate_source: str | None = None
    execution_assumptions: dict = field(default_factory=dict)


class BlumForexExecutionSimulator:
    def submit(self, order: ForexOrderRequest, quote: ForexQuote, broker: ForexBrokerProfile, *, now: datetime) -> ForexExecutionResult:
        return self._execute(order, quote, broker, closing=False, now=now)

    def close(self, order: ForexOrderRequest, quote: ForexQuote, broker: ForexBrokerProfile, *, reason: str, now: datetime) -> ForexExecutionResult:
        return self._execute(order, quote, broker, closing=True, reason=reason, now=now)

    def _execute(self, order: ForexOrderRequest, quote: ForexQuote, broker: ForexBrokerProfile, *, closing: bool, now: datetime, reason: str = "") -> ForexExecutionResult:
        config = pair_config(order.pair)
        if quote.timestamp > now:
            return self._rejected(order, quote, broker, "FUTURE_QUOTE")
        if (now-quote.timestamp).total_seconds() > 180:
            return self._rejected(order, quote, broker, "STALE_QUOTE")
        if order.side not in {ForexDirection.LONG,ForexDirection.SHORT} or any(
            isinstance(value,bool) or not isinstance(value,(int,float)) or not isfinite(value) or value<=0
            for value in (order.quantity_lots,order.theoretical_price)
        ):
            return self._rejected(order, quote, broker, "INVALID_ORDER")
        if order.order_type not in broker.supported_order_types:
            return self._rejected(order, quote, broker, "UNSUPPORTED_ORDER_TYPE")
        quantity = floor(order.quantity_lots / broker.lot_step + 1e-9) * broker.lot_step
        if quantity < broker.minimum_lot:
            return self._rejected(order, quote, broker, "MINIMUM_LOT")
        is_long_fill = (order.side == ForexDirection.LONG and not closing) or (order.side == ForexDirection.SHORT and closing)
        market_side = quote.ask if is_long_fill else quote.bid
        if not closing and order.order_type in {"LIMIT", "STOP_LIMIT"} and order.limit_price is not None:
            limit_triggered = quote.ask <= order.limit_price if order.side == ForexDirection.LONG else quote.bid >= order.limit_price
            if not limit_triggered:
                return self._pending(order, quote, broker)
        if not closing and order.order_type in {"STOP", "STOP_LIMIT"} and order.stop_price is not None:
            stop_triggered = quote.ask >= order.stop_price if order.side == ForexDirection.LONG else quote.bid <= order.stop_price
            if not stop_triggered:
                return self._pending(order, quote, broker)
        slippage_direction = 1 if is_long_fill else -1
        slippage = self._slippage_pips(order, broker)
        fill = market_side + slippage_direction * slippage * config.pip_size
        if not closing and order.order_type in {"LIMIT", "STOP_LIMIT"} and order.limit_price is not None:
            if (is_long_fill and fill > order.limit_price) or (not is_long_fill and fill < order.limit_price):
                return self._pending(order, quote, broker)
        if closing and reason == "STOP_HIT" and order.stop_price is not None:
            fill = min(fill, order.stop_price) if order.side == ForexDirection.LONG else max(fill, order.stop_price)
        spread_pips = (quote.ask - quote.bid) / config.pip_size
        filled_quantity = min(quantity, broker.maximum_immediate_fill_lots) if broker.supports_partial_fills else quantity
        mid = (quote.bid + quote.ask) / 2
        if order.account_conversion:
            fx_rate = float(order.account_conversion['rate'])
            fx_source = 'OBSERVED_CONVERSION'
        elif config.quote_currency == broker.account_currency:
            fx_rate, fx_source = 1.0, "IDENTITY"
        elif config.base_currency == broker.account_currency:
            fx_rate, fx_source = 1.0 / quote.bid, "PAIR_DERIVED"
        else:
            if not closing:
                return self._rejected(order, quote, broker, 'ACCOUNT_CONVERSION_UNAVAILABLE')
            fx_rate, fx_source = None, 'ACCOUNT_CONVERSION_UNAVAILABLE'
        pip_value = config.pip_size * 100_000 * filled_quantity * fx_rate if fx_rate is not None else None
        spread_cost = spread_pips * pip_value / 2 if pip_value is not None else None
        slippage_cost = slippage * pip_value if pip_value is not None else None
        commission = max(broker.minimum_commission, broker.commission_per_lot_round_trip * filled_quantity / 2)
        notional = filled_quantity * 100_000 if config.base_currency == broker.account_currency else abs(fill * filled_quantity * 100_000) * fx_rate if fx_rate is not None else None
        status = "PARTIALLY_FILLED" if filled_quantity < quantity else "FILLED"
        history = ("CREATED", "SUBMITTED", "ACKNOWLEDGED", status)
        return ForexExecutionResult(
            status=status, theoretical_price=order.theoretical_price, bid=quote.bid, ask=quote.ask,
            requested_price=order.limit_price or order.stop_price or order.theoretical_price, fill_price=fill,
            filled_quantity_lots=filled_quantity, slippage_pips=slippage, spread_pips=spread_pips,
            spread_source="ESTIMATED" if quote.source.startswith("ESTIMATED") else "QUOTED", spread_cost=spread_cost, slippage_cost=slippage_cost,
            commission=commission, swap=0.0, total_cost=spread_cost + slippage_cost + commission if spread_cost is not None else None,
            margin_required=notional * broker.margin_requirement if notional is not None else 0.0, execution_model_version=broker.model_version,
            state_history=history,
            execution_latency_ms=broker.execution_latency_ms,
            account_fx_rate=fx_rate,
            fx_rate_source=fx_source,
            execution_assumptions={
                "cost_currency": broker.account_currency if fx_rate is not None else None,
                "account_cost_status": "CONVERTED" if fx_rate is not None else "CONVERSION_PENDING",
                "session": order.session,
                "liquidity_score": order.liquidity_score,
                "volatility_score": order.volatility_score,
                "event_impact": order.event_impact,
                "slippage_model": "broker_base_x_liquidity_x_volatility_x_event_v1",
            },
        )

    def _rejected(self, order, quote, broker, reason) -> ForexExecutionResult:
        return ForexExecutionResult("REJECTED", order.theoretical_price, quote.bid, quote.ask, order.theoretical_price, None, 0.0, 0.0, 0.0, "QUOTED", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, broker.model_version, reason, ("CREATED", "SUBMITTED", "REJECTED"))

    def _pending(self, order, quote, broker) -> ForexExecutionResult:
        return ForexExecutionResult("ACKNOWLEDGED", order.theoretical_price, quote.bid, quote.ask, order.limit_price or order.stop_price or order.theoretical_price, None, 0.0, 0.0, (quote.ask - quote.bid) / pair_config(order.pair).pip_size, "QUOTED", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, broker.model_version, None, ("CREATED", "SUBMITTED", "ACKNOWLEDGED"))

    def accrue_swap(self, order: ForexOrderRequest, broker: ForexBrokerProfile, *, nights: int, weekday: int) -> float:
        rate = broker.swap_long[order.pair] if order.side == ForexDirection.LONG else broker.swap_short[order.pair]
        multiplier = nights + (2 if weekday == broker.triple_swap_day else 0)
        return rate * multiplier * order.quantity_lots

    @staticmethod
    def _slippage_pips(order: ForexOrderRequest, broker: ForexBrokerProfile) -> float:
        liquidity_multiplier = 1.0 + max(0.0, 0.75 - order.liquidity_score) * 2.0
        volatility_multiplier = 1.0 + max(0.0, order.volatility_score - 0.5) * 1.5
        event_multiplier = {"LOW_IMPACT": 1.0, "MEDIUM_IMPACT": 1.5, "HIGH_IMPACT": 3.0}.get(order.event_impact, 1.25)
        session_multiplier = broker.session_spread_multiplier.get(order.session, 1.25)
        return broker.slippage_pips * liquidity_multiplier * volatility_multiplier * event_multiplier * session_multiplier
