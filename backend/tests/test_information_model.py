"""Engineering fixtures only: these fitted models are never alpha evidence."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from app.services.information.context import FEATURE_SCHEMA_HASH
from app.services.trading_ml.contracts import InsufficientTrainingEvidenceError
from app.services.trading_ml.registry import TradingMLModelRegistry
from test_trading_ml_inference import db
from test_trading_ml_training import examples
from test_opportunity_context import asset, build, event


def labeled_rows():
    price_features = dict(examples()[0].features)
    return tuple(
        replace(
            row,
            setup_type="momentum",
            regime="risk_on",
            features={
                **price_features,
                "setup_type": "momentum",
                "regime": "risk_on",
                "event_novelty": 2.0 if row.label_positive_r else 0.0,
                "information_coverage": 0.5,
                "calendar_known": 0.0,
                "strategy_fingerprint": "frozen-spec",
                "information_feature_schema_hash": FEATURE_SCHEMA_HASH,
            },
        )
        for row in examples(240)
    )


@pytest.fixture(scope="module")
def fitted():
    from app.services.information.model import InformationModelTrainer

    return InformationModelTrainer(
        parameters={"max_iter": 30, "min_samples_leaf": 5}
    ).fit(
        labeled_rows(),
        maximum_holding_horizon=timedelta(days=2),
    )


def publish(db, tmp_path, fitted):
    registry = TradingMLModelRegistry(tmp_path)
    row = registry.store_candidate(db, market_family="equity", result=fitted)
    return registry, row, row.created_at + timedelta(seconds=1)


def context_at(db, at, *, has_event=False):
    asset(db, "AAPL")
    if has_event:
        event(
            db,
            published=at - timedelta(minutes=2),
            observed=at - timedelta(minutes=1),
            available=at - timedelta(minutes=1),
        )
    return build(db, at=at)


def baseline():
    return {
        "rank": 1.0,
        "direction": "LONG",
        "setup_type": "momentum",
        "regime": "risk_on",
        "features": dict(labeled_rows()[0].features),
        "blockers": [],
        "target_distance_bps": 50.0,
        "estimated_round_trip_cost_bps": 7.0,
    }


def test_fit_calibration_evaluation_have_distinct_purged_clocks(fitted):
    metadata = fitted.model_bundle.metadata
    train_end = datetime.fromisoformat(metadata["training_outcome_cutoff"])
    cal_start = datetime.fromisoformat(metadata["calibration_start"])
    cal_end = datetime.fromisoformat(metadata["calibration_outcome_cutoff"])
    evaluation_start = datetime.fromisoformat(metadata["evaluation_start"])
    assert train_end < cal_start - timedelta(days=2)
    assert cal_end < evaluation_start - timedelta(days=2)
    assert set(metadata["training_source_uids"]).isdisjoint(
        metadata["calibration_source_uids"]
    )
    assert set(metadata["evaluation_source_uids"]).isdisjoint(
        metadata["calibration_source_uids"]
    )
    assert metadata["information_feature_schema_hash"] == FEATURE_SCHEMA_HASH
    assert metadata["calibration_support"]
    assert fitted.validation_metrics["brier_score"] is not None
    assert fitted.validation_metrics["log_loss"] is not None
    assert not fitted.decision_authority


def test_unfinished_overlapping_labels_cannot_form_a_calibrated_model():
    from app.services.information.model import InformationModelTrainer

    rows = tuple(
        replace(row, outcome_timestamp=row.decision_timestamp + timedelta(days=200))
        for row in labeled_rows()
    )
    with pytest.raises(InsufficientTrainingEvidenceError):
        InformationModelTrainer().fit(rows, maximum_holding_horizon=timedelta(days=2))


@pytest.mark.parametrize("label,net_r", [(0, -0.6), (1, 1.0)])
def test_one_class_outcomes_are_unsupported(label, net_r):
    from app.services.information.model import InformationModelTrainer

    rows = tuple(
        replace(row, label_positive_r=label, realized_net_r=net_r)
        for row in labeled_rows()
    )
    with pytest.raises(InsufficientTrainingEvidenceError):
        InformationModelTrainer().fit(rows, maximum_holding_horizon=timedelta(days=2))


def test_future_published_checkpoint_cannot_enter_historical_decision(
    db, tmp_path, fitted
):
    from app.services.trading_ml.contracts import FeatureSchema

    registry, row, _ = publish(db, tmp_path, fitted)
    loaded = registry.load_as_of(
        db,
        "equity",
        as_of=row.created_at - timedelta(seconds=1),
        schema_hash=FeatureSchema.information().hash,
        model_uid=row.model_uid,
    )
    assert loaded.model is None
    assert loaded.status == "NO_MODEL_AS_OF"


def test_v1_artifact_is_never_loaded_as_information_v2(db, tmp_path):
    from app.services.trading_ml.contracts import FeatureSchema
    from app.services.trading_ml.training import SklearnTradingModelTrainer

    registry = TradingMLModelRegistry(tmp_path)
    row = registry.store_candidate(
        db, market_family="equity", result=SklearnTradingModelTrainer().fit(examples())
    )
    loaded = registry.load_as_of(
        db,
        "equity",
        as_of=row.created_at + timedelta(seconds=1),
        schema_hash=FeatureSchema.information().hash,
        model_uid=row.model_uid,
    )
    assert loaded.model is None
    assert "SCHEMA_MISMATCH" in loaded.warnings


def test_no_model_or_unsupported_group_has_no_probability(db, tmp_path, fitted):
    from app.services.information.model import InformationOutcomeAdvisor

    registry, row, at = publish(db, tmp_path, fitted)
    context = context_at(db, at)
    advisor = InformationOutcomeAdvisor(registry)
    unsupported = advisor.advise(
        db,
        context=context,
        strategy_fingerprint="unseen-spec",
        baseline=baseline(),
        as_of=at,
        model_uid=row.model_uid,
    )
    assert unsupported.probability_positive_r is None
    assert unsupported.predicted_net_r is None
    absent = advisor.advise(
        db,
        context=context,
        strategy_fingerprint="frozen-spec",
        baseline=baseline(),
        as_of=at,
    )
    assert (
        absent.probability_positive_r is None
    )  # A challenger is not implicitly active.


def test_costed_net_label_prediction_is_not_charged_twice(db, tmp_path, fitted):
    from app.services.information.model import (
        InformationOutcomeAdvisor,
        information_example,
    )

    registry, row, at = publish(db, tmp_path, fitted)
    context = context_at(db, at, has_event=True)
    inputs = baseline()
    advice = InformationOutcomeAdvisor(registry).advise(
        db,
        context=context,
        strategy_fingerprint="frozen-spec",
        baseline=inputs,
        as_of=at,
        model_uid=row.model_uid,
    )
    example = information_example(context, inputs, strategy_fingerprint="frozen-spec")
    _, predicted_r = fitted.model_bundle.predict((example,))
    assert advice.predicted_net_r == pytest.approx(float(predicted_r[0]))
    assert advice.probability_positive_r is not None
    assert advice.net_costs_included is True
    assert advice.feature_schema_hash == fitted.model_bundle.schema_hash
    assert advice.model_hash == row.artifact_sha256
    assert advice.training_cutoff < context.decision_at
    expensive = InformationOutcomeAdvisor(registry).advise(
        db,
        context=context,
        strategy_fingerprint="frozen-spec",
        baseline={**inputs, "estimated_round_trip_cost_bps": 900.0},
        as_of=at,
        model_uid=row.model_uid,
    )
    assert expensive.predicted_net_r == advice.predicted_net_r
    assert not advice.decision_authority


def test_fixed_prices_information_ablation_changes_rank_without_fake_probability(
    db, tmp_path
):
    from app.services.information.model import InformationOutcomeAdvisor
    from app.services.information.policy import InformationPolicy

    at = datetime(2026, 10, 21, 10)
    empty = context_at(db, at)
    event(
        db,
        published=at - timedelta(minutes=2),
        observed=at - timedelta(minutes=1),
        available=at - timedelta(minutes=1),
    )
    informed = build(db, at=at)
    assert informed.price_refs == empty.price_refs
    advisor = InformationOutcomeAdvisor(TradingMLModelRegistry(tmp_path))
    price_only = InformationPolicy().apply(
        baseline=baseline(),
        context=empty,
        advice=advisor.advise(
            db,
            context=empty,
            strategy_fingerprint="frozen-spec",
            baseline=baseline(),
            as_of=at,
        ),
        risk_multiplier=0.1,
    )
    event_policy = InformationPolicy().apply(
        baseline=baseline(),
        context=informed,
        advice=advisor.advise(
            db,
            context=informed,
            strategy_fingerprint="frozen-spec",
            baseline=baseline(),
            as_of=at,
        ),
        risk_multiplier=0.1,
    )
    assert event_policy["rank"] != price_only["rank"]
    assert event_policy["probability_positive_r"] is None
    assert event_policy["information_effects"]
    assert event_policy["risk_multiplier"] <= 0.1


def test_information_policy_cannot_remove_blockers_or_raise_risk(db, tmp_path):
    from app.services.information.model import InformationOutcomeAdvisor
    from app.services.information.policy import InformationPolicy

    at = datetime(2026, 10, 21, 10)
    context = context_at(db, at, has_event=True)
    blocked = {**baseline(), "blockers": ["STALE_DATA"], "direction": "ABSTAIN"}
    advice = InformationOutcomeAdvisor(TradingMLModelRegistry(tmp_path)).advise(
        db,
        context=context,
        strategy_fingerprint="frozen-spec",
        baseline=blocked,
        as_of=at,
    )
    output = InformationPolicy().apply(
        baseline=blocked, context=context, advice=advice, risk_multiplier=0.05
    )
    assert output["blockers"] == ["STALE_DATA"]
    assert output["direction"] == "ABSTAIN"
    assert output["risk_multiplier"] <= 0.05


def test_information_net_r_target_is_not_silently_clipped_to_old_v1_range():
    from app.services.information.model import InformationModelTrainer

    rows = tuple(
        replace(row, realized_net_r=8.0 if row.label_positive_r else -4.0)
        for row in labeled_rows()
    )
    result = InformationModelTrainer(
        parameters={"max_iter": 70, "min_samples_leaf": 5}
    ).fit(rows, maximum_holding_horizon=timedelta(days=2))
    _, predictions = result.model_bundle.predict((rows[1], rows[0]))
    assert predictions[0] > 6.0
    assert predictions[1] < -3.5


def test_legacy_inference_cannot_inject_todays_active_model_into_yesterday(
    db, tmp_path
):
    from app.services.trading_ml.inference import TradingMLInferenceService
    from test_trading_ml_inference import active

    _, row = active(db, tmp_path)
    advice = TradingMLInferenceService(TradingMLModelRegistry(tmp_path)).advise(
        db,
        market_family="equity",
        features=examples()[1].features,
        decision_timestamp=row.created_at - timedelta(days=1),
    )
    assert advice.probability_positive_r is None
    assert advice.predicted_net_r is None


def test_fitted_model_consumes_events_with_fixed_prices_and_checkpoint(
    db, tmp_path, fitted
):
    from app.services.information.model import InformationOutcomeAdvisor

    registry, row, at = publish(db, tmp_path, fitted)
    empty = context_at(db, at)
    event(
        db,
        published=at - timedelta(minutes=2),
        observed=at - timedelta(minutes=1),
        available=at - timedelta(minutes=1),
    )
    event(
        db,
        url="https://example.org/dividend",
        title="Apple declares special dividend",
        published=at - timedelta(minutes=2),
        observed=at - timedelta(minutes=1),
        available=at - timedelta(minutes=1),
    )
    informed = build(db, at=at)
    advisor = InformationOutcomeAdvisor(registry)
    control = advisor.advise(
        db,
        context=empty,
        strategy_fingerprint="frozen-spec",
        baseline=baseline(),
        as_of=at,
        model_uid=row.model_uid,
    )
    candidate = advisor.advise(
        db,
        context=informed,
        strategy_fingerprint="frozen-spec",
        baseline=baseline(),
        as_of=at,
        model_uid=row.model_uid,
    )
    assert candidate.model_uid == control.model_uid
    assert informed.price_refs == empty.price_refs
    assert candidate.probability_positive_r > control.probability_positive_r
    assert candidate.predicted_net_r > control.predicted_net_r


def test_equity_and_forex_are_not_pooled_into_one_calibrator():
    from app.services.information.model import InformationModelTrainer

    rows = labeled_rows()
    with pytest.raises(InsufficientTrainingEvidenceError):
        InformationModelTrainer().fit(
            (*rows[:-1], replace(rows[-1], market_family="forex")),
            maximum_holding_horizon=timedelta(days=2),
        )


def test_outcome_model_conditions_on_the_frozen_strategy_not_only_prices():
    from app.services.information.model import InformationModelTrainer

    records = []
    for index, row in enumerate(labeled_rows()):
        for fingerprint, win in (
            ("strategy-a", index % 4 != 0),
            ("strategy-b", index % 4 == 0),
        ):
            records.append(
                replace(
                    row,
                    source_object_id=f"{fingerprint}-{index}",
                    label_positive_r=int(win),
                    realized_net_r=1.0 if win else -0.6,
                    features={
                        **row.features,
                        "event_novelty": 0.0,
                        "strategy_fingerprint": fingerprint,
                    },
                )
            )
    result = InformationModelTrainer(
        parameters={"max_iter": 50, "min_samples_leaf": 5}
    ).fit(records, maximum_holding_horizon=timedelta(days=2))
    probabilities, _ = result.model_bundle.predict((records[0], records[1]))
    assert probabilities[0] > probabilities[1] + 0.1


def test_changing_only_evaluation_outcomes_cannot_change_fitted_predictions(fitted):
    import numpy as np
    from app.services.information.model import InformationModelTrainer

    rows = labeled_rows()
    changed = tuple(
        (
            replace(
                row,
                label_positive_r=1 - row.label_positive_r,
                realized_net_r=-0.6 if row.label_positive_r else 1.0,
            )
            if index >= 192
            else row
        )
        for index, row in enumerate(rows)
    )
    other = InformationModelTrainer(
        parameters={"max_iter": 30, "min_samples_leaf": 5}
    ).fit(changed, maximum_holding_horizon=timedelta(days=2))
    original_p, original_r = fitted.model_bundle.predict(rows[:4])
    changed_p, changed_r = other.model_bundle.predict(rows[:4])
    assert np.allclose(original_p, changed_p)
    assert np.allclose(original_r, changed_r)
