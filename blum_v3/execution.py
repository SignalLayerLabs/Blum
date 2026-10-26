"""Conservative, declared bar scenarios. Results are modeled fills, never broker fills."""
from datetime import datetime
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR

from .domain import Bar, Contract, Instrument, decimal, utc
from .orders import ExecutionProfile


class FillOutcome(Contract):
    status: str
    quantity: D = D(0)
    price: D | None = None
    fee: D = D(0)
    at: datetime | None = None
    reason: str = ''
    liquidity_basis: str = ''


def observation_capacity(instrument: Instrument,bar: Bar,profile: ExecutionProfile) -> D:
    raw=(bar.volume or D(0))*profile.participation if instrument.market=='equity' else profile.fx_capacity
    return (raw/instrument.lot_size).to_integral_value(rounding=ROUND_FLOOR)*instrument.lot_size


def simulate_order(order: dict, bar: Bar, profile: ExecutionProfile, *, eligible_index=0,capacity_remaining=None) -> FillOutcome:
    effective_decision=max(utc(order['decision_at']),utc(order.get('triggered_at',order['decision_at'])))
    if bar.timestamp <= effective_decision:
        return FillOutcome(status='WAITING',reason='not_after_decision')
    if order.get('expires_at') and bar.available_at>utc(order['expires_at']):
        return FillOutcome(status='EXPIRED',reason='order_expired')
    if eligible_index<profile.latency_bars:
        return FillOutcome(status='WAITING',reason='latency')
    instrument=Instrument.model_validate(order['instrument'])
    buy=order['side']=='BUY';kind=order['kind'];base=bar.open
    if kind in {'STOP','STOP_LIMIT'}:
        stop=decimal(order['stop_price'])
        reached=bar.high>=stop if buy else bar.low<=stop
        if not reached: return FillOutcome(status='WAITING',reason='stop_not_reached')
        if kind=='STOP_LIMIT':
            return FillOutcome(status='TRIGGERED',reason='intrabar_sequence_unknown_wait_for_next_bar')
        base=max(base,stop) if buy else min(base,stop)
    if kind=='LIMIT':
        limit=decimal(order['limit_price'])
        reached=bar.low<=limit if buy else bar.high>=limit
        if not reached: return FillOutcome(status='WAITING',reason='limit_not_reached')
        base=min(base,limit) if buy else max(base,limit)
    # Quotes belong to the observable bar close, not its earlier opening.
    if bar.bid is not None and kind=='MARKET':
        base=bar.ask if buy else bar.bid
        adverse=profile.slippage_bps
    else:
        adverse=profile.spread_bps/2+profile.slippage_bps
    px=base*(1+(adverse/D(10000))*(1 if buy else -1))
    px=(px/instrument.tick_size).to_integral_value(rounding=ROUND_CEILING if buy else ROUND_FLOOR)*instrument.tick_size
    if px<=0: return FillOutcome(status='WAITING',reason='invalid_adverse_price')
    if kind=='LIMIT':
        limit=decimal(order['limit_price'])
        if (buy and px>limit) or (not buy and px<limit):
            return FillOutcome(status='WAITING',reason='cost_adjusted_limit_not_executable')
    if instrument.market=='equity':
        if bar.volume is None or bar.volume<=0:
            return FillOutcome(status='WAITING',reason='missing_equity_capacity',liquidity_basis='reported_bar_volume')
        capacity=bar.volume*profile.participation
        basis='reported_bar_volume'
    else:
        capacity=profile.fx_capacity
        basis='declared_otc_capacity'
    if capacity_remaining is not None:capacity=min(capacity,max(D(0),decimal(capacity_remaining)))
    quantity=(min(decimal(order['remaining']),capacity)/instrument.lot_size).to_integral_value(rounding=ROUND_FLOOR)*instrument.lot_size
    if quantity<=0: return FillOutcome(status='WAITING',reason='capacity_below_lot',liquidity_basis=basis)
    fee=max(profile.minimum_commission,quantity*px*profile.commission_bps/D(10000))
    return FillOutcome(status='FILLED' if quantity==decimal(order['remaining']) else 'PARTIALLY_FILLED',
        quantity=quantity,price=px,fee=fee,at=bar.available_at,liquidity_basis=basis,
        reason='bar_scenario_reconciled_at_close')
