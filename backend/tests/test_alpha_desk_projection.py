from datetime import datetime, timedelta

from sqlalchemy import event

from app.models import DashboardSnapshot
from app.services import alpha_desk
from test_alpha_desk import db, paper, register, close, snapshot, NOW


def test_a_forex_registration_burst_cannot_erase_the_equity_journal(db, monkeypatch):
    monkeypatch.setattr(alpha_desk, 'WINDOW', 4)
    equity = paper(db, uid='older-equity')
    register(db, equity)
    for index in range(5):
        register(db, paper(db, uid=f'busy-fx-{index}', ticker='EURUSD=X', market='forex'))
    value = snapshot(db)
    assert value['markets']['equity']['registered_total'] == 1
    assert value['markets']['forex']['registered_total'] == 5
    assert any(row['source_uid'] == 'paper:older-equity' for row in value['journal'])
    assert value['window']['by_market']['forex']['recent_truncated'] is True


def test_mature_executed_evidence_survives_a_burst_of_new_unexecuted_decisions(db, monkeypatch):
    monkeypatch.setattr(alpha_desk, 'WINDOW', 4)
    mature = paper(db, uid='mature')
    register(db, mature)
    close(mature)
    for index in range(5):
        register(db, paper(db, uid=f'new-idea-{index}'))
    value = snapshot(db)
    assert value['markets']['equity']['qualified_closed'] == 1
    assert value['window']['by_market']['equity']['executed_evaluated'] == 1


def test_missing_projection_is_unavailable_and_never_calculates_from_a_public_read(db):
    from app.services.alpha_desk_projection import AlphaDeskProjectionService
    statements = []
    event.listen(db.bind,'before_cursor_execute',lambda c,cur,sql,p,ctx,many:statements.append(sql))
    value = AlphaDeskProjectionService().latest(db)
    assert value['snapshot_status'] == 'missing'
    assert value['registered_count'] is None
    assert value['markets'] == {}
    assert len(statements) == 1
    assert statements[0].lstrip().upper().startswith('SELECT')
    assert 'alpha_call_registrations' not in statements[0].lower()


def stored(db, *, generated_at, expires_at):
    payload = {'status':'READY','generated_at':generated_at.isoformat(),'registered_count':7,'markets':{'equity':{'registered':7,'qualified_closed':1,'active_calls':[{'source_uid':'old-active','active_eligible':True}]}},'journal':[{'source_uid':'old-active','market':'equity','outcome_status':'PENDING','active_eligible':True,'quote_at':generated_at.isoformat(),'blockers':[]}]}
    db.add(DashboardSnapshot(snapshot_type='registered_alpha_desk_summary',created_at=generated_at,expires_at=expires_at,payload_json=payload))
    db.commit()


def test_stored_read_is_one_select_and_does_not_present_old_eligibility_as_current(db):
    from app.services.alpha_desk_projection import AlphaDeskProjectionService
    now = datetime.utcnow()
    stored(db, generated_at=now-timedelta(seconds=30), expires_at=now+timedelta(minutes=5))
    statements = []
    event.listen(db.bind,'before_cursor_execute',lambda c,cur,sql,p,ctx,many:statements.append(sql))
    value = AlphaDeskProjectionService().latest(db, now=now)
    assert len(statements) == 1
    assert value['registered_count'] == 7
    assert value['markets']['equity']['qualified_closed'] == 1
    assert value['markets']['equity']['active_calls'] == []
    assert value['markets']['equity']['active_calls_current'] is False
    assert value['journal'][0]['active_eligible'] is False
    assert value['generated_at'] != value['read_at']
    assert not db.new and not db.dirty and not db.deleted


def test_expired_projection_remains_observable_with_its_real_timestamp(db):
    from app.services.alpha_desk_projection import AlphaDeskProjectionService
    now = datetime.utcnow()
    generated = now-timedelta(minutes=20)
    stored(db, generated_at=generated, expires_at=now-timedelta(minutes=10))
    value = AlphaDeskProjectionService().latest(db, now=now)
    assert value['snapshot_status'] == 'stale'
    assert value['generated_at'] == generated.isoformat()
    assert value['snapshot_is_stale'] is True


def test_a_future_generated_projection_cannot_establish_current_results(db):
    from app.services.alpha_desk_projection import AlphaDeskProjectionService
    now = datetime.utcnow()
    stored(db, generated_at=now+timedelta(minutes=2), expires_at=now+timedelta(minutes=12))
    value = AlphaDeskProjectionService().latest(db, now=now)
    assert value['snapshot_status'] == 'invalid_clock'
    assert value['registered_count'] is None
    assert value['markets'] == {}


def test_public_desk_delivery_never_falls_back_to_a_full_recalculation(db, monkeypatch):
    from app.engine.facade import BlumEngineFacade
    def forbidden(*args,**kwargs):
        raise AssertionError('Public reads must not evaluate the registration history')
    monkeypatch.setattr(alpha_desk.AlphaDeskService,'snapshot',forbidden)
    value = BlumEngineFacade().alpha_desk_snapshot(db)
    assert value['snapshot_status'] == 'missing'
    assert value['registered_count'] is None


def test_background_snapshot_producer_publishes_the_registered_desk(db):
    from app.services.central_brain_runtime import SnapshotProducerService
    from app.services.alpha_desk_projection import AlphaDeskProjectionService
    register(db,paper(db,uid='published-in-background'))
    produced = SnapshotProducerService().produce(db,'registered_alpha_desk_summary')
    assert produced['payload']['registered_count'] == 1
    delivered = AlphaDeskProjectionService().latest(db)
    assert delivered['registered_count'] == 1
