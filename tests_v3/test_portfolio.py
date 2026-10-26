from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from decimal import Decimal as D

import pytest

T = datetime(2024, 1, 2, 21, tzinfo=timezone.utc)


def service(tmp_path):
    from blum_v3.storage import Repository
    from blum_v3.portfolio import PortfolioService
    return PortfolioService(Repository('sqlite:///' + str(tmp_path/'portfolio.db')), clock=lambda: T+timedelta(days=1))


def setup_account(svc, **kwargs):
    return svc.open_account(name='Research', market=kwargs.pop('market','equity'), currency=kwargs.pop('currency','USD'), cash='10000', key='opening', opened_at=T, **kwargs)['id']


def order(svc, account, **changes):
    from blum_v3.domain import Instrument
    defaults = dict(instrument=Instrument(symbol='SPY', market='equity',quote_currency='USD'), side='BUY',quantity='10',
        reference_price='100',decision_at=T,key='order-1',reference_at=T,source_ref='fixture')
    return svc.submit_order(account, **(defaults | changes))


def test_fill_cash_reservations_journal_and_retry_are_consistent(tmp_path):
    svc=service(tmp_path); account=setup_account(svc)
    o=order(svc,account)
    assert D(svc.snapshot(account)['reserved_cash']) == D('1020')
    fill=dict(quantity='4',price='101',fee='1',at=T+timedelta(hours=1),fill_id='fill-a')
    svc.apply_fill(account,o['id'],**fill)
    svc.apply_fill(account,o['id'],**fill)
    state=svc.snapshot(account)
    assert D(state['cash']) == D('9595')
    assert D(state['reserved_cash']) == D('612')
    assert D(state['positions']['SPY']['quantity']) == D('4')
    assert state['orders'][o['id']]['status']=='PARTIALLY_FILLED'
    svc.cancel_order(account,o['id'],key='cancel')
    assert D(svc.snapshot(account)['reserved_cash']) == 0
    assert all(sum(D(p['amount']) for p in e['postings']) == 0 for e in svc.journal(account))


def test_changed_idempotent_payload_rejected_and_reopen_preserves_cash(tmp_path):
    svc=service(tmp_path); account=setup_account(svc)
    o=order(svc,account)
    assert order(svc,account)['id']==o['id']
    with pytest.raises(ValueError,match='idempotency_conflict'):
        order(svc,account,quantity='11')
    assert D(service(tmp_path).snapshot(account)['reserved_cash'])==D('1020')


def test_pending_orders_count_toward_instrument_budget(tmp_path):
    svc=service(tmp_path); account=setup_account(svc)
    order(svc,account)
    order(svc,account,key='second')
    with pytest.raises(ValueError,match='instrument_limit'):
        order(svc,account,key='third',quantity='1')


def test_racing_submissions_cannot_exceed_frozen_risk_limit(tmp_path):
    svc=service(tmp_path); account=setup_account(svc)
    def submit(key):
        try: return order(svc,account,key=key,quantity='15')['status']
        except ValueError: return 'DENIED'
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(submit,['a','b']))
    assert sorted(results)==['ACCEPTED','DENIED']


def test_open_nav_drawdown_and_realized_pnl_include_costs(tmp_path):
    svc=service(tmp_path); account=setup_account(svc)
    o=order(svc,account)
    svc.apply_fill(account,o['id'],quantity='10',price='100',fee='1',at=T+timedelta(hours=1),fill_id='buy')
    svc.mark(account,{'SPY':dict(price='110',at=T+timedelta(hours=2),source_ref='mark')},key='mark')
    assert D(svc.snapshot(account)['nav'])==D('10099')
    sell=order(svc,account,side='SELL',quantity='10',reference_price='110',decision_at=T+timedelta(hours=2),reference_at=T+timedelta(hours=2),key='sell',reduce_only=True)
    svc.apply_fill(account,sell['id'],quantity='10',price='110',fee='1',at=T+timedelta(hours=3),fill_id='exit')
    state=svc.snapshot(account)
    assert D(state['cash'])==D('10098')
    assert D(state['realized_pnl'])==D('100')
    assert D(state['fees'])==D('2')
    assert all(sum(D(p['amount']) for p in e['postings'])==0 for e in svc.journal(account))


def test_forex_requires_valid_conversion_and_equity_cannot_short(tmp_path):
    from blum_v3.domain import Instrument
    svc=service(tmp_path); account=setup_account(svc)
    with pytest.raises(ValueError,match='equity_short_disabled'):
        order(svc,account,side='SELL')
    fx=svc.open_account(name='FX',market='forex',currency='EUR',cash='10000',key='fx',opened_at=T)['id']
    inst=Instrument(symbol='EURUSD',market='forex',quote_currency='USD',base_currency='EUR',tick_size='0.00001',lot_size='1')
    with pytest.raises(ValueError,match='missing_conversion'):
        order(svc,fx,instrument=inst,quantity='100',reference_price='1.1')
    converted=order(svc,fx,instrument=inst,side='SELL',quantity='100',reference_price='1.1',key='converted-order',fx=dict(rate='0.9',at=T,source_ref='EURUSD-rate'))
    svc.apply_fill(fx,converted['id'],quantity='100',price='1.1',fee='0',at=T+timedelta(hours=1),fill_id='fx-fill',fx=dict(rate='0.9',at=T,source_ref='EURUSD-rate'))
    assert D(svc.snapshot(fx)['cash'])==D('10099')


@pytest.mark.parametrize('changes,reason',[(dict(quantity='0'),'positive_quantity'),(dict(reference_price='NaN'),'finite'),(dict(reference_at=T-timedelta(days=10)),'stale_reference'),(dict(reference_at=T+timedelta(hours=1)),'future_reference')])
def test_invalid_risk_inputs_do_not_create_orders(tmp_path,changes,reason):
    svc=service(tmp_path); account=setup_account(svc)
    with pytest.raises(ValueError,match=reason): order(svc,account,**changes)
    assert not svc.snapshot(account)['orders']


def test_fill_before_decision_and_excess_fill_are_rejected(tmp_path):
    svc=service(tmp_path); account=setup_account(svc); o=order(svc,account)
    with pytest.raises(ValueError,match='execution_clock'):
        svc.apply_fill(account,o['id'],quantity='1',price='100',fee='0',at=T,fill_id='bad-time')
    with pytest.raises(ValueError,match='remaining_quantity'):
        svc.apply_fill(account,o['id'],quantity='11',price='100',fee='0',at=T+timedelta(hours=1),fill_id='bad-size')
    assert D(svc.snapshot(account)['cash'])==D('10000')
