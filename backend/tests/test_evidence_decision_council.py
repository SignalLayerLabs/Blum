from datetime import datetime, timedelta

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    AgentCouncilReflection,
    AgentCouncilRun,
    AgentCouncilTurn,
    BlumKnowledgeRecord,
    BlumThesisOutcome,
    EngineVote,
)
from app.services.decision_council import EvidenceBoundDecisionCouncil


NOW = datetime(2026, 8, 3, 12, 0)


def _db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def _record(db: Session, *, suffix: str = "one", confidence: float = 70.0) -> BlumKnowledgeRecord:
    row = BlumKnowledgeRecord(
        ticker="AAPL",
        sector="Technology",
        source_type="test",
        reasoning_hash=f"council-{suffix}",
        market_regime="risk_on",
        volatility_regime="normal",
        confidence=confidence,
        conviction_score=confidence,
        market_context={"benchmark": "SPY", "as_of": NOW.isoformat()},
        asset_context={"data_quality_score": 85.0},
        blum_reasoning={
            "thesis": "Trend continuation remains possible.",
            "trade_plan": {"risk_reward": 2.2, "invalidation_level": 95.0, "stop_loss": 96.0},
        },
        self_critique={
            "skeptic_view": {"key_points": ["Valuation is extended."]},
            "historical_view": {"key_points": ["Similar risk-on continuations were mixed."]},
        },
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def _vote(
    db: Session,
    record: BlumKnowledgeRecord,
    engine: str,
    vote: str,
    confidence: float,
    reliability: float = 0.7,
) -> None:
    db.add(
        EngineVote(
            thesis_id=record.id,
            ticker=record.ticker,
            engine_name=engine,
            vote=vote,
            confidence=confidence,
            evidence_quality=80.0,
            horizon="swing",
            regime=record.market_regime,
            sector=record.sector,
            reliability_weight_at_time=reliability,
            created_at=record.created_at,
        )
    )


def test_council_persists_analyst_debate_risk_and_portfolio_verdict():
    db = _db()
    record = _record(db)
    _vote(db, record, "technical_engine", "bullish", 78)
    _vote(db, record, "fundamental_engine", "bullish", 66)
    _vote(db, record, "regime_engine", "bullish", 72)
    db.commit()

    result = EvidenceBoundDecisionCouncil().run_for_record(db, record.id, as_of=NOW)

    run = db.get(AgentCouncilRun, result["run_id"])
    stages = set(db.scalars(select(AgentCouncilTurn.stage).where(AgentCouncilTurn.run_id == run.id)))
    assert run.status == "COMPLETED"
    assert run.final_action == "BUY"
    assert {"analyst", "research_debate", "risk_debate", "portfolio_verdict"}.issubset(stages)
    assert run.final_decision_json["invalidation_level"] == 95.0
    assert run.final_decision_json["source_record_id"] == record.id


def test_council_disagreement_reduces_confidence():
    db = _db()
    aligned = _record(db, suffix="aligned")
    divided = _record(db, suffix="divided")
    for engine in ("technical_engine", "fundamental_engine", "regime_engine"):
        _vote(db, aligned, engine, "bullish", 75)
    _vote(db, divided, "technical_engine", "bullish", 75)
    _vote(db, divided, "fundamental_engine", "bearish", 75)
    _vote(db, divided, "regime_engine", "neutral", 75)
    db.commit()

    aligned_result = EvidenceBoundDecisionCouncil().run_for_record(db, aligned.id, as_of=NOW)
    divided_result = EvidenceBoundDecisionCouncil().run_for_record(db, divided.id, as_of=NOW)

    assert divided_result["disagreement_score"] > aligned_result["disagreement_score"]
    assert divided_result["final_confidence"] < aligned_result["final_confidence"]
    assert divided_result["final_action"] == "WAIT"


def test_council_waits_when_evidence_is_insufficient():
    db = _db()
    record = _record(db, suffix="thin")
    _vote(db, record, "technical_engine", "bullish", 90)
    db.commit()

    result = EvidenceBoundDecisionCouncil().run_for_record(db, record.id, as_of=NOW)

    assert result["final_action"] == "WAIT"
    assert "insufficient_independent_evidence" in result["warnings"]


def test_council_is_idempotent_and_does_not_duplicate_turns():
    db = _db()
    record = _record(db, suffix="idempotent")
    _vote(db, record, "technical_engine", "bullish", 75)
    _vote(db, record, "regime_engine", "bullish", 75)
    db.commit()

    first = EvidenceBoundDecisionCouncil().run_for_record(db, record.id, as_of=NOW)
    turn_count = db.scalar(select(func.count(AgentCouncilTurn.id)))
    second = EvidenceBoundDecisionCouncil().run_for_record(db, record.id, as_of=NOW)

    assert second["run_id"] == first["run_id"]
    assert db.scalar(select(func.count(AgentCouncilRun.id))) == 1
    assert db.scalar(select(func.count(AgentCouncilTurn.id))) == turn_count


def test_mature_outcome_creates_reflection_used_by_later_same_ticker_decision():
    db = _db()
    first = _record(db, suffix="memory-one")
    _vote(db, first, "technical_engine", "bullish", 70)
    _vote(db, first, "regime_engine", "bullish", 70)
    db.commit()
    first_result = EvidenceBoundDecisionCouncil(min_memory_samples=1).run_for_record(db, first.id, as_of=NOW)
    outcome = BlumThesisOutcome(
            knowledge_record_id=first.id,
            ticker="AAPL",
            horizon_days=5,
            expected_direction="up_or_resilient",
            realized_return=4.0,
            outcome="correct",
            success=True,
            outcome_payload={"benchmark_return": 1.0},
            created_at=NOW + timedelta(days=1),
            updated_at=NOW + timedelta(days=1),
        )
    db.add(outcome)
    db.commit()

    reflected = EvidenceBoundDecisionCouncil(min_memory_samples=1).reflect_mature_outcomes(db)
    assert reflected["created"] == 1
    assert db.scalar(select(func.count(AgentCouncilReflection.id))) == 1
    # The reflection became available after the historical outcome matured.
    reflection = db.scalar(select(AgentCouncilReflection))
    reflection.created_at = outcome.updated_at
    db.commit()

    second = _record(db, suffix="memory-two", confidence=65)
    second.created_at = NOW + timedelta(days=7)
    _vote(db, second, "technical_engine", "bullish", 65)
    _vote(db, second, "regime_engine", "bullish", 65)
    db.commit()
    second_result = EvidenceBoundDecisionCouncil(min_memory_samples=1).run_for_record(
        db,
        second.id,
        as_of=NOW + timedelta(days=7),
    )

    assert first_result["memory_used"]["sample_size"] == 0
    assert second_result["memory_used"]["sample_size"] == 1
    assert second_result["memory_adjustment"] > 0


def test_outcome_known_before_council_clock_cannot_create_reflection():
    db = _db()
    record = _record(db, suffix="known-outcome")
    _vote(db, record, "technical_engine", "bullish", 70)
    _vote(db, record, "regime_engine", "bullish", 70)
    db.add(
        BlumThesisOutcome(
            knowledge_record_id=record.id,
            ticker="AAPL",
            horizon_days=5,
            realized_return=4.0,
            outcome="correct",
            success=True,
            created_at=NOW - timedelta(days=1),
            updated_at=NOW - timedelta(days=1),
        )
    )
    db.commit()
    EvidenceBoundDecisionCouncil().run_for_record(db, record.id, as_of=NOW)

    result = EvidenceBoundDecisionCouncil().reflect_mature_outcomes(db)

    assert result["created"] == 0
    assert db.scalar(select(func.count(AgentCouncilReflection.id))) == 0


def test_council_rejects_knowledge_created_after_decision_clock():
    db = _db()
    record = _record(db, suffix="future")
    record.created_at = NOW + timedelta(minutes=1)
    db.commit()

    result = EvidenceBoundDecisionCouncil().run_for_record(db, record.id, as_of=NOW)

    assert result["status"] == "REJECTED"
    assert result["reason"] == "knowledge_created_after_decision_clock"


def test_duplicate_votes_from_one_engine_do_not_fake_independent_evidence():
    db = _db()
    record = _record(db, suffix="duplicate-engine")
    _vote(db, record, "technical_engine", "bullish", 70)
    _vote(db, record, "technical_engine", "bullish", 90)
    list(db.new)[-1].horizon = "position"
    db.commit()

    result = EvidenceBoundDecisionCouncil().run_for_record(db, record.id, as_of=NOW)

    assert result["final_action"] == "WAIT"
    assert result["decision"]["evidence_sources"] == ["technical_engine"]
    assert "insufficient_independent_evidence" in result["warnings"]


def test_new_engine_evidence_creates_a_new_council_version():
    db = _db()
    record = _record(db, suffix="new-evidence")
    _vote(db, record, "technical_engine", "bullish", 70)
    _vote(db, record, "regime_engine", "bullish", 70)
    db.commit()
    first = EvidenceBoundDecisionCouncil().run_for_record(db, record.id, as_of=NOW)

    _vote(db, record, "fundamental_engine", "bearish", 80)
    db.commit()
    second = EvidenceBoundDecisionCouncil().run_for_record(db, record.id, as_of=NOW + timedelta(minutes=1))

    assert second["run_id"] != first["run_id"]
    assert db.scalar(select(func.count(AgentCouncilRun.id))) == 2
