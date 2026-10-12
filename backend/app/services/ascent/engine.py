"""Checkpointed research-only OBSERVE → RETAIN/REJECT cycle.

The host is trusted orchestration. Candidate arithmetic has no capabilities and
receives one scalar confidence at a time. Source artifacts cannot replace the
application, evaluator, benchmark, risk policy or deployment configuration.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from uuid import uuid4

from filelock import FileLock, Timeout
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (AscentEvidenceUse, AscentExperiment, AscentGeneration,
                        StrategyCandidateVariant, TradingMLModelVersion)
from app.services.trading_ml.contracts import TradingMLExample
from app.services.trading_ml.validation import PurgedWalkForwardEvaluator, example_source_uid
from .dataset import AscentDatasetRepository
from .evaluation import (EMBARGO_DAYS, LANES, POLICY_VERSION, decision_identity, freeze_split,
                         metrics_json, predictions, utc_naive, validate_candidate)
from .kernel import ArithmeticKernel, IDENTITY_SOURCE, KERNEL_VERSION, generate_candidates


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def pack(row: TradingMLExample) -> dict:
    return {"source_object_type": row.source_object_type, "source_object_id": row.source_object_id,
            "market_family": row.market_family, "evidence_lane": row.evidence_lane,
            "decision_timestamp": utc_naive(row.decision_timestamp).isoformat(),
            "outcome_timestamp": utc_naive(row.outcome_timestamp).isoformat(),
            "asset_key": row.asset_key, "setup_type": row.setup_type, "regime": row.regime,
            "features": dict(row.features), "realized_net_r": row.realized_net_r,
            "label_positive_r": row.label_positive_r, "benchmark_excess": row.benchmark_excess,
            "sample_weight": row.sample_weight}


def unpack(value: dict) -> TradingMLExample:
    value = dict(value)
    for field in ("decision_timestamp", "outcome_timestamp"):
        value[field] = datetime.fromisoformat(value[field])
    return TradingMLExample(**value)


def trusted_code_hash() -> str:
    files = [Path(__file__), Path(__file__).with_name("kernel.py"), Path(__file__).with_name("evaluation.py"),
             Path(__file__).with_name("dataset.py"), Path(__file__).parents[1] / "trading_ml" / "validation.py"]
    return digest({path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files})


def source_revision() -> str:
    configured = os.environ.get("BLUM_SOURCE_REVISION", "")
    if re.fullmatch(r"[0-9a-f]{40}", configured):
        return configured
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parents[4],
                                       stderr=subprocess.DEVNULL, timeout=2, env={"PATH": os.defpath}).decode().strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


class AscentEvolutionEngine:
    def __init__(self, *, artifact_root=None, enabled=None, source_revision=None,
                 max_rows=None, max_seconds=None):
        settings = get_settings()
        self.enabled = settings.ascent_enabled if enabled is None else enabled
        self.root = Path(artifact_root or settings.ascent_artifact_root).resolve()
        self.revision = source_revision or globals()["source_revision"]()
        self.max_rows = max(400, min(2000, max_rows or settings.ascent_max_rows))
        self.max_seconds = max(1, min(90, max_seconds or settings.ascent_max_seconds))

    def run_once(self, db: Session, *, market_family="equity", evidence_lane="REPLAY_EVIDENCE",
                 generation_uid=None, examples=None, as_of=None, stop_after=None) -> dict:
        if not self.enabled:
            return {"status": "DISABLED", "production_eligible": False}
        if market_family not in ("equity", "forex") or evidence_lane not in LANES:
            raise ValueError("UNSUPPORTED_RESEARCH_LANE")
        if stop_after not in (None, "GENERATED", "SELECTED"):
            raise ValueError("INVALID_CHECKPOINT")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            with FileLock(str(self.root / ".cycle.lock"), timeout=0):
                return self._run_locked(db, market_family, evidence_lane, generation_uid,
                                        examples, utc_naive(as_of or now()), stop_after)
        except Timeout:
            return {"status": "BUSY", "production_eligible": False}

    def _run_locked(self, db, market, lane, uid, examples, as_of, stop_after):
        started = time.monotonic()
        if uid and not re.fullmatch(r"ascent-[0-9a-f]{32}", uid):
            raise ValueError("INVALID_GENERATION_UID")
        generation = db.scalar(select(AscentGeneration).where(AscentGeneration.generation_uid == uid)) if uid else db.scalar(
            select(AscentGeneration).where(AscentGeneration.market_family == market,
                AscentGeneration.evidence_lane == lane, AscentGeneration.status.in_(("FROZEN", "GENERATED", "SELECTED", "VALIDATING")))
            .order_by(AscentGeneration.id).limit(1))
        if uid and generation is None:
            raise ValueError("GENERATION_NOT_FOUND")
        if generation and generation.status in ("COMPLETED", "FAILED", "BLOCKED"):
            return self._generation_json(generation)
        if generation is None:
            daily = db.scalar(select(func.count(AscentGeneration.id)).where(AscentGeneration.started_at >= now() - timedelta(days=1)))
            if daily >= 8:
                return {"status": "DAILY_BUDGET_EXHAUSTED", "production_eligible": False}
            generation = self._observe(db, market, lane, examples, as_of)
            if generation.status == "BLOCKED":
                return self._generation_json(generation)
        try:
            if generation.holdout_opened:
                raise ValueError("HOLDOUT_ALREADY_OPENED")
            if generation.manifest_json["trusted_code_hash"] != trusted_code_hash():
                raise ValueError("TRUSTED_EVALUATOR_CHANGED")
            if generation.manifest_json["dataset_hash"] != digest(generation.snapshot_json):
                raise ValueError("SNAPSHOT_HASH_MISMATCH")
            if generation.source_revision != self.revision:
                raise ValueError("SOURCE_REVISION_CHANGED")
            development = tuple(unpack(row) for row in generation.snapshot_json["development"])
            if generation.status == "FROZEN":
                self._generate(db, generation, development)
            experiments = db.scalars(select(AscentExperiment).where(
                AscentExperiment.generation_uid == generation.generation_uid).order_by(AscentExperiment.id)).all()
            for experiment in experiments:
                self._read_source(generation, experiment)
            if stop_after == "GENERATED":
                return self._generation_json(generation)
            if generation.status == "GENERATED":
                self._compete(db, generation, experiments, development, started)
            if stop_after == "SELECTED":
                return self._generation_json(generation)
            self._check_budget(started)
            chosen = next(row for row in experiments if row.experiment_uid == generation.selected_experiment_uid)
            # Opening is durable before reading labels. A crash here consumes the holdout.
            generation.status, generation.holdout_opened = "VALIDATING", True
            db.commit()
            holdout = tuple(unpack(row) for row in generation.snapshot_json["holdout"])
            result = validate_candidate(holdout, source=self._read_source(generation, chosen),
                champion_source=generation.snapshot_json["champion_source"],
                prior=generation.manifest_json["training_prior"],
                trial_number=generation.manifest_json["trial_number"])
            self._check_budget(started)
            if not re.fullmatch(r"[0-9a-f]{40}", generation.source_revision):
                result["blockers"].append("MISSING_CODE_REVISION")
                result["research_eligible"] = False
            chosen.result_json = result
            chosen.status = "RETAINED_RESEARCH" if result["research_eligible"] else "REJECTED"
            for row in experiments:
                if row is not chosen:
                    row.status = "NOT_SELECTED"
                    row.result_json = {"blockers": ["DEVELOPMENT_COMPARISON_LOST"], "holdout_evaluated": False,
                                       "production_eligible": False}
            generation.summary_json = {**generation.summary_json, "blockers": result["blockers"],
                "research_retained": result["research_eligible"], "financial_effect": "UNCHANGED_DECISIONS",
                "duration_seconds": round(time.monotonic() - started, 3)}
            generation.status, generation.completed_at = "COMPLETED", now()
            db.commit()
        except Exception as exc:
            db.rollback()
            generation.status, generation.completed_at = "FAILED", now()
            generation.summary_json = {**generation.summary_json, "blockers": [str(exc)[:240]],
                "error_type": type(exc).__name__, "research_retained": False,
                "duration_seconds": round(time.monotonic() - started, 3)}
            for row in db.scalars(select(AscentExperiment).where(AscentExperiment.generation_uid == generation.generation_uid)):
                row.status = "FAILED"
                row.result_json = {"blockers": [str(exc)[:240]], "production_eligible": False}
            db.commit()
        return self._generation_json(generation)

    def _observe(self, db, market, lane, examples, as_of):
        previous = db.scalars(select(AscentGeneration).where(AscentGeneration.market_family == market,
            AscentGeneration.evidence_lane == lane).order_by(desc(AscentGeneration.id)).limit(100)).all()
        cursor = next((row.manifest_json.get("next_cursor") for row in previous if row.snapshot_json), None)
        pending = previous[0] if previous and previous[0].status == "BLOCKED" else None
        pending_rows = tuple(unpack(row) for row in pending.snapshot_json.get("pending", [])) if pending else ()
        if pending_rows and (pending.manifest_json.get("dataset_hash") != digest(pending.snapshot_json) or
                pending.manifest_json.get("trusted_code_hash") != trusted_code_hash()):
            raise ValueError("PENDING_SNAPSHOT_CHANGED")
        repository = AscentDatasetRepository()
        if examples is None:
            page = repository.read_slice(db, market_family=market, after_cursor=cursor, limit=self.max_rows - len(pending_rows))
            examples = (*pending_rows, *page.examples)
            next_cursor, considered, rejected = page.next_cursor, page.rows_considered, page.rows_rejected
        else:
            examples = tuple(examples)
            next_cursor, considered, rejected = cursor, len(examples), 0
        if len(examples) > self.max_rows:
            raise ValueError("ROW_BUDGET_EXCEEDED")
        uids = [example_source_uid(row) for row in examples]
        identities = [decision_identity(row) for row in examples]
        used_rows = db.execute(select(AscentEvidenceUse.source_uid, AscentEvidenceUse.decision_identity).where(or_(
            AscentEvidenceUse.source_uid.in_(uids), AscentEvidenceUse.decision_identity.in_(identities)))).all()
        used_uids, used_identities = {row[0] for row in used_rows}, {row[1] for row in used_rows}
        unused = tuple(row for row in examples if example_source_uid(row) not in used_uids and decision_identity(row) not in used_identities)
        filtered = tuple(row for row in unused if
                         row.market_family == market and row.evidence_lane == lane)
        provenance = {**(pending.manifest_json.get("source_provenance", {}) if pending else {}),
                      **repository.frozen_builder.provenance}
        provenance = {example_source_uid(row): provenance[example_source_uid(row)] for row in filtered
                      if example_source_uid(row) in provenance}
        generation = AscentGeneration(generation_uid=f"ascent-{uuid4().hex}",
            parent_uid=previous[0].generation_uid if previous else None,
            market_family=market, evidence_lane=lane, status="FROZEN", source_revision=self.revision,
            hypothesis="Shrink frozen decision confidence toward training net-positive-R frequency to improve calibration without changing trade selection.",
            started_at=now(), summary_json={"excluded_previously_used": len(examples) - len(unused),
                "rows_considered": considered, "adapter_rejected": rejected,
                "excluded_other_lanes": len(unused) - len(filtered)})
        db.add(generation)
        try:
            split = freeze_split(filtered, as_of=as_of)
            evaluator = PurgedWalkForwardEvaluator(min_folds=3, embargo_days=EMBARGO_DAYS)
            first_train = evaluator.split(split.development)[0].train
            if len(first_train) < 30:
                raise ValueError("INSUFFICIENT_INITIAL_TRAINING_SAMPLE")
            prior = sum(row.label_positive_r for row in first_train) / len(first_train)
            champion = self._research_champion(db, market, lane,
                available_before=min(row.decision_timestamp for row in split.development))
            generation.snapshot_json = {"development": [pack(row) for row in split.development],
                "holdout": [pack(row) for row in split.holdout],
                "champion_source": champion.source_text if champion else IDENTITY_SOURCE}
            generation.manifest_json = {"as_of": as_of.isoformat(), "dataset_hash": digest(generation.snapshot_json),
                "trusted_code_hash": trusted_code_hash(), "policy_version": POLICY_VERSION,
                "kernel_version": KERNEL_VERSION, "seed": generation.seed, "python_version": sys.version.split()[0],
                "training_prior": prior, "training_samples": len(first_train), "development_samples": len(split.development),
                "holdout_samples": len(split.holdout), "purged_rows": split.purged_count, "embargo_days": EMBARGO_DAYS,
                "trial_number": int(db.scalar(select(func.count(AscentGeneration.id)).where(AscentGeneration.holdout_opened.is_(True))) or 0),
                "next_cursor": next_cursor, "champion_experiment_uid": champion.experiment_uid if champion else None,
                "champion_status": "TEMPORALLY_ELIGIBLE_RESEARCH_CHAMPION" if champion else "NO_TEMPORALLY_ELIGIBLE_RESEARCH_CHAMPION",
                "baseline_model": "frozen_confidence_proxy", "source_provenance": provenance,
                "budgets": {"max_rows": self.max_rows, "max_candidates": 4, "max_seconds": self.max_seconds,
                            "gpu_seconds": 0, "external_inference_calls": 0, "max_generations_per_day": 8}}
            train_ids = {example_source_uid(row) for row in split.development}
            holdout_ids = {example_source_uid(row) for row in split.holdout}
            for row in filtered:
                uid = example_source_uid(row)
                db.add(AscentEvidenceUse(source_uid=uid, decision_identity=decision_identity(row), generation_uid=generation.generation_uid,
                    partition="HOLDOUT" if uid in holdout_ids else "DEVELOPMENT" if uid in train_ids else "PURGED"))
            db.commit()
        except ValueError as exc:
            generation.status, generation.completed_at = "BLOCKED", now()
            # Bounded pages accumulate while preserving the cursor. Other invalid
            # snapshots are rejected rather than poisoning every later page.
            keep = str(exc).startswith("INSUFFICIENT_") and len(filtered) < self.max_rows
            generation.snapshot_json = {"pending": [pack(row) for row in filtered] if keep else []}
            generation.manifest_json = {"next_cursor": next_cursor, "dataset_hash": digest(generation.snapshot_json),
                                        "trusted_code_hash": trusted_code_hash(), "source_provenance": provenance if keep else {}}
            generation.summary_json = {**generation.summary_json, "blockers": [str(exc)]}
            db.commit()
        return generation

    def _generate(self, db, generation, development):
        existing = db.scalars(select(AscentExperiment).where(AscentExperiment.generation_uid == generation.generation_uid)).all()
        if existing:
            raise ValueError("PARTIAL_GENERATION_REQUIRES_REVIEW")
        prior = generation.manifest_json["training_prior"]
        for index, source in enumerate(generate_candidates(prior=prior)):
            kernel = ArithmeticKernel(source)
            uid = f"{generation.generation_uid}-c{index + 1}"
            workspace = self._workspace(generation.generation_uid, uid)
            workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
            cases = [{"input": p, "expected": kernel.predict(p)} for p in (0, 0.25, 0.5, 0.75, 1)]
            self._write_new(workspace / "candidate.py", source)
            self._write_new(workspace / "regression_cases.json", json.dumps(cases, indent=2))
            db.add(AscentExperiment(experiment_uid=uid, generation_uid=generation.generation_uid,
                status="GENERATED", source_text=source, source_sha256=kernel.sha256))
        generation.status = "GENERATED"
        db.commit()

    def _compete(self, db, generation, experiments, development, started):
        evaluator = PurgedWalkForwardEvaluator(min_folds=3, embargo_days=EMBARGO_DAYS)
        baseline = predictions(generation.snapshot_json["champion_source"], development)
        for row in experiments:
            self._check_budget(started)
            if row.development_json:
                continue
            source = self._read_source(generation, row)
            evaluation = evaluator.evaluate(predictions(source, development), baseline, development)
            row.development_json = {"candidate": metrics_json(evaluation.candidate),
                "champion": metrics_json(evaluation.baseline), "brier_improvement": evaluation.brier_improvement,
                "folds": [{"index": fold.fold.fold_index, "validation_start": fold.fold.validation_start.isoformat(),
                    "train_samples": len(fold.fold.train), "validation_samples": len(fold.fold.validation),
                    "brier_improvement": fold.baseline.metrics.brier_score - fold.candidate.metrics.brier_score} for fold in evaluation.folds]}
            row.status = "TESTED"
            db.commit()
        selected = min(experiments, key=lambda row: (row.development_json["candidate"]["brier_score"], row.experiment_uid))
        generation.selected_experiment_uid, generation.status = selected.experiment_uid, "SELECTED"
        generation.summary_json = {**generation.summary_json, "diagnosis": "Calibration candidates ranked using development walk-forward Brier loss only.",
                                  "selection_frozen_before_holdout": True}
        db.commit()

    def _workspace(self, generation_uid, experiment_uid):
        if not re.fullmatch(r"ascent-[0-9a-f]{32}", generation_uid) or not re.fullmatch(re.escape(generation_uid) + r"-c[1-4]", experiment_uid):
            raise ValueError("INVALID_WORKSPACE_ID")
        path = self.root / generation_uid / experiment_uid
        if path.resolve() != path or not path.is_relative_to(self.root):
            raise ValueError("WORKSPACE_SYMLINK_OR_ESCAPE")
        return path

    @staticmethod
    def _write_new(path, content):
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)

    def _read_source(self, generation, experiment):
        path = self._workspace(generation.generation_uid, experiment.experiment_uid) / "candidate.py"
        if path.is_symlink() or path.stat().st_size > 2048:
            raise ValueError("INVALID_ARTIFACT_PATH_OR_SIZE")
        source = path.read_text()
        kernel = ArithmeticKernel(source) if hashlib.sha256(source.encode()).hexdigest() == experiment.source_sha256 else None
        if kernel is None or source != experiment.source_text:
            raise ValueError("ARTIFACT_HASH_MISMATCH")
        # Generated tests are checked against a separate closed-form contract.
        prior = generation.manifest_json["training_prior"]
        index = int(experiment.experiment_uid[-1]) - 1
        slope = (0.0, 0.25, 0.5, 0.75)[index]
        for p in (0, 0.25, 0.5, 0.75, 1):
            if abs(kernel.predict(p) - (slope * p + (1 - slope) * prior)) > 1e-10:
                raise ValueError("GENERATED_REGRESSION_TEST_FAILED")
        return source

    def _check_budget(self, started):
        if time.monotonic() - started > self.max_seconds:
            raise ValueError("WALL_TIME_BUDGET_EXHAUSTED")

    @staticmethod
    def _research_champion(db, market, lane, *, available_before=None):
        rows = db.scalars(select(AscentExperiment).join(AscentGeneration,
            AscentGeneration.generation_uid == AscentExperiment.generation_uid).where(
                AscentExperiment.status == "RETAINED_RESEARCH", AscentGeneration.market_family == market,
                AscentGeneration.evidence_lane == lane).order_by(desc(AscentExperiment.id)).limit(100)).all()
        for row in rows:
            if available_before is not None:
                parent = db.scalar(select(AscentGeneration).where(AscentGeneration.generation_uid == row.generation_uid))
                terminal = max(datetime.fromisoformat(record["outcome_timestamp"])
                               for record in parent.snapshot_json["holdout"])
                if terminal >= available_before - timedelta(days=EMBARGO_DAYS):
                    continue
            return row
        return None

    @staticmethod
    def _generation_json(row):
        manifest = {key: value for key, value in row.manifest_json.items() if key != "source_provenance"}
        manifest["provenance_rows"] = len(row.manifest_json.get("source_provenance", {}))
        manifest["provenance_hash"] = digest(row.manifest_json.get("source_provenance", {}))
        return {"generation_uid": row.generation_uid, "parent_uid": row.parent_uid, "market_family": row.market_family,
            "evidence_lane": row.evidence_lane, "status": row.status, "source_revision": row.source_revision,
            "hypothesis": row.hypothesis, "selected_experiment_uid": row.selected_experiment_uid,
            "holdout_opened": row.holdout_opened, "manifest": manifest, **row.summary_json,
            "started_at": row.started_at.isoformat(), "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "production_eligible": False}

    def snapshot(self, db: Session, *, limit=20) -> dict:
        generations = db.scalars(select(AscentGeneration).order_by(desc(AscentGeneration.id)).limit(max(1, min(100, limit)))).all()
        ids = [row.generation_uid for row in generations]
        experiments = db.scalars(select(AscentExperiment).where(AscentExperiment.generation_uid.in_(ids)).order_by(desc(AscentExperiment.id))).all()
        champions = [self._research_champion(db, market, lane) for market in ("equity", "forex") for lane in LANES]
        production = db.scalars(select(TradingMLModelVersion).where(TradingMLModelVersion.status == "ACTIVE").limit(20)).all()
        strategies = db.scalars(select(StrategyCandidateVariant).where(StrategyCandidateVariant.is_champion.is_(True)).limit(20)).all()
        return {"status": "READY" if generations else "NO_EXPERIMENTS", "enabled": self.enabled,
            "scheduler_enabled": get_settings().ascent_scheduler_enabled, "training_triggered": False,
            "production_eligible": False, "generations": [self._generation_json(row) for row in generations],
            "experiments": [{"experiment_uid": row.experiment_uid, "generation_uid": row.generation_uid,
                "status": row.status, "source_sha256": row.source_sha256, "source_text": row.source_text,
                "development": row.development_json, "validation": row.result_json} for row in experiments],
            "research_champions": [{"experiment_uid": row.experiment_uid, "source_sha256": row.source_sha256} for row in champions if row],
            "production_champions": [{"model_uid": row.model_uid, "market_family": row.market_family} for row in production],
            "strategy_champions": [{"fingerprint": row.fingerprint, "family": row.family} for row in strategies],
            "level_2": {"status": "EXISTING_HF_PIPELINE_ONLY", "training_launched": False,
                        "champion_repository": get_settings().hf_training_champion_repository},
            "policy": "Research retention has no production authority. Historical and forward evidence remain separate."}
