
from test_live_forward_paper_trading import advance_execution_clock_with_fixture_market_days
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import LiveForwardPaperGame, LiveForwardPaperTrade

NOW = datetime(2026, 10, 13, 12)


@pytest.fixture
def fixed_close_clock(monkeypatch):
    class CloseClock(datetime):
        @classmethod
        def utcnow(cls):
            return NOW + timedelta(days=1)
    monkeypatch.setattr('app.services.trading_intelligence_lab.datetime',CloseClock)
    return CloseClock.utcnow()


@pytest.fixture
def db():
    engine = create_engine('sqlite:///:memory:',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def paper(db, *, uid='one', ticker='SPY', market='equity'):
    game = db.scalar(select(LiveForwardPaperGame))
    if game is None:
        game = LiveForwardPaperGame(game_id='desk-test')
        db.add(game)
        db.flush()
    row = LiveForwardPaperTrade(
        game_id=game.id, trade_uid=uid, duplicate_key=uid, ticker=ticker,
        setup_type='trend', model_version_used='baseline', side='LONG',
        market=market, status='OPEN', decision_timestamp=NOW,
        opened_at=NOW + timedelta(minutes=1), entry_price=100, position_size=1,
        stop_loss=95, target_1=110, confidence=65, notional_value=100,
        accounting_status='VALID', accounting_version='paper-forward-direction-v2',
        evidence_type='PAPER_FORWARD', benchmark_ticker='SPY',
        frozen_decision_payload={'confidence':65, 'side':'LONG',
            'trade_plan':{'entry_price':100, 'stop_price':95, 'target_1':110},
            'price_context':{'provider':'test-market-feed', 'latest_date':NOW.date().isoformat(),
                'available_at':(NOW-timedelta(minutes=1)).isoformat(),
                'latest_price':100, 'data_quality_score':90}},
    )
    db.add(row)
    db.flush()
    return row


def close(row, *, benchmark=3, net=9):
    row.status='CLOSED'
    row.closed_at=NOW+timedelta(days=1)
    row.exit_price=110
    row.gross_pnl_eur=10
    row.net_pnl_eur=net
    row.costs_paid=1
    row.commission_cost=1
    row.r_multiple=1.8
    row.benchmark_return_same_period=benchmark
    row.execution_costs={'benchmark_period':{'ticker':row.benchmark_ticker,'kind':'price',
        'start':{'date':row.opened_at.date().isoformat(),'price':100,'provider':'test',
            'available_at':row.opened_at.isoformat()},
        'end':{'date':row.closed_at.date().isoformat(),'price':103,'provider':'test',
            'available_at':row.closed_at.isoformat()}}}


def register(db, row):
    from app.services.alpha_desk import AlphaCallRegistry
    return AlphaCallRegistry().register(db,row,registered_at=NOW+timedelta(seconds=1))


def snapshot(db):
    from app.services.alpha_desk import AlphaDeskService
    db.flush()
    return AlphaDeskService().snapshot(db,now=NOW+timedelta(days=2))


def test_registration_is_idempotent_and_refuses_changed_frozen_inputs(db):
    row=paper(db)
    original=register(db,row)
    assert register(db,row).id==original.id
    row.frozen_decision_payload={**row.frozen_decision_payload,'confidence':99}
    with pytest.raises(ValueError,match='CHANGED'):
        register(db,row)


def test_closed_legacy_call_cannot_be_registered_prospectively(db):
    from app.services.alpha_desk import AlphaCallRegistry
    row=paper(db)
    close(row)
    with pytest.raises(ValueError,match='RETROSPECTIVE'):
        AlphaCallRegistry().register(db,row,registered_at=NOW+timedelta(days=2))
    assert snapshot(db)['markets']['equity']['qualified_closed']==0


def test_paired_alpha_uses_cost_adjusted_holding_return(db):
    row=paper(db)
    register(db,row)
    close(row)
    payload=snapshot(db)
    equity=payload['markets']['equity']
    assert equity['qualified_closed']==1
    assert equity['paired_sample']==1
    assert equity['mean_net_return_percent']==9
    assert equity['mean_paired_excess_percent']==6
    assert equity['verdict']=='INSUFFICIENT_EVIDENCE'
    assert payload['journal'][0]['confidence_semantics']=='HEURISTIC_NOT_PROBABILITY'


@pytest.mark.parametrize('failure,expected',[
    ('future','FUTURE_INPUT'),('stale','STALE_AT_DECISION'),
    ('provider','MISSING_PROVENANCE'),('mutated','SOURCE_CHANGED'),
    ('cost','COST_RECONCILIATION_FAILED'),('nan','INVALID_ACCOUNTING'),
])
def test_invalid_evidence_stays_visible_and_cannot_raise_sample(db,failure,expected):
    row=paper(db)
    context=row.frozen_decision_payload['price_context']
    if failure=='future': context['available_at']=(NOW+timedelta(hours=1)).isoformat()
    if failure=='stale': context['latest_date']=(NOW-timedelta(days=10)).date().isoformat()
    if failure=='provider': context.pop('provider')
    register(db,row)
    close(row)
    if failure=='mutated': row.frozen_decision_payload={**row.frozen_decision_payload,'confidence':99}
    if failure=='cost': row.net_pnl_eur=20
    if failure=='nan': row.costs_paid=float('inf')
    payload=snapshot(db)
    assert payload['markets']['equity']['qualified_closed']==0
    assert expected in payload['journal'][0]['blockers']


def test_missing_benchmark_and_inconsistent_notional_do_not_become_zero_alpha(db):
    row=paper(db)
    register(db,row)
    close(row,benchmark=None)
    payload=snapshot(db)
    assert payload['markets']['equity']['qualified_closed']==1
    assert payload['markets']['equity']['paired_sample']==0
    assert payload['markets']['equity']['mean_paired_excess_percent'] is None
    row.benchmark_return_same_period=3
    row.notional_value=1000
    assert snapshot(db)['markets']['equity']['paired_sample']==0


def test_unfilled_orders_never_contribute_realized_pnl(db):
    row=paper(db)
    register(db,row)
    row.status='EXPIRED'
    row.net_pnl_eur=500
    row.closed_at=NOW+timedelta(days=1)
    payload=snapshot(db)
    assert payload['markets']['equity']['qualified_closed']==0
    assert payload['markets']['equity']['observed_net_pnl'] is None
    assert payload['journal'][0]['outcome_status']=='NO_FILL'


def test_forex_and_equity_samples_are_not_pooled(db):
    equity=paper(db,uid='eq')
    forex=paper(db,uid='fx',ticker='EURUSD=X',market='forex')
    register(db,equity)
    register(db,forex)
    close(equity)
    close(forex,net=-10)
    payload=snapshot(db)
    assert payload['markets']['equity']['qualified_closed']==1
    assert payload['markets']['forex']['qualified_closed']==0
    assert 'pooled_alpha' not in payload


def test_reading_desk_does_not_register_legacy_calls_or_write_rows(db):
    row=paper(db)
    db.commit()
    first=snapshot(db)
    second=snapshot(db)
    assert first['registered_count']==second['registered_count']==0
    assert db.get(LiveForwardPaperTrade,row.id).status=='OPEN'
    assert not db.new and not db.dirty and not db.deleted


def test_date_cluster_interval_requires_breadth_and_reports_literal_positive_mean():
    from app.services.alpha_desk import paired_interval
    rows=[{'date':f'2026-01-{i%30+1:02d}','asset':str(i%3),'excess':2.0} for i in range(120)]
    result=paired_interval(rows)
    assert result['mean']==result['lower_95']==result['upper_95']==2
    assert result['observations']==120 and result['dates']==30 and result['assets']==3
    assert result['positive_sample'] is True
    assert paired_interval(rows[:20])['positive_sample'] is False
    assert paired_interval([{**row,'date':'2026-01-01'} for row in rows])['positive_sample'] is False


def test_active_call_with_invalid_geometry_is_not_ranked(db):
    row=paper(db)
    row.net_expectancy_bps=50
    row.frozen_decision_payload['trade_plan']['stop_price']=105
    register(db,row)
    from app.services.alpha_desk import AlphaDeskService
    result=AlphaDeskService().snapshot(db,now=NOW+timedelta(seconds=2))
    assert result['markets']['equity']['active_calls']==[]
    assert 'INVALID_PLAN' in result['journal'][0]['blockers']


def test_paper_candidate_creator_registers_original_inputs_before_any_outcome(db):
    from app.models import AlphaCallRegistration
    from app.services.live_forward_paper_trading import LiveForwardPaperTradingService
    candidate={'ticker':'SPY','side':'LONG','asset':{'asset_type':'etf'},
        'setup':{'setup_type':'test'},'confidence':70,'trade_plan':{'stop_price':95,'target_1':110},
        'price_context':{'latest_price':100,'latest_date':NOW.date().isoformat(),'rows':100,'data_quality_score':90}}
    row=LiveForwardPaperTradingService().create_candidate(db,candidate)
    record=db.scalar(select(AlphaCallRegistration).where(AlphaCallRegistration.source_id==row.id))
    assert record is not None
    assert record.manifest_json['inputs']['price_context']['latest_price']==100
    assert record.registered_at>=record.decision_at
    assert row.closed_at is None


def test_alpha_includes_older_closed_trades_and_deduplicates_live_evidence(db):
    from app.services.trader_brain import TraderBrainService
    row=paper(db,uid='older')
    close(row)
    row.created_at=NOW-timedelta(days=20)
    for i in range(501):
        newer=paper(db,uid=f'no-fill-{i}')
        newer.created_at=NOW+timedelta(seconds=i)
        newer.status='EXPIRED'
    db.commit()
    payload=TraderBrainService().alpha(db)
    assert payload['evidence_split']['paper_forward']['closed_trade_count']==1
    assert payload['total_evidence_sample_size']==1


def test_positive_historical_rows_without_provenance_are_not_strong_evidence():
    from app.engine.brain.trader_brain import trading_game_evidence_split
    from app.models import TradingGameTrade
    rows=[TradingGameTrade(ticker='SPY',net_pnl_eur=10,realized_r_multiple=2,
        pnl_percent=10,benchmark_return_same_period=2,outcome_label='win') for _ in range(120)]
    result=trading_game_evidence_split(rows,label='Historical Replay',data_source='trading_game_trades')
    assert result['evidence_grade']=='INSUFFICIENT_EVIDENCE'
    assert result['provenance_status']=='UNVERIFIED_LEGACY'


def test_desk_api_is_read_only_and_does_not_register_a_legacy_row(db):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.database import get_db
    row=paper(db)
    db.commit()
    def dependency():
        yield db
    app.dependency_overrides[get_db]=dependency
    try:
        client=TestClient(app)
        response=client.get('/api/alpha/desk')
        assert response.status_code==200
        assert response.json()['registered_count'] is None
        assert response.json()['snapshot_status']=='missing'
        assert client.post('/api/alpha/desk',json={}).status_code==405
        assert db.get(LiveForwardPaperTrade,row.id).status=='OPEN'
    finally:
        app.dependency_overrides.clear()


def forex_source(db):
    from app.models import ForexDecision,ForexTraderCycle,ForexPosition
    cycle=ForexTraderCycle(cycle_uid='fx-test',cycle_key='fx-test',configuration_hash='test-config',
        data_coverage_hash='test-input',code_commit='test-revision')
    db.add(cycle)
    db.flush()
    row=ForexDecision(cycle_id=cycle.id,decision_uid='fx-test-call',pair='EURUSD=X',
        strategy_id='frozen-baseline',status='APPROVED',direction='LONG',decision_timestamp=NOW,
        input_snapshot={'as_of':NOW.isoformat(),'quote':{'bid':1.1,'ask':1.101,
            'timestamp':(NOW-timedelta(seconds=10)).isoformat(),'source':'market-feed'},
            'timeframes':{'1m':{'market_timestamp':(NOW-timedelta(seconds=20)).isoformat(),
                'acquired_at':(NOW-timedelta(seconds=10)).isoformat(),'provider':'market-feed','quality_score':90}}},
        proposal_json={'entry':1.1,'stop':1.09,'target':1.12,'confidence':0.6,'expected_net_pips':30})
    db.add(row)
    db.flush()
    position=ForexPosition(position_uid='fx-test-position',decision_id=row.id,pair=row.pair,
        strategy_id=row.strategy_id,direction='LONG',quantity_lots=0.001,entry_price=1.1,
        stop_price=1.09,target_price=1.12,current_price=1.1,opened_at=NOW+timedelta(seconds=2),
        contract_json={'account_fx_rate':1.0,'fx_rate_source':'IDENTITY','account_currency':'EUR'})
    db.add(position)
    db.flush()
    return row,position


def test_native_forex_swap_credit_is_income_and_never_pooled_with_equity(db):
    row,position=forex_source(db)
    register(db,row)
    position.status='CLOSED'
    position.closed_at=NOW+timedelta(hours=1)
    position.exit_price=1.12
    position.gross_pnl=2
    position.spread_cost=0.4
    position.slippage_cost=0.3
    position.commission=0.3
    position.swap_accrued=0.5
    position.net_pnl=1.5
    result=snapshot(db)
    assert result['markets']['forex']['qualified_closed']==1
    assert result['markets']['forex']['observed_net_pnl']==1.5
    assert result['markets']['forex']['paired_sample']==0
    assert result['markets']['equity']['qualified_closed']==0


@pytest.mark.parametrize('native_forex', [False, True])
def test_closed_record_without_positive_fill_is_unqualified(db,native_forex):
    if native_forex:
        row,position=forex_source(db)
        register(db,row)
        position.status='CLOSED'
        position.closed_at=NOW+timedelta(hours=1)
        position.exit_price=1.12
        position.quantity_lots=0
    else:
        row=paper(db)
        register(db,row)
        close(row)
        row.position_size=0
    payload=snapshot(db)
    market='forex' if native_forex else 'equity'
    assert payload['markets'][market]['qualified_closed']==0
    assert 'MISSING_FILL' in payload['journal'][0]['blockers']


def test_completed_forex_position_cannot_be_retroactively_registered(db):
    from app.services.alpha_desk import AlphaCallRegistry
    row,position=forex_source(db)
    position.status='CLOSED'
    position.closed_at=NOW+timedelta(hours=1)
    db.flush()
    with pytest.raises(ValueError,match='RETROSPECTIVE'):
        AlphaCallRegistry().register(db,row,registered_at=NOW+timedelta(days=1))


def test_unavailable_quality_and_delayed_registration_block_forward_qualification(db):
    row=paper(db)
    row.frozen_decision_payload['price_context']['data_quality_score']=10
    from app.services.alpha_desk import AlphaCallRegistry
    AlphaCallRegistry().register(db,row,registered_at=NOW+timedelta(hours=1))
    close(row)
    result=snapshot(db)
    assert result['markets']['equity']['qualified_closed']==0
    assert 'LOW_DATA_QUALITY' in result['journal'][0]['blockers']
    assert 'REGISTRATION_DELAY' in result['journal'][0]['blockers']


def test_candidate_freezes_matching_database_price_provenance(db):
    from app.models import Asset,PriceHistory
    from app.services.live_forward_paper_trading import LiveForwardPaperTradingService
    now=datetime.utcnow()
    asset=Asset(ticker='SPY',name='SPY',category='ETF',sector='equity',country='US',asset_type='ETF')
    db.add(asset)
    db.flush()
    price=PriceHistory(asset_id=asset.id,date=now.date()-timedelta(days=1),open=99,high=101,low=98,
        close=100,volume=1000000,provider='stooq',created_at=now-timedelta(hours=1))
    db.add(price)
    db.flush()
    candidate={'ticker':'SPY','side':'LONG','asset':{'asset_type':'ETF'},'setup':{'setup_type':'trend'},
        'confidence':70,'trade_plan':{'stop_price':95,'target_1':110},
        'price_context':{'latest_price':100,'latest_date':price.date.isoformat(),'data_quality_score':90,'rows':100}}
    row=LiveForwardPaperTradingService().create_candidate(db,candidate)
    context=row.frozen_decision_payload['price_context']
    assert context['provider']=='stooq'
    assert context['source_price_id']==price.id
    assert context['available_at']==price.created_at.isoformat()


@pytest.mark.parametrize('failure',['inputs','context','provider','quality','frames','empty_frames'])
def test_invalid_source_shapes_stay_visible_without_qualifying_or_breaking_reads(db,failure):
    native=failure in {'frames','empty_frames'}
    if native:
        row,position=forex_source(db)
        row.input_snapshot['timeframes']=['malformed'] if failure=='frames' else {}
        register(db,row)
        position.status='CLOSED'
        position.closed_at=NOW+timedelta(hours=1)
        position.exit_price=1.12
    else:
        row=paper(db)
        if failure=='inputs': row.frozen_decision_payload=['malformed']
        if failure=='context': row.frozen_decision_payload['price_context']=['malformed']
        if failure=='provider': row.frozen_decision_payload['price_context']['provider']={'not':'a name'}
        if failure=='quality': row.frozen_decision_payload['price_context']['data_quality_score']=1000
        register(db,row)
        close(row)
    result=snapshot(db)
    assert result['markets']['forex' if native else 'equity']['qualified_closed']==0
    assert result['journal'][0]['blockers']
    if failure=='provider': assert result['journal'][0]['provider'] is None


@pytest.mark.parametrize('reason',['TIME_EXIT','INVALIDATION_HIT'])
def test_actual_filled_terminal_exit_remains_closed_evidence(db,reason,fixed_close_clock):
    from app.services.live_forward_paper_trading import LiveForwardPaperTradingService
    from app.engine.brain.trader_brain import paper_forward_trade_is_closed
    row=paper(db)
    register(db,row)
    service=LiveForwardPaperTradingService()
    service.close_trade(db,db.get(LiveForwardPaperGame,row.game_id),row,fixed_close_clock.date(),98,reason)
    result=snapshot(db)
    assert result['journal'][0]['outcome_status']=='CLOSED'
    assert result['markets']['equity']['qualified_closed']==1
    assert result['markets']['equity']['observed_net_pnl']==-2
    assert paper_forward_trade_is_closed(row)
    # It must also be sampled separately from hundreds of newer no-fills.
    from app.engine.brain.trader_brain import TraderBrainService
    for i in range(501):
        unfilled=paper(db,uid=f'expired-{i}')
        unfilled.status='EXPIRED'
        unfilled.position_size=0
        unfilled.opened_at=None
        unfilled.created_at=NOW+timedelta(days=3,seconds=i)
    db.commit()
    assert TraderBrainService().alpha(db)['evidence_split']['paper_forward']['closed_trade_count']==1


def test_real_close_benchmark_uses_actual_entry_and_retains_endpoint_provenance(db,fixed_close_clock):
    from app.models import Asset,PriceHistory
    from app.services.live_forward_paper_trading import LiveForwardPaperTradingService
    row=paper(db)
    row.decision_timestamp=NOW-timedelta(days=2)
    row.decision_date=row.decision_timestamp.date()
    row.entry_date=row.opened_at.date()
    row.frozen_decision_payload['price_context']['latest_date']=row.decision_date.isoformat()
    row.frozen_decision_payload['price_context']['available_at']=row.decision_timestamp.isoformat()
    from app.services.alpha_desk import AlphaCallRegistry
    AlphaCallRegistry().register(db,row,registered_at=row.decision_timestamp+timedelta(seconds=1))
    asset=Asset(ticker='SPY',name='SPY',category='ETF',sector='equity',country='US',asset_type='ETF')
    db.add(asset);db.flush()
    for d,p in [(row.decision_date,100),(row.entry_date,200),(NOW.date()+timedelta(days=1),200)]:
        db.add(PriceHistory(asset_id=asset.id,date=d,open=p,high=p,low=p,close=p,volume=1000,
            provider='test',created_at=datetime.combine(d,datetime.min.time())))
    db.flush()
    LiveForwardPaperTradingService().close_trade(db,db.get(LiveForwardPaperGame,row.game_id),row,NOW.date()+timedelta(days=1),110,'TARGET_1_HIT')
    assert row.benchmark_return_same_period==0
    assert snapshot(db)['journal'][0]['paired_excess_percent']==10


@pytest.mark.parametrize('failure',['missing','future','stale','wrong_period'])
def test_unverified_benchmark_endpoints_never_enter_paired_alpha(db,failure):
    row=paper(db);register(db,row);close(row)
    period=row.execution_costs['benchmark_period']
    if failure=='missing': row.execution_costs={}
    if failure=='future': period['start']['available_at']=(row.opened_at+timedelta(days=1)).isoformat()
    if failure=='stale': period['end']['date']=(row.closed_at-timedelta(days=1)).date().isoformat()
    if failure=='wrong_period': period['ticker']='QQQ'
    result=snapshot(db)
    assert result['markets']['equity']['qualified_closed']==1
    assert result['markets']['equity']['paired_sample']==0
    assert result['journal'][0]['paired_excess_percent'] is None


def test_realistic_fill_costs_reconcile_actual_target_lifecycle(monkeypatch):
    from test_live_forward_paper_trading import setup_db,seed_asset,add_price,candidate,run_lifecycle
    from app.services.live_forward_paper_trading import LiveForwardPaperTradingService
    from app.services.alpha_desk import AlphaDeskService
    class FutureDatetime(datetime):
        @classmethod
        def utcnow(cls): return datetime.utcnow()+timedelta(days=3)
    monkeypatch.setattr('app.services.live_forward_paper_trading.settings.paper_execution_account_currency','USD')
    with setup_db() as session:
        asset=seed_asset(session)
        service=LiveForwardPaperTradingService()
        payload=candidate(target_1=104,target_2=150)
        payload['price_context']['latest_date']=datetime.utcnow().date().isoformat()
        row=service.create_candidate(session,payload)
        add_price(session,asset,1,100)
        run_lifecycle(service,session)
        add_price(session,asset,2,106)
        monkeypatch.setattr('app.services.trading_intelligence_lab.datetime',FutureDatetime)
        run_lifecycle(service,session)
        result=AlphaDeskService().snapshot(session,now=datetime.utcnow()+timedelta(days=4))
        assert row.status=='CLOSED'
        assert result['journal'][0]['qualified_closed']
        assert result['journal'][0]['net_pnl']==row.net_pnl_eur


def test_real_close_reconciles_explicit_cash_costs_in_foreign_account_currency(db,fixed_close_clock):
    from app.services.live_forward_paper_trading import LiveForwardPaperTradingService
    row=paper(db);register(db,row)
    row.notional_value=80
    row.costs_paid=0.3
    row.execution_costs={'accounting':{'reconciled':True,'account_currency':'EUR',
        'entry_fx_rate':1.25,'exit_fx_rate':1.25,'entry_commission':0.01,
        'entry_fx_cost':0.01,'exit_commission':0.01,'exit_fx_cost':0.01,'explicit_costs':0.04}}
    LiveForwardPaperTradingService().close_trade(db,db.get(LiveForwardPaperGame,row.game_id),row,fixed_close_clock.date(),110,'TARGET_1_HIT')
    result=snapshot(db)
    assert row.net_pnl_eur==7.96
    assert result['journal'][0]['qualified_closed']
    assert result['journal'][0]['account_currency']=='EUR'


def test_account_currency_totals_are_not_pooled(db):
    for i,currency in enumerate(['EUR','USD']):
        row=paper(db,uid=str(i));register(db,row);close(row)
        row.execution_costs={**row.execution_costs,'accounting':{'reconciled':True,
            'account_currency':currency,'entry_fx_rate':1,'exit_fx_rate':1,
            'entry_commission':1,'entry_fx_cost':0,'exit_commission':0,'exit_fx_cost':0,'explicit_costs':1}}
    result=snapshot(db)['markets']['equity']
    assert result['qualified_closed']==2
    assert result['observed_net_pnl'] is None
    assert result['observed_net_pnl_by_currency']=={'EUR':9,'USD':9}


@pytest.mark.parametrize('frozen_accounting,executed_accounting,currency',[
    ({'account_currency':'USD'},None,'USD'),
    ({'account_currency':'USD'},{'account_currency':'EUR'},None),
    ({'account_currency':'EUR'},{'account_currency':None},None),
    ({'account_currency':'usd'},None,None),
    ({'account_currency':'ÉUR'},None,None),
    ('malformed',None,None),
])
def test_qualified_results_respect_frozen_currency_and_reject_ambiguous_contracts(
    db,frozen_accounting,executed_accounting,currency,
):
    row=paper(db)
    row.frozen_decision_payload={**row.frozen_decision_payload,'accounting':frozen_accounting}
    register(db,row)
    close(row)
    if executed_accounting is not None:
        row.execution_costs={**row.execution_costs,'accounting':executed_accounting}
    result=snapshot(db)
    call=result['journal'][0]
    assert call['account_currency']==currency
    assert call['qualified_closed'] is (currency is not None)
    assert result['markets']['equity']['observed_net_pnl_by_currency']==({currency:9} if currency else {})


@pytest.mark.parametrize('field',['costs_paid','spread_cost'])
def test_realistic_accounting_rejects_non_finite_diagnostic_costs(db,field):
    row=paper(db);register(db,row);close(row)
    row.execution_costs={**row.execution_costs,'accounting':{'reconciled':True,
        'account_currency':'USD','entry_fx_rate':1,'exit_fx_rate':1,
        'entry_commission':1,'entry_fx_cost':0,'exit_commission':0,'exit_fx_cost':0,'explicit_costs':1}}
    setattr(row,field,float('inf'))
    result=snapshot(db)
    assert result['markets']['equity']['qualified_closed']==0
    assert 'INVALID_ACCOUNTING' in result['journal'][0]['blockers']
