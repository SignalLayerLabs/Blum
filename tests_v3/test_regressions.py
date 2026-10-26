from datetime import timedelta
from decimal import Decimal as D
import pytest

from test_portfolio import service,setup_account,order,T
from test_execution import dataset,bar


def test_adverse_fill_cannot_expand_past_instrument_risk_budget(tmp_path):
    svc=service(tmp_path);account=setup_account(svc);o=order(svc,account,quantity='20')
    with pytest.raises(ValueError,match='fill_risk_limit'):
        svc.apply_fill(account,o['id'],quantity='20',price='110',fee='0',at=T+timedelta(hours=1),fill_id='over-budget')
    assert svc.snapshot(account)['cash']=='10000'


def test_financing_is_a_balanced_deduplicated_cash_event(tmp_path):
    svc=service(tmp_path);account=setup_account(svc)
    kwargs=dict(amount='2.5',at=T+timedelta(hours=1),source_ref='declared-financing',key='financing')
    svc.apply_financing(account,**kwargs);svc.apply_financing(account,**kwargs)
    assert D(svc.snapshot(account)['cash'])==D('9997.5')
    event=svc.journal(account)[-1]
    assert event['kind']=='FINANCING_RECORDED'
    assert sum(D(p['amount']) for p in event['postings'])==0


def test_confirmation_cannot_be_reused_by_renaming_a_trial_family(tmp_path):
    from blum_v3.storage import Repository
    from blum_v3.research import ResearchService
    repo=Repository('sqlite:///'+str(tmp_path/'r.db'));data=dataset(length=40);repo.save_dataset(data)
    research=ResearchService(repo)
    registered=research.create(data.dataset_id,{'lookback':3},family_id='before',key='before')
    research.confirm(registered['id'])
    with pytest.raises(ValueError,match='confirmation_already_opened'):
        research.create(data.dataset_id,{'lookback':2},family_id='after',key='after')


def test_paper_does_not_refill_same_bar_on_retry(tmp_path):
    from blum_v3.storage import Repository
    from blum_v3.portfolio import PortfolioService
    from blum_v3.paper import PaperService
    from blum_v3.domain import Instrument,Provenance
    from blum_v3.data import accept_dataset
    repo=Repository('sqlite:///'+str(tmp_path/'p.db'));clock=lambda:T+timedelta(days=1)
    svc=PortfolioService(repo,clock=clock);account=setup_account(svc)
    order(svc,account,quantity='10')
    observation=bar(timestamp=T+timedelta(hours=1),available_at=T+timedelta(hours=2),volume='400').model_dump(mode='json')
    source=accept_dataset(Instrument(symbol='SPY',market='equity',quote_currency='USD'),[observation],
        Provenance(provider='contract',rights='unit-only',first_seen_at=T+timedelta(days=1),availability_policy='historical_bar_close'))
    repo.save_dataset(source);paper=PaperService(repo,clock=clock)
    assert paper.step(account,source.dataset_id)['fills']==1
    assert paper.step(account,source.dataset_id)['fills']==0
    assert D(svc.snapshot(account)['positions']['SPY']['quantity'])==4


def test_stop_limit_trigger_is_durable_and_cannot_fill_trigger_bar(tmp_path):
    from blum_v3.execution import simulate_order
    from blum_v3.orders import ExecutionProfile
    svc=service(tmp_path);account=setup_account(svc)
    o=order(svc,account,kind='STOP_LIMIT',stop_price='103',limit_price='102')
    triggered=svc.trigger_order(account,o['id'],at=T+timedelta(hours=1),source_ref='unit-bar',key='trigger')
    assert triggered['kind']=='LIMIT'
    source=bar(timestamp=T+timedelta(hours=1),available_at=T+timedelta(hours=2))
    assert simulate_order(triggered,source,ExecutionProfile()).quantity==0


def test_two_execution_cost_scenarios_do_not_hide_financing(tmp_path):
    from blum_v3.replay import ReplayConfig,run_replay
    from blum_v3.orders import ExecutionProfile
    data=dataset(length=30)
    zero=run_replay(data,ReplayConfig(strategy='hold',execution=ExecutionProfile(financing_bps_per_day='0')),stress=False)
    financed=run_replay(data,ReplayConfig(strategy='hold',execution=ExecutionProfile(financing_bps_per_day='10')),stress=False)
    assert financed['metrics']['return_percent']<zero['metrics']['return_percent']


def test_valid_risk_rejection_is_recorded_once_with_its_reason(tmp_path):
    svc=service(tmp_path);account=setup_account(svc)
    for _ in range(2):
        with pytest.raises(ValueError,match='instrument_limit'):order(svc,account,quantity='30')
    rejected=[event for event in svc.journal(account) if event['kind']=='ORDER_REJECTED']
    assert len(rejected)==1
    assert rejected[0]['payload']['reason']=='instrument_limit'


def test_running_research_can_stop_at_a_bounded_progress_boundary():
    from blum_v3.replay import run_replay,ReplayConfig
    with pytest.raises(InterruptedError,match='job_no_longer_owned'):
        run_replay(dataset(length=40),ReplayConfig(lookback=3),progress=lambda:False)


def test_safe_reducing_order_does_not_require_complete_portfolio_nav(tmp_path):
    svc=service(tmp_path);account=setup_account(svc);o=order(svc,account)
    svc.apply_fill(account,o['id'],quantity='10',price='100',fee='0',at=T+timedelta(hours=1),fill_id='entry')
    svc.clock=lambda:T+timedelta(days=8)
    assert svc.snapshot(account)['nav'] is None
    result=order(svc,account,side='SELL',quantity='10',reduce_only=True,key='safe-exit',
        reference_at=svc.clock(),decision_at=svc.clock())
    assert result['status']=='ACCEPTED'


def test_fractional_average_cost_does_not_unbalance_partial_exit(tmp_path):
    svc=service(tmp_path);account=setup_account(svc);o=order(svc,account,quantity='3')
    svc.apply_fill(account,o['id'],quantity='1',price='100',fee='0',at=T+timedelta(hours=1),fill_id='one')
    svc.apply_fill(account,o['id'],quantity='2',price='101',fee='0',at=T+timedelta(hours=2),fill_id='two')
    sell=order(svc,account,side='SELL',quantity='1',reduce_only=True,key='partial-exit',decision_at=T+timedelta(hours=2),reference_at=T+timedelta(hours=2),reference_price='101')
    svc.apply_fill(account,sell['id'],quantity='1',price='102',fee='0',at=T+timedelta(hours=3),fill_id='partial')
    assert D(svc.snapshot(account)['cash'])==D('9800')
    assert all(sum(D(p['amount']) for p in e['postings'])==0 for e in svc.journal(account))


def test_cross_currency_paper_fill_uses_an_observable_conversion(tmp_path):
    from blum_v3.storage import Repository
    from blum_v3.portfolio import PortfolioService
    from blum_v3.paper import PaperService
    from blum_v3.domain import Instrument,Provenance
    from blum_v3.data import accept_dataset
    repo=Repository('sqlite:///'+str(tmp_path/'fx.db'));clock=lambda:T+timedelta(days=1)
    svc=PortfolioService(repo,clock=clock)
    account=svc.open_account(name='EUR FX sleeve',market='forex',currency='EUR',cash='10000',key='epoch',opened_at=T)['id']
    instrument=Instrument(symbol='EURUSD',market='forex',quote_currency='USD',base_currency='EUR',tick_size='0.00001')
    svc.submit_order(account,instrument=instrument,side='BUY',quantity='100',reference_price='1.10',decision_at=T,reference_at=T,
        source_ref='unit-reference',key='fx-buy',fx=dict(rate='0.9',at=T,source_ref='unit-conversion'))
    row=bar(timestamp=T+timedelta(hours=1),available_at=T+timedelta(hours=2),open='1.10',high='1.20',low='1.00',close='1.15',volume=None)
    source=accept_dataset(instrument,[row.model_dump(mode='json')],Provenance(provider='contract',rights='unit-test-only',first_seen_at=clock(),availability_policy='historical_bar_close'))
    repo.save_dataset(source)
    result=PaperService(repo,clock=clock).step(account,source.dataset_id)
    assert result['fills']==1
    assert D(result['portfolio']['positions']['EURUSD']['quantity'])==100
    assert result['portfolio']['positions']['EURUSD']['mark']['fx']['source_ref']
