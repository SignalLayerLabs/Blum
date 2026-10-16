from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import time

import polars as pl
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    BackgroundJobState,
    BrainRuntimeEvent,
    DashboardSnapshot,
    TradingMLModelVersion,
    TradingMLTrainingRun,
)
from app.services.trading_ml.contracts import InsufficientTrainingEvidenceError
from app.services.trading_ml.dataset import DatasetSlice
from app.services.trading_ml.feature_store import ProjectionResult, _row_from_example
from app.services.trading_ml.registry import TradingMLModelRegistry
from app.services.trading_ml.training import SklearnTradingModelTrainer
from app.services.trading_ml.worker import TradingMLLearningWorker
from test_forex_historical_dataset import _write_dataset
from test_trading_ml_training import examples


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class FakeProjector:
    def __init__(self, source_count=16):
        self.source_count = source_count
        self.offsets = {"equity": 0, "forex": 0}
        self.rows = {"equity": [], "forex": []}

    def project(self, db, *, market_family, limit):
        offset = self.offsets[market_family]
        source = examples(self.source_count)[offset : offset + limit]
        mapped = [
            replace(
                row,
                source_object_id=f"{market_family}-{offset + index + 1}",
                market_family=market_family,
                features={**dict(row.features), "market_family": market_family},
                asset_key=(
                    f"FX{index % 6}" if market_family == "forex" else row.asset_key
                ),
            )
            for index, row in enumerate(source)
        ]
        self.rows[market_family].extend(mapped)
        self.offsets[market_family] += len(mapped)
        return ProjectionResult(
            rows_written=len(mapped),
            partitions_written=1 if mapped else 0,
            dataset_hash=f"dataset-{market_family}-{self.offsets[market_family]}",
            source_cursor={
                "source_table": "fake",
                "last_source_id": self.offsets[market_family],
                "source_offsets": {"fake": self.offsets[market_family]},
            },
            rows_considered=len(mapped),
            rows_rejected=0,
            is_exhausted=self.offsets[market_family] >= self.source_count,
        )

    def scan(self, *, market_family):
        return pl.DataFrame(
            [_row_from_example(row) for row in self.rows[market_family]]
        ).lazy()

    def manifest(self):
        return {
            "source_cursors": {
                family: {
                    "source_table": "fake",
                    "last_source_id": offset,
                    "source_offsets": {"fake": offset},
                }
                for family, offset in self.offsets.items()
            }
        }

    def online_page(self, *, market_family, cursor, limit):
        offset = int((cursor or {}).get("offset", 0))
        rows = self.rows[market_family][offset : offset + limit]
        return {
            "rows": [_row_from_example(row) for row in rows],
            "cursor": {"offset": offset + len(rows)},
            "rows_considered": len(rows),
            "rows_rejected": 0,
            "exhausted": offset + len(rows) >= len(self.rows[market_family]),
        }


def worker(tmp_path):
    instance = TradingMLLearningWorker(
        artifact_root=tmp_path, max_rows=8, max_runtime_seconds=30
    )
    instance.projector = FakeProjector()
    return instance


def test_worker_resumes_cursor_after_budget(db, tmp_path):
    instance = worker(tmp_path)
    first = instance.run_once(db, "test")
    first_cursor = dict(
        db.query(BackgroundJobState)
        .filter_by(job_name=instance.job_name)
        .one()
        .cursor_json
    )
    second = instance.run_once(db, "test")
    second_cursor = (
        db.query(BackgroundJobState)
        .filter_by(job_name=instance.job_name)
        .one()
        .cursor_json
    )
    assert first["markets"]["equity"]["status"] == "SHADOW"
    assert (
        second_cursor["equity"]["last_source_id"]
        >= first_cursor["equity"]["last_source_id"]
    )
    assert (
        db.query(DashboardSnapshot).filter_by(snapshot_type="trading_ml_status").count()
        == 2
    )
    assert (
        db.query(BrainRuntimeEvent).filter_by(source_module=instance.job_name).count()
        == 2
    )


def test_optional_external_work_cannot_consume_the_core_learning_budget_first(
    db, tmp_path, monkeypatch
):
    instance = worker(tmp_path)
    clock = {"now": 0.0}
    monkeypatch.setattr(
        "app.services.trading_ml.worker.time.perf_counter", lambda: clock["now"]
    )

    def expensive_optional(started):
        clock["now"] = 60.0
        return {"status": "TIMEOUT", "paper_only": True}

    monkeypatch.setattr(instance, "_run_finrlx", expensive_optional)
    result = instance.run_once(db, "budget-priority")
    assert result["markets"]["equity"]["status"] == "SHADOW"
    assert result["markets"]["forex"]["status"] == "SHADOW"


def test_worker_learns_old_unread_parts_and_does_not_retrain_unchanged_rows(
    db, tmp_path
):
    from app.services.trading_ml.feature_store import TradingMLFeatureStoreProjector
    from test_trading_ml_online_queue import Repository

    instance = TradingMLLearningWorker(
        artifact_root=tmp_path, max_rows=5, online_max_rows=5, max_runtime_seconds=30
    )
    instance.projector = TradingMLFeatureStoreProjector(
        root=tmp_path / "feature_store",
        repository=Repository(examples(20)),
        max_partition_rows=7,
    )
    instance.projector.project(None, market_family="equity", limit=20)
    results = [
        instance._run_market(db, "equity", "queue-test", time.perf_counter())
        for _ in range(5)
    ]
    assert [row["online"]["new_samples"] for row in results] == [5, 5, 5, 5, 0]
    assert [row["online"]["total_samples"] for row in results] == [5, 10, 15, 20, 20]


def test_empty_rejected_page_never_learns_the_latest_stable_window(tmp_path):
    instance = worker(tmp_path)
    stable = examples(8)

    class RejectedPage:
        def online_page(self, **kwargs):
            return dict(
                rows=[],
                cursor={"offset": 5},
                rows_considered=5,
                rows_rejected=5,
                exhausted=False,
            )

    instance.projector = RejectedPage()
    result, progress = instance._update_online("equity", stable)
    assert result is None
    assert progress["new_samples"] == progress["total_samples"] == 0


def test_lost_checkpoint_cannot_resume_from_a_reader_that_skips_old_history(
    db, tmp_path
):
    instance = worker(tmp_path)
    instance.run_once(db, "first")
    (tmp_path / "shadow" / "equity.sqlite").unlink()
    result = instance.run_once(db, "lost-checkpoint")
    assert result["markets"]["equity"]["status"] == "FAILED"
    assert "ONLINE_READER_CHECKPOINT_MISSING" in result["markets"]["equity"]["error"]


def test_online_progress_survives_registry_publication_failure(
    db, tmp_path, monkeypatch
):
    instance = worker(tmp_path)

    def broken_publication(*args, **kwargs):
        raise OSError("artifact disk unavailable")

    monkeypatch.setattr(instance.registry, "store_candidate", broken_publication)
    result = instance.run_once(db, "publication-failure")
    assert result["new_examples_learned"] == 16
    assert result["markets"]["equity"]["online"]["new_samples"] == 8
    assert result["markets"]["forex"]["online"]["new_samples"] == 8


def test_worker_isolates_market_family_failure(db, tmp_path, monkeypatch):
    instance = worker(tmp_path)
    original = instance._run_market

    def isolated(session, market_family, trigger, started, **kwargs):
        if market_family == "equity":
            raise RuntimeError("equity lane failed")
        return original(session, market_family, trigger, started, **kwargs)

    monkeypatch.setattr(instance, "_run_market", isolated)
    result = instance.run_once(db, "test")
    assert result["markets"]["equity"]["status"] == "FAILED"
    assert result["markets"]["forex"]["status"] == "SHADOW"


def test_worker_records_insufficient_chronology_as_evidence_gap(
    db, tmp_path, monkeypatch
):
    instance = TradingMLLearningWorker(
        artifact_root=tmp_path, max_rows=320, max_runtime_seconds=30
    )
    instance.projector = FakeProjector(source_count=320)

    def insufficient(*args, **kwargs):
        raise InsufficientTrainingEvidenceError(
            "Insufficient chronological history after applying purge and embargo for fold 1"
        )

    monkeypatch.setattr(
        "app.services.trading_ml.worker.BoundedOptunaChallengerSearch.search",
        insufficient,
    )

    result = instance.run_once(db, "test")

    assert result["status"] == "COMPLETED"
    assert result["markets"]["equity"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["markets"]["forex"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert {row.status for row in db.query(TradingMLTrainingRun).all()} == {
        "INSUFFICIENT_EVIDENCE"
    }


def test_worker_governs_invalid_active_artifact_outside_read_path(db, tmp_path):
    result = SklearnTradingModelTrainer().fit(examples())
    row = TradingMLModelRegistry(tmp_path).store_candidate(
        db,
        market_family="equity",
        result=result,
        asset_count=6,
        regime_count=2,
        setup_count=2,
    )
    row.status = "ACTIVE"
    row.sample_count = 300
    db.commit()
    Path(row.artifact_path).write_bytes(b"tampered")

    instance = worker(tmp_path)
    instance.run_once(db, "test")

    db.refresh(row)
    assert row.status == "DEGRADED"


def test_end_to_end_challenger_audit_chain(db, tmp_path):
    instance = worker(tmp_path)
    result = instance.run_once(db, "certification")
    assert result["markets"]["equity"]["status"] == "SHADOW"
    model = db.query(TradingMLModelVersion).first()
    assert model.dataset_hash
    assert model.artifact_sha256
    assert model.status == "SHADOW"


class FakeFinRLXEngine:
    enabled = True

    def __init__(self, *, result_by_market=None):
        self.training_requests = []
        self.result_by_market = result_by_market or {}

    def status(self, market_family="forex"):
        return {"status": "NO_VALIDATED_ARTIFACT", "paper_only": True}

    def run_training(self, *, market_family, request):
        self.training_requests.append((market_family, request))
        return self.result_by_market.get(market_family) or {
            "status": "VALIDATED_SHADOW",
            "paper_only": True,
            "manifest": {"algorithm": "PPO", "market_family": market_family},
        }


class ExistingFinRLXEngine(FakeFinRLXEngine):
    def __init__(self, dataset_hash):
        super().__init__()
        self.dataset_hash = dataset_hash

    def status(self, market_family="forex"):
        return {
            "status": "READY_SHADOW",
            "paper_only": True,
            "manifest": {
                "market_family": market_family,
                "dataset_hash": self.dataset_hash,
            },
        }


def test_worker_runs_optional_finrlx_research_inside_existing_budget(db, tmp_path):
    instance = worker(tmp_path)
    finrlx = FakeFinRLXEngine()
    instance.finrlx = finrlx

    result = instance.run_once(db, "test")

    assert result["finrlx"]["status"] == "VALIDATED_SHADOW"
    assert finrlx.training_requests[0][0] == "forex"
    assert finrlx.training_requests[1][0] == "equity"
    assert finrlx.training_requests[0][1]["max_rows"] == 8
    assert set(result["finrlx"]["markets"]) == {"equity", "forex"}
    stored = (
        db.query(DashboardSnapshot).filter_by(snapshot_type="trading_ml_status").first()
    )
    assert stored.payload_json["finrlx"]["paper_only"] is True


def test_worker_projects_external_forex_history_before_finrlx_training(
    db,
    tmp_path,
):
    source = tmp_path / "forex.csv"
    _write_dataset(source)
    instance = TradingMLLearningWorker(
        artifact_root=tmp_path / "artifacts",
        max_rows=500,
        max_runtime_seconds=30,
        forex_history_source=source,
    )
    finrlx = FakeFinRLXEngine()
    instance.finrlx = finrlx

    result = instance.run_once(db, "test")

    assert result["forex_history"]["status"] == "READY"
    assert result["forex_history"]["examples_available"] > 0
    assert (tmp_path / "artifacts" / "forex_historical_knowledge.json").is_file()
    assert finrlx.training_requests[0][0] == "forex"


def test_worker_retrains_finrlx_only_when_feature_dataset_changed(tmp_path):
    instance = TradingMLLearningWorker(
        artifact_root=tmp_path,
        max_rows=8,
        max_runtime_seconds=30,
    )
    current_hash = instance.projector.market_dataset_hash("forex")
    current = ExistingFinRLXEngine(current_hash)
    instance.finrlx = current

    unchanged = instance._run_finrlx(time.perf_counter())

    assert unchanged["markets"]["forex"]["status"] == "READY_SHADOW"
    assert current.training_requests == []

    stale = ExistingFinRLXEngine("old-dataset")
    instance.finrlx = stale
    changed = instance._run_finrlx(time.perf_counter())

    assert changed["markets"]["forex"]["status"] == "VALIDATED_SHADOW"
    assert [market for market, _ in stale.training_requests] == ["forex", "equity"]


def test_optional_finrlx_respects_the_budget_remaining_after_core_work(
    db,
    tmp_path,
    monkeypatch,
):
    instance = worker(tmp_path)
    instance.max_runtime_seconds = 2
    finrlx = FakeFinRLXEngine()
    instance.finrlx = finrlx

    def consume_budget(session, market_family, trigger, started, **kwargs):
        time.sleep(2.05)
        return {"status": "SHADOW", "rows_considered": 0}

    monkeypatch.setattr(instance, "_run_market", consume_budget)

    result = instance.run_once(db, "test")

    assert result["finrlx"]["status"] == "BUDGET_EXHAUSTED"
    assert finrlx.training_requests == []


def test_both_online_lanes_update_before_equity_challenger_consumes_remaining_budget(
    db, tmp_path, monkeypatch
):
    instance = TradingMLLearningWorker(
        artifact_root=tmp_path, max_rows=320, max_runtime_seconds=30
    )
    instance.projector = FakeProjector(source_count=320)
    clock = {"now": 0.0}
    monkeypatch.setattr(
        "app.services.trading_ml.worker.time.perf_counter", lambda: clock["now"]
    )

    def consume_challenger(*args, **kwargs):
        clock["now"] = 60.0
        raise InsufficientTrainingEvidenceError("bounded test search")

    monkeypatch.setattr(
        "app.services.trading_ml.worker.BoundedOptunaChallengerSearch.search",
        consume_challenger,
    )
    result = instance.run_once(db, "fair-core-budget")
    assert result["markets"]["equity"]["online"]["new_samples"] == 320
    assert result["markets"]["forex"]["online"]["new_samples"] == 320
    assert result["new_examples_learned"] == 640


def test_an_entirely_skipped_cycle_is_reported_as_budget_exhausted(
    db, tmp_path, monkeypatch
):
    instance = worker(tmp_path)
    calls = {"count": 0}

    def clock():
        calls["count"] += 1
        return 0.0 if calls["count"] == 1 else 100.0

    monkeypatch.setattr("app.services.trading_ml.worker.time.perf_counter", clock)
    result = instance.run_once(db, "no-budget")
    assert result["status"] == "BUDGET_EXHAUSTED"
    assert result["new_examples_learned"] == 0


def test_worker_can_validate_equity_when_forex_evidence_is_single_class(db, tmp_path):
    instance = worker(tmp_path)
    finrlx = FakeFinRLXEngine(
        result_by_market={
            "forex": {
                "status": "INSUFFICIENT_EVIDENCE",
                "reason": "Both positive and negative outcomes are required.",
                "sample_count": 500,
                "paper_only": True,
            }
        }
    )
    instance.finrlx = finrlx

    result = instance.run_once(db, "test")

    assert result["finrlx"]["status"] == "VALIDATED_SHADOW"
    assert result["finrlx"]["markets"]["forex"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["finrlx"]["markets"]["equity"]["status"] == "VALIDATED_SHADOW"


def test_finrlx_market_training_gets_half_of_worker_budget(tmp_path):
    instance = TradingMLLearningWorker(
        artifact_root=tmp_path,
        max_rows=500,
        max_runtime_seconds=120,
    )
    finrlx = FakeFinRLXEngine()
    instance.finrlx = finrlx

    result = instance._run_finrlx(time.perf_counter())

    assert result["status"] == "VALIDATED_SHADOW"
    assert {
        request["max_runtime_seconds"] for _, request in finrlx.training_requests
    } == {60}


def test_online_backlog_can_exceed_the_small_challenger_window(db, tmp_path):
    from app.services.trading_ml.feature_store import TradingMLFeatureStoreProjector
    from test_trading_ml_online_queue import Repository

    instance = TradingMLLearningWorker(
        artifact_root=tmp_path, max_rows=5, online_max_rows=20, max_runtime_seconds=30
    )
    instance.projector = TradingMLFeatureStoreProjector(
        root=tmp_path / "feature_store",
        repository=Repository(examples(20)),
        max_partition_rows=7,
    )
    instance.projector.project(None, market_family="equity", limit=20)
    result = instance._run_market(
        db, "equity", "bigger-online-slice", time.perf_counter()
    )
    assert result["sample_count"] == 5
    assert result["online"]["new_samples"] == result["online"]["total_samples"] == 20


@pytest.mark.parametrize("cleanup_also_fails", [False, True])
def test_cursor_publication_failure_reports_already_committed_online_progress(
    db, tmp_path, monkeypatch, cleanup_also_fails
):
    instance = worker(tmp_path)

    def no_replace(*args, **kwargs):
        raise OSError("reader publication unavailable")

    monkeypatch.setattr("app.services.trading_ml.worker.os.replace", no_replace)
    if cleanup_also_fails:
        original_unlink = Path.unlink

        def failed_reader_cleanup(path, *args, **kwargs):
            if "reader.json" in path.name and path.name.endswith(".tmp"):
                raise OSError("reader cleanup also unavailable")
            return original_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", failed_reader_cleanup)
    result = instance.run_once(db, "cursor-publication-failed")
    assert result["new_examples_learned"] == 16
    assert result["markets"]["equity"]["online"]["new_samples"] == 8
