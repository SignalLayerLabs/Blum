"""Native outcome identity and historical provenance cannot change on retry."""

from datetime import datetime, timedelta
import pytest

from app.services.trading_ml.features import TradingMLFeatureBuilder
from test_trading_ml_features import DECISION_AT, equity_prediction, equity_outcome


def test_historical_prediction_created_today_keeps_original_decision_clock_and_lane():
    prediction = equity_prediction()
    prediction.created_at = datetime(2026, 10, 21, 10)
    outcome = equity_outcome(realized_return=2.0)
    outcome.created_at = prediction.created_at
    example = TradingMLFeatureBuilder().from_equity(prediction, outcome)
    assert example.decision_timestamp == DECISION_AT
    assert example.evidence_lane == "REPLAY_EVIDENCE"
    assert example.outcome_timestamp < prediction.created_at


def test_online_information_schema_preserves_legacy_state_and_uses_events(tmp_path):
    from dataclasses import replace
    from app.services.trading_ml.contracts import FeatureSchema
    from app.services.trading_ml.training import OnlineShadowTrainer
    from test_information_model import labeled_rows
    from test_trading_ml_training import examples

    legacy = OnlineShadowTrainer(tmp_path)
    legacy_result = legacy.partial_fit(examples(48))
    information = OnlineShadowTrainer(tmp_path, schema=FeatureSchema.information())
    rows = labeled_rows()
    first = information.partial_fit(rows)
    repeated = information.partial_fit(rows)
    assert first.sample_count == repeated.sample_count == 240
    assert repeated.parameters["new_samples"] == 0
    assert repeated.model_bundle.schema_hash == FeatureSchema.information().hash
    assert legacy.current("equity").sample_count == legacy_result.sample_count == 48
    same_price = rows[0]
    informed = replace(
        same_price, features={**same_price.features, "event_novelty": 2.0}
    )
    probabilities, _ = repeated.model_bundle.predict((same_price, informed))
    assert probabilities[1] > probabilities[0]
    assert first.decision_authority is False


def test_online_v2_rejects_an_unmarked_legacy_example(tmp_path):
    from app.services.trading_ml.contracts import FeatureSchema
    from app.services.trading_ml.training import OnlineShadowTrainer
    from test_trading_ml_training import examples

    with pytest.raises(ValueError, match="INFORMATION_SCHEMA_REQUIRED"):
        OnlineShadowTrainer(tmp_path, schema=FeatureSchema.information()).partial_fit(
            examples()
        )
