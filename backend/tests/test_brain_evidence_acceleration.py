from __future__ import annotations

from datetime import date, datetime, timedelta, time
from test_live_forward_paper_trading import advance_execution_clock_with_fixture_market_days

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    Asset,
    BlumTradingPowerScore,
    LearningRun,
    LiveForwardPaperTrade,
    PriceHistory,
)
from app.services.learning_intelligence import BlumTradingPowerScoreService
from app.services.live_forward_paper_trading import LiveForwardPaperTradingService
from app.services import realtime


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def productive_run(db: Session, run_id: str = "productive-1") -> LearningRun:
    row = LearningRun(
        run_id=run_id,
        trigger="test",
        status="completed",
        predictions_created=2,
        outcomes_evaluated=1,
        memory_updates=1,
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    return row


def seed_asset(db: Session, ticker: str = "NVDA", close: float = 100.0) -> Asset:
    asset = Asset(
        ticker=ticker,
        name=ticker,
        category="Stock",
        sector="Technology",
        country="USA",
        asset_type="Stock",
        currency="USD",
        exchange="NASDAQ",
        is_active=True,
    )
    db.add(asset)
    db.flush()
    add_price(db, asset, date.today(), close)
    return asset


def add_price(db: Session, asset: Asset, price_date: date, close: float) -> None:
    db.add(
        PriceHistory(
            asset_id=asset.id,
            date=price_date,
            open=close - 1,
            high=close + 1,
            low=close - 2,
            close=close,
            volume=1_000_000,
            provider="test",
        )
    )
    db.commit()

    db.info["fixture_market_time"] = max(db.info.get("fixture_market_time", datetime.utcnow()), datetime.combine(price_date, time(22)))


def candidate(ticker: str = "NVDA") -> dict:
    return {
        "ticker": ticker,
        "asset": {"name": ticker, "asset_type": "Stock", "sector": "Technology"},
        "actionability": "active_setup",
        "sniper_score": 78.0,
        "confidence": 64.0,
        "setup": {"setup_type": "momentum_breakout"},
        "trade_plan": {
            "entry_type": "MARKET",
            "entry_trigger": "close above 100 with volume confirmation",
            "confirmation_condition": "relative volume > 1.5x",
            "invalidation_level": 96.0,
            "target_1": 130.0,
            "target_2": 150.0,
        },
        "price_context": {"latest_price": 100.0, "data_quality_score": 88.0, "rows": 120},
        "market_regime": {"regime_primary": "risk_on"},
    }


def test_brain_score_projector_skips_when_no_productive_learning_exists():
    with setup_db() as db:
        result = BlumTradingPowerScoreService().persist_if_evidence_changed(db)

        assert result["status"] == "skipped"
        assert result["reason"] == "no_productive_learning_evidence"
        assert db.scalar(select(func.count(BlumTradingPowerScore.id))) == 0


def test_brain_score_projector_persists_once_per_evidence_state():
    with setup_db() as db:
        productive_run(db)
        service = BlumTradingPowerScoreService()

        first = service.persist_if_evidence_changed(db)
        second = service.persist_if_evidence_changed(db)
        stored = db.scalar(select(BlumTradingPowerScore))

        assert first["status"] == "persisted"
        assert second["status"] == "unchanged"
        assert db.scalar(select(func.count(BlumTradingPowerScore.id))) == 1
        assert stored.warnings_json["evidence_fingerprint"] == first["evidence_fingerprint"]
        assert stored.warnings_json["evidence_source"]["learning_run_id"] == "productive-1"


def test_brain_score_projector_persists_new_productive_state():
    with setup_db() as db:
        productive_run(db, "productive-1")
        service = BlumTradingPowerScoreService()
        service.persist_if_evidence_changed(db)
        productive_run(db, "productive-2")

        result = service.persist_if_evidence_changed(db)

        assert result["status"] == "persisted"
        assert db.scalar(select(func.count(BlumTradingPowerScore.id))) == 2


def test_scheduled_paper_forward_cycle_scans_before_lifecycle(monkeypatch):
    calls: list[str] = []

    class FakeService:
        def run_once(self, db):
            calls.append("scan")
            return {"status": "ok", "created": [{"trade_id": 1}]}

        def run_lifecycle(self, db):
            calls.append("lifecycle")
            return {"status": "ok", "opened_trades": 1}

    monkeypatch.setattr(realtime.settings, "paper_forward_lifecycle_enabled", True)
    result = realtime.advance_live_forward_paper_trading(None, service=FakeService())

    assert calls == ["scan", "lifecycle"]
    assert result["scan"]["created"]
    assert result["lifecycle"]["opened_trades"] == 1


def test_opened_paper_forward_trade_gets_default_time_stop(monkeypatch):
    monkeypatch.setattr("app.services.live_forward_paper_trading.settings.paper_execution_account_currency", "USD")
    with setup_db() as db:
        asset = seed_asset(db)
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(db, candidate())
        add_price(db, asset, date.today() + timedelta(days=1), 101.0)

        service.run_lifecycle(db, override=True)
        opened = db.get(LiveForwardPaperTrade, trade.id)

        assert opened.status == "OPEN"
        assert opened.expires_at is not None
        assert opened.opened_at is not None
        assert opened.expires_at == opened.opened_at + timedelta(days=10)


def test_legacy_open_trade_without_expiry_is_backfilled_and_time_exited(monkeypatch):
    monkeypatch.setattr("app.services.live_forward_paper_trading.settings.paper_execution_account_currency", "USD")
    with setup_db() as db:
        asset = seed_asset(db)
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(db, candidate())
        add_price(db, asset, date.today() + timedelta(days=1), 100.0)
        service.run_lifecycle(db, override=True)

        opened = db.get(LiveForwardPaperTrade, trade.id)
        opened.opened_at = datetime.utcnow() - timedelta(days=11)
        opened.expires_at = None
        db.commit()
        add_price(db, asset, date.today() + timedelta(days=2), 101.0)

        service.run_lifecycle(db, override=True)
        closed = db.get(LiveForwardPaperTrade, trade.id)

        assert closed.expires_at == opened.opened_at + timedelta(days=10)
        assert closed.status == "EXPIRED"
        assert closed.close_reason == "TIME_EXIT"
