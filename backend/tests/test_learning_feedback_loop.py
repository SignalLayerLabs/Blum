from datetime import date, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    Asset,
    ExecutionSimulation,
    FeedbackLoopAudit,
    HistoricalPrediction,
    LearningFocusPriority,
    LearningRun,
    ModelVersion,
    PriceHistory,
    SignalPerformance,
    StrategyMemory,
)
from app.services.learning_loop import (
    BASE_SIGNAL_WEIGHTS,
    HistoricalSamplerService,
    LearningLoopService,
    ModelScoreService,
    PredictionEngine,
    learning_mode_metadata,
)
from app.services.trading_game import TradingGameSimulator


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def prediction_context() -> dict:
    return {
        "asset": {"ticker": "NVDA", "sector": "Technology"},
        "analysis_date": "2024-06-01",
        "initial_price": 100.0,
        "technical": {
            "status": "ready",
            "trend_direction": "uptrend",
            "moving_averages": {"alignment": "bullish_stack"},
            "technical_indicators": {"rsi": 62.0, "macd_hist": 1.0},
            "volume": {"relative_volume": 1.2},
            "volatility": {"regime": "medium"},
            "levels": {"nearest_support": 94.0, "nearest_resistance": 118.0, "invalidation_level": 94.0},
            "risk_reward_estimate": {"status": "estimated"},
            "technical_summary": "Uptrend with constructive momentum.",
        },
        "fundamentals": {"status": "ready", "quality_score": 56.0},
        "news": {"article_count_total_as_of": 10, "article_count_14d": 8, "average_quality_14d": 2.0, "themes_14d": [{"theme": "AI"}]},
        "macro": {"status": "ready"},
        "market_context": {"market_regime": "Bull Expansion", "volatility_regime": "Low"},
        "data_quality_score": 76.0,
        "point_in_time_policy": {"future": "hidden"},
    }


def seed_asset_history(db: Session) -> Asset:
    asset = Asset(
        ticker="NVDA",
        name="NVIDIA",
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
    start = date(2020, 1, 1)
    for offset in range(2200):
        close = 100.0 + offset * 0.05
        db.add(
            PriceHistory(
                asset_id=asset.id,
                date=start + timedelta(days=offset),
                open=close - 0.5,
                high=close + 1.0,
                low=close - 1.0,
                close=close,
                volume=1_000_000 + offset * 100,
                provider="test",
            )
        )
    db.commit()
    return asset


def known_memory_provenance():
    # Synthetic state explicitly published before every decision in these tests.
    return {"available_at": "2020-01-01T00:00:00", "outcome_cutoff": "2019-12-31T00:00:00",
            "contract_version": "legacy-direction-v1", "scope": {
                "asset_key": "NVDA", "timeframe": "mid", "holding_horizon": 63,
                "setup_type": "legacy_direction_forecast", "regime": "Bull Expansion",
                "strategy_fingerprint": "legacy-direction-v1"}}


def scoped_prediction_context():
    return {**prediction_context(), "timeframe": "mid", "holding_horizon": 63,
            "setup_type": "legacy_direction_forecast", "strategy_fingerprint": "legacy-direction-v1"}


def test_active_model_version_weights_change_future_prediction_output():
    with setup_db() as db:
        base = PredictionEngine().predict(prediction_context())
        learned_weights = dict(BASE_SIGNAL_WEIGHTS)
        learned_weights["sentiment"] = 0.72
        learned_weights["trend_structure"] = 0.04
        db.add(
            ModelVersion(
                version="learned-sentiment-heavy",
                model_name="BLUM Learning Loop",
                weights=learned_weights,
                previous_weights=BASE_SIGNAL_WEIGHTS,
                is_active=True,
                created_at=datetime(2020, 1, 1),
                training_window=known_memory_provenance(),
            )
        )
        db.commit()

        learned = PredictionEngine().predict(prediction_context(), db=db)

    assert learned["model_version_used"] == "learned-sentiment-heavy"
    assert learned["weights_used"]["sentiment"] > base["weights_used"]["sentiment"]
    assert learned["prediction"]["aggregate_score"] != base["prediction"]["aggregate_score"]


def test_fallback_to_base_weights_without_active_model_version():
    with setup_db() as db:
        prediction = PredictionEngine().predict(prediction_context(), db=db)

    assert prediction["model_version_used"] == "base-static"
    assert prediction["feedback_loop"]["weight_source"] == "base_signal_weights"
    assert prediction["weights_used"] == BASE_SIGNAL_WEIGHTS


def test_learning_mode_metadata_is_mutually_exclusive():
    training = learning_mode_metadata("test", {"sampling_reason": "learning_focus_priority"})
    walk_forward = learning_mode_metadata("test", {"sampling_reason": "random_point_in_time"})
    paper = learning_mode_metadata("paper_forward", {"mode": "paper_forward"})

    assert training["mode"] == "training_replay"
    assert training["training_replay"] is True
    assert training["walk_forward_validation"] is False
    assert training["paper_forward"] is False
    assert walk_forward["mode"] == "walk_forward_validation"
    assert walk_forward["training_replay"] is False
    assert walk_forward["walk_forward_validation"] is True
    assert walk_forward["paper_forward"] is False
    assert paper["mode"] == "paper_forward"
    assert paper["training_replay"] is False
    assert paper["walk_forward_validation"] is False
    assert paper["paper_forward"] is True


def test_signal_performance_changes_confidence():
    with setup_db() as db:
        context = scoped_prediction_context()
        base = PredictionEngine().predict(context, db=db)
        db.add(
            SignalPerformance(
                signal_name="trend_structure",
                timeframe="mid",
                market_regime="Bull Expansion",
                sample_count=20,
                correct_count=16,
                false_positive_count=1,
                false_negative_count=0,
                reliability_score=78.0,
                weight_adjustment=0.05,
                created_at=datetime(2020, 1, 1), updated_at=datetime(2020, 1, 1),
                evidence=known_memory_provenance(),
            )
        )
        db.commit()

        learned = PredictionEngine().predict(context, db=db)

    assert learned["feedback_loop"]["learning_memory_used"]["signal_performance"]
    assert learned["feedback_loop"]["strategy_memory_used"]["rows"] == []
    assert learned["feedback_loop"]["confidence_adjustment"] > 0
    assert learned["prediction"]["aggregate_confidence"] > base["prediction"]["aggregate_confidence"]


def test_strategy_memory_changes_confidence():
    with setup_db() as db:
        context = scoped_prediction_context()
        base = PredictionEngine().predict(context, db=db)
        db.add(
            StrategyMemory(
                memory_key="volume_confirmation:relative-volume",
                category="volume_confirmation",
                lesson="Momentum setups improve when volume confirms.",
                conditions={"relative_volume_gt": 1.0},
                reliability_score=72.0,
                sample_count=8,
                positive_count=6,
                negative_count=2,
                created_at=datetime(2020, 1, 1), updated_at=datetime(2020, 1, 1),
                evidence=known_memory_provenance(),
            )
        )
        db.commit()

        learned = PredictionEngine().predict(context, db=db)

    assert learned["feedback_loop"]["learning_memory_used"]["signal_performance"] == []
    assert learned["feedback_loop"]["strategy_memory_used"]["rows"]
    assert learned["feedback_loop"]["confidence_adjustment"] > 0
    assert learned["prediction"]["aggregate_confidence"] > base["prediction"]["aggregate_confidence"]


def test_research_planner_priority_appears_in_sample_metadata():
    with setup_db() as db:
        seed_asset_history(db)
        focus = LearningFocusPriority(
            priority_type="missed_entry_replay",
            target="NVDA",
            reason="Replay high-quality missed entries.",
            expected_learning_value=88.0,
            urgency="high",
            status="active",
        )
        db.add(focus)
        db.commit()

        sample = HistoricalSamplerService().focus_priority_sample(db)

    assert sample is not None
    assert sample["sampling_reason"] == "learning_focus_priority"
    assert sample["learning_focus_priority_id"] == focus.id
    assert sample["priority_type"] == "missed_entry_replay"


def test_run_single_sample_persists_weights_memory_research_priority_and_audit():
    with setup_db() as db:
        asset = seed_asset_history(db)
        focus = LearningFocusPriority(
            priority_type="missed_entry_replay",
            target="NVDA",
            reason="Replay high-quality missed entries.",
            expected_learning_value=88.0,
            urgency="high",
            status="active",
        )
        run = LearningRun(run_id="feedback-run", status="running", trigger="test")
        db.add_all([focus, run])
        db.add(
            ModelVersion(
                version="learned-active",
                model_name="BLUM Learning Loop",
                weights={**BASE_SIGNAL_WEIGHTS, "momentum": 0.5},
                previous_weights=BASE_SIGNAL_WEIGHTS,
                is_active=True,
                created_at=datetime(2020, 1, 1),
                training_window=known_memory_provenance(),
            )
        )
        db.commit()

        report = LearningLoopService().run_single_sample(
            db,
            run,
            {
                "asset": asset,
                "analysis_date": date(2022, 5, 1),
                "sampling_reason": "learning_focus_priority",
                "learning_focus_priority_id": focus.id,
                "priority_type": focus.priority_type,
            },
        )
        prediction = db.scalar(select(HistoricalPrediction).where(HistoricalPrediction.ticker == "NVDA"))
        audit = db.scalar(select(FeedbackLoopAudit).where(FeedbackLoopAudit.prediction_id == prediction.id))

    assert prediction.model_version_used == "learned-active"
    assert prediction.weights_used["momentum"] > BASE_SIGNAL_WEIGHTS["momentum"]
    assert prediction.learning_memory_used["policy"].startswith("SignalPerformance")
    assert prediction.strategy_memory_used["policy"].startswith("StrategyMemory")
    assert prediction.research_priority_used["priority_type"] == "missed_entry_replay"
    assert prediction.prediction_payload["learning_mode_metadata"]["training_replay"] is True
    assert prediction.prediction_payload["learning_mode_metadata"]["walk_forward_validation"] is False
    assert report["feedback_loop_audit"]["model_version_used"] == "learned-active"
    assert report["feedback_loop_audit"]["counterfactual_audit"]["baseline_prediction"]["model_version_used"] == "base-static"
    assert "score_delta" in report["feedback_loop_audit"]["counterfactual_audit"]["differences"]
    comparison = report["feedback_loop_audit"]["counterfactual_audit"]["outcome_comparison"]
    assert "baseline_direction_correct" in comparison
    assert "learned_direction_correct" in comparison
    assert "baseline_would_trade" in comparison
    assert "learned_would_trade" in comparison
    assert "avoided_loss" in comparison
    assert "missed_gain" in comparison
    assert "improvement_reason" in comparison
    assert report["feedback_loop_audit"]["improvement_detected"] == comparison["improvement_detected"]
    assert audit is not None
    assert audit.future_decision_json["ticker"] == "NVDA"
    assert audit.changes_applied_json["counterfactual_audit"]["learned_prediction"]["model_version_used"] == "learned-active"
    assert audit.outcome_json["improvement_reason"] == comparison["improvement_reason"]


def test_paper_trade_payload_includes_feedback_loop_metadata():
    with setup_db() as db:
        asset = seed_asset_history(db)
        run = LearningRun(run_id="feedback-trade-run", status="running", trigger="test")
        db.add(run)
        db.add(
            ModelVersion(
                version="learned-paper",
                model_name="BLUM Learning Loop",
                weights={**BASE_SIGNAL_WEIGHTS, "momentum": 0.5},
                previous_weights=BASE_SIGNAL_WEIGHTS,
                is_active=True,
                created_at=datetime(2020, 1, 1),
                training_window=known_memory_provenance(),
            )
        )
        db.commit()
        LearningLoopService().run_single_sample(db, run, {"asset": asset, "analysis_date": date(2022, 5, 1)})
        prediction = db.scalar(select(HistoricalPrediction).where(HistoricalPrediction.ticker == "NVDA"))
        simulation = ExecutionSimulation(
            prediction_id=prediction.id,
            ticker="NVDA",
            setup_type="momentum_breakout",
            realized_r_multiple=1.4,
            max_adverse_excursion=-0.4,
            max_favorable_excursion=1.8,
            time_in_trade=12,
            target_hit=True,
            simulation_payload={"timeframe": "daily"},
        )
        db.add(simulation)
        simulator = TradingGameSimulator()
        game = simulator.create_game(db, reason="test")
        db.flush()

        trade = simulator.apply_simulation(db, game, simulation, prediction)

    feedback = trade.payload["feedback_loop"]
    assert feedback["model_version_used"] == "learned-paper"
    assert feedback["weights_used"]["momentum"] > BASE_SIGNAL_WEIGHTS["momentum"]
    assert feedback["learning_memory_used"]["policy"].startswith("SignalPerformance")
    assert feedback["strategy_memory_used"]["policy"].startswith("StrategyMemory")
    assert "learning_mode_metadata" in feedback


def test_model_version_is_not_created_with_insufficient_evidence():
    with setup_db() as db:
        db.add(
            SignalPerformance(
                signal_name="momentum",
                timeframe="short",
                market_regime="Bull Expansion",
                sample_count=1,
                correct_count=1,
                false_positive_count=0,
                false_negative_count=0,
                reliability_score=85.0,
                weight_adjustment=0.1,
            )
        )
        db.commit()

        result = ModelScoreService().recalculate(db)

    assert result["status"] == "insufficient_evidence"
    assert result["thresholds"]["min_outcomes"] >= 30
    assert db.scalar(select(ModelVersion)) is None
