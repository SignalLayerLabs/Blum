from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import Base
from app.models import TradingMLModelVersion, TradingMLPrediction, TradingMLTrainingRun


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def migration_head() -> str | None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head()


def test_trading_ml_model_version_enforces_one_model_identity(db):
    row = TradingMLModelVersion(
        model_uid="ml-equity-test",
        market_family="equity",
        algorithm="hist_gradient_boosting",
        status="SHADOW",
        feature_schema_version="trading-ml-features-v1",
        feature_schema_hash="schema-hash",
        dataset_hash="dataset-hash",
        artifact_path="/data/models/test.joblib",
        artifact_sha256="artifact-hash",
    )
    db.add(row)
    db.commit()

    duplicate = TradingMLModelVersion(
        model_uid="ml-equity-test",
        market_family="equity",
        algorithm="hist_gradient_boosting",
        status="SHADOW",
        feature_schema_version="trading-ml-features-v1",
        feature_schema_hash="schema-hash",
        dataset_hash="dataset-hash",
        artifact_path="/data/models/duplicate.joblib",
        artifact_sha256="duplicate-hash",
    )
    db.add(duplicate)

    with pytest.raises(IntegrityError):
        db.commit()

    db.rollback()
    assert db.scalar(select(TradingMLModelVersion)).model_uid == "ml-equity-test"


def test_trading_ml_records_keep_training_prediction_audit_data(db):
    model = TradingMLModelVersion(
        model_uid="ml-forex-test",
        market_family="forex",
        algorithm="hist_gradient_boosting",
        status="CHALLENGER",
        feature_schema_version="trading-ml-features-v1",
        feature_schema_hash="schema-hash",
        dataset_hash="dataset-hash",
        evidence_lane_counts_json={"REPLAY_EVIDENCE": 300},
        training_window_json={"start": "2026-01-01"},
        validation_window_json={"folds": 3},
        validation_metrics_json={"brier_score": 0.18},
        baseline_metrics_json={"brier_score": 0.21},
        promotion_gates_json={"minimum_folds": True},
        artifact_path="/data/models/forex.joblib",
        artifact_sha256="artifact-hash",
        warnings_json=["replay-only"],
        explanation="Awaiting forward evidence.",
    )
    db.add(model)
    db.flush()
    run = TradingMLTrainingRun(
        run_uid="run-forex-test",
        market_family="forex",
        trigger="scheduled",
        cursor_json={"last_source_id": 19},
        resource_limits_json={"max_runtime_seconds": 120},
        split_metadata_json={"folds": 3},
        candidate_model_version_id=model.id,
    )
    prediction = TradingMLPrediction(
        source_object_type="forex_decision",
        source_object_id="42",
        model_version_id=model.id,
        market_family="forex",
        feature_hash="feature-hash",
        probability_positive_r=0.71,
        predicted_net_r=0.4,
        uncertainty=0.1,
        baseline_output_json={"confidence": 68.0},
        proposed_confidence_adjustment=4.0,
        applied_confidence_adjustment=3.0,
        guardrails_json=["MAX_CONFIDENCE_ADJUSTMENT"],
        explanation_json=["Positive expected R"],
        realized_outcome_json={"net_r": 0.5},
    )
    db.add_all([run, prediction])
    db.commit()

    stored = db.scalar(select(TradingMLPrediction))
    assert stored is not None
    assert stored.guardrails_json == ["MAX_CONFIDENCE_ADJUSTMENT"]
    assert stored.model_version_id == model.id
    assert db.scalar(select(TradingMLTrainingRun)).cursor_json == {"last_source_id": 19}


def test_trading_ml_prediction_is_unique_per_source_and_model(db):
    model = TradingMLModelVersion(
        model_uid="ml-identity-test",
        market_family="equity",
        algorithm="hist_gradient_boosting",
        status="SHADOW",
        feature_schema_version="trading-ml-features-v1",
        feature_schema_hash="schema-hash",
        dataset_hash="dataset-hash",
        artifact_path="/data/models/identity.joblib",
        artifact_sha256="artifact-hash",
    )
    db.add(model)
    db.flush()
    db.add_all(
        [
            TradingMLPrediction(
                source_object_type="historical_prediction",
                source_object_id="99",
                model_version_id=model.id,
                market_family="equity",
                feature_hash="first",
            ),
            TradingMLPrediction(
                source_object_type="historical_prediction",
                source_object_id="99",
                model_version_id=model.id,
                market_family="equity",
                feature_hash="second",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db.commit()


def test_trading_ml_settings_have_evidence_bound_defaults():
    settings = Settings()

    assert settings.trading_ml_enabled is True
    assert settings.trading_ml_max_runtime_seconds == 120
    assert settings.trading_ml_max_rows_per_slice == 500
    assert settings.trading_ml_min_replay_samples == 300
    assert settings.trading_ml_min_folds == 3
    assert settings.trading_ml_min_assets == 6
    assert settings.trading_ml_brier_improvement == 0.05
    assert settings.trading_ml_max_confidence_adjustment == 5.0
    assert settings.trading_ml_max_combined_adjustment == 10.0
    assert settings.trading_ml_artifact_root == "/data/trading_ml"


def test_migration_head_includes_alpha_desk_indexes():
    assert migration_head() == "0048_forex_order_accounting"
