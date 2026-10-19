from datetime import datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Asset, ReplayDataCoverage, ReplayMarketBar
from app.services import curriculum_worker as worker


def database():
    db = Session(
        create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
    )
    Base.metadata.create_all(db.get_bind())
    asset = Asset(
        ticker="TEST",
        name="Test",
        sector="Technology",
        country="USA",
        category="Stock",
        asset_type="Stock",
        currency="USD",
        exchange="NASDAQ",
        is_active=True,
    )
    db.add(asset)
    db.flush()
    from app.services.market_bar_clock import nyse_calendar

    sessions = nyse_calendar().sessions_in_range("2020-01-01", "2024-01-01")[:800]
    for i in range(800):
        price = 100 + i * 0.1
        db.add(
            ReplayMarketBar(
                asset_id=asset.id,
                source_symbol="TEST",
                normalized_symbol="TEST",
                market="USA",
                timeframe="1d",
                bar_timestamp=sessions[i].to_pydatetime(),
                open=price,
                high=price + 1,
                low=price - 0.2,
                close=price + 0.5,
                volume=1e6,
                provider="fixture",
                data_quality_score=95,
                acquired_at=datetime(2024, 1, 1),
            )
        )
    db.add(
        ReplayDataCoverage(
            asset_id=asset.id,
            source_symbol="TEST",
            normalized_symbol="TEST",
            market="USA",
            timeframe="1d",
            provider="fixture",
            rows_available=800,
            data_quality_score=95,
            available_end=sessions[-1].to_pydatetime(),
        )
    )
    db.commit()
    return db


def test_worker_persists_reproducible_curriculum_and_does_not_relearn_development():
    with database() as db:
        service = worker.TradingCurriculumWorker()
        result = service.run_once(db, now=datetime(2026, 10, 19), max_lanes=1)
        assert result["status"] == "ok"
        snapshot = service.snapshot(db)
        lane = snapshot["lanes"][0]
        assert lane["training_episodes"] == 1
        assert lane["learned_outcomes"] > 0
        assert lane["benchmark"]["confirmation_opened"] is False
        assert lane["benchmark"]["policy"]["trade_count"] > 0
        assert lane["forward"]["status"] == "STALE_CONTEXT"
        state = db.scalar(select(worker.TradingCurriculumState))
        first_checkpoint = state.payload["checkpoint"]
        first_n = lane["learned_outcomes"]
        service.run_once(db, now=datetime(2026, 10, 19, 0, 15), max_lanes=1)
        db.expire_all()
        lane = service.snapshot(db)["lanes"][0]
        assert lane["training_episodes"] == 2
        assert lane["learned_outcomes"] > first_n
        assert lane["checkpoint"] != first_checkpoint
        assert (
            len(
                db.scalars(
                    select(worker.TradingCurriculumEpisode).where(
                        worker.TradingCurriculumEpisode.phase == "train"
                    )
                ).all()
            )
            == 2
        )
        assert (
            lane["benchmark"]["window_hash"]
            == snapshot["lanes"][0]["benchmark"]["window_hash"]
        )


def test_public_snapshot_never_creates_state_or_runs_replay():
    with database() as db:
        service = worker.TradingCurriculumWorker()
        assert service.snapshot(db)["lanes"] == []
        assert db.scalar(select(worker.TradingCurriculumState)) is None


def test_training_exhaustion_is_not_relabelled_as_new_outcomes():
    with database() as db:
        service = worker.TradingCurriculumWorker()
        for _ in range(7):
            service.run_once(db, now=datetime(2026, 10, 19), max_lanes=1)
        first = service.snapshot(db)["lanes"][0]
        service.run_once(db, now=datetime(2026, 10, 19), max_lanes=1)
        last = service.snapshot(db)["lanes"][0]
        assert last["training_status"] == "PACK_EXHAUSTED"
        assert last["learned_outcomes"] == first["learned_outcomes"]
        assert last["training_episodes"] == first["training_episodes"]


def test_actual_seed_country_is_discovered_and_source_pack_stays_frozen():
    with database() as db:
        asset = db.scalar(select(Asset))
        asset.country = "United States"
        coverage = db.scalar(select(ReplayDataCoverage))
        coverage.market = "United States"
        db.commit()
        service = worker.TradingCurriculumWorker()
        service.run_once(db, now=datetime(2026, 10, 19))
        assert service.snapshot(db)["lanes"]
        first = service.snapshot(db)["lanes"][0]["source_hash"]
        bar = db.scalar(select(ReplayMarketBar))
        bar.close = bar.high
        db.commit()
        service.run_once(db, now=datetime(2026, 10, 19))
        snapshot = service.snapshot(db)
        assert snapshot["lanes"][0]["source_hash"] == first
        assert "source_pack" not in str(snapshot)


def test_routes_are_stored_public_read_and_protected_mutation():
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from app.api.routers.training import router
    from app.api.public_access import public_access_error
    from app.core.database import get_db

    app = FastAPI()
    app.include_router(router)
    with database() as db:
        app.dependency_overrides[get_db] = lambda: db

        @app.middleware("http")
        async def guard(request: Request, call_next):
            error = public_access_error(
                request, app.router.routes, enabled=True, admin_key="test-private"
            )
            return error if error is not None else await call_next(request)

        client = TestClient(app)
        assert client.get("/api/training/curriculum").status_code == 200
        assert client.get("/api/training/curriculum").json()["lanes"] == []
        assert client.post("/api/training/curriculum/run").status_code == 403
        assert db.scalar(select(worker.TradingCurriculumState)) is None


def test_prospective_journal_freezes_decision_then_learns_only_when_future_closes():
    from copy import deepcopy
    from app.services import trading_curriculum as k

    with database() as db:
        service = worker.TradingCurriculumWorker()
        now = datetime(2026, 10, 19, 8)
        service.run_once(db, now=now)
        payload = deepcopy(db.scalar(select(worker.TradingCurriculumState)).payload)
        historical = deepcopy(payload["model"])
        # Fresh context follows the frozen research corpus; it is never imported into development.
        from app.services.market_bar_clock import nyse_calendar

        sessions = nyse_calendar().sessions_in_range("2026-07-01", "2026-10-16")[-65:]
        for i, session in enumerate(sessions):
            day = session.to_pydatetime()
            price = 200 + i * 0.15
            db.add(
                ReplayMarketBar(
                    asset_id=payload["asset_id"],
                    source_symbol="TEST",
                    normalized_symbol="TEST",
                    market="USA",
                    timeframe="1d",
                    bar_timestamp=day,
                    open=price,
                    high=price + 1,
                    low=price - 0.2,
                    close=price + 0.5,
                    volume=1e6,
                    provider="fixture",
                    data_quality_score=95,
                    acquired_at=now - timedelta(minutes=1),
                )
            )
        db.commit()
        service._forward(db, payload, now)
        assert payload["forward"]["status"] == "PENDING"
        proposal = deepcopy(payload["forward"]["proposal"])
        db.commit()
        assert (
            db.scalar(
                select(worker.TradingCurriculumEpisode).where(
                    worker.TradingCurriculumEpisode.phase == "forward"
                )
            ).payload["outcome"]
            is None
        )
        assert not payload.get("live_updates")
        sessions = nyse_calendar().sessions_in_range("2026-10-19", "2026-11-06")[:12]
        for i, session in enumerate(sessions):
            day = session.to_pydatetime()
            db.add(
                ReplayMarketBar(
                    asset_id=payload["asset_id"],
                    source_symbol="TEST",
                    normalized_symbol="TEST",
                    market="USA",
                    timeframe="1d",
                    bar_timestamp=day,
                    open=210,
                    high=220,
                    low=209.9,
                    close=219,
                    volume=1e6,
                    provider="fixture",
                    data_quality_score=95,
                    acquired_at=now + timedelta(days=i),
                )
            )
        db.commit()
        service._forward(db, payload, now + timedelta(days=20))
        assert payload["forward"]["status"] == "CLOSED"
        assert payload["forward"]["closed_count"] == 1
        assert payload["forward"]["learned_outcomes"] == 1
        assert payload["model"] == historical
        outcome = payload["forward"]["last_outcome"]
        assert outcome["decision_at"] == proposal["decision_at"]
        assert outcome["entry_at"] > proposal["decision_at"]
        assert outcome["input_hash"] == proposal["input_hash"]
        assert outcome["entry_at"].startswith("2026-10-19T13:30")


def test_inactive_recent_coverage_cannot_hide_active_eligible_history():
    with database() as db:
        for i in range(13):
            asset = Asset(
                ticker=f"OFF{i}",
                name="Inactive",
                sector="Technology",
                country="USA",
                category="Stock",
                asset_type="Stock",
                currency="USD",
                exchange="NASDAQ",
                is_active=False,
            )
            db.add(asset)
            db.flush()
            db.add(
                ReplayDataCoverage(
                    asset_id=asset.id,
                    source_symbol=asset.ticker,
                    normalized_symbol=asset.ticker,
                    market="USA",
                    timeframe="1d",
                    provider="fixture",
                    rows_available=800,
                    data_quality_score=95,
                    available_end=datetime(2025, 1, 1),
                )
            )
        db.commit()
        worker.TradingCurriculumWorker().run_once(db, now=datetime(2026, 10, 19))
        assert (
            worker.TradingCurriculumWorker().snapshot(db)["lanes"][0]["ticker"]
            == "TEST"
        )


def test_adapter_preserves_invalid_and_low_quality_future_bar_evidence():
    with database() as db:
        row = db.scalar(select(ReplayMarketBar).order_by(ReplayMarketBar.bar_timestamp))
        row.high = 1
        row.data_quality_score = 20
        db.commit()
        result = worker.TradingCurriculumWorker()._bars(
            db,
            row.asset_id,
            "1d",
            "USA",
            datetime(2026, 10, 19),
            limit=2,
            after=row.bar_timestamp - timedelta(hours=1),
        )
        assert len(result) == 2
        assert result[0]["invalid_reason"] == "LOW_SOURCE_QUALITY"
        assert result[0]["high"] == 1


def test_rejected_nonfinite_market_values_are_json_safe_for_durable_blocked_paths():
    from app.services import trading_curriculum as k

    with database() as db:
        row = db.scalar(select(ReplayMarketBar).order_by(ReplayMarketBar.bar_timestamp))
        row.high = float("inf")
        db.commit()
        result = worker.TradingCurriculumWorker()._bars(
            db,
            row.asset_id,
            "1d",
            "USA",
            datetime(2026, 10, 19),
            limit=1,
            after=row.bar_timestamp - timedelta(hours=1),
        )
        assert result[0]["high"] is None
        assert result[0]["invalid_reason"] == "NON_FINITE_MARKET_DATA"
        assert not k.valid_bar(result[0])
        assert k.digest(result)
