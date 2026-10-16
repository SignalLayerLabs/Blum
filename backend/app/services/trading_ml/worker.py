"""Bounded background orchestration for trading ML research."""

from __future__ import annotations

from collections import Counter
import json
import os
from filelock import FileLock
from datetime import datetime, timedelta
from pathlib import Path
import time
from typing import Iterable
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import BackgroundJobState, TradingMLModelVersion, TradingMLTrainingRun
from app.services.central_brain_runtime import BrainEventBus
from app.services.dashboard_snapshots import DashboardSnapshotService

from .contracts import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    InsufficientTrainingEvidenceError,
    TradingMLExample,
)
from .feature_store import TradingMLFeatureStoreProjector
from .finrlx import FinRLXQuantEngine
from .forex_history import (
    KAGGLE_FOREX_SOURCE_URL,
    ForexHistoricalDatasetService,
    bundled_forex_history_path,
)
from .registry import TradingMLModelRegistry, TradingMLPromotionService
from .training import (
    BoundedOptunaChallengerSearch,
    OnlineShadowTrainer,
    SklearnTradingModelTrainer,
    dataset_fingerprint,
)


class MarketLearningError(RuntimeError):
    def __init__(self, error: Exception, online: dict):
        super().__init__(f"{type(error).__name__}: {error}")
        self.online = online


class TradingMLLearningWorker:
    job_name = "trading_ml_learning"

    def __init__(
        self,
        *,
        artifact_root: str | Path | None = None,
        max_runtime_seconds: int | None = None,
        max_rows: int | None = None,
        online_max_rows: int | None = None,
        forex_history_source: str | Path | None = None,
    ) -> None:
        settings = get_settings()
        self.root = Path(artifact_root or settings.trading_ml_artifact_root)
        self.max_runtime_seconds = int(
            max_runtime_seconds or settings.trading_ml_max_runtime_seconds
        )
        self.max_rows = int(max_rows or settings.trading_ml_max_rows_per_slice)
        self.settings = settings
        self.online_max_rows = int(
            online_max_rows
            if online_max_rows is not None
            else settings.trading_ml_online_max_rows_per_slice
        )
        if not 1 <= self.online_max_rows <= 100_000:
            raise ValueError("Online slice limit must be in [1, 100000]")
        configured_history = (
            Path(settings.forex_history_source_path)
            if settings.forex_history_source_path
            else bundled_forex_history_path()
        )
        self.forex_history_source = Path(forex_history_source or configured_history)
        self.forex_history_enabled = bool(
            forex_history_source is not None or settings.forex_history_enabled
        )
        self.projector = TradingMLFeatureStoreProjector(
            root=self.root / "feature_store",
            max_rows_per_projection=self.max_rows,
        )
        self.registry = TradingMLModelRegistry(self.root)
        self.promotion = TradingMLPromotionService(self.root)
        self.finrlx = FinRLXQuantEngine()

    def run_once(self, db: Session, trigger: str = "scheduled") -> dict:
        started = time.perf_counter()
        state = self._state(db)
        state.status = "running"
        state.last_started_at = datetime.utcnow()
        state.max_items = self.online_max_rows * 2
        db.commit()
        markets: dict[str, dict] = {}
        continuations = {}
        for market_family in ("equity", "forex"):
            if time.perf_counter() - started >= self.max_runtime_seconds:
                markets[market_family] = {"status": "BUDGET_EXHAUSTED"}
                continue
            try:
                market_result = self._run_market(
                    db, market_family, trigger, started, defer_challenger=True
                )
                continuation = market_result.pop("_continuation", None)
                if continuation is not None:
                    continuations[market_family] = continuation
                markets[market_family] = market_result
            except Exception as exc:
                db.rollback()
                markets[market_family] = {
                    "status": "FAILED",
                    "error": f"{type(exc).__name__}: {exc}",
                    "online": (
                        exc.online if isinstance(exc, MarketLearningError) else {}
                    ),
                }

        # Both online lanes get first access. Expensive challengers cannot starve
        # Forex's incremental update behind an equity hyperparameter search.
        for family, continuation in continuations.items():
            if time.perf_counter() - started >= self.max_runtime_seconds:
                markets[family]["challenger_status"] = "BUDGET_EXHAUSTED"
                continue
            try:
                markets[family] = continuation()
            except Exception as exc:
                db.rollback()
                markets[family] = {
                    **markets[family],
                    "status": "FAILED",
                    "error": f"{type(exc).__name__}: {exc}",
                }
        total_processed = sum(
            int((item.get("online") or {}).get("new_samples") or 0)
            for item in markets.values()
        )
        forex_history = self._ensure_forex_history()
        # Optional initialization receives only the time left after core learning.
        finrlx = self._run_finrlx(started)
        duration = time.perf_counter() - started
        statuses = {item.get("status") for item in markets.values()}
        cycle_status = (
            "BUDGET_EXHAUSTED"
            if statuses == {"BUDGET_EXHAUSTED"}
            else (
                "FAILED"
                if statuses.issubset({"FAILED", "BUDGET_EXHAUSTED"})
                else "COMPLETED"
            )
        )
        payload = {
            "status": cycle_status,
            "trigger": trigger,
            "markets": markets,
            "finrlx": finrlx,
            "forex_history": forex_history,
            "duration_seconds": round(duration, 4),
            "bounded": True,
            "new_examples_learned": total_processed,
            "decision_policy": "shadow/challenger models have no authority; only evidence-gated ACTIVE models advise within guardrails",
            "last_run_at": datetime.utcnow().isoformat(),
        }
        state = self._state(db)
        state.status = cycle_status.lower()
        state.items_processed = total_processed
        state.duration_ms = duration * 1000
        state.last_completed_at = datetime.utcnow()
        state.next_run_after = datetime.utcnow() + timedelta(
            minutes=self.settings.trading_ml_worker_minutes
        )
        state.cursor_json = self.projector.manifest().get("source_cursors") or {}
        state.error_message = (
            "Worker budget exhausted before core learning."
            if cycle_status == "BUDGET_EXHAUSTED"
            else "No market-family lane completed." if cycle_status == "FAILED" else ""
        )
        db.commit()
        DashboardSnapshotService().write(
            db,
            "trading_ml_status",
            payload,
            source_modules={"producer": self.job_name},
            ttl_seconds=max(300, self.settings.trading_ml_worker_minutes * 120),
            warnings=[
                item["error"]
                for item in markets.values()
                if item.get("status") == "FAILED" and item.get("error")
            ],
        )
        BrainEventBus().publish(
            db,
            (
                "learning_cycle_completed"
                if payload["status"] == "COMPLETED"
                else "module_failed"
            ),
            self.job_name,
            status=payload["status"].lower(),
            duration_ms=duration * 1000,
            payload={"markets": markets, "items_processed": total_processed},
        )
        return payload

    def _ensure_forex_history(self) -> dict:
        if not self.forex_history_enabled:
            return {
                "status": "DISABLED",
                "reason": "External Forex history bootstrap is disabled.",
                "paper_authority": False,
            }
        if not self.forex_history_source.is_file():
            return {
                "status": "UNAVAILABLE",
                "reason": f"Forex history source is missing: {self.forex_history_source}",
                "paper_authority": False,
            }
        try:
            service = ForexHistoricalDatasetService(
                source_path=self.forex_history_source,
                source_url=KAGGLE_FOREX_SOURCE_URL,
                license_name="CC BY-SA 4.0",
                source_version="1",
                sample_weight=self.settings.forex_history_sample_weight,
            )
            bundle = service.prepare()
            projection = self.projector.append_external(
                bundle.examples,
                source_id=str(bundle.provenance["source_id"]),
                provenance=bundle.provenance,
            )
            service.write_knowledge(
                bundle,
                self.root / "forex_historical_knowledge.json",
            )
            return {
                "status": "READY",
                "rows_written": projection.rows_written,
                "examples_available": len(bundle.examples),
                "pairs": bundle.provenance["pairs"],
                "source_sha256": bundle.provenance["source_sha256"],
                "evidence_lane": "external_historical_replay",
                "sample_weight": bundle.provenance["sample_weight"],
                "paper_authority": False,
            }
        except Exception as exc:
            return {
                "status": "FAILED",
                "reason": f"{type(exc).__name__}: {exc}",
                "paper_authority": False,
            }

    def _run_finrlx(self, started: float) -> dict:
        """Run optional external research without affecting core worker success."""
        markets: dict[str, dict] = {}
        for market_family in ("forex", "equity"):
            remaining_seconds = self.max_runtime_seconds - (
                time.perf_counter() - started
            )
            if remaining_seconds < 1:
                markets[market_family] = {
                    "status": "BUDGET_EXHAUSTED",
                    "reason": "No worker budget remains for optional FinRL-X initialization.",
                    "paper_only": True,
                }
                continue
            try:
                status = self.finrlx.status(market_family=market_family)
                current_dataset_hash = (
                    self.projector.market_dataset_hash(market_family)  # type: ignore[arg-type]
                    if hasattr(self.projector, "market_dataset_hash")
                    else str(self.projector.manifest().get("dataset_hash") or "")
                )
                artifact_dataset_hash = str(
                    (status.get("manifest") or {}).get("dataset_hash") or ""
                )
                artifact_is_current = (
                    status.get("status") == "READY_SHADOW"
                    and artifact_dataset_hash == current_dataset_hash
                )
                if artifact_is_current:
                    markets[market_family] = status
                    continue
                if status.get("status") not in {
                    "NO_VALIDATED_ARTIFACT",
                    "READY_SHADOW",
                }:
                    markets[market_family] = status
                    continue
                per_market_budget = max(
                    1,
                    min(
                        int(remaining_seconds),
                        max(10, self.max_runtime_seconds // 2),
                    ),
                )
                markets[market_family] = self.finrlx.run_training(
                    market_family=market_family,
                    request={
                        "feature_store_root": str(
                            (self.root / "feature_store").resolve()
                        ),
                        "artifact_root": str(
                            Path(
                                getattr(
                                    self.finrlx,
                                    "artifact_root",
                                    self.root / "finrlx",
                                )
                            ).resolve()
                        ),
                        "max_rows": self.max_rows,
                        "max_runtime_seconds": per_market_budget,
                        "paper_only": True,
                    },
                )
            except Exception as exc:
                markets[market_family] = {
                    "status": "FAILED",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "paper_only": True,
                }
        return {
            "status": _aggregate_finrlx_status(markets.values()),
            "markets": markets,
            "paper_only": True,
        }

    def _run_market(
        self,
        db: Session,
        market_family: str,
        trigger: str,
        started: float,
        *,
        defer_challenger=False,
    ) -> dict:
        active = db.scalar(
            select(TradingMLModelVersion)
            .where(
                TradingMLModelVersion.market_family == market_family,
                TradingMLModelVersion.status == "ACTIVE",
            )
            .order_by(
                desc(TradingMLModelVersion.activated_at), desc(TradingMLModelVersion.id)
            )
            .limit(1)
        )
        if active is not None:
            loaded = self.registry.load_active(db, market_family)
            if loaded.status == "DEGRADED":
                self.promotion.rollback(
                    db,
                    active,
                    reason="; ".join(loaded.warnings)
                    or "Active artifact failed verification.",
                )

        projection = self.projector.project(db, market_family=market_family, limit=self.max_rows)  # type: ignore[arg-type]
        rows = self._load_examples(market_family)
        run = TradingMLTrainingRun(
            run_uid=f"trading-ml-{market_family}-{uuid4().hex}",
            market_family=market_family,
            trigger=trigger,
            cursor_json=projection.source_cursor or {},
            resource_limits_json={
                "max_runtime_seconds": self.max_runtime_seconds,
                "max_rows": self.max_rows,
                "online_max_rows": self.online_max_rows,
                "optuna_trials": min(12, self.settings.trading_ml_optuna_trials),
            },
            rows_considered=projection.rows_considered,
            rows_accepted=len(rows),
            rows_rejected=projection.rows_rejected,
            status="RUNNING",
        )
        db.add(run)
        db.flush()
        if not rows:
            run.status = "INSUFFICIENT_EVIDENCE"
            run.completed_at = datetime.utcnow()
            db.commit()
            return {
                "status": "INSUFFICIENT_EVIDENCE",
                "rows_considered": projection.rows_considered,
                "sample_count": 0,
                "reason": "No point-in-time cost-adjusted labels are available.",
            }

        # Rapid online learning is always shadow-only.
        shadow, online = self._update_online(market_family, rows)
        try:
            return self._after_online(
                db,
                market_family,
                started,
                run,
                projection,
                rows,
                shadow,
                online,
                defer_challenger=defer_challenger,
            )
        except Exception as exc:
            raise MarketLearningError(exc, online) from exc

    def _after_online(
        self,
        db,
        market_family,
        started,
        run,
        projection,
        rows,
        shadow,
        online,
        *,
        defer_challenger,
    ):
        if shadow is None:
            run.status = "SHADOW"
            run.completed_at = datetime.utcnow()
            db.commit()
            return {
                "status": "SHADOW",
                "online": online,
                "sample_count": len(rows),
                "reason": "No accepted rows in this bounded online page.",
            }
        latest_same_dataset = db.scalar(
            select(TradingMLModelVersion)
            .where(
                TradingMLModelVersion.market_family == market_family,
                TradingMLModelVersion.dataset_hash == shadow.dataset_hash,
                TradingMLModelVersion.algorithm == shadow.model_bundle.algorithm,
            )
            .order_by(desc(TradingMLModelVersion.id))
            .limit(1)
        )
        if latest_same_dataset is None:
            shadow_row = self.registry.store_candidate(
                db,
                market_family=market_family,
                result=shadow,
                evidence_lane_counts=shadow.parameters["evidence_lane_counts"],
                asset_count=shadow.parameters["asset_count"],
                regime_count=shadow.parameters["regime_count"],
                setup_count=shadow.parameters["setup_count"],
                explanation="Persistent exactly-once classifier and net-R learner; permanently shadow-only.",
            )
            shadow_row.status = "SHADOW"
            shadow_row.promotion_decision = "SHADOW_ONLY"
            db.commit()

        if len(rows) < self.settings.trading_ml_min_replay_samples:
            run.status = "SHADOW"
            run.split_metadata_json = {
                "minimum_samples": self.settings.trading_ml_min_replay_samples
            }
            run.completed_at = datetime.utcnow()
            db.commit()
            return {
                "online": online,
                "status": "SHADOW",
                "rows_considered": projection.rows_considered,
                "sample_count": len(rows),
                "minimum_samples": self.settings.trading_ml_min_replay_samples,
            }
        if len({row.asset_key for row in rows}) < self.settings.trading_ml_min_assets:
            run.status = "INSUFFICIENT_EVIDENCE"
            run.completed_at = datetime.utcnow()
            db.commit()
            return {
                "online": online,
                "status": "INSUFFICIENT_EVIDENCE",
                "rows_considered": projection.rows_considered,
                "sample_count": len(rows),
                "reason": "Insufficient asset/pair diversity.",
            }
        dataset_hash = dataset_fingerprint(rows)
        existing = db.scalar(
            select(TradingMLModelVersion)
            .where(
                TradingMLModelVersion.market_family == market_family,
                TradingMLModelVersion.dataset_hash == dataset_hash,
                TradingMLModelVersion.algorithm
                == "hist_gradient_boosting_classifier_regressor",
            )
            .order_by(desc(TradingMLModelVersion.id))
            .limit(1)
        )
        if existing is not None:
            run.status = existing.status
            run.candidate_model_version_id = existing.id
            run.completed_at = datetime.utcnow()
            db.commit()
            return {
                "online": online,
                "status": existing.status,
                "sample_count": len(rows),
                "rows_considered": projection.rows_considered,
                "model_uid": existing.model_uid,
                "reused_dataset": True,
            }

        if defer_challenger:
            run.status = "SHADOW"
            run.completed_at = datetime.utcnow()
            db.commit()
            return {
                "status": "SHADOW",
                "online": online,
                "sample_count": len(rows),
                "challenger_status": "PENDING",
                "_continuation": lambda: self._fit_challenger(
                    db, market_family, started, run, projection, rows, online
                ),
            }
        return self._fit_challenger(
            db, market_family, started, run, projection, rows, online
        )

    def _fit_challenger(
        self, db, market_family, started, run, projection, rows, online
    ):
        try:
            search = BoundedOptunaChallengerSearch(
                max_trials=self.settings.trading_ml_optuna_trials,
                timeout_seconds=min(
                    self.settings.trading_ml_optuna_timeout_seconds,
                    max(
                        1,
                        int(self.max_runtime_seconds - (time.perf_counter() - started)),
                    ),
                ),
                min_folds=self.settings.trading_ml_min_folds,
            ).search(rows)
            stable = SklearnTradingModelTrainer(
                min_folds=self.settings.trading_ml_min_folds,
                parameters=search.parameters,
            ).fit(rows)
        except InsufficientTrainingEvidenceError as exc:
            run.status = "INSUFFICIENT_EVIDENCE"
            run.rejection_reasons_json = {
                "evidence_gap": str(exc),
                "policy": "Leakage-safe validation cannot be relaxed to manufacture a challenger.",
            }
            run.completed_at = datetime.utcnow()
            run.duration_seconds = round(time.perf_counter() - started, 4)
            db.commit()
            return {
                "online": online,
                "status": "INSUFFICIENT_EVIDENCE",
                "rows_considered": projection.rows_considered,
                "sample_count": len(rows),
                "reason": str(exc),
            }
        candidate = self.registry.store_candidate(
            db,
            market_family=market_family,
            result=stable,
            evidence_lane_counts=Counter(row.evidence_lane for row in rows),
            asset_count=len({row.asset_key for row in rows}),
            regime_count=len({row.regime for row in rows}),
            setup_count=len({row.setup_type for row in rows}),
            explanation="Stable deterministic challenger validated with purged walk-forward folds.",
        )
        decision = self.promotion.promote(db, candidate)
        run.candidate_model_version_id = candidate.id
        run.status = decision.status
        run.split_metadata_json = {
            "folds": (
                len(stable.validation_result.folds) if stable.validation_result else 0
            )
        }
        run.rejection_reasons_json = {
            "candidate": dict(stable.validation_metrics),
            "baseline": dict(stable.baseline_metrics),
            "promotion": {
                "status": decision.status,
                "failed_gates": list(decision.failed_gates),
            },
            "optuna": {
                "trials_completed": search.trials_completed,
                "duration_seconds": search.duration_seconds,
                "parameters": dict(search.parameters),
            },
        }
        run.completed_at = datetime.utcnow()
        run.duration_seconds = round(time.perf_counter() - started, 4)
        db.commit()
        return {
            "online": online,
            "status": decision.status,
            "rows_considered": projection.rows_considered,
            "sample_count": len(rows),
            "model_uid": candidate.model_uid,
            "failed_gates": list(decision.failed_gates),
            "validation": dict(stable.validation_metrics),
        }

    def _update_online(self, market_family: str, stable_rows):
        root = self.root / "shadow"
        root.mkdir(parents=True, exist_ok=True)
        cursor_path = root / f"{market_family}-reader.json"
        with FileLock(str(root / f"{market_family}-reader.lock"), timeout=10):
            cursor = (
                json.loads(cursor_path.read_text()) if cursor_path.exists() else None
            )
            trainer = OnlineShadowTrainer(root)
            if (
                cursor
                and cursor.get("_model_samples", 0)
                and not (root / f"{market_family}.sqlite").is_file()
            ):
                raise ValueError("ONLINE_READER_CHECKPOINT_MISSING")
            current = trainer.current(market_family)
            if cursor and cursor.get("_model_samples", 0):
                if current is None or current.sample_count < cursor["_model_samples"]:
                    raise ValueError("ONLINE_READER_CHECKPOINT_BEHIND")
                if (
                    current.sample_count == cursor["_model_samples"]
                    and current.dataset_hash != cursor["_model_hash"]
                ):
                    raise ValueError("ONLINE_READER_CHECKPOINT_CHANGED")
            page = self.projector.online_page(
                market_family=market_family, cursor=cursor, limit=self.online_max_rows
            )
            incoming = tuple(_example_from_store_row(row) for row in page["rows"])
            result = trainer.partial_fit(incoming) if incoming else current
            if result is not None:
                page["cursor"].update(
                    _model_samples=result.sample_count, _model_hash=result.dataset_hash
                )
            temporary = cursor_path.with_name(cursor_path.name + f".{uuid4().hex}.tmp")
            try:
                with temporary.open("w") as handle:
                    json.dump(page["cursor"], handle, sort_keys=True)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, cursor_path)
            except Exception as exc:
                raise MarketLearningError(exc, _online_progress(result, page)) from exc
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    # Cleanup must not conceal committed progress or replace
                    # the primary publication failure on unavailable storage.
                    pass
        return result, _online_progress(result, page)

    def _load_examples(self, market_family: str) -> tuple[TradingMLExample, ...]:
        frame = (
            self.projector.scan(market_family=market_family)  # type: ignore[arg-type]
            .sort(["decision_timestamp", "outcome_timestamp", "source_uid"])
            .tail(self.max_rows)
            .collect()
        )
        return tuple(_example_from_store_row(row) for row in frame.to_dicts())

    def _state(self, db: Session) -> BackgroundJobState:
        row = db.scalar(
            select(BackgroundJobState).where(
                BackgroundJobState.job_name == self.job_name,
                BackgroundJobState.stage_name == "default",
            )
        )
        if row is None:
            row = BackgroundJobState(
                job_name=self.job_name,
                stage_name="default",
                status="idle",
                enabled=True,
            )
            db.add(row)
            db.flush()
        return row


def _example_from_store_row(row: dict) -> TradingMLExample:
    return TradingMLExample(
        source_object_type=str(row["source_object_type"]),
        source_object_id=str(row["source_object_id"]),
        market_family=str(row["market_family"]),  # type: ignore[arg-type]
        evidence_lane=str(row["evidence_lane"]),
        decision_timestamp=row["decision_timestamp"],
        outcome_timestamp=row["outcome_timestamp"],
        asset_key=str(row["asset_key"]),
        setup_type=str(row["setup_type"]),
        regime=str(row["regime"]),
        features={
            name: row.get(name) for name in (*NUMERIC_FEATURES, *CATEGORICAL_FEATURES)
        },
        realized_net_r=float(row["realized_net_r"]),
        label_positive_r=int(row["label_positive_r"]),
        benchmark_excess=(
            float(row["benchmark_excess"])
            if row.get("benchmark_excess") is not None
            else None
        ),
        sample_weight=float(row["sample_weight"]),
    )


def _aggregate_finrlx_status(results: Iterable[dict]) -> str:
    statuses = {str(result.get("status") or "FAILED").upper() for result in results}
    for preferred in (
        "VALIDATED_SHADOW",
        "READY_SHADOW",
        "INSUFFICIENT_EVIDENCE",
        "NO_VALIDATED_ARTIFACT",
        "BUDGET_EXHAUSTED",
        "DISABLED",
        "UNAVAILABLE",
        "REJECTED",
        "TIMEOUT",
        "FAILED",
    ):
        if preferred in statuses:
            return preferred
    return "FAILED"


def _online_progress(result, page):
    if result is None:
        return {
            "new_samples": 0,
            "total_samples": 0,
            "rows_considered": page["rows_considered"],
            "rows_rejected": page["rows_rejected"],
            "backlog_exhausted": page["exhausted"],
            "decision_authority": False,
        }
    progress = {
        "new_samples": result.parameters["new_samples"],
        "total_samples": result.sample_count,
        "duplicate_samples": result.parameters["duplicate_samples"],
        "rows_considered": page["rows_considered"],
        "rows_rejected": page["rows_rejected"],
        "backlog_exhausted": page["exhausted"],
        "measurements": dict(result.validation_metrics),
        "baseline": dict(result.baseline_metrics),
        "dataset_hash": result.dataset_hash,
        "decision_authority": False,
    }
    return progress
