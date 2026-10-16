from datetime import datetime, timedelta

from sqlalchemy import create_engine, event, select, func
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import BackgroundJobState, ForexTraderRuntimeState, ForexTraderCycle


NOW = datetime(2026, 10, 15, 12)


def test_empty_operating_state_is_unknown_and_never_initializes_a_worker():
    from app.runtime.operating_state import OperatingStateService

    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        statements = []
        event.listen(engine, 'before_cursor_execute', lambda c, cur, sql, p, ctx, many: statements.append(sql))
        value = OperatingStateService().read(db, now=NOW)
        assert value['markets']['forex']['heartbeat_at'] is None
        assert value['markets']['forex']['worker_observed_alive'] is False
        assert value['markets']['equity']['workers'][0]['status'] == 'UNOBSERVED'
        assert all(sql.lstrip().upper().startswith('SELECT') for sql in statements)
        assert len(statements) <= 5
        assert db.scalar(select(func.count(ForexTraderRuntimeState.id))) == 0


def test_control_state_overrides_old_running_snapshot_and_only_completed_cycle_is_reported():
    from app.runtime.operating_state import OperatingStateService

    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(ForexTraderRuntimeState(runtime_key='default', desired_state='PAUSED', scheduler_status='RISK_PAUSED', heartbeat_at=NOW))
        db.add(ForexTraderCycle(cycle_uid='done', cycle_key='done', status='COMPLETED', configuration_hash='test', data_coverage_hash='test', started_at=NOW-timedelta(minutes=1), completed_at=NOW-timedelta(seconds=30), blockers=['NO_NET_EDGE']))
        db.add(ForexTraderCycle(cycle_uid='in-flight', cycle_key='in-flight', status='RUNNING', configuration_hash='test', data_coverage_hash='test', started_at=NOW))
        db.commit()
        value = OperatingStateService().read(db, now=NOW)['markets']['forex']
        assert value['desired_state'] == 'PAUSED'
        assert value['status'] == 'PAUSED'
        assert value['last_completed_cycle']['cycle_id'] == 'done'
        assert value['active_blockers'] == ['NO_NET_EDGE']


def test_stale_heartbeat_and_failed_equity_job_do_not_mean_running():
    from app.runtime.operating_state import OperatingStateService

    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(ForexTraderRuntimeState(runtime_key='default', desired_state='RUNNING', scheduler_status='RUNNING', heartbeat_at=NOW-timedelta(hours=1)))
        db.add(BackgroundJobState(job_name='intraday_paper_trading', status='failed', last_started_at=NOW-timedelta(seconds=10), error_message='private provider detail'))
        db.commit()
        value = OperatingStateService().read(db, now=NOW)
        assert value['markets']['forex']['status'] == 'STALE_HEARTBEAT'
        assert value['markets']['forex']['worker_observed_alive'] is False
        assert value['markets']['equity']['workers'][0]['status'] == 'ERROR'
        assert 'private provider detail' not in str(value)


def test_future_heartbeat_cannot_establish_worker_liveness():
    from app.runtime.operating_state import OperatingStateService

    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(ForexTraderRuntimeState(runtime_key='default', desired_state='RUNNING', scheduler_status='RUNNING', heartbeat_at=NOW+timedelta(minutes=1)))
        db.commit()
        value = OperatingStateService().read(db, now=NOW)['markets']['forex']
        assert value['worker_observed_alive'] is False
        assert value['status'] == 'CLOCK_INCONSISTENT'


def test_public_operating_route_reads_without_admin_access_or_side_effects():
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from sqlalchemy.pool import StaticPool
    from app.api.routers.runtime import router
    from app.api.public_access import public_access_error
    from app.core.database import get_db

    engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(router)

    def session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = session

    @app.middleware('http')
    async def guard(request: Request, call_next):
        error = public_access_error(request, app.router.routes, enabled=True, admin_key='private-test-key')
        return error if error is not None else await call_next(request)

    statements = []
    event.listen(engine, 'before_cursor_execute', lambda c, cur, sql, p, ctx, many: statements.append(sql))
    with TestClient(app) as client:
        response = client.get('/api/runtime/operating-state')
        assert response.status_code == 200
        assert response.json()['mode'] == 'paper_research'
        assert len(statements) == 3
        assert all(sql.lstrip().upper().startswith('SELECT') for sql in statements)
        assert client.get('/api/runtime/operating-state?refresh=true').status_code == 403
