from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
import sqlite3
import json
from concurrent.futures import ThreadPoolExecutor

from app.services.trading_ml.training import OnlineShadowTrainer
from test_trading_ml_training import examples


def test_online_updates_accumulate_and_survive_a_new_worker_instance(tmp_path):
    first = OnlineShadowTrainer(tmp_path).partial_fit(examples()[:24])
    second = OnlineShadowTrainer(tmp_path).partial_fit(examples()[24:])
    assert first.sample_count == 24
    assert second.sample_count == 48
    assert second.model_bundle.classifier.t_ == 49
    assert second.parameters["new_samples"] == 24
    duplicate = OnlineShadowTrainer(tmp_path).partial_fit(examples())
    assert duplicate.parameters["new_samples"] == 0
    assert duplicate.artifact_sha256 == second.artifact_sha256
    assert duplicate.model_bundle.classifier.t_ == 49


def test_batch_boundaries_do_not_reset_coordinates_or_learning(tmp_path):
    all_at_once = OnlineShadowTrainer(tmp_path / "one").partial_fit(examples())
    OnlineShadowTrainer(tmp_path / "many").partial_fit(examples()[:20])
    resumed = OnlineShadowTrainer(tmp_path / "many").partial_fit(examples()[20:])
    np.testing.assert_allclose(
        resumed.model_bundle.classifier.coef_, all_at_once.model_bundle.classifier.coef_
    )
    np.testing.assert_allclose(
        resumed.model_bundle.regressor.coef_, all_at_once.model_bundle.regressor.coef_
    )
    assert resumed.validation_metrics == all_at_once.validation_metrics


def test_markets_keep_independent_learning_state(tmp_path):
    OnlineShadowTrainer(tmp_path).partial_fit(examples()[:16])
    forex = [
        replace(
            row,
            market_family="forex",
            features={**row.features, "market_family": "forex"},
        )
        for row in examples()[:8]
    ]
    fx = OnlineShadowTrainer(tmp_path).partial_fit(forex)
    equity = OnlineShadowTrainer(tmp_path).partial_fit(examples()[:16])
    assert fx.sample_count == 8 and equity.sample_count == 16
    assert equity.parameters["new_samples"] == 0
    assert fx.status == equity.status == "SHADOW"
    assert not fx.decision_authority and not equity.decision_authority


def test_rewritten_label_or_weight_cannot_silently_retrain_an_identity(tmp_path):
    row = examples()[0]
    original = OnlineShadowTrainer(tmp_path).partial_fit([row])
    with pytest.raises(ValueError, match="CHANGED"):
        OnlineShadowTrainer(tmp_path).partial_fit([replace(row, sample_weight=0.1)])
    assert (
        OnlineShadowTrainer(tmp_path).partial_fit([row]).artifact_sha256
        == original.artifact_sha256
    )


def test_future_outcomes_never_enter_the_online_state(tmp_path):
    row = examples()[0]
    with pytest.raises(ValueError, match="mature"):
        OnlineShadowTrainer(tmp_path).partial_fit([row], as_of=row.decision_timestamp)


def test_metrics_exclude_labels_that_were_unavailable_at_the_decision(tmp_path):
    rows = list(examples()[:3])
    rows[0] = replace(
        rows[0], outcome_timestamp=rows[0].decision_timestamp + timedelta(days=10)
    )
    result = OnlineShadowTrainer(tmp_path).partial_fit(rows)
    assert result.validation_metrics["prequential_samples"] == 1
    assert result.validation_metrics["overlap_samples_excluded"] == 2
    assert result.sample_count == 3


def test_new_categories_and_missing_initial_numeric_values_do_not_change_dimensions(
    tmp_path,
):
    first = examples()[0]
    first = replace(first, features={**first.features, "volume_score": None})
    OnlineShadowTrainer(tmp_path).partial_fit([first])
    next_row = replace(
        examples()[1], features={**examples()[1].features, "regime": "unseen-regime"}
    )
    result = OnlineShadowTrainer(tmp_path).partial_fit([next_row])
    probability, net_r = result.model_bundle.predict([next_row])
    assert np.isfinite(probability).all() and np.isfinite(net_r).all()


def test_sample_weights_affect_updates_without_counting_extra_observations(tmp_path):
    rows = examples()[:12]
    full = OnlineShadowTrainer(tmp_path / "full").partial_fit(rows)
    weighted = OnlineShadowTrainer(tmp_path / "weighted").partial_fit(
        [replace(row, sample_weight=0.1) for row in rows]
    )
    assert full.sample_count == weighted.sample_count == 12
    assert not np.allclose(
        full.model_bundle.classifier.coef_, weighted.model_bundle.classifier.coef_
    )


def test_concurrent_workers_cannot_learn_the_same_evidence_twice(tmp_path):
    rows = examples()[:12]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: OnlineShadowTrainer(tmp_path).partial_fit(rows), range(2)
            )
        )
    assert sorted(row.parameters["new_samples"] for row in results) == [0, 12]
    assert {row.sample_count for row in results} == {12}


def test_corrupted_measurements_cannot_be_resumed_as_valid_learning(tmp_path):
    OnlineShadowTrainer(tmp_path).partial_fit(examples()[:12])
    with sqlite3.connect(tmp_path / "equity.sqlite") as db:
        stats = json.loads(db.execute("SELECT stats FROM checkpoint").fetchone()[0])
        stats["count"] = 999
        db.execute("UPDATE checkpoint SET stats=?", (json.dumps(stats),))
    with pytest.raises(ValueError, match="CHECKSUM"):
        OnlineShadowTrainer(tmp_path).partial_fit(examples()[:12])
