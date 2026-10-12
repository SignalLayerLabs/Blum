from datetime import datetime, timedelta
from dataclasses import replace
from types import SimpleNamespace
import json
from copy import deepcopy

import pytest
from filelock import FileLock
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import AscentExperiment, AscentGeneration, AscentEvidenceUse
from app.services.ascent.engine import AscentEvolutionEngine
from app.services.ascent.dataset import FrozenConfidenceBuilder
from test_ascent_evaluation import evidence
from test_trading_ml_features import equity_prediction as raw_equity_prediction, equity_outcome


def equity_prediction():
    prediction = raw_equity_prediction()
    prediction.model_version_used = "base-static"
    prediction.learning_memory_used = {}
    prediction.strategy_memory_used = {}
    return prediction


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def engine(tmp_path, **kwargs):
    return AscentEvolutionEngine(artifact_root=tmp_path, enabled=True,
        source_revision="a" * 40, **kwargs)


def test_full_cycle_persists_real_source_and_holdout_result(db, tmp_path):
    service = engine(tmp_path)
    result = service.run_once(db, examples=evidence(), as_of=datetime(2026, 1, 1))
    assert result["status"] == "COMPLETED"
    experiments = db.scalars(select(AscentExperiment)).all()
    assert len(experiments) == 4
    retained = [row for row in experiments if row.status == "RETAINED_RESEARCH"]
    assert len(retained) == 1
    # Purge leaves 54 positive outcomes among 109 initial training examples.
    assert result["manifest"]["training_prior"] == pytest.approx(54 / 109)
    assert retained[0].result_json["candidate"]["brier_score"] == pytest.approx(0.25002104199982883)
    assert retained[0].result_json["production_eligible"] is False
    assert len(db.scalars(select(AscentEvidenceUse)).all()) == 600
    workspace = tmp_path / result["generation_uid"] / retained[0].experiment_uid
    assert "def calibrate(p)" in (workspace / "candidate.py").read_text()
    assert json.loads((workspace / "regression_cases.json").read_text())
    assert not (workspace / "holdout.json").exists()
    assert service.snapshot(db)["research_champions"]


def test_consumed_evidence_never_enters_later_optimization(db, tmp_path):
    service = engine(tmp_path)
    service.run_once(db, examples=evidence(), as_of=datetime(2026, 1, 1))
    result = service.run_once(db, examples=evidence(), as_of=datetime(2026, 1, 1))
    assert result["status"] == "BLOCKED"
    assert "INSUFFICIENT_OR_EXCESSIVE_SAMPLE" in result["blockers"]
    assert result["excluded_previously_used"] == 600


def test_checkpoint_resumes_same_generation_without_new_candidates(db, tmp_path):
    service = engine(tmp_path)
    first = service.run_once(db, examples=evidence(), as_of=datetime(2026, 1, 1), stop_after="GENERATED")
    assert first["status"] == "GENERATED"
    resumed = service.run_once(db, generation_uid=first["generation_uid"])
    assert resumed["status"] == "COMPLETED"
    assert resumed["generation_uid"] == first["generation_uid"]
    assert len(db.scalars(select(AscentExperiment)).all()) == 4


def test_tampered_source_is_failed_without_rewriting_or_executing_it(db, tmp_path):
    service = engine(tmp_path)
    result = service.run_once(db, examples=evidence(), as_of=datetime(2026, 1, 1), stop_after="GENERATED")
    row = db.scalars(select(AscentExperiment)).first()
    target = tmp_path / result["generation_uid"] / row.experiment_uid / "candidate.py"
    target.write_text("import os\nos.system('touch compromised')\n")
    resumed = service.run_once(db, generation_uid=result["generation_uid"])
    assert resumed["status"] == "FAILED"
    assert "ARTIFACT_HASH_MISMATCH" in resumed["blockers"]
    assert not (tmp_path / "compromised").exists()


def test_opened_holdout_cannot_be_replayed_after_interruption(db, tmp_path):
    service = engine(tmp_path)
    result = service.run_once(db, examples=evidence(), as_of=datetime(2026, 1, 1), stop_after="GENERATED")
    row = db.scalar(select(AscentGeneration))
    row.status = "VALIDATING"
    row.holdout_opened = True
    db.commit()
    resumed = service.run_once(db, generation_uid=result["generation_uid"])
    assert resumed["status"] == "FAILED"
    assert "HOLDOUT_ALREADY_OPENED" in resumed["blockers"]


def test_disabled_or_concurrent_cycles_do_not_create_experiments(db, tmp_path):
    disabled = AscentEvolutionEngine(artifact_root=tmp_path, enabled=False)
    assert disabled.run_once(db)["status"] == "DISABLED"
    with FileLock(str(tmp_path / ".cycle.lock")):
        assert engine(tmp_path).run_once(db)["status"] == "BUSY"
    assert not db.scalars(select(AscentExperiment)).all()


def test_adapter_keeps_historical_replay_and_frozen_confidence(db):
    prediction = equity_prediction()
    prediction.point_in_time_context.pop("future_prices")
    row = FrozenConfidenceBuilder().from_equity(prediction, equity_outcome(realized_return=4))
    assert row.evidence_lane == "REPLAY_EVIDENCE"
    assert row.features["confidence"] == 72
    assert set(row.features) == {"confidence", "data_quality_score", "expected_cost"}


def test_adapter_blocks_future_input_instead_of_silently_dropping_it():
    prediction = equity_prediction()
    prediction.point_in_time_context["technical"] = {"as_of": "2026-01-03T10:00:00"}
    with pytest.raises(ValueError, match="FUTURE"):
        FrozenConfidenceBuilder().from_equity(prediction, equity_outcome(realized_return=4))


def test_known_outcome_frame_cannot_become_a_calibration_input():
    row = FrozenConfidenceBuilder().from_equity(equity_prediction(), equity_outcome(realized_return=4))
    assert row.features["confidence"] == 72
    assert "future_prices" not in row.features


def test_real_historical_ledger_uses_analysis_date_even_when_created_today():
    prediction = equity_prediction()
    prediction.analysis_date = datetime(2020, 1, 1).date()
    prediction.created_at = datetime(2026, 10, 12)
    prediction.point_in_time_context = {"market_timestamp": "2020-01-01T16:00:00"}
    outcome = equity_outcome(realized_return=4, evaluation_date=datetime(2020, 1, 20))
    row = FrozenConfidenceBuilder().from_equity(prediction, outcome)
    assert row.decision_timestamp.date() == datetime(2020, 1, 1).date()
    assert row.outcome_timestamp > row.decision_timestamp


def test_blocked_pages_accumulate_evidence_and_advance_cursor(db, tmp_path, monkeypatch):
    from app.services.ascent.dataset import AscentDatasetRepository
    after = []
    rows = evidence()
    def read_page(self, db, *, market_family, after_cursor, limit):
        after.append(after_cursor)
        offset = 0 if after_cursor is None else after_cursor["offset"]
        return SimpleNamespace(examples=rows[offset:offset + 300], next_cursor={"offset": offset + 300},
            rows_considered=300, rows_rejected=0)
    monkeypatch.setattr(AscentDatasetRepository, "read_slice", read_page)
    service = engine(tmp_path)
    assert service.run_once(db, as_of=datetime(2026, 1, 1))["status"] == "BLOCKED"
    second = service.run_once(db, as_of=datetime(2026, 1, 1))
    assert after == [None, {"offset": 300}]
    assert second["status"] == "COMPLETED"
    assert len(db.scalars(select(AscentEvidenceUse)).all()) == 600


def test_backfilled_dataset_cannot_use_champion_selected_on_future_evidence(db, tmp_path):
    service = engine(tmp_path)
    service.run_once(db, examples=evidence(), as_of=datetime(2026, 1, 1))
    backfill = tuple(replace(row, source_object_id=f"backfill-{row.source_object_id}",
        decision_timestamp=row.decision_timestamp - timedelta(days=1000),
        outcome_timestamp=row.outcome_timestamp - timedelta(days=1000)) for row in evidence())
    second = service.run_once(db, examples=backfill, as_of=datetime(2026, 1, 1))
    assert second["manifest"]["champion_experiment_uid"] is None
    assert second["manifest"]["champion_status"] == "NO_TEMPORALLY_ELIGIBLE_RESEARCH_CHAMPION"


def test_historical_confidence_with_unverified_learned_weights_is_ineligible():
    prediction = equity_prediction()
    prediction.model_version_used = "trained-after-the-historical-decision"
    with pytest.raises(ValueError, match="UNVERIFIED_HISTORICAL_MODEL"):
        FrozenConfidenceBuilder().from_equity(prediction, equity_outcome(realized_return=4))


def test_historical_memory_adjustments_cannot_leak_later_outcomes():
    prediction = equity_prediction()
    prediction.learning_memory_used = {"signal_performance": [{"samples": 20}], "confidence_delta": 3}
    with pytest.raises(ValueError, match="UNVERIFIED_HISTORICAL_MEMORY"):
        FrozenConfidenceBuilder().from_equity(prediction, equity_outcome(realized_return=4))


def test_changed_benchmark_evidence_invalidates_the_frozen_snapshot(db, tmp_path):
    service = engine(tmp_path)
    result = service.run_once(db, examples=evidence(), as_of=datetime(2026, 1, 1), stop_after="GENERATED")
    row = db.scalar(select(AscentGeneration))
    changed = deepcopy(row.snapshot_json)
    changed["holdout"][0]["benchmark_excess"] = 99999
    row.snapshot_json = changed
    db.commit()
    resumed = service.run_once(db, generation_uid=result["generation_uid"])
    assert resumed["status"] == "FAILED"
    assert "SNAPSHOT_HASH_MISMATCH" in resumed["blockers"]
    assert not resumed["holdout_opened"]


def test_regenerated_ledger_ids_cannot_reuse_the_same_economic_decisions(db, tmp_path):
    service = engine(tmp_path)
    service.run_once(db, examples=evidence(), as_of=datetime(2026, 1, 1))
    regenerated = tuple(replace(row, source_object_id=f"regenerated-{row.source_object_id}") for row in evidence())
    result = service.run_once(db, examples=regenerated, as_of=datetime(2026, 1, 1))
    assert result["status"] == "BLOCKED"
    assert result["excluded_previously_used"] == 600
