from datetime import timedelta
from decimal import Decimal as D
from fastapi.testclient import TestClient
import pytest

from blum_v3.domain import Instrument,Provenance
from blum_v3.data import accept_dataset
from blum_v3.storage import Repository
from blum_v3.portfolio import PortfolioService
from blum_v3.paper import PaperService
from test_portfolio import T,service,setup_account,order
from test_execution import bar,dataset
from test_api import socket_free_loop,AUTH


def source(repo,rows,instrument=None):
    result=accept_dataset(instrument or Instrument(symbol='SPY',market='equity',quote_currency='USD'),
        [row.model_dump(mode='json') for row in rows],Provenance(provider='review-unit-contract',rights='unit-test-only',
        first_seen_at=T+timedelta(days=10),availability_policy='historical_bar_close'))
    repo.save_dataset(result);return result


def test_api_retry_reuses_frozen_resolution_after_clock_advances(tmp_path):
    from blum_v3.api import create_app
    repo=Repository('sqlite:///'+str(tmp_path/'api.db'));data=dataset(length=40);repo.save_dataset(data)
    clock=[data.provenance.first_seen_at+timedelta(minutes=1)]
    client=TestClient(create_app(repository=repo,token='unit-secret',clock=lambda:clock[0]),backend_options={'loop_factory':socket_free_loop})
    account=client.post('/api/v3/accounts',json=dict(name='Review',market='equity',currency='USD',cash='10000'),headers=AUTH|{'Idempotency-Key':'epoch'}).json()
    url='/api/v3/accounts/'+account['id']+'/orders';body=dict(dataset_id=data.dataset_id,side='BUY',quantity='1');headers=AUTH|{'Idempotency-Key':'same-request'}
    first=client.post(url,json=body,headers=headers);clock[0]+=timedelta(seconds=1);second=client.post(url,json=body,headers=headers)
    assert first.status_code==second.status_code==201
    assert first.json()['id']==second.json()['id']


def test_manual_paper_orders_execute_without_strategy_subscription(tmp_path):
    repo=Repository('sqlite:///'+str(tmp_path/'p.db'));svc=PortfolioService(repo,clock=lambda:T+timedelta(days=1));account=setup_account(svc)
    order(svc,account,quantity='5')
    source(repo,[bar(timestamp=T+timedelta(hours=1),available_at=T+timedelta(hours=2))])
    result=PaperService(repo,clock=svc.clock).cycle()
    assert sum(r['fills'] for r in result)==1
    assert D(svc.snapshot(account)['positions']['SPY']['quantity'])==5


def test_same_symbol_cannot_merge_incompatible_instrument_contracts(tmp_path):
    svc=service(tmp_path);account=setup_account(svc);o=order(svc,account,quantity='1')
    svc.apply_fill(account,o['id'],quantity='1',price='100',fee='0',at=T+timedelta(hours=1),fill_id='usd')
    with pytest.raises(ValueError,match='instrument_contract_conflict'):
        order(svc,account,instrument=Instrument(symbol='SPY',market='equity',quote_currency='EUR'),quantity='1',key='eur',
            decision_at=T+timedelta(hours=1),reference_at=T+timedelta(hours=1),fx=dict(rate='2',at=T,source_ref='conversion'))


def test_halted_account_rejects_previously_accepted_new_risk_fill(tmp_path):
    svc=service(tmp_path);account=setup_account(svc);entry=order(svc,account)
    svc.apply_fill(account,entry['id'],quantity='10',price='100',fee='0',at=T+timedelta(hours=1),fill_id='entry')
    pending=order(svc,account,instrument=Instrument(symbol='QQQ',market='equity',quote_currency='USD'),quantity='5',key='pending',decision_at=T+timedelta(hours=1),reference_at=T+timedelta(hours=1))
    svc.mark(account,{'SPY':dict(price='70',at=T+timedelta(hours=2),source_ref='loss')},key='loss')
    assert svc.snapshot(account)['status']=='HALTED'
    with pytest.raises(ValueError,match='account_not_open_for_risk'):
        svc.apply_fill(account,pending['id'],quantity='5',price='100',fee='0',at=T+timedelta(hours=3),fill_id='after-halt')


def test_bar_capacity_is_shared_by_orders_and_survives_retry(tmp_path):
    repo=Repository('sqlite:///'+str(tmp_path/'p.db'));svc=PortfolioService(repo,clock=lambda:T+timedelta(days=1));account=setup_account(svc)
    order(svc,account,quantity='5',key='one');order(svc,account,quantity='5',key='two')
    data=source(repo,[bar(timestamp=T+timedelta(hours=1),available_at=T+timedelta(hours=2),volume='500')])
    paper=PaperService(repo,clock=svc.clock);paper.step(account,data.dataset_id);paper.step(account,data.dataset_id)
    assert D(svc.snapshot(account)['positions']['SPY']['quantity'])==5


def test_partially_filled_stop_remains_activated_on_later_bar(tmp_path):
    repo=Repository('sqlite:///'+str(tmp_path/'p.db'));svc=PortfolioService(repo,clock=lambda:T+timedelta(days=1));account=setup_account(svc)
    pending=order(svc,account,kind='STOP',stop_price='101')
    data=source(repo,[bar(timestamp=T+timedelta(hours=1),available_at=T+timedelta(hours=2),high='102',close='101',volume='100'),
        bar(timestamp=T+timedelta(hours=3),available_at=T+timedelta(hours=4),open='99',high='100',low='98',close='99',volume='1000')])
    PaperService(repo,clock=svc.clock).step(account,data.dataset_id,profile=dict(spread_bps='0',slippage_bps='0',commission_bps='0'))
    assert svc.snapshot(account)['orders'][pending['id']]['status']=='FILLED'


def test_paper_financing_is_posted_once_for_elapsed_holding_time(tmp_path):
    repo=Repository('sqlite:///'+str(tmp_path/'p.db'));svc=PortfolioService(repo,clock=lambda:T+timedelta(days=2));account=setup_account(svc)
    pending=order(svc,account,quantity='1');svc.apply_fill(account,pending['id'],quantity='1',price='100',fee='0',at=T+timedelta(hours=1),fill_id='entry')
    data=source(repo,[bar(timestamp=T+timedelta(days=1),available_at=T+timedelta(days=1,hours=1),high='101',low='99',close='100',volume='0')])
    paper=PaperService(repo,clock=svc.clock)
    for _ in range(2):paper.step(account,data.dataset_id,profile=dict(financing_bps_per_day='10'))
    assert D(svc.snapshot(account)['cash'])==D('9899.9')


def test_future_provenance_and_overlapping_availability_are_rejected():
    inst=Instrument(symbol='SPY',market='equity',quote_currency='USD')
    provenance=Provenance(provider='unit',rights='unit-only',first_seen_at=T+timedelta(days=2),availability_policy='historical_bar_close')
    with pytest.raises(ValueError,match='future_provenance'):
        accept_dataset(inst,[bar(timestamp=T+timedelta(days=1),available_at=T+timedelta(days=1,hours=1)).model_dump(mode='json')],provenance,clock=lambda:T)
    rows=[bar(timestamp=T,available_at=T+timedelta(hours=3)),bar(timestamp=T+timedelta(hours=1),available_at=T+timedelta(hours=2))]
    accepted=accept_dataset(inst,[r.model_dump(mode='json') for r in rows],provenance,clock=lambda:T+timedelta(days=3))
    assert len(accepted.bars)==1


def test_consumed_confirmation_is_not_reset_by_provenance_refresh(tmp_path):
    from blum_v3.research import ResearchService
    repo=Repository('sqlite:///'+str(tmp_path/'r.db'));data=dataset(length=40);repo.save_dataset(data);research=ResearchService(repo)
    trial=research.create(data.dataset_id,{'lookback':3},family_id='first',key='first');research.confirm(trial['id'])
    refreshed=accept_dataset(data.instrument,[b.model_dump(mode='json') for b in data.bars],data.provenance.model_copy(update={'source_revision':'refreshed-only'}));repo.save_dataset(refreshed)
    with pytest.raises(ValueError,match='confirmation_already_opened'):
        research.create(refreshed.dataset_id,{'lookback':4},family_id='renamed',key='renamed')


def test_new_trial_updates_registry_count_and_invalidates_old_adjustment(tmp_path):
    from blum_v3.research import ResearchService
    repo=Repository('sqlite:///'+str(tmp_path/'r.db'));data=dataset(length=40);repo.save_dataset(data);research=ResearchService(repo)
    trial=research.create(data.dataset_id,{'lookback':3},family_id='family',key='one');research.run(trial['id'])
    research.create(data.dataset_id,{'lookback':4},family_id='family',key='two')
    refreshed=research.get(trial['id'])
    assert refreshed['family_trial_count']==2
    interval=refreshed['report']['paired_interval']
    assert interval['status'] in {'STALE','UNAVAILABLE'} or interval['family_trials']==2
