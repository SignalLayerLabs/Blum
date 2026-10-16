from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.engine.brain.trader_brain import TraderBrainService
from app.models import (
    AlphaLossAttribution,
    DashboardSnapshot,
    LearningBenchmarkComparison,
    LearningFocusPriority,
    LearningRun,
    LearningStrengthWeaknessMap,
    SelfImprovementAction,
    TradeLearningEvidence,
    TradingGame,
    TradingGameTrade,
    TradingIntelligenceMetric,
)
from app.services.research_planner import AutonomousResearchPlanner, RESEARCH_PLANNER_SNAPSHOT_TYPE


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_planner_evidence(db: Session) -> None:
    game = TradingGame(game_id="research-planner-game", current_capital=96.0, starting_capital=100.0, target_capital=10000.0)
    db.add(game)
    db.flush()
    now = datetime.utcnow()
    trades = [
        dict(ticker="NVDA", setup="momentum_breakout", sector="Technology", r=-1.0, excess=-6.0, confidence=82.0, outcome="stopped_out", missed=False, stop=True),
        dict(ticker="AMD", setup="momentum_breakout", sector="Technology", r=-0.8, excess=-4.0, confidence=78.0, outcome="stopped_out", missed=False, stop=True),
        dict(ticker="QQQ", setup="momentum_breakout", sector="Technology", r=0.0, excess=8.5, confidence=63.0, outcome="missed_entry", missed=True, stop=False),
        dict(ticker="META", setup="trend_continuation", sector="Communication Services", r=0.0, excess=7.0, confidence=61.0, outcome="no_trade_missed_opportunity", missed=True, stop=False),
    ]
    for index, row in enumerate(trades):
        db.add(
            TradingGameTrade(
                game_id=game.id,
                ticker=row["ticker"],
                setup_type=row["setup"],
                sector=row["sector"],
                market_regime_at_entry="risk_on",
                benchmark_ticker="QQQ",
                entry_date=date(2026, 1, 2) + timedelta(days=index),
                exit_date=date(2026, 1, 12) + timedelta(days=index),
                entry_price=100.0,
                exit_price=98.0 if row["r"] < 0 else None,
                position_size=1.0,
                risk_amount=1.0,
                risk_percent=1.0,
                realized_r_multiple=row["r"],
                net_pnl_eur=row["r"],
                confidence_at_entry=row["confidence"],
                excess_return_vs_benchmark=row["excess"],
                stop_hit=row["stop"],
                missed_entry=row["missed"],
                outcome_label=row["outcome"],
                created_at=now + timedelta(seconds=index),
            )
        )
    db.add(
        TradingIntelligenceMetric(
            scope="global",
            trades_count=32,
            missed_entry_rate=0.31,
            exit_timing_score=48.0,
            sizing_quality_score=52.0,
            benchmark_excess=-8.2,
            calculated_at=now,
        )
    )
    db.add(
        LearningBenchmarkComparison(
            benchmark_name="QQQ",
            result_label="underperforming",
            excess_return=-8.2,
            sample_size=32,
            statistical_confidence="low evidence",
            calculated_at=now,
        )
    )
    db.add(
        LearningStrengthWeaknessMap(
            dimension="setup_type",
            entity="momentum_breakout",
            strength_score=41.0,
            weakness_score=76.0,
            sample_size=18,
            main_problem="High-confidence breakouts are failing and missed entries are repeated.",
            priority="high",
            status="open",
        )
    )
    db.add(
        AlphaLossAttribution(
            benchmark_name="QQQ",
            category="missed_entry",
            ticker="QQQ",
            setup_type="momentum_breakout",
            sector="Technology",
            contribution_value=-7.5,
            sample_size=18,
            confidence=52.0,
            explanation="Missed entries caused alpha drag versus QQQ.",
        )
    )
    db.add(
        TradeLearningEvidence(
            ticker="NVDA",
            setup_type="momentum_breakout",
            regime="risk_on",
            lesson_type="entry_timing_bad",
            observation="Late confirmation caused poor entry quality.",
            sample_size=18,
            confidence=64.0,
            created_at=now,
        )
    )
    db.add(
        SelfImprovementAction(
            source_metric="missed_entry_rate",
            source_dimension="setup_type",
            detected_problem="Missed entry rate is elevated.",
            recommended_action="Test pullback-retest entry against breakout-close entry.",
            affected_module="EntryExitEngine",
            priority="high",
            expected_impact="Reduce missed entries without increasing false positives.",
            status="proposed",
        )
    )
    db.add(
        LearningRun(
            run_id="planner-run",
            status="completed",
            trigger="autonomous_engine",
            predictions_created=7,
            outcomes_evaluated=5,
            memory_updates=2,
            started_at=now,
            completed_at=now,
        )
    )
    db.commit()


def test_research_priorities_are_generated_and_persisted_as_knowledge_only():
    with setup_db() as db:
        seed_planner_evidence(db)

        payload = AutonomousResearchPlanner().generate(db, persist=True)

        assert payload["status"] == "ready"
        assert payload["current_research_objective"]["target"]
        assert payload["expected_information_gain"] > 0
        assert payload["queued_experiments"]
        assert any(row["priority_type"] == "broad_exploration" for row in payload["queued_experiments"])
        assert payload["policy"].startswith("Autonomous Research Planner updates stored knowledge")
        assert db.scalar(select(LearningFocusPriority).where(LearningFocusPriority.status == "active")) is not None
        assert db.scalar(select(DashboardSnapshot).where(DashboardSnapshot.snapshot_type == RESEARCH_PLANNER_SNAPSHOT_TYPE)) is not None


def test_research_planner_summary_is_read_only_for_training_page():
    with setup_db() as db:
        seed_planner_evidence(db)
        AutonomousResearchPlanner().generate(db, persist=True)
        priorities_before = db.scalar(select(func.count(LearningFocusPriority.id)))
        snapshots_before = db.scalar(select(func.count(DashboardSnapshot.id)))

        summary = AutonomousResearchPlanner().summary(db)
        training_payload = TraderBrainService().training_ground(db)

        assert summary["current_research_objective"]["target"]
        assert training_payload["research_planner"]["current_research_objective"]["target"] == summary["current_research_objective"]["target"]
        assert db.scalar(select(func.count(LearningFocusPriority.id))) == priorities_before
        assert db.scalar(select(func.count(DashboardSnapshot.id))) == snapshots_before




def test_autonomous_engine_generates_planner_before_learning_loop():
    engine_file = Path(__file__).resolve().parents[1] / "app" / "services" / "autonomous_engine.py"
    text = engine_file.read_text()

    assert 'stage("research_planner"' in text
    assert text.index('stage("research_planner"') < text.index('stage("blum_learning_loop"')
