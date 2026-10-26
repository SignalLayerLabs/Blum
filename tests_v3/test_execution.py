from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from blum_v3.domain import Bar, Instrument, Provenance
from blum_v3.data import accept_dataset

T=datetime(2024,1,2,14,30,tzinfo=timezone.utc)


def bar(**kwargs):
    return Bar(**(dict(timestamp=T,available_at=T+timedelta(hours=6),open='100',high='105',low='95',close='102',volume='1000')|kwargs))


def order(**kwargs):
    return dict(id='unit-order',instrument=Instrument(symbol='SPY',market='equity',quote_currency='USD').model_dump(mode='json'),
        side='BUY',remaining='20',decision_at=(T-timedelta(hours=18)).isoformat(),kind='MARKET',limit_price=None,stop_price=None,expires_at=None)|kwargs


def test_capacity_costs_and_tick_rounding_have_literal_expected_values():
    from blum_v3.execution import simulate_order
    from blum_v3.orders import ExecutionProfile
    fill=simulate_order(order(),bar(),ExecutionProfile(spread_bps='10',slippage_bps='5',commission_bps='1',participation='0.01'))
    assert fill.status=='PARTIALLY_FILLED'
    assert fill.quantity==D('10')
    assert fill.price==D('100.10')
    assert fill.fee==D('0.10010')


@pytest.mark.parametrize('volume',[None,'0'])
def test_missing_equity_capacity_never_generates_fills(volume):
    from blum_v3.execution import simulate_order
    from blum_v3.orders import ExecutionProfile
    assert simulate_order(order(),bar(volume=volume),ExecutionProfile()).quantity==0


def test_same_bar_and_latency_do_not_fill_early():
    from blum_v3.execution import simulate_order
    from blum_v3.orders import ExecutionProfile
    assert simulate_order(order(decision_at=T.isoformat()),bar(),ExecutionProfile()).reason=='not_after_decision'
    assert simulate_order(order(),bar(),ExecutionProfile(latency_bars=1),eligible_index=0).reason=='latency'


def test_limits_are_never_violated_and_stop_limit_ambiguity_waits():
    from blum_v3.execution import simulate_order
    from blum_v3.orders import ExecutionProfile
    profile=ExecutionProfile(spread_bps='0',slippage_bps='0')
    assert simulate_order(order(kind='LIMIT',limit_price='96'),bar(),profile).price==D('96')
    assert simulate_order(order(kind='LIMIT',limit_price='94'),bar(),profile).quantity==0
    trigger=simulate_order(order(kind='STOP_LIMIT',stop_price='103',limit_price='102'),bar(),profile)
    assert trigger.status=='TRIGGERED'
    assert trigger.quantity==0


def test_stop_gaps_and_expiry_are_conservative():
    from blum_v3.execution import simulate_order
    from blum_v3.orders import ExecutionProfile
    profile=ExecutionProfile(spread_bps='0',slippage_bps='0')
    assert simulate_order(order(kind='STOP',stop_price='99'),bar(),profile).price==D('100')
    assert simulate_order(order(expires_at=(T-timedelta(minutes=1)).isoformat()),bar(),profile).status=='EXPIRED'


def test_otc_capacity_is_explicit_in_the_scenario():
    from blum_v3.execution import simulate_order
    from blum_v3.orders import ExecutionProfile
    inst=Instrument(symbol='EURUSD',market='forex',quote_currency='USD',base_currency='EUR',tick_size='0.00001')
    result=simulate_order(order(instrument=inst.model_dump(mode='json')),bar(volume=None),ExecutionProfile(fx_capacity='3'))
    assert result.quantity==D('3')
    assert result.liquidity_basis=='declared_otc_capacity'


def dataset(length=30, changed_tail=False,market='equity'):
    days=[T+timedelta(days=i) for i in range(60) if (T+timedelta(days=i)).weekday()<5][:length]
    rows=[]
    for i,day in enumerate(days):
        price=100+i if not changed_tail or i<20 else 200+i
        rows.append(dict(timestamp=day,available_at=day+timedelta(hours=6),open=str(price),high=str(price+2),low=str(price-2),close=str(price+1),volume='1000000'))
    inst=Instrument(symbol='SPY' if market=='equity' else 'EURUSD',market=market,quote_currency='USD')
    return accept_dataset(inst,rows,Provenance(provider='unit-contract',rights='unit-test-only',first_seen_at=days[-1]+timedelta(days=1),availability_policy='historical_bar_close'))


def test_replay_is_deterministic_and_future_tail_does_not_change_prefix():
    from blum_v3.replay import run_replay, ReplayConfig
    config=ReplayConfig(lookback=3)
    first=run_replay(dataset(),config)
    again=run_replay(dataset(),config)
    changed=run_replay(dataset(changed_tail=True),config)
    assert first['fingerprint']==again['fingerprint']
    assert first['curve'][:20]==changed['curve'][:20]
    assert first['decisions'][:20]==changed['decisions'][:20]
    assert first['fills']
    assert all(row['at']>row['decision_at'] for row in first['fills'])
    assert first['evidence_tier']=='MODELED_PAPER'
    assert first['benchmark']['name']=='passive_allocation'


def test_realistic_cost_stress_and_forex_lane_remain_separate():
    from blum_v3.replay import run_replay, ReplayConfig
    result=run_replay(dataset(market='forex'),ReplayConfig(lookback=3))
    assert result['market']=='forex'
    assert result['benchmark']['name']=='cash_zero_interest_reference'
    assert '2x_costs' in result['stress']
    assert result['qualification']['status']=='EXPERIMENTAL'


def test_native_dependency_is_bounded_and_reports_actual_version():
    from blum_v3.native import native_health
    result=native_health()
    assert result['status'] in {'AVAILABLE','UNAVAILABLE','INCOMPATIBLE'}
    if result['status']=='AVAILABLE': assert result['version']=='1.230.0'
