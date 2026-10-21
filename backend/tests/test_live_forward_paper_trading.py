from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    Asset,
    LiveForwardPaperTrade,
    LiveForwardPaperTradeEvent,
    PaperForwardTrade,
    PaperForwardTradeEvent,
    ModelVersion,
    PaperExecutionFill,
    PaperExecutionOrder,
    PriceHistory,
    ReplayMarketBar,
    TradeLearningEvidence,
    LearningEvent,
)
from app.services.learning_loop import BASE_SIGNAL_WEIGHTS
from app.services.live_forward_paper_trading import LiveForwardPaperTradingService
from app.services.trading_intelligence_lab import latest_market_price_after
from app.services.paper_forward_opportunity_scanner import (
    BLOCKED_CANDIDATE,
    DATA_BLOCKED_CANDIDATE,
    TRADE_CANDIDATE,
    WATCHLIST_CANDIDATE,
    PaperForwardOpportunityScanner,
)


@pytest.fixture(autouse=True)
def use_same_currency_test_account(monkeypatch):
    monkeypatch.setattr("app.services.live_forward_paper_trading.settings.paper_execution_account_currency", "USD")


@pytest.fixture(autouse=True)
def advance_execution_clock_with_fixture_market_days(monkeypatch):
    execution_bars = LiveForwardPaperTradingService.daily_execution_bars

    def bars_at_fixture_time(self, db, ticker, after, *, now=None):
        return execution_bars(
            self, db, ticker, after,
            now=now if now is not None else db.info.get("fixture_market_time"),
        )

    monkeypatch.setattr(LiveForwardPaperTradingService, "daily_execution_bars", bars_at_fixture_time)


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


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
    db.add(
        PriceHistory(
            asset_id=asset.id,
            date=date.today(),
            open=close - 1,
            high=close + 1,
            low=close - 2,
            close=close,
            volume=1_000_000,
            provider="test",
        )
    )
    db.commit()
    return asset


def add_price(db: Session, asset: Asset, day_offset: int, close: float) -> None:
    market_date = date.today() + timedelta(days=day_offset)
    db.add(
        PriceHistory(
            asset_id=asset.id,
            date=market_date,
            open=close - 1,
            high=close + 1,
            low=close - 2,
            close=close,
            volume=1_000_000,
            provider="test",
        )
    )
    db.commit()
    # These lifecycle fixtures simulate later sessions, so advance the existing
    # execution clock injection point with the newly observed completed session.
    db.info["fixture_market_time"] = max(
        db.info.get("fixture_market_time", datetime.utcnow()),
        datetime.combine(market_date, time(hour=22)),
    )


def add_price_history(db: Session, asset: Asset, rows: int = 130, start_close: float = 100.0) -> None:
    for offset in range(1, rows + 1):
        db.add(
            PriceHistory(
                asset_id=asset.id,
                date=date.today() - timedelta(days=rows + 1 - offset),
                open=start_close + offset * 0.05 - 1,
                high=start_close + offset * 0.05 + 1,
                low=start_close + offset * 0.05 - 2,
                close=start_close + offset * 0.05,
                volume=1_000_000 + offset,
                provider="test",
            )
        )
    db.commit()


def run_lifecycle(service: LiveForwardPaperTradingService, db: Session) -> dict:
    return service.run_lifecycle(db, override=True)


def candidate(
    ticker: str = "NVDA",
    price: float | None = 100.0,
    *,
    actionability: str = "active_setup",
    confidence: float | None = 64.0,
    data_quality_score: float = 88.0,
    entry_type: str = "MARKET",
    trigger_price: float | None = None,
    invalidation_level: float = 96.0,
    target_1: float = 105.0,
    target_2: float = 112.0,
) -> dict:
    plan = {
        "entry_type": entry_type,
        "entry_trigger": "close above 100 with volume confirmation",
        "confirmation_condition": "relative volume > 1.5x",
        "invalidation_level": invalidation_level,
        "target_1": target_1,
        "target_2": target_2,
    }
    if trigger_price is not None:
        plan["trigger_price"] = trigger_price
    return {
        "ticker": ticker,
        "asset": {"name": ticker, "asset_type": "Stock", "sector": "Technology"},
        "actionability": actionability,
        "sniper_score": 78.0,
        "confidence": confidence,
        "setup": {"setup_type": "momentum_breakout"},
        "trade_plan": plan,
        "price_context": {"latest_price": price, "data_quality_score": data_quality_score, "rows": 120},
        "market_regime": {"regime_primary": "risk_on"},
    }


def install_scanner_payloads(monkeypatch, payloads: list[dict], db: Session | None = None) -> None:
    if db is not None:
        for payload in payloads:
            ticker = str(payload.get("ticker") or "").upper()
            if ticker and db.scalar(select(Asset).where(Asset.ticker == ticker)) is None:
                seed_asset(db, ticker, close=payload.get("price_context", {}).get("latest_price") or 100.0)
    monkeypatch.setattr(
        "app.services.live_forward_paper_trading.PaperForwardOpportunityScanner",
        lambda: PaperForwardOpportunityScanner(candidate_provider=lambda _db, _limit: payloads),
    )


def test_live_forward_duplicate_prevention_by_decision_key():
    with setup_db() as db:
        seed_asset(db)
        service = LiveForwardPaperTradingService()
        game = service.active_or_create_live_game(db)

        first = service.open_eligible_trades(db, game, [candidate()])
        second = service.open_eligible_trades(db, game, [candidate()])

        assert len(first["opened"]) == 1
        assert len(second["duplicates"]) == 1
        assert db.scalar(select(func.count(LiveForwardPaperTrade.id)).where(LiveForwardPaperTrade.ticker == "NVDA")) == 1


@pytest.mark.parametrize("verified_cutoff", [True, False])
def test_live_forward_freezes_decision_without_future_prices(verified_cutoff):
    with setup_db() as db:
        seed_asset(db)
        published = datetime.utcnow() - timedelta(days=1)
        provenance = {"contract_version": "legacy-direction-v1", "available_at": published.isoformat(),
                      "outcome_cutoff": (published - timedelta(days=1)).isoformat()} if verified_cutoff else {}
        db.add(ModelVersion(version="live-test-v1", weights={**BASE_SIGNAL_WEIGHTS, "sentiment": 0.5}, previous_weights=BASE_SIGNAL_WEIGHTS,
                            is_active=True, created_at=published, training_window=provenance))
        db.commit()
        service = LiveForwardPaperTradingService()
        game = service.active_or_create_live_game(db)

        service.open_eligible_trades(db, game, [candidate()])
        trade = db.scalar(select(LiveForwardPaperTrade).where(LiveForwardPaperTrade.ticker == "NVDA"))

        assert trade is not None
        assert trade.model_version_used == ("live-test-v1" if verified_cutoff else "base-static")
        assert trade.frozen_decision_payload["no_future_data_policy"].startswith("Frozen payload")
        assert "future_prices" not in trade.frozen_decision_payload
        if verified_cutoff:
            assert trade.weights_used["sentiment"] > BASE_SIGNAL_WEIGHTS["sentiment"]


def test_live_forward_open_update_close_and_lesson_creation():
    with setup_db() as db:
        asset = seed_asset(db)
        service = LiveForwardPaperTradingService()
        game = service.active_or_create_live_game(db)
        service.open_eligible_trades(db, game, [candidate()])
        trade = db.scalar(select(LiveForwardPaperTrade).where(LiveForwardPaperTrade.status == "OPEN"))
        assert trade is not None

        add_price(db, asset, 1, 106.0)
        updated = service.update_open_trades(db, game)
        lessons = service.publish_lessons(db, updated["closed"])
        db.commit()

        closed = db.get(LiveForwardPaperTrade, trade.id)
        assert closed.status == "CLOSED"
        assert closed.close_reason == "TARGET_1_HIT"
        assert closed.r_multiple is not None
        assert lessons
        assert db.scalar(select(TradeLearningEvidence).where(TradeLearningEvidence.trade_id == closed.ledger_trade_id)) is not None


def test_live_forward_data_blocked_when_no_future_market_data():
    with setup_db() as db:
        seed_asset(db)
        service = LiveForwardPaperTradingService()
        game = service.active_or_create_live_game(db)
        service.open_eligible_trades(db, game, [candidate()])

        updated = service.update_open_trades(db, game)
        events = db.scalars(select(LiveForwardPaperTradeEvent).where(LiveForwardPaperTradeEvent.event_type == "DATA_BLOCKED")).all()

        assert updated["data_blocked"]
        assert events


def test_live_forward_missing_entry_price_creates_data_blocked_decision():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()
        game = service.active_or_create_live_game(db)

        result = service.open_eligible_trades(db, game, [candidate(price=None)])

        assert len(result["data_blocked"]) == 1
        trade = db.scalar(select(LiveForwardPaperTrade).where(LiveForwardPaperTrade.status == "DATA_BLOCKED"))
        assert trade is not None
        assert trade.frozen_decision_payload["price_context"]["latest_price"] is None


def test_paper_forward_candidate_foundation_freezes_decision_and_event():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()

        trade = service.create_candidate(db, candidate())
        db.commit()

        stored = db.get(PaperForwardTrade, trade.id)
        event = db.scalar(select(PaperForwardTradeEvent).where(PaperForwardTradeEvent.paper_trade_id == trade.id))
        assert stored is not None
        assert stored.status == "CANDIDATE"
        assert stored.ledger_trade_id is None
        assert stored.open_timestamp is None
        assert stored.decision_payload_frozen["ticker"] == "NVDA"
        assert stored.decision_payload_frozen["no_future_data_policy"].startswith("Frozen payload")
        assert stored.weights_used
        assert event is not None
        assert event.event_type == "DECISION_CREATED"
        assert event.trade_id == trade.id


def test_create_candidate_preserves_scanner_metadata_and_benchmark_event():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()
        payload = candidate("AAPL")
        payload["asset"] = {
            **payload.get("asset", {}),
            "market": "us_equities",
            "asset_class": "equities",
            "benchmark_asset": "SPY",
            "benchmark_available": True,
            "data_quality_status": "OK",
            "tradability_status": "TRADABLE_FOR_PAPER",
        }
        payload["benchmark_context"] = {
            "benchmark_asset": "SPY",
            "benchmark_available": True,
            "benchmark_reason": "us_equities/Stock mapped to SPY",
        }
        payload["paper_forward_classification"] = TRADE_CANDIDATE
        payload["opportunity_scanner"] = {
            "classification": TRADE_CANDIDATE,
            "rank": 1,
            "score": 88.5,
            "market": "us_equities",
            "asset_class": "equities",
            "benchmark_asset": "SPY",
        }

        trade = service.create_candidate(db, payload)
        db.commit()

        frozen = trade.frozen_decision_payload
        benchmark_event = db.scalar(
            select(PaperForwardTradeEvent).where(
                PaperForwardTradeEvent.paper_trade_id == trade.id,
                PaperForwardTradeEvent.event_type == "BENCHMARK_MAPPED",
            )
        )
        assert frozen["paper_forward_classification"] == TRADE_CANDIDATE
        assert frozen["opportunity_scanner"]["market"] == "us_equities"
        assert frozen["asset"]["asset_class"] == "equities"
        assert frozen["asset"]["benchmark_asset"] == "SPY"
        assert benchmark_event is not None
        assert benchmark_event.payload["benchmark_asset"] == "SPY"


def test_paper_forward_create_candidate_is_idempotent():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()

        first = service.create_candidate(db, candidate())
        second = service.create_candidate(db, candidate())
        db.commit()

        assert second.id == first.id
        assert db.scalar(select(func.count(PaperForwardTrade.id)).where(PaperForwardTrade.ticker == "NVDA")) == 1


def test_paper_forward_avoid_candidate_is_skipped_with_actionability_rejection_event():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()

        trade = service.create_candidate(db, candidate(actionability="avoid", target_1=110.0, invalidation_level=96.0))
        db.commit()

        stored = db.get(PaperForwardTrade, trade.id)
        events = db.scalars(select(PaperForwardTradeEvent).where(PaperForwardTradeEvent.paper_trade_id == trade.id)).all()
        rejection = [event for event in events if event.event_type == "ACTIONABILITY_REJECTED"][0]

        assert stored.status == "SKIPPED"
        assert stored.decision_payload_frozen["actionability_diagnosis"]["actionability_status"] == "SKIPPED_AVOID_SIGNAL"
        assert rejection.reason == "actionability_avoid"
        assert rejection.payload["actionability_status"] == "SKIPPED_AVOID_SIGNAL"
        assert not any(event.event_type == "ERROR" for event in events)


def test_paper_forward_bad_risk_reward_has_specific_rejection_reason():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()

        trade = service.create_candidate(db, candidate(actionability="active_setup", target_1=101.0, invalidation_level=96.0))
        db.commit()

        stored = db.get(PaperForwardTrade, trade.id)
        event = db.scalar(select(PaperForwardTradeEvent).where(PaperForwardTradeEvent.paper_trade_id == trade.id, PaperForwardTradeEvent.event_type == "ACTIONABILITY_REJECTED"))

        assert stored.status == "SKIPPED"
        assert stored.decision_payload_frozen["actionability_diagnosis"]["actionability_status"] == "REJECTED_BAD_RISK_REWARD"
        assert event.payload["risk_reward_ratio"] == 0.25


def test_paper_forward_wait_for_trigger_status_is_not_error():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()

        trade = service.create_candidate(db, candidate(actionability="wait_for_trigger"))
        db.commit()

        stored = db.get(PaperForwardTrade, trade.id)
        event = db.scalar(select(PaperForwardTradeEvent).where(PaperForwardTradeEvent.paper_trade_id == trade.id, PaperForwardTradeEvent.event_type == "ACTIONABILITY_REJECTED"))

        assert stored.status == "WAITING_FOR_TRIGGER"
        assert stored.decision_payload_frozen["actionability_diagnosis"]["actionability_status"] == "WAITING_FOR_TRIGGER"
        assert event is not None


def test_waiting_candidate_opens_after_later_frozen_trigger_is_confirmed():
    with setup_db() as db:
        asset = seed_asset(db, close=100.0)
        service = LiveForwardPaperTradingService()
        payload = candidate(
            actionability="wait_for_trigger",
            entry_type="ABOVE_TRIGGER",
            trigger_price=101.0,
            target_1=110.0,
            target_2=116.0,
        )
        payload["paper_forward_classification"] = WATCHLIST_CANDIDATE
        trade = service.create_candidate(db, payload)
        db.commit()
        assert trade.status == "WAITING_FOR_TRIGGER"

        add_price(db, asset, 1, 102.0)
        result = service.open_eligible_trades(db)
        db.commit()

        stored = db.get(PaperForwardTrade, trade.id)
        order = db.scalar(select(PaperExecutionOrder).where(PaperExecutionOrder.paper_trade_id == trade.id))
        assert [row["trade_id"] for row in result["opened"]] == [trade.id]
        assert stored.status == "OPEN"
        assert stored.entry_price == order.average_fill_price
        assert stored.entry_price != 102.0
        assert stored.expected_risk <= stored.risk_amount
        assert stored.decision_payload_frozen["trade_plan"]["trigger_price"] == 101.0


def test_waiting_candidate_is_skipped_when_entry_risk_reward_has_deteriorated():
    with setup_db() as db:
        asset = seed_asset(db, close=100.0)
        service = LiveForwardPaperTradingService()
        payload = candidate(
            actionability="wait_for_trigger",
            entry_type="ABOVE_TRIGGER",
            trigger_price=101.0,
            invalidation_level=96.0,
            target_1=105.0,
            target_2=112.0,
        )
        payload["paper_forward_classification"] = WATCHLIST_CANDIDATE
        trade = service.create_candidate(db, payload)
        db.commit()

        add_price(db, asset, 1, 104.0)
        result = service.open_eligible_trades(db)
        db.commit()

        stored = db.get(PaperForwardTrade, trade.id)
        event = db.scalar(
            select(PaperForwardTradeEvent).where(
                PaperForwardTradeEvent.paper_trade_id == trade.id,
                PaperForwardTradeEvent.event_type == "ENTRY_RISK_REWARD_DETERIORATED",
            )
        )
        assert result["opened"] == []
        assert result["skipped"][0]["reason"] == "entry_risk_reward_deteriorated"
        assert stored.status == "SKIPPED"
        assert stored.outcome_label == "NO_TRADE_ENTRY_GEOMETRY"
        assert stored.ledger_trade_id is None
        assert event is not None
        assert event.payload["actual_risk_reward"] < 1.0


def test_lifecycle_quarantines_closed_watchlist_trade_with_invalid_entry_geometry():
    with setup_db() as db:
        seed_asset(db, close=100.0)
        service = LiveForwardPaperTradingService()
        payload = candidate(
            actionability="wait_for_trigger",
            entry_type="ABOVE_TRIGGER",
            trigger_price=101.0,
            invalidation_level=96.0,
            target_1=105.0,
            target_2=112.0,
        )
        payload["paper_forward_classification"] = WATCHLIST_CANDIDATE
        trade = service.create_candidate(db, payload)
        trade.status = "CLOSED"
        trade.entry_price = 104.0
        trade.exit_price = 104.0
        trade.closed_at = datetime.utcnow()
        trade.close_reason = "TARGET_1_HIT"
        trade.outcome_label = "BREAKEVEN"
        db.add(
            PaperForwardTradeEvent(
                paper_trade_id=trade.id,
                event_type="WATCHLIST_TRIGGER_CONFIRMED",
                price_used=104.0,
                reason="Legacy watchlist entry.",
                payload={},
            )
        )
        db.commit()

        result = service.quarantine_invalid_entry_geometry(db)
        db.commit()

        stored = db.get(PaperForwardTrade, trade.id)
        event = db.scalar(
            select(PaperForwardTradeEvent).where(
                PaperForwardTradeEvent.paper_trade_id == trade.id,
                PaperForwardTradeEvent.event_type == "EVIDENCE_QUARANTINED",
            )
        )
        assert result["quarantined"] == [trade.id]
        assert stored.evidence_type == "PAPER_FORWARD_INVALID_ENTRY_GEOMETRY"
        assert stored.outcome_label == "EVIDENCE_QUARANTINED"
        assert event is not None


def test_new_market_snapshot_creates_new_candidate_without_overwriting_frozen_decision():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()
        first_payload = candidate(price=100.0, actionability="wait_for_trigger")
        first_payload["paper_forward_classification"] = WATCHLIST_CANDIDATE
        first_payload["price_context"]["data_timestamp"] = "2026-07-20T14:00:00"
        first = service.create_candidate(db, first_payload)

        second_payload = candidate(price=102.0, actionability="active_setup")
        second_payload["paper_forward_classification"] = TRADE_CANDIDATE
        second_payload["price_context"]["data_timestamp"] = "2026-07-20T14:05:00"
        second = service.create_candidate(db, second_payload)
        db.commit()

        assert second.id != first.id
        assert first.decision_payload_frozen["price_context"]["latest_price"] == 100.0
        assert second.decision_payload_frozen["price_context"]["latest_price"] == 102.0
        assert db.scalar(select(func.count(PaperForwardTrade.id)).where(PaperForwardTrade.ticker == "NVDA")) == 2


def test_paper_forward_append_event_uses_event_log():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(db, candidate())

        event = service.append_event(db, trade.id, "POSITION_UPDATED", "manual test event", payload={"check": True}, price_used=101.0)
        db.commit()

        assert event.id is not None
        assert event.trade_id == trade.id
        assert event.payload["check"] is True
        assert event.price_used == 101.0


def test_paper_forward_snapshot_get_is_read_only_without_snapshot():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()

        before = db.scalar(select(func.count(PaperForwardTrade.id)))
        payload = service.snapshot(db)
        after = db.scalar(select(func.count(PaperForwardTrade.id)))

        assert payload["status"] == "missing"
        assert before == after == 0


def test_paper_forward_get_style_methods_are_read_only_and_report_blockers():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()

        before = db.scalar(select(func.count(PaperForwardTrade.id)))
        status = service.status_readonly(db)
        trades = service.paper_trades(db, limit=5)
        detail = service.trade_detail(db, 999)
        events = service.events(db, 999)
        after = db.scalar(select(func.count(PaperForwardTrade.id)))

        assert before == after == 0
        assert status["readiness"] == "NO_SNAPSHOTS"
        assert status["current_blockers"] == ["no_live_forward_paper_game"]
        assert trades["rows"] == []
        assert detail["status"] == "not_found"
        assert events["events"] == []


def test_paper_forward_run_once_freezes_candidates_without_opening_positions(monkeypatch):
    with setup_db() as db:
        service = LiveForwardPaperTradingService()
        install_scanner_payloads(monkeypatch, [candidate()], db)

        report = service.run_once(db)
        trade = db.scalar(select(PaperForwardTrade).where(PaperForwardTrade.ticker == "NVDA"))
        events = db.scalars(select(PaperForwardTradeEvent).where(PaperForwardTradeEvent.paper_trade_id == trade.id)).all()

        assert report["status"] == "ok"
        assert report["mode"] == "foundation_candidate_freeze"
        assert trade.status == "CANDIDATE"
        assert trade.ledger_trade_id is None
        assert any(event.event_type == "DECISION_CREATED" for event in events)


def test_live_trading_run_cycle_delegates_to_scanner_owned_foundation(monkeypatch):
    calls = {"run_once": 0}

    def fake_run_once(self, db):
        calls["run_once"] += 1
        return {"status": "ok", "mode": "foundation_candidate_freeze", "scanner_summary": {"scanned_count": 0}}

    monkeypatch.setattr("app.services.live_forward_paper_trading.settings.paper_forward_lifecycle_enabled", False)
    monkeypatch.setattr(LiveForwardPaperTradingService, "run_once", fake_run_once)

    with setup_db() as db:
        report = LiveForwardPaperTradingService().run_cycle(db)

    assert calls["run_once"] == 1
    assert report["mode"] == "foundation_candidate_freeze"


def test_paper_forward_run_once_reports_actionability_summary(monkeypatch):
    monkeypatch.setattr("app.services.live_forward_paper_trading.settings.paper_forward_lifecycle_enabled", False)
    with setup_db() as db:
        service = LiveForwardPaperTradingService()
        install_scanner_payloads(monkeypatch, [
            candidate(),
            candidate(ticker="AMD", actionability="avoid", target_1=101.0),
            candidate(ticker="MSFT", price=None),
        ], db)

        report = service.run_once(db)
        snapshot = service.snapshot_payload(db)

        assert report["actionability_summary"]["total_candidates"] == 3
        assert snapshot["actionability_summary"]["actionable_count"] == 1
        assert snapshot["actionability_summary"]["skipped_count"] == 1
        assert snapshot["actionability_summary"]["data_blocked_count"] == 1
        assert snapshot["paper_forward_lifecycle_mode"] == "CANDIDATE_FREEZE_ONLY"


def test_actionability_summary_does_not_count_skipped_trade_as_operationally_actionable():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(db, candidate())
        trade.status = "SKIPPED"
        trade.classification_reason = "entry_geometry_deteriorated"
        db.commit()

        summary = service.actionability_summary(db)

    assert summary["actionable_count"] == 0
    assert summary["skipped_count"] == 1


def test_lifecycle_selection_prioritizes_active_candidate_over_old_waiting_rows():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()
        game = service.active_or_create_live_game(db)
        for index in range(51):
            db.add(
                PaperForwardTrade(
                    trade_uid=f"waiting-{index}",
                    duplicate_key=f"waiting-{index}",
                    game_id=game.id,
                    ticker=f"W{index}",
                    setup_type="pullback",
                    status="WAITING_FOR_TRIGGER",
                    decision_timestamp=datetime(2026, 1, 1) + timedelta(minutes=index),
                    sniper_score=90.0,
                )
            )
        active = PaperForwardTrade(
            trade_uid="active-priority",
            duplicate_key="active-priority",
            game_id=game.id,
            ticker="NVDA",
            setup_type="momentum_breakout",
            status="CANDIDATE",
            decision_timestamp=datetime(2026, 2, 1),
            sniper_score=70.0,
            frozen_decision_payload={"opportunity_scanner": {"score": 95.0}},
        )
        lower_ranked = PaperForwardTrade(
            trade_uid="lower-composite-priority",
            duplicate_key="lower-composite-priority",
            game_id=game.id,
            ticker="META",
            setup_type="momentum_breakout",
            status="CANDIDATE",
            decision_timestamp=datetime(2026, 2, 2),
            sniper_score=99.0,
            frozen_decision_payload={"opportunity_scanner": {"score": 50.0}},
        )
        db.add_all([active, lower_ranked])
        db.commit()

        selected = service.lifecycle_candidates(db, game)

    assert len(selected) == 50
    assert selected[0].trade_uid == "active-priority"


def test_paper_forward_opportunity_scanner_classifies_trade_watchlist_blocked_and_data_blocked():
    with setup_db() as db:
        seed_asset(db, "NVDA")
        seed_asset(db, "AMD")
        seed_asset(db, "MSFT")
        scanner = PaperForwardOpportunityScanner(
            candidate_provider=lambda _db, _limit: [
                candidate(ticker="NVDA", confidence=72.0, target_1=112.0, invalidation_level=96.0),
                candidate(ticker="AMD", actionability="wait_for_trigger", confidence=66.0, target_1=110.0, invalidation_level=96.0),
                candidate(ticker="MSFT", actionability="active_setup", confidence=20.0, target_1=102.0, invalidation_level=96.0),
                candidate(ticker="TSLA", price=None),
            ]
        )

        report = scanner.scan(db, limit=4)

        assert report["scanned_count"] == 4
        assert report["trade_candidate_count"] == 1
        assert report["watchlist_candidate_count"] == 1
        assert report["blocked_candidate_count"] == 1
        assert report["data_blocked_candidate_count"] == 1
        assert report["best_trade_candidate"]["classification"] == TRADE_CANDIDATE
        assert report["best_watchlist_candidate"]["classification"] == WATCHLIST_CANDIDATE
        assert any(item["paper_forward_classification"] == BLOCKED_CANDIDATE for item in report["candidate_payloads_for_persistence"])
        assert any(item["paper_forward_classification"] == DATA_BLOCKED_CANDIDATE for item in report["candidate_payloads_for_persistence"])
        assert report["markets_scanned"]
        assert report["asset_classes_scanned"]
        assert report["skipped_markets"]


def test_paper_forward_run_once_returns_scanner_summary_and_persists_classifications(monkeypatch):
    with setup_db() as db:
        service = LiveForwardPaperTradingService()
        install_scanner_payloads(monkeypatch, [
            candidate(ticker="NVDA", confidence=72.0, target_1=112.0, invalidation_level=96.0),
            candidate(ticker="AMD", actionability="wait_for_trigger", confidence=66.0, target_1=110.0, invalidation_level=96.0),
            candidate(ticker="TSLA", price=None),
        ], db)

        report = service.run_once(db)
        rows = db.scalars(select(PaperForwardTrade).order_by(PaperForwardTrade.ticker)).all()
        snapshot = service.snapshot_payload(db)

        assert report["scanner_summary"]["scanned_count"] == 3
        assert report["scanner_summary"]["trade_candidate_count"] == 1
        assert report["scanner_summary"]["watchlist_candidate_count"] == 1
        assert report["scanner_summary"]["data_blocked_candidate_count"] == 1
        assert report["markets_scanned"]
        assert report["skipped_markets"]
        assert {row.frozen_decision_payload["paper_forward_classification"] for row in rows} == {
            TRADE_CANDIDATE,
            WATCHLIST_CANDIDATE,
            DATA_BLOCKED_CANDIDATE,
        }
        assert snapshot["scanned_count"] == 3
        assert snapshot["trade_candidate_count"] == 1
        assert snapshot["watchlist_candidate_count"] == 1
        assert snapshot["data_blocked_candidate_count"] == 1


def test_paper_forward_snapshot_exposes_scanner_acceleration_and_count_reasons():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()
        payload = candidate("NVDA")
        payload["asset"] = {
            **payload.get("asset", {}),
            "market": "us_equities",
            "asset_class": "equities",
            "benchmark_asset": "SPY",
        }
        payload["benchmark_context"] = {"benchmark_asset": "SPY", "benchmark_available": True}
        payload["paper_forward_classification"] = TRADE_CANDIDATE
        payload["opportunity_scanner"] = {
            "classification": TRADE_CANDIDATE,
            "rank": 1,
            "score": 92.0,
            "market": "us_equities",
            "asset_class": "equities",
            "benchmark_asset": "SPY",
        }

        service.create_candidate(db, payload)
        db.add(
            LearningEvent(
                event_type="OPPORTUNITY_SCANNED",
                severity="Info",
                title="Paper-forward scanner completed",
                description="Scanner found candidates and learning priorities.",
                payload={
                    "generated_at": datetime.utcnow().isoformat(),
                    "scanned_count": 48,
                    "trade_candidate_count": 4,
                    "watchlist_candidate_count": 9,
                    "blocked_candidate_count": 21,
                    "data_blocked_candidate_count": 14,
                    "best_cross_market_candidate": {"ticker": "NVDA", "score": 92.0},
                    "markets_scanned": ["us_equities", "europe_equities"],
                    "asset_classes_scanned": ["equities", "etfs"],
                    "enabled_market_desk_agents": ["NasdaqAgent", "DAXAgent"],
                    "agents_run": ["NasdaqAgent"],
                    "agents_skipped": [{"agent_name": "DAXAgent", "status": "NO_ASSETS_CONFIGURED"}],
                    "opportunities_by_agent": {"NasdaqAgent": {"trade_candidates": 4}},
                    "best_opportunity_by_agent": {"NasdaqAgent": {"ticker": "NVDA", "score": 92.0}},
                    "top_cross_market_opportunities": [{"ticker": "NVDA", "score": 92.0}],
                    "quant_edge_summary": {"assessed_count": 14, "approved_count": 4},
                    "rejected_no_edge_count": 3,
                    "rejected_overfitting_count": 2,
                    "rejected_insufficient_sample_count": 5,
                    "diversification_summary": {"selected_by_market": {"nasdaq": 4}},
                    "repeated_ticker_warning": False,
                    "reason_if_same_tickers_repeat": None,
                    "learning_acceleration": {
                        "status": "ready",
                        "priority_markets": ["us_equities"],
                        "priority_setups": ["momentum_breakout"],
                        "repeated_blockers": ["BENCHMARK_STALE"],
                        "missed_opportunity_targets": ["NVDA"],
                    },
                },
            )
        )
        db.commit()

        snapshot = service.snapshot_payload(db)

        assert snapshot["scanner_last_run_at"] is not None
        assert snapshot["scanned_count"] == 48
        assert snapshot["trade_candidate_count"] == 4
        assert snapshot["best_cross_market_candidate"]["ticker"] == "NVDA"
        assert snapshot["markets_scanned"] == ["us_equities", "europe_equities"]
        assert snapshot["learning_acceleration_status"] == "ready"
        assert snapshot["priority_markets"] == ["us_equities"]
        assert snapshot["priority_setups"] == ["momentum_breakout"]
        assert snapshot["repeated_blockers"] == ["BENCHMARK_STALE"]
        assert snapshot["missed_opportunity_targets"] == ["NVDA"]
        assert snapshot["enabled_market_desk_agents"] == ["NasdaqAgent", "DAXAgent"]
        assert snapshot["agents_run"] == ["NasdaqAgent"]
        assert snapshot["agents_skipped"][0]["agent_name"] == "DAXAgent"
        assert snapshot["opportunities_by_agent"]["NasdaqAgent"]["trade_candidates"] == 4
        assert snapshot["top_cross_market_opportunities"][0]["ticker"] == "NVDA"
        assert snapshot["quant_edge_summary"]["approved_count"] == 4
        assert snapshot["rejected_insufficient_sample_count"] == 5
        assert snapshot["diversification_summary"]["selected_by_market"] == {"nasdaq": 4}
        assert "No paper-forward trades have opened yet" in snapshot["open_count_reason"]
        assert "No paper-forward trades have closed yet" in snapshot["closed_count_reason"]


def test_paper_forward_scouting_falls_back_to_real_ohlcv_universe(monkeypatch):
    with setup_db() as db:
        nvda = seed_asset(db, "NVDA")
        amd = seed_asset(db, "AMD")
        add_price_history(db, nvda)
        add_price_history(db, amd)

        monkeypatch.setattr(
            "app.services.market_sniper.MarketSniperEngine.candidates",
            lambda self, _db, limit=30, persist=False: {"candidates": []},
        )
        monkeypatch.setattr(
            "app.services.market_sniper.MarketSniperEngine.evaluate_asset",
            lambda self, _db, asset, persist=False: candidate(ticker=asset.ticker),
        )

        rows = LiveForwardPaperTradingService().scan_candidates(db, limit=2)

        assert {row["ticker"] for row in rows} == {"AMD", "NVDA"}
        assert all(row["scouting_source"] == "broad_ohlcv_universe" for row in rows)
        assert all(row["scouting_policy"] == "real_stored_ohlcv_only_no_synthetic_candidates" for row in rows)


def test_paper_forward_run_lifecycle_refuses_when_disabled_without_override(monkeypatch):
    monkeypatch.setattr("app.services.live_forward_paper_trading.settings.paper_forward_lifecycle_enabled", False)
    with setup_db() as db:
        service = LiveForwardPaperTradingService()
        service.create_candidate(db, candidate())
        db.commit()

        report = service.run_lifecycle(db)
        stored = db.scalar(select(PaperForwardTrade).where(PaperForwardTrade.ticker == "NVDA"))

        assert report["status"] == "disabled"
        assert report["paper_forward_lifecycle_mode"] == "LIFECYCLE_DISABLED_BY_SETTINGS"
        assert "paper_forward_lifecycle_disabled_by_settings" in report["current_blockers"]
        assert stored.status == "CANDIDATE"
        assert stored.ledger_trade_id is None


def test_paper_forward_run_once_duplicate_does_not_overwrite_frozen_payload(monkeypatch):
    with setup_db() as db:
        service = LiveForwardPaperTradingService()
        install_scanner_payloads(monkeypatch, [candidate()], db)

        first_report = service.run_once(db)
        trade = db.scalar(select(PaperForwardTrade).where(PaperForwardTrade.ticker == "NVDA"))
        frozen_before = dict(trade.decision_payload_frozen)

        install_scanner_payloads(monkeypatch, [candidate(price=100.0) | {"confidence": 12.0}], db)
        second_report = service.run_once(db)
        refreshed = db.get(PaperForwardTrade, trade.id)

        assert first_report["created"]
        assert second_report["duplicates"]
        assert db.scalar(select(func.count(PaperForwardTrade.id)).where(PaperForwardTrade.ticker == "NVDA")) == 1
        assert refreshed.id == trade.id
        assert refreshed.decision_payload_frozen == frozen_before
        assert refreshed.decision_payload_frozen["confidence"] == 64.0


def test_paper_forward_lifecycle_opens_candidate_when_trigger_is_met():
    with setup_db() as db:
        asset = seed_asset(db)
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(db, candidate(entry_type="ABOVE_TRIGGER", trigger_price=102.0, target_1=130.0, target_2=150.0))
        frozen_before = dict(trade.frozen_decision_payload)
        add_price(db, asset, 1, 103.0)

        report = run_lifecycle(service, db)
        opened = db.get(PaperForwardTrade, trade.id)
        events = db.scalars(select(PaperForwardTradeEvent).where(PaperForwardTradeEvent.paper_trade_id == trade.id)).all()

        assert report["status"] == "ok"
        assert opened.status == "OPEN"
        order = db.scalar(select(PaperExecutionOrder).where(PaperExecutionOrder.paper_trade_id == trade.id))
        assert opened.open_price == order.average_fill_price
        assert opened.open_price != 103.0
        assert opened.ledger_trade_id is not None
        assert opened.decision_payload_frozen == frozen_before
        assert any(event.event_type == "ENTRY_TRIGGERED" for event in events)
        assert any(event.event_type == "POSITION_OPENED" for event in events)


def test_daily_paper_trigger_opens_only_from_persisted_realistic_fill():
    with setup_db() as db:
        asset = seed_asset(db)
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(
            db,
            candidate(entry_type="ABOVE_TRIGGER", trigger_price=102.0, target_1=130.0, target_2=150.0),
        )
        add_price(db, asset, 1, 103.0)

        run_lifecycle(service, db)
        run_lifecycle(service, db)
        stored = db.get(PaperForwardTrade, trade.id)
        order = db.scalar(select(PaperExecutionOrder).where(PaperExecutionOrder.paper_trade_id == trade.id))
        fills = db.scalars(select(PaperExecutionFill).where(PaperExecutionFill.order_id == order.id)).all() if order else []
        order_count = db.scalar(select(func.count(PaperExecutionOrder.id)).where(PaperExecutionOrder.paper_trade_id == trade.id))

    assert order is not None
    assert order_count == 1
    assert order.status == "FILLED"
    assert len(fills) == 1
    assert stored.status == "OPEN"
    assert stored.entry_price == order.average_fill_price
    assert stored.entry_price != 103.0
    assert stored.costs_paid > 0


def test_daily_paper_execution_blocks_missing_point_in_time_fx(monkeypatch):
    monkeypatch.setattr("app.services.live_forward_paper_trading.settings.paper_execution_account_currency", "EUR")
    with setup_db() as db:
        asset = seed_asset(db)
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(
            db,
            candidate(entry_type="ABOVE_TRIGGER", trigger_price=102.0, target_1=130.0, target_2=150.0),
        )
        add_price(db, asset, 1, 103.0)

        report = run_lifecycle(service, db)
        stored = db.get(PaperForwardTrade, trade.id)

    assert stored.status == "SKIPPED"
    assert stored.outcome_label == "DATA_BLOCKED"
    assert any(row["reason"] == "fx_rate_unavailable" for row in report["phases"]["open_eligible_trades"]["skipped"])


def test_daily_point_in_time_fx_rate_reuses_stored_intraday_fx_evidence(monkeypatch):
    monkeypatch.setattr("app.services.live_forward_paper_trading.settings.paper_execution_account_currency", "EUR")
    with setup_db() as db:
        fx_asset = Asset(
            ticker="EURUSD=X",
            name="EUR/USD",
            category="Currency",
            sector="Foreign Exchange",
            industry="Major FX Pair",
            country="Forex",
            asset_type="Forex",
            currency="USD",
            exchange="FX",
            is_active=True,
        )
        db.add(fx_asset)
        db.flush()
        at = datetime.utcnow()
        db.add(
            ReplayMarketBar(
                asset_id=fx_asset.id,
                source_symbol=fx_asset.ticker,
                normalized_symbol=fx_asset.ticker,
                market="FOREX",
                timeframe="1m",
                bar_timestamp=at - timedelta(minutes=1),
                open=1.0899,
                high=1.0902,
                low=1.0897,
                close=1.09,
                volume=0,
                provider="fixture",
                acquired_at=at,
                data_quality_score=90.0,
            )
        )
        db.commit()

        rate = LiveForwardPaperTradingService().daily_point_in_time_fx_rate(db, "USD", "EUR", at)

    assert rate == 1.09


def test_equity_trigger_can_mature_from_later_stored_intraday_bar():
    with setup_db() as db:
        asset = seed_asset(db)
        decision_at = datetime.utcnow() - timedelta(hours=2)
        observed_at = decision_at + timedelta(hours=1)
        db.add(
            ReplayMarketBar(
                asset_id=asset.id,
                source_symbol=asset.ticker,
                normalized_symbol=asset.ticker,
                market="USA",
                timeframe="1h",
                bar_timestamp=observed_at,
                open=101.0,
                high=103.0,
                low=100.5,
                close=102.5,
                volume=500_000,
                provider="fixture",
                acquired_at=observed_at,
                data_quality_score=95.0,
            )
        )
        db.commit()

        observation = latest_market_price_after(
            db,
            asset.ticker,
            decision_at,
            now=decision_at + timedelta(hours=1, minutes=5),
        )

    assert observation == (observed_at.date(), 102.5)


def test_equity_trigger_ignores_intraday_bar_after_runtime_now():
    with setup_db() as db:
        asset = seed_asset(db)
        decision_at = datetime.utcnow() - timedelta(hours=2)
        runtime_now = decision_at + timedelta(minutes=30)
        db.add(
            ReplayMarketBar(
                asset_id=asset.id,
                source_symbol=asset.ticker,
                normalized_symbol=asset.ticker,
                market="USA",
                timeframe="1h",
                bar_timestamp=runtime_now + timedelta(minutes=30),
                open=101.0,
                high=104.0,
                low=100.0,
                close=103.0,
                volume=500_000,
                provider="fixture",
                acquired_at=runtime_now + timedelta(minutes=30),
                data_quality_score=95.0,
            )
        )
        db.commit()

        observation = latest_market_price_after(
            db,
            asset.ticker,
            decision_at,
            now=runtime_now,
        )

    assert observation is None


def test_equity_execution_bars_use_only_post_decision_observations_up_to_now():
    with setup_db() as db:
        asset = seed_asset(db)
        decision_at = datetime.utcnow() - timedelta(hours=3)
        runtime_now = decision_at + timedelta(hours=2)
        for offset, close in ((-30, 99.0), (30, 101.0), (90, 102.0), (150, 110.0)):
            timestamp = decision_at + timedelta(minutes=offset)
            db.add(
                ReplayMarketBar(
                    asset_id=asset.id,
                    source_symbol=asset.ticker,
                    normalized_symbol=asset.ticker,
                    market="USA",
                    timeframe="1h",
                    bar_timestamp=timestamp,
                    open=close - 0.5,
                    high=close + 1.0,
                    low=close - 1.0,
                    close=close,
                    volume=500_000,
                    provider="fixture",
                    acquired_at=timestamp,
                    data_quality_score=95.0,
                )
            )
        db.commit()

        bars = LiveForwardPaperTradingService().daily_execution_bars(
            db,
            asset.ticker,
            decision_at,
            now=runtime_now,
        )

    assert [bar.close for bar in bars] == [101.0, 102.0]
    assert all(decision_at < bar.timestamp <= runtime_now for bar in bars)


@pytest.mark.parametrize(
    ("market", "runtime_now", "expected_closes", "latest_available_at"),
    (
        ("USA", datetime(2024, 1, 3, 12), [101.0], datetime(2024, 1, 2, 21, 1)),
        ("USA", datetime(2024, 1, 3, 21, 0, 59), [101.0], datetime(2024, 1, 2, 21, 1)),
        ("USA", datetime(2024, 1, 3, 21, 1), [101.0, 102.0], datetime(2024, 1, 3, 21, 1)),
        ("USA", datetime(2024, 7, 9, 12), [101.0], datetime(2024, 7, 8, 20, 1)),
        ("USA", datetime(2024, 7, 9, 20, 0, 59), [101.0], datetime(2024, 7, 8, 20, 1)),
        ("USA", datetime(2024, 7, 9, 20, 1), [101.0, 102.0], datetime(2024, 7, 9, 20, 1)),
        ("US", datetime(2024, 1, 3, 12), [101.0], datetime(2024, 1, 2, 21, 1)),
        ("United States", datetime(2024, 7, 9, 20, 1), [101.0, 102.0], datetime(2024, 7, 9, 20, 1)),
    ),
)
def test_daily_execution_bars_respect_virtual_clock_and_new_york_close(
    market, runtime_now, expected_closes, latest_available_at
):
    with setup_db() as db:
        asset = seed_asset(db)
        asset.country = market
        for offset, close in ((-1, 101.0), (0, 102.0), (1, 110.0)):
            db.add(
                PriceHistory(
                    asset_id=asset.id,
                    date=runtime_now.date() + timedelta(days=offset),
                    open=close - 0.5,
                    high=close + 1,
                    low=close - 1,
                    close=close,
                    volume=500_000,
                    provider="fixture",
                )
            )
        db.commit()
        decision_at = datetime.combine(runtime_now.date() - timedelta(days=2), time(hour=22))

        bars = LiveForwardPaperTradingService().daily_execution_bars(
            db, asset.ticker, decision_at, now=runtime_now
        )

    assert [bar.close for bar in bars] == expected_closes
    assert bars[-1].timestamp == latest_available_at
    assert all(decision_at < bar.timestamp <= runtime_now for bar in bars)


def test_daily_execution_bars_can_use_intraday_fallback_before_daily_close():
    with setup_db() as db:
        asset = seed_asset(db)
        db.add(
            PriceHistory(
                asset_id=asset.id, date=date(2024, 1, 3),
                open=100, high=112, low=98, close=110,
                volume=500_000, provider="fixture",
            )
        )
        db.add(
            ReplayMarketBar(
                asset_id=asset.id, source_symbol=asset.ticker, normalized_symbol=asset.ticker,
                market="USA", timeframe="1h", bar_timestamp=datetime(2024, 1, 3, 12),
                open=100, high=102, low=99, close=101, volume=100_000,
                provider="fixture", acquired_at=datetime(2024, 1, 3, 12), data_quality_score=95,
            )
        )
        db.commit()

        bars = LiveForwardPaperTradingService().daily_execution_bars(
            db, asset.ticker, datetime(2024, 1, 2, 18), now=datetime(2024, 1, 3, 13)
        )

    assert [(bar.timestamp, bar.close) for bar in bars] == [(datetime(2024, 1, 3, 12), 101.0)]


def test_cost_adjusted_edge_gate_rejects_zero_expectancy_setup():
    with setup_db() as db:
        asset = seed_asset(db)
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(
            db,
            candidate(
                confidence=50.0,
                entry_type="ABOVE_TRIGGER",
                trigger_price=102.0,
                invalidation_level=96.0,
                target_1=110.0,
                target_2=115.0,
            ),
        )
        add_price(db, asset, 1, 103.0)

        report = run_lifecycle(service, db)
        stored = db.get(PaperForwardTrade, trade.id)

    assert stored.status == "SKIPPED"
    assert stored.outcome_label == "EDGE_DESTROYED_BY_COSTS"
    assert any(row["reason"] == "non_positive_net_expectancy" for row in report["phases"]["open_eligible_trades"]["skipped"])


def test_paper_forward_lifecycle_allows_only_one_open_position_per_ticker():
    with setup_db() as db:
        asset = seed_asset(db)
        service = LiveForwardPaperTradingService()
        first_payload = candidate(target_1=130.0, target_2=150.0)
        second_payload = candidate(target_1=128.0, target_2=145.0)
        second_payload["setup"] = {"setup_type": "pullback"}
        second_payload["trade_plan"] = {
            **second_payload["trade_plan"],
            "entry_trigger": "pullback reclaim above support",
        }
        service.create_candidate(db, first_payload)
        service.create_candidate(db, second_payload)
        add_price(db, asset, 1, 101.0)

        report = run_lifecycle(service, db)
        open_rows = db.scalars(
            select(PaperForwardTrade).where(
                PaperForwardTrade.ticker == "NVDA",
                PaperForwardTrade.status == "OPEN",
            )
        ).all()

    assert len(open_rows) == 1
    assert any(
        row.get("reason") == "ticker_position_already_open"
        for row in report["phases"]["open_eligible_trades"]["skipped"]
    )


def test_paper_forward_lifecycle_keeps_candidate_when_trigger_not_met():
    with setup_db() as db:
        asset = seed_asset(db)
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(db, candidate(entry_type="ABOVE_TRIGGER", trigger_price=104.0, target_1=130.0, target_2=150.0))
        add_price(db, asset, 1, 101.0)

        report = run_lifecycle(service, db)
        stored = db.get(PaperForwardTrade, trade.id)
        opened_events = db.scalars(
            select(PaperForwardTradeEvent).where(PaperForwardTradeEvent.paper_trade_id == trade.id, PaperForwardTradeEvent.event_type == "POSITION_OPENED")
        ).all()

        assert report["phases"]["open_eligible_trades"]["waiting"]
        assert stored.status == "CANDIDATE"
        assert opened_events == []


def test_paper_forward_lifecycle_rejects_trigger_after_frozen_entry_window_expires():
    with setup_db() as db:
        asset = seed_asset(db)
        service = LiveForwardPaperTradingService()
        payload = candidate(entry_type="ABOVE_TRIGGER", trigger_price=102.0, target_1=130.0, target_2=150.0)
        payload["trade_plan"]["expected_holding_days"] = 2
        trade = service.create_candidate(db, payload)
        add_price(db, asset, 3, 103.0)

        report = run_lifecycle(service, db)
        stored = db.get(PaperForwardTrade, trade.id)

    assert stored.status == "SKIPPED"
    assert stored.outcome_label == "SIGNAL_DECAY_BEFORE_ENTRY"
    assert any(row["reason"] == "signal_decay_before_entry" for row in report["phases"]["open_eligible_trades"]["skipped"])


def test_paper_forward_lifecycle_data_blocked_when_market_data_missing():
    with setup_db() as db:
        seed_asset(db)
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(db, candidate())

        report = run_lifecycle(service, db)
        stored = db.get(PaperForwardTrade, trade.id)
        events = db.scalars(select(PaperForwardTradeEvent).where(PaperForwardTradeEvent.paper_trade_id == trade.id)).all()

        assert stored.status == "CANDIDATE"
        assert report["phases"]["open_eligible_trades"]["data_blocked"]
        assert any(event.event_type == "DATA_BLOCKED" for event in events)


def test_paper_forward_lifecycle_updates_open_trade_unrealized_pnl():
    with setup_db() as db:
        asset = seed_asset(db)
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(db, candidate(target_1=130.0, target_2=150.0))
        add_price(db, asset, 1, 100.0)
        run_lifecycle(service, db)
        add_price(db, asset, 2, 103.0)

        report = run_lifecycle(service, db)
        refreshed = db.get(PaperForwardTrade, trade.id)
        events = db.scalars(select(PaperForwardTradeEvent).where(PaperForwardTradeEvent.paper_trade_id == trade.id)).all()

        assert refreshed.status == "OPEN"
        assert refreshed.current_price == 103.0
        assert refreshed.unrealized_pnl > 0
        assert report["phases"]["update_open_trades"]["updated"]
        assert any(event.event_type == "POSITION_UPDATED" for event in events)


def test_paper_forward_lifecycle_stop_hit_closes_trade_and_calculates_pnl():
    with setup_db() as db:
        asset = seed_asset(db)
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(db, candidate(invalidation_level=96.0, target_1=130.0, target_2=150.0))
        add_price(db, asset, 1, 100.0)
        run_lifecycle(service, db)
        add_price(db, asset, 2, 94.0)

        run_lifecycle(service, db)
        closed = db.get(PaperForwardTrade, trade.id)
        events = db.scalars(select(PaperForwardTradeEvent).where(PaperForwardTradeEvent.paper_trade_id == trade.id)).all()

        assert closed.status == "CLOSED"
        assert closed.close_reason == "STOP_HIT"
        assert closed.outcome == "LOSS"
        assert closed.exit_price < 93.0
        assert closed.pnl_per_share == round(closed.exit_price - closed.entry_price, 4)
        assert closed.execution_costs["exit"]["gap_cost"] > 0
        assert closed.pnl_percent < 0
        assert closed.r_multiple < 0
        assert any(event.event_type == "STOP_HIT" for event in events)
        assert any(event.event_type == "POSITION_CLOSED" for event in events)


def test_paper_forward_lifecycle_target_hit_closes_with_lesson_and_audit_events():
    with setup_db() as db:
        asset = seed_asset(db)
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(db, candidate(target_1=104.0, target_2=150.0))
        add_price(db, asset, 1, 100.0)
        run_lifecycle(service, db)
        add_price(db, asset, 2, 106.0)

        run_lifecycle(service, db)
        closed = db.get(PaperForwardTrade, trade.id)
        events = db.scalars(select(PaperForwardTradeEvent).where(PaperForwardTradeEvent.paper_trade_id == trade.id)).all()
        lesson = db.scalar(select(TradeLearningEvidence).where(TradeLearningEvidence.trade_id == closed.ledger_trade_id))

        assert closed.status == "CLOSED"
        assert closed.close_reason == "TARGET_1_HIT"
        assert closed.outcome == "WIN"
        assert closed.net_pnl_eur > 0
        assert closed.gross_pnl_eur > closed.net_pnl_eur
        assert closed.execution_costs["accounting"]["reconciled"] is True
        assert round(closed.game.current_capital, 4) == round(100.0 + closed.net_pnl_eur, 4)
        assert lesson is not None
        assert lesson.supporting_trades_json["paper_forward_trade_id"] == closed.id
        assert any(event.event_type == "TARGET_HIT" for event in events)
        assert any(event.event_type == "OUTCOME_EVALUATED" for event in events)
        assert any(event.event_type == "LESSON_CREATED" for event in events)


def test_paper_forward_lifecycle_expiry_closes_trade():
    with setup_db() as db:
        asset = seed_asset(db)
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(db, candidate(target_1=130.0, target_2=150.0))
        add_price(db, asset, 1, 100.0)
        run_lifecycle(service, db)
        opened = db.get(PaperForwardTrade, trade.id)
        opened.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
        add_price(db, asset, 2, 101.0)

        run_lifecycle(service, db)
        closed = db.get(PaperForwardTrade, trade.id)

        assert closed.status == "EXPIRED"
        assert closed.close_reason == "TIME_EXIT"
        assert closed.close_price == 101.0


def test_paper_forward_lifecycle_invalidation_closes_trade():
    with setup_db() as db:
        asset = seed_asset(db)
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(db, candidate(invalidation_level=96.0, target_1=130.0, target_2=150.0))
        add_price(db, asset, 1, 100.0)
        run_lifecycle(service, db)
        opened = db.get(PaperForwardTrade, trade.id)
        opened.stop_loss = None
        db.commit()
        add_price(db, asset, 2, 95.0)

        run_lifecycle(service, db)
        closed = db.get(PaperForwardTrade, trade.id)

        assert closed.status == "INVALIDATED"
        assert closed.close_reason == "INVALIDATION_HIT"
        assert closed.invalidation_hit is True


def test_paper_forward_lifecycle_is_idempotent_after_open_and_close():
    with setup_db() as db:
        asset = seed_asset(db)
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(db, candidate(target_1=104.0, target_2=150.0))
        add_price(db, asset, 1, 100.0)
        run_lifecycle(service, db)
        add_price(db, asset, 2, 106.0)
        run_lifecycle(service, db)
        event_count = db.scalar(select(func.count(PaperForwardTradeEvent.id)).where(PaperForwardTradeEvent.paper_trade_id == trade.id))
        lesson_count = db.scalar(select(func.count(TradeLearningEvidence.id)))

        run_lifecycle(service, db)
        event_count_after = db.scalar(select(func.count(PaperForwardTradeEvent.id)).where(PaperForwardTradeEvent.paper_trade_id == trade.id))
        lesson_count_after = db.scalar(select(func.count(TradeLearningEvidence.id)))

        assert event_count_after == event_count
        assert lesson_count_after == lesson_count


def test_paper_forward_lifecycle_calculates_benchmark_excess_when_available():
    with setup_db() as db:
        asset = seed_asset(db)
        spy = seed_asset(db, ticker="SPY", close=100.0)
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(db, candidate(target_1=104.0, target_2=150.0))
        add_price(db, asset, 1, 100.0)
        add_price(db, spy, 1, 101.0)
        run_lifecycle(service, db)
        add_price(db, asset, 2, 106.0)
        add_price(db, spy, 2, 102.0)

        run_lifecycle(service, db)
        closed = db.get(PaperForwardTrade, trade.id)

        assert closed.benchmark_return is not None
        assert closed.benchmark_excess is not None
        assert closed.benchmark_excess > 0


def test_paper_forward_scheduler_scans_then_advances_lifecycle_without_legacy_run_cycle():
    source = (Path(__file__).resolve().parents[1] / "app" / "services" / "realtime.py").read_text()
    start = source.index("def advance_live_forward_paper_trading")
    block = source[start : source.index("\n\ndef ", start + 1)]

    assert ".run_once(db)" in block
    assert ".run_lifecycle(db)" in block
    assert "paper_forward_lifecycle_enabled" in block
    assert ".run_cycle(db)" not in block
