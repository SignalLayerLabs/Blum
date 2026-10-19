from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import threading
from typing import Any

from app.core.config import get_settings


settings = get_settings()


@dataclass(frozen=True)
class WorkerDefinition:
    name: str
    queue_name: str
    cadence: str
    max_seconds: int
    max_items: int
    dependencies: tuple[str, ...] = ()
    owns_state: bool = True


WORKER_DEFINITIONS: dict[str, WorkerDefinition] = {
    "runtime_snapshot_watchdog": WorkerDefinition("runtime_snapshot_watchdog", "runtime", "5m", 30, 10),
    "snapshot_producer": WorkerDefinition("snapshot_producer", "snapshots", "10m", 120, settings.blum_autonomous_max_items_per_job),
    "brain_evidence_projector": WorkerDefinition("brain_evidence_projector", "learning_evidence", "10m", 120, 1),
    "autonomous_research_engine": WorkerDefinition("autonomous_research_engine", "research", "configured", settings.blum_autonomous_max_seconds_per_job, settings.blum_autonomous_max_items_per_job),
    "news_refresh": WorkerDefinition("news_refresh", "news", "configured", 120, 35),
    "market_refresh": WorkerDefinition(
        "market_refresh",
        "market",
        "configured",
        settings.blum_autonomous_max_seconds_per_job,
        min(
            settings.max_update_assets,
            settings.blum_autonomous_max_items_per_job,
            settings.market_refresh_max_items_per_job,
        ),
    ),
    "data_gap_repair": WorkerDefinition("data_gap_repair", "data_repair", "configured", settings.blum_autonomous_max_seconds_per_job, settings.max_update_assets),
    "accuracy_audit": WorkerDefinition("accuracy_audit", "accuracy", "configured", settings.blum_autonomous_max_seconds_per_job, settings.max_update_assets),
    "macro_refresh": WorkerDefinition("macro_refresh", "macro", "configured", 120, 25),
    "fundamentals_refresh": WorkerDefinition("fundamentals_refresh", "fundamentals", "configured", 120, min(settings.max_update_assets, 24)),
    "ipo_refresh": WorkerDefinition("ipo_refresh", "filings", "configured", 120, 45),
    "financial_brain_learning": WorkerDefinition("financial_brain_learning", "learning", "configured", settings.blum_autonomous_max_seconds_per_job, settings.max_update_assets),
    "blum_financial_model_cycle": WorkerDefinition("blum_financial_model_cycle", "model_learning", "configured", settings.blum_autonomous_max_seconds_per_job, settings.blum_model_cycle_limit),
    "blum_point_in_time_learning_loop": WorkerDefinition("blum_point_in_time_learning_loop", "point_in_time_learning", "configured", settings.blum_autonomous_max_seconds_per_job, settings.learning_batch_size),
    "blum_trading_game": WorkerDefinition("blum_trading_game", "trading_game", "configured", settings.blum_autonomous_max_seconds_per_job, settings.trading_game_batch_size),
    "live_forward_paper_trading": WorkerDefinition("live_forward_paper_trading", "paper_forward", "configured", settings.blum_autonomous_max_seconds_per_job, settings.live_trading_game_max_open_positions),
    "intraday_paper_trading": WorkerDefinition("intraday_paper_trading", "intraday_paper", "configured", min(120, settings.intraday_max_runtime_seconds), settings.intraday_max_assets_per_run),
    "alpha_strategy_factory": WorkerDefinition("alpha_strategy_factory", "strategy_research", "configured", 120, settings.strategy_factory_max_variants_per_family * 10),
    "paper_execution_lifecycle": WorkerDefinition("paper_execution_lifecycle", "paper_execution", "configured", 60, settings.intraday_max_open_positions),
    "deterministic_execution_core": WorkerDefinition(
        "deterministic_execution_core",
        "execution_shadow",
        "10m",
        settings.blum_nautilus_max_job_seconds,
        settings.blum_nautilus_max_items_per_job,
    ),
    "evidence_decision_council": WorkerDefinition(
        "evidence_decision_council",
        "decision_council",
        "10m",
        120,
        settings.decision_council_max_items,
    ),
    "blum_professional_learning_cycle": WorkerDefinition("blum_professional_learning_cycle", "professional_learning", "configured", settings.blum_autonomous_max_seconds_per_job, settings.professional_learning_batch_size),
    "hyperbolic_replay_training": WorkerDefinition("hyperbolic_replay_training", "replay_training", "configured", min(120, settings.replay_max_seconds_per_cycle), settings.replay_max_trades_per_cycle),
    "trading_curriculum": WorkerDefinition("trading_curriculum", "curriculum", "1m", 20, 2),
    "trading_ml_learning": WorkerDefinition("trading_ml_learning", "trading_ml", "15m", settings.trading_ml_max_runtime_seconds, settings.trading_ml_max_rows_per_slice),
    "blum_hf_training_supervisor": WorkerDefinition("blum_hf_training_supervisor", "hf_training", "configured", 300, settings.hf_training_max_examples),
    "startup_snapshot_warmup": WorkerDefinition("startup_snapshot_warmup", "startup", "startup", 120, settings.blum_autonomous_max_items_per_job),
    "startup_pipeline": WorkerDefinition("startup_pipeline", "startup", "startup", settings.blum_autonomous_max_seconds_per_job, settings.startup_pipeline_limit),
    "autonomous_startup": WorkerDefinition("autonomous_startup", "startup", "startup", settings.blum_autonomous_max_seconds_per_job, settings.blum_autonomous_max_items_per_job),
}


class RuntimeWorkerCoordinator:
    """In-process worker registry and lock manager.

    The coordinator is deliberately lightweight. It does not run financial
    computation and it does not dispatch jobs. APScheduler still owns timing;
    this layer only prevents duplicate runs of the same worker and exposes
    worker state so the Central Brain can observe the runtime without importing
    the scheduler module.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._scheduler_started = False
        self._running_jobs: dict[str, dict[str, Any]] = {}
        self._last_job: str | None = None
        self._last_started_at: str | None = None
        self._last_completed_at: str | None = None
        self._last_status = "idle"
        self._last_error = ""
        self._last_result: dict[str, Any] = {}

    def mark_scheduler_started(self) -> None:
        with self._lock:
            self._scheduler_started = True

    def mark_scheduler_stopped(self) -> None:
        with self._lock:
            self._scheduler_started = False
            self._running_jobs = {}

    def begin(self, job_name: str, *, max_items: int = 0) -> tuple[bool, dict[str, Any]]:
        with self._lock:
            if job_name in self._running_jobs:
                return False, {
                    "status": "deferred",
                    "reason": "same_worker_already_running",
                    "blocking_job": job_name,
                    "running_job": self._running_jobs[job_name],
                }
            now = datetime.utcnow().isoformat()
            definition = self.definition(job_name)
            payload = {
                "job_name": job_name,
                "queue_name": definition.queue_name,
                "status": "running",
                "started_at": now,
                "max_seconds": definition.max_seconds,
                "max_items": max_items or definition.max_items,
                "dependencies": list(definition.dependencies),
            }
            self._running_jobs[job_name] = payload
            self._last_job = job_name
            self._last_started_at = now
            self._last_status = "running"
            self._last_error = ""
            self._last_result = {}
            return True, payload

    def complete(self, job_name: str, *, result: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._running_jobs.pop(job_name, None)
            self._last_job = job_name
            self._last_completed_at = datetime.utcnow().isoformat()
            self._last_status = "ok"
            self._last_error = ""
            self._last_result = result or {}

    def fail(self, job_name: str, *, error: str, result: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._running_jobs.pop(job_name, None)
            self._last_job = job_name
            self._last_completed_at = datetime.utcnow().isoformat()
            self._last_status = "error"
            self._last_error = error
            self._last_result = result or {}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "started": self._scheduler_started,
                "running": bool(self._running_jobs),
                "running_count": len(self._running_jobs),
                "running_jobs": dict(self._running_jobs),
                "last_started_at": self._last_started_at,
                "last_completed_at": self._last_completed_at,
                "last_job": self._last_job,
                "last_status": self._last_status,
                "last_error": self._last_error,
                "last_result": self._last_result,
                "worker_registry": self.registry(),
                "policy": "Workers are isolated by worker name. One worker cannot block unrelated workers.",
            }

    def registry(self) -> list[dict[str, Any]]:
        return [asdict(item) for item in WORKER_DEFINITIONS.values()]

    def definition(self, job_name: str) -> WorkerDefinition:
        return WORKER_DEFINITIONS.get(
            job_name,
            WorkerDefinition(
                name=job_name,
                queue_name="unregistered",
                cadence="ad_hoc",
                max_seconds=settings.blum_autonomous_max_seconds_per_job,
                max_items=settings.blum_autonomous_max_items_per_job,
            ),
        )


runtime_worker_coordinator = RuntimeWorkerCoordinator()
