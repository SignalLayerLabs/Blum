from __future__ import annotations

from datetime import datetime, timedelta
import time
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    AlphaRecoveryAction,
    BackgroundJobState,
    BrainRuntimeEvent,
    BusinessQualityScore,
    CapitalAllocationSnapshot,
    DashboardSnapshot,
    DecisionSuperiorityScore,
    LearningBenchmarkComparison,
    LearningEvent,
    LearningRun,
    PortfolioQualityScore,
    TradingGame,
)
from app.services.dashboard_snapshots import DashboardSnapshotService
from app.services.learning_summary import LearningSummaryService
from app.services.performance import performance_recorder
from app.services.worker_runtime import runtime_worker_coordinator


settings = get_settings()

RUNTIME_MODULES = [
    "market_data",
    "news_sentiment",
    "signals",
    "learning_loop",
    "research_planner",
    "trading_game",
    "decision_intelligence",
    "business_quality",
    "portfolio_intelligence",
    "capital_allocation",
    "alpha_recovery",
    "meta_cognition",
    "snapshot_producer",
    "execution_kernel",
    "decision_council",
]

RUNTIME_MODULE_EVENT_SOURCES: dict[str, tuple[str, ...]] = {
    "market_data": ("market_data", "market_refresh", "data_gap_repair"),
    "news_sentiment": ("news_sentiment", "news_refresh"),
    "signals": ("signals", "market_refresh", "accuracy_audit"),
    "learning_loop": (
        "learning_loop",
        "financial_brain_learning",
        "blum_financial_model_cycle",
        "blum_point_in_time_learning_loop",
        "hyperbolic_replay_training",
    ),
    "research_planner": ("research_planner", "autonomous_research_engine", "alpha_strategy_factory"),
    "trading_game": ("trading_game", "blum_trading_game", "live_forward_paper_trading", "intraday_paper_trading"),
    "decision_intelligence": ("decision_intelligence", "brain_evidence_projector", "accuracy_audit"),
    "business_quality": ("business_quality", "fundamentals_refresh"),
    "portfolio_intelligence": ("portfolio_intelligence", "blum_trading_game", "brain_evidence_projector"),
    "capital_allocation": ("capital_allocation", "blum_trading_game", "live_forward_paper_trading"),
    "alpha_recovery": ("alpha_recovery", "alpha_strategy_factory", "brain_evidence_projector"),
    "meta_cognition": ("meta_cognition", "hyperbolic_replay_training", "brain_evidence_projector"),
    "snapshot_producer": ("snapshot_producer", "startup_snapshot_warmup"),
    "execution_kernel": ("deterministic_execution_core",),
    "decision_council": ("evidence_decision_council",),
}

CRITICAL_SNAPSHOT_TYPES = [
    "learning_summary",
    "dashboard_overview_summary",
    "registered_alpha_desk_summary",
    "trading_game_summary",
    "benchmark_summary",
    "intelligence_growth_summary",
    "truth_panel_summary",
    "decision_intelligence_summary",
    "business_quality_summary",
    "portfolio_intelligence_summary",
    "capital_allocation_summary",
    "alpha_recovery_summary",
    "meta_cognition_summary",
    "research_planner_summary",
    "trading_game_readiness",
    "brain_command_summary",
    "alpha_readiness_summary",
    "alpha_edge_map_summary",
    "alpha_gates_summary",
    "paper_copy_summary",
    "paper_forward_snapshot",
    "forex_trader_summary",
    "unified_paper_trading_summary",
    "copy_readiness_summary",
    "trader_brain_summary",
    "trader_training_ground_summary",
    "trader_paper_trading_summary",
    "trader_alpha_summary",
    "trading_game_ledger_snapshot",
    "equity_curve_snapshot",
    "deterministic_execution_summary",
    "decision_council_summary",
]


class BrainEventBus:
    """Persistent internal event bus for runtime observability.

    The bus records module progress and failures. It intentionally does not run
    financial computation, dispatch remote work, or mutate model weights.
    """

    def publish(
        self,
        db: Session,
        event_type: str,
        source_module: str,
        *,
        status: str = "ok",
        duration_ms: float | None = None,
        payload: dict | None = None,
        error_message: str = "",
    ) -> dict:
        row = BrainRuntimeEvent(
            event_type=event_type,
            source_module=source_module,
            status=status,
            duration_ms=duration_ms,
            payload_json=json_safe(payload or {}),
            error_message=error_message[:4000],
        )
        db.add(row)
        db.commit()
        return serialize_event(row)

    def latest_by_module(self, db: Session, limit: int = 300) -> dict[str, dict]:
        latest_ids = (
            select(
                BrainRuntimeEvent.source_module.label("source_module"),
                func.max(BrainRuntimeEvent.id).label("event_id"),
            )
            .group_by(BrainRuntimeEvent.source_module)
            .subquery()
        )
        rows = db.scalars(
            select(BrainRuntimeEvent)
            .join(latest_ids, BrainRuntimeEvent.id == latest_ids.c.event_id)
            .order_by(desc(BrainRuntimeEvent.created_at))
            .limit(limit)
        ).all()
        return {row.source_module: serialize_event(row) for row in rows}

    def recent(self, db: Session, limit: int = 80) -> list[dict]:
        rows = db.scalars(select(BrainRuntimeEvent).order_by(desc(BrainRuntimeEvent.created_at)).limit(limit)).all()
        return [serialize_event(row) for row in rows]


class BackgroundJobStateService:
    """State store for small resumable background jobs."""

    def start(self, db: Session, job_name: str, *, stage_name: str = "default", max_items: int = 0, cursor: dict | None = None) -> BackgroundJobState:
        row = self._get_or_create(db, job_name, stage_name)
        row.status = "running"
        row.last_started_at = datetime.utcnow()
        row.last_completed_at = None
        row.duration_ms = None
        row.error_message = ""
        row.max_items = max_items
        if cursor is not None:
            row.cursor_json = json_safe(cursor)
        db.commit()
        BrainEventBus().publish(db, "module_started", job_name, status="running", payload={"stage_name": stage_name, "max_items": max_items})
        return row

    def heartbeat(self, db: Session, job_name: str, *, stage_name: str = "default", items_processed: int | None = None, cursor: dict | None = None) -> BackgroundJobState:
        row = self._get_or_create(db, job_name, stage_name)
        if items_processed is not None:
            row.items_processed = items_processed
        if cursor is not None:
            row.cursor_json = json_safe(cursor)
        db.commit()
        return row

    def complete(
        self,
        db: Session,
        job_name: str,
        *,
        stage_name: str = "default",
        duration_ms: float | None = None,
        items_processed: int | None = None,
        cursor: dict | None = None,
        next_run_after: datetime | None = None,
        payload: dict | None = None,
    ) -> BackgroundJobState:
        row = self._get_or_create(db, job_name, stage_name)
        row.status = "completed"
        row.duration_ms = duration_ms
        row.last_completed_at = datetime.utcnow()
        row.next_run_after = next_run_after
        row.error_message = ""
        if items_processed is not None:
            row.items_processed = items_processed
        if cursor is not None:
            row.cursor_json = json_safe(cursor)
        db.commit()
        BrainEventBus().publish(db, "module_completed", job_name, status="ok", duration_ms=duration_ms, payload=payload or {"stage_name": stage_name})
        return row

    def fail(
        self,
        db: Session,
        job_name: str,
        *,
        stage_name: str = "default",
        duration_ms: float | None = None,
        error_message: str = "",
        next_run_after: datetime | None = None,
    ) -> BackgroundJobState:
        row = self._get_or_create(db, job_name, stage_name)
        row.status = "failed"
        row.duration_ms = duration_ms
        row.last_completed_at = datetime.utcnow()
        row.next_run_after = next_run_after
        row.error_message = error_message[:4000]
        db.commit()
        BrainEventBus().publish(db, "module_failed", job_name, status="error", duration_ms=duration_ms, error_message=error_message)
        return row

    def recover_interrupted(self, db: Session, *, reason: str = "process_startup_recovery", archive_failed: bool = False) -> dict:
        """Mark stale in-process job state after a process restart."""

        now = datetime.utcnow()
        statuses = ["running"]
        if archive_failed:
            statuses.append("failed")
        rows = db.scalars(select(BackgroundJobState).where(BackgroundJobState.status.in_(statuses))).all()
        recovered = []
        for row in rows:
            previous_status = row.status
            row.status = "interrupted" if previous_status == "running" else "previous_failed"
            row.last_completed_at = now
            if previous_status == "running" and row.last_started_at:
                row.duration_ms = max(0.0, (now - row.last_started_at).total_seconds() * 1000)
            if previous_status == "running":
                row.error_message = reason
            else:
                row.error_message = f"{reason}; archived previous failure: {row.error_message or 'unknown'}"[:4000]
            recovered.append({"job_name": row.job_name, "stage_name": row.stage_name, "previous_status": previous_status, "new_status": row.status})
        db.commit()
        for item in recovered:
            BrainEventBus().publish(
                db,
                "worker_recovered",
                item["job_name"],
                status="ok",
                payload={**item, "reason": reason},
            )
        if recovered:
            BrainEventBus().publish(
                db,
                "worker_recovered",
                "runtime_startup",
                status="ok",
                payload={"recovered_interrupted_jobs": recovered, "reason": reason},
            )
        return {"recovered": len(recovered), "jobs": recovered, "reason": reason}

    def list(self, db: Session, limit: int = 80) -> list[dict]:
        rows = db.scalars(select(BackgroundJobState).order_by(desc(BackgroundJobState.last_started_at)).limit(limit)).all()
        return [serialize_job(row) for row in rows]

    def should_stop(self, started_at: float, items_processed: int, max_items: int | None = None, max_seconds: int | None = None) -> bool:
        item_limit = max_items if max_items is not None else settings.blum_autonomous_max_items_per_job
        second_limit = max_seconds if max_seconds is not None else settings.blum_autonomous_max_seconds_per_job
        if item_limit and items_processed >= item_limit:
            return True
        return (time.perf_counter() - started_at) >= max(1, second_limit)

    def _get_or_create(self, db: Session, job_name: str, stage_name: str) -> BackgroundJobState:
        row = db.scalar(select(BackgroundJobState).where(BackgroundJobState.job_name == job_name, BackgroundJobState.stage_name == stage_name).limit(1))
        if row is None:
            row = BackgroundJobState(job_name=job_name, stage_name=stage_name, enabled=True)
            db.add(row)
            db.flush()
        return row


class SnapshotProducerService:
    """Produces UI-ready snapshots from latest stored evidence only."""

    def produce(self, db: Session, snapshot_type: str) -> dict:
        started = time.perf_counter()
        warnings: list[str] = []
        missing_sections: list[str] = []
        try:
            payload = self._payload(db, snapshot_type, missing_sections, warnings)
            result = DashboardSnapshotService().write(
                db,
                snapshot_type,
                payload,
                source_modules={"producer": "SnapshotProducerService", "runtime_policy": "latest_stored_rows_only"},
                ttl_seconds=600,
                warnings=warnings,
                missing_sections=missing_sections,
                computation_duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )
            BrainEventBus().publish(
                db,
                "snapshot_refreshed",
                "snapshot_producer",
                status="ok",
                duration_ms=result.get("computation_duration_ms"),
                payload={"snapshot_type": snapshot_type, "missing_sections": missing_sections},
            )
            return result
        except Exception as exc:
            db.rollback()
            BrainEventBus().publish(db, "snapshot_failed", "snapshot_producer", status="error", error_message=f"{type(exc).__name__}: {exc}", payload={"snapshot_type": snapshot_type})
            raise

    def produce_many(self, db: Session, snapshot_types: list[str] | None = None, *, max_items: int | None = None) -> dict:
        selected = list(snapshot_types or CRITICAL_SNAPSHOT_TYPES)
        limit = max_items or settings.blum_autonomous_max_items_per_job
        produced = []
        failed = []
        for snapshot_type in selected[: max(1, limit)]:
            try:
                produced.append(self.produce(db, snapshot_type))
            except Exception as exc:
                db.rollback()
                failed.append({"snapshot_type": snapshot_type, "error": f"{type(exc).__name__}: {exc}"})
        return {"produced": len(produced), "failed": failed, "requested": len(selected), "budget_items": limit}

    def _payload(self, db: Session, snapshot_type: str, missing_sections: list[str], warnings: list[str]) -> dict:
        if snapshot_type == "registered_alpha_desk_summary":
            from app.services.alpha_desk import AlphaDeskService

            return AlphaDeskService().snapshot(db)
        if snapshot_type == "learning_summary":
            return LearningSummaryService().summary(db)
        if snapshot_type == "dashboard_overview_summary":
            from app.services.dashboard import build_dashboard_overview_live

            return build_dashboard_overview_live(db)
        if snapshot_type == "trading_game_ledger_snapshot":
            from app.services.trading_game_runtime import TradingGameRuntimeSnapshotService

            return TradingGameRuntimeSnapshotService().produce_ledger_snapshot(db)
        if snapshot_type == "equity_curve_snapshot":
            from app.services.trading_game_runtime import TradingGameRuntimeSnapshotService

            return TradingGameRuntimeSnapshotService().produce_equity_snapshot(db)
        if snapshot_type == "paper_forward_snapshot":
            from app.services.live_forward_paper_trading import LiveForwardPaperTradingService

            return LiveForwardPaperTradingService().snapshot_payload(db)
        if snapshot_type == "deterministic_execution_summary":
            from app.services.deterministic_execution.snapshot import DeterministicExecutionSnapshotService

            return DeterministicExecutionSnapshotService().build(db)
        if snapshot_type == "decision_council_summary":
            from app.services.decision_council import DecisionCouncilSnapshotService

            return DecisionCouncilSnapshotService().build(db)
        if snapshot_type == "forex_trader_summary":
            from app.services.forex_trader import ForexTraderSnapshotService
            return ForexTraderSnapshotService().read(db)
        if snapshot_type == "unified_paper_trading_summary":
            from app.services.unified_paper_trading import UnifiedPaperTradingProjectionService

            return UnifiedPaperTradingProjectionService().build(db)
        if snapshot_type == "copy_readiness_summary":
            from app.services.copy_readiness_evidence import CopyReadinessSummaryService

            return CopyReadinessSummaryService().summary(db)
        if snapshot_type == "trading_game_summary":
            game = db.scalar(select(TradingGame).order_by(desc(TradingGame.updated_at)).limit(1))
            if game is None:
                missing_sections.append("trading_game")
                return {"status": "missing", "summary": "No trading game rows are stored yet."}
            return {
                "status": "ready",
                "game_id": game.game_id,
                "current_capital": game.current_capital,
                "starting_capital": game.starting_capital,
                "target_capital": game.target_capital,
                "trade_count": game.trade_count,
                "win_rate": game.win_rate,
                "expectancy_r": game.expectancy_r,
                "updated_at": game.updated_at.isoformat() if game.updated_at else None,
            }
        if snapshot_type == "benchmark_summary":
            rows = db.scalars(select(LearningBenchmarkComparison).order_by(desc(LearningBenchmarkComparison.calculated_at)).limit(24)).all()
            if not rows:
                missing_sections.append("learning_benchmark_comparisons")
            return {"status": "ready" if rows else "missing", "benchmarks": [benchmark_payload(row) for row in rows[:12]]}
        if snapshot_type == "intelligence_growth_summary":
            latest = db.scalar(select(LearningRun).order_by(desc(LearningRun.started_at)).limit(1))
            if latest is None:
                missing_sections.append("learning_runs")
            return {"status": "ready" if latest else "missing", "latest_learning_run": learning_run_payload(latest)}
        if snapshot_type == "truth_panel_summary":
            return {"status": "ready", "truth_panel": truth_panel_from_latest(db, warnings)}
        if snapshot_type == "decision_intelligence_summary":
            row = db.scalar(select(DecisionSuperiorityScore).order_by(desc(DecisionSuperiorityScore.calculated_at)).limit(1))
            if row is None:
                missing_sections.append("decision_superiority_scores")
            return {"status": "ready" if row else "missing", "score": getattr(row, "score", None), "classification": getattr(row, "classification", "initializing")}
        if snapshot_type == "business_quality_summary":
            row = db.scalar(select(BusinessQualityScore).order_by(desc(BusinessQualityScore.calculated_at)).limit(1))
            if row is None:
                missing_sections.append("business_quality_scores")
            return {"status": "ready" if row else "missing", "score": getattr(row, "business_quality_score", None), "ticker": getattr(row, "ticker", None)}
        if snapshot_type == "portfolio_intelligence_summary":
            row = db.scalar(select(PortfolioQualityScore).order_by(desc(PortfolioQualityScore.calculated_at)).limit(1))
            if row is None:
                missing_sections.append("portfolio_quality_scores")
            return {"status": "ready" if row else "missing", "score": getattr(row, "portfolio_quality_score", None)}
        if snapshot_type == "capital_allocation_summary":
            row = db.scalar(select(CapitalAllocationSnapshot).order_by(desc(CapitalAllocationSnapshot.calculated_at)).limit(1))
            if row is None:
                missing_sections.append("capital_allocation_snapshots")
            return {"status": "ready" if row else "missing", "allocation_quality_score": getattr(row, "allocation_quality_score", None)}
        if snapshot_type == "alpha_recovery_summary":
            row = db.scalar(select(AlphaRecoveryAction).order_by(desc(AlphaRecoveryAction.created_at)).limit(1))
            if row is None:
                missing_sections.append("alpha_recovery_actions")
            return {"status": "ready" if row else "missing", "latest_action": alpha_action_payload(row)}
        if snapshot_type == "meta_cognition_summary":
            from app.services.meta_cognition import MetaCognitionEngine

            return MetaCognitionEngine().summary(db)
        if snapshot_type == "research_planner_summary":
            from app.services.research_planner import AutonomousResearchPlanner

            return AutonomousResearchPlanner().generate(db, persist=False)
        if snapshot_type == "trading_game_readiness":
            from app.services.alpha_operating_system import TradingGameReadinessService

            return TradingGameReadinessService().readiness(db)
        if snapshot_type == "brain_command_summary":
            from app.services.alpha_operating_system import BrainCommandSummaryService

            return BrainCommandSummaryService().summary(db)
        if snapshot_type == "alpha_readiness_summary":
            from app.services.alpha_operating_system import AlphaReadinessEngine

            return AlphaReadinessEngine().readiness(db)
        if snapshot_type == "alpha_edge_map_summary":
            from app.services.alpha_operating_system import EdgeMapService

            return EdgeMapService().edge_map(db)
        if snapshot_type == "alpha_gates_summary":
            from app.services.alpha_operating_system import AlphaGateService

            return AlphaGateService().gates(db)
        if snapshot_type == "paper_copy_summary":
            from app.services.alpha_operating_system import PaperCopyTradingService

            return PaperCopyTradingService().summary(db)
        if snapshot_type == "trader_brain_summary":
            from app.services.trader_brain import TraderBrainService

            return TraderBrainService().brain(db)
        if snapshot_type == "trader_training_ground_summary":
            from app.services.trader_brain import TraderBrainService

            return TraderBrainService().training_ground(db)
        if snapshot_type == "trader_paper_trading_summary":
            from app.services.trader_brain import TraderBrainService

            return TraderBrainService().paper_trading(db)
        if snapshot_type == "trader_alpha_summary":
            from app.services.trader_brain import TraderBrainService

            return TraderBrainService().alpha(db)
        missing_sections.append("unknown_snapshot_type")
        return {"status": "unknown_snapshot_type", "snapshot_type": snapshot_type}


class SnapshotWatchdogService:
    """Detects missing/stale snapshots and unhealthy producers."""

    def health(self, db: Session, *, queue_rebuild: bool = False) -> dict:
        now = datetime.utcnow()
        latest = latest_snapshot_map(db)
        missing = [item for item in CRITICAL_SNAPSHOT_TYPES if item not in latest]
        stale = []
        for snapshot_type in CRITICAL_SNAPSHOT_TYPES:
            row = latest.get(snapshot_type)
            if row is None:
                continue
            if row.expires_at and row.expires_at < now:
                stale.append(snapshot_type)
            elif row.is_stale:
                stale.append(snapshot_type)
        jobs = BackgroundJobStateService().list(db, limit=120)
        long_running = [job for job in jobs if job.get("status") == "running" and duration_since(job.get("last_started_at")) > settings.blum_autonomous_max_seconds_per_job]
        failed_jobs = [job for job in jobs if job.get("status") == "failed"]
        if queue_rebuild and missing:
            for snapshot_type in missing[: settings.blum_autonomous_max_items_per_job]:
                BrainEventBus().publish(db, "snapshot_requested", "snapshot_watchdog", payload={"snapshot_type": snapshot_type})
        return {
            "status": "healthy" if not missing and not stale and not failed_jobs and not long_running else "degraded",
            "checked_at": now.isoformat(),
            "missing_snapshots": missing,
            "stale_snapshots": stale,
            "failed_producers": failed_jobs,
            "long_running_jobs": long_running,
            "snapshot_freshness": snapshot_freshness_payload(latest),
            "policy": "Watchdog detects and requests lightweight snapshot rebuilds; it does not run financial recalculation from GET endpoints.",
        }


class CentralBrainRuntime:
    """Read-only runtime state composed from events, snapshots and job heartbeats."""

    def state(self, db: Session) -> dict:
        events = BrainEventBus().latest_by_module(db)
        snapshot_health = SnapshotWatchdogService().health(db, queue_rebuild=False)
        jobs = BackgroundJobStateService().list(db)
        failed_modules = [module for module, event in events.items() if event.get("status") == "error"]
        stale_modules = stale_modules_from_events(events)
        bottleneck = current_bottleneck()
        learning_health = LearningHealthService().health(db, snapshot_health=snapshot_health, jobs=jobs)
        return {
            "generated_at": datetime.utcnow().isoformat(),
            "active_modules": RUNTIME_MODULES,
            "worker_registry": runtime_worker_coordinator.snapshot().get("worker_registry", []),
            "last_event_per_module": events,
            "stale_modules": stale_modules,
            "failed_modules": failed_modules,
            "missing_snapshots": snapshot_health["missing_snapshots"],
            "snapshot_freshness": snapshot_health["snapshot_freshness"],
            "background_queue_status": {
                "jobs": jobs,
                "running_count": sum(1 for job in jobs if job.get("status") == "running"),
                "failed_count": sum(1 for job in jobs if job.get("status") == "failed"),
            },
            "learning_health": learning_health,
            "current_bottleneck": bottleneck,
            "system_readiness": runtime_readiness(snapshot_health, failed_modules, learning_health),
            "policy": "Central Brain Runtime observes, coordinates snapshots and exposes readiness. Heavy computation stays in background workers.",
        }


class LearningHealthService:
    def health(self, db: Session, *, snapshot_health: dict | None = None, jobs: list[dict] | None = None) -> dict:
        now = datetime.utcnow()
        latest_learning = db.scalar(select(LearningRun).order_by(desc(LearningRun.started_at)).limit(1))
        latest_successful_learning = db.scalar(
            select(LearningRun)
            .where(
                func.lower(LearningRun.status).in_(
                    ("ok", "completed", "success", "successful")
                ),
                LearningRun.completed_at.is_not(None),
            )
            .order_by(desc(LearningRun.completed_at))
            .limit(1)
        )
        runtime = runtime_worker_coordinator.snapshot()
        events_24h = int(db.scalar(select(func.count(LearningEvent.id)).where(LearningEvent.created_at >= now - timedelta(hours=24))) or 0)
        missing = (snapshot_health or SnapshotWatchdogService().health(db)).get("missing_snapshots", [])
        resolved_jobs = jobs if jobs is not None else BackgroundJobStateService().list(db)
        failed_jobs = [job for job in resolved_jobs if job.get("status") == "failed"]
        worker_alive = bool(runtime.get("started"))
        stale_modules = stale_modules_from_events(BrainEventBus().latest_by_module(db))
        latest_status = str(latest_learning.status if latest_learning else "").lower()
        successful_at = (
            latest_successful_learning.completed_at
            if latest_successful_learning
            else None
        )
        successful_age_seconds = (
            round((now - successful_at).total_seconds(), 3)
            if successful_at
            else None
        )
        stale_success = (
            successful_age_seconds is None
            or successful_age_seconds > module_freshness_seconds("learning_loop")
        )
        reasons = []
        if failed_jobs:
            reasons.append("background_job_failed")
        if latest_status in {"error", "failed", "failure"}:
            reasons.append("latest_learning_run_failed")
        if latest_status == "degraded":
            reasons.append("latest_learning_run_degraded")
        if stale_success:
            reasons.append("successful_learning_cycle_stale_or_missing")
        if events_24h == 0:
            reasons.append("no_learning_events_last_24h")
        if "learning_loop" in stale_modules:
            reasons.append("learning_loop_module_stale")
        if not worker_alive:
            reasons.append("worker_not_alive")
        if missing:
            reasons.append("missing_snapshots")

        if failed_jobs or latest_status in {"error", "failed", "failure"}:
            status = "failed"
        elif latest_status == "degraded":
            status = "degraded"
        elif stale_success or events_24h == 0 or "learning_loop" in stale_modules:
            status = "stale"
        elif not worker_alive or missing:
            status = "degraded"
        else:
            status = "healthy"
        return {
            "status": status,
            "worker_alive": worker_alive,
            "current_job": runtime.get("last_job"),
            "current_stage": runtime.get("current_stage"),
            "latest_learning_run_status": latest_learning.status if latest_learning else None,
            "last_successful_learning_cycle": successful_at.isoformat() if successful_at else None,
            "last_successful_learning_cycle_age_seconds": successful_age_seconds,
            "last_successful_trading_game_cycle": latest_job_completion(resolved_jobs, "blum_trading_game"),
            "last_successful_alpha_recovery_cycle": latest_job_completion(resolved_jobs, "alpha_recovery"),
            "last_successful_meta_cognition_cycle": latest_job_completion(resolved_jobs, "meta_cognition"),
            "learning_events_last_24h": events_24h,
            "errors_last_24h": len(failed_jobs),
            "next_scheduled_job": next_job(resolved_jobs),
            "missing_snapshots": missing,
            "stale_modules": stale_modules,
            "health_reasons": reasons,
            "frontend_policy": "read_only_snapshot_observer",
        }


def latest_snapshot_map(db: Session) -> dict[str, DashboardSnapshot]:
    ranked = (
        select(
            DashboardSnapshot.id.label("snapshot_id"),
            func.row_number()
            .over(
                partition_by=DashboardSnapshot.snapshot_type,
                order_by=(
                    DashboardSnapshot.created_at.desc(),
                    DashboardSnapshot.id.desc(),
                ),
            )
            .label("snapshot_rank"),
        )
        .subquery()
    )
    rows = db.scalars(
        select(DashboardSnapshot)
        .join(ranked, DashboardSnapshot.id == ranked.c.snapshot_id)
        .where(ranked.c.snapshot_rank == 1)
    ).all()
    return {row.snapshot_type: row for row in rows}


def snapshot_freshness_payload(latest: dict[str, DashboardSnapshot]) -> dict:
    now = datetime.utcnow()
    payload = {}
    for snapshot_type in CRITICAL_SNAPSHOT_TYPES:
        row = latest.get(snapshot_type)
        if row is None:
            payload[snapshot_type] = {"status": "missing"}
            continue
        is_stale = bool(row.is_stale or (row.expires_at is not None and row.expires_at < now))
        payload[snapshot_type] = {
            "status": "stale" if is_stale else "ready",
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "age_seconds": round((now - row.created_at).total_seconds(), 3) if row.created_at else None,
            "missing_sections": row.missing_sections_json or [],
            "warnings": row.warnings_json or [],
        }
    return payload


def stale_modules_from_events(events: dict[str, dict]) -> list[str]:
    now = datetime.utcnow()
    stale = []
    for module in RUNTIME_MODULES:
        candidate_events = [
            events[source]
            for source in RUNTIME_MODULE_EVENT_SOURCES.get(module, (module,))
            if source in events
        ]
        if not candidate_events:
            stale.append(module)
            continue
        created_values = [parse_datetime(event.get("created_at")) for event in candidate_events]
        created_values = [value for value in created_values if value is not None]
        if not created_values or (now - max(created_values)).total_seconds() > module_freshness_seconds(module):
            stale.append(module)
    return stale


def module_freshness_seconds(module: str) -> float:
    default_seconds = 60 * 60 * 6
    if module == "business_quality":
        fundamentals_cadence = max(1, settings.fundamentals_refresh_minutes) * 60
        return max(default_seconds, fundamentals_cadence * 1.25)
    return default_seconds


def current_bottleneck() -> dict:
    diagnostics = performance_recorder.diagnostics()
    bottlenecks = diagnostics.get("top_10_bottlenecks") or []
    return bottlenecks[0] if bottlenecks else {"status": "not_enough_timing_data"}


def runtime_readiness(snapshot_health: dict, failed_modules: list[str], learning_health: dict) -> dict:
    if failed_modules:
        state = "degraded"
    elif snapshot_health.get("status") != "healthy":
        state = "degraded"
    elif learning_health.get("status") in {"failed", "stale"}:
        state = "degraded"
    else:
        state = "ready"
    return {
        "status": state,
        "api_ready": True,
        "ui_ready": True,
        "background_learning_ready": learning_health.get("status") not in {"failed"},
        "reason": "Runtime is ready." if state == "ready" else "Some modules, jobs or snapshots need background attention.",
    }


def truth_panel_from_latest(db: Session, warnings: list[str]) -> list[str]:
    latest_benchmark = db.scalar(select(LearningBenchmarkComparison).order_by(desc(LearningBenchmarkComparison.calculated_at)).limit(1))
    lines = []
    if latest_benchmark is None:
        lines.append("No benchmark comparison has enough stored evidence yet.")
    else:
        lines.append(f"Latest benchmark result: {latest_benchmark.benchmark_name} is {latest_benchmark.result_label}.")
    lines.extend(warnings[:4])
    return lines[:6]


def benchmark_payload(row: LearningBenchmarkComparison) -> dict:
    return {
        "benchmark_name": row.benchmark_name,
        "result_label": row.result_label,
        "excess_return": row.excess_return,
        "sample_size": row.sample_size,
        "calculated_at": row.calculated_at.isoformat() if row.calculated_at else None,
    }


def learning_run_payload(row: LearningRun | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "status": row.status,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "trigger": row.trigger,
    }


def alpha_action_payload(row: AlphaRecoveryAction | None) -> dict | None:
    if row is None:
        return None
    return {
        "action_type": row.action_type,
        "status": row.status,
        "priority": row.priority,
        "affected_module": row.affected_module,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def serialize_event(row: BrainRuntimeEvent) -> dict:
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "event_type": row.event_type,
        "source_module": row.source_module,
        "status": row.status,
        "duration_ms": row.duration_ms,
        "payload": row.payload_json or {},
        "error_message": row.error_message,
    }


def serialize_job(row: BackgroundJobState) -> dict:
    return {
        "id": row.id,
        "job_name": row.job_name,
        "stage_name": row.stage_name,
        "status": row.status,
        "cursor": row.cursor_json or {},
        "items_processed": row.items_processed,
        "max_items": row.max_items,
        "duration_ms": row.duration_ms,
        "last_started_at": row.last_started_at.isoformat() if row.last_started_at else None,
        "last_completed_at": row.last_completed_at.isoformat() if row.last_completed_at else None,
        "next_run_after": row.next_run_after.isoformat() if row.next_run_after else None,
        "error_message": row.error_message,
        "enabled": row.enabled,
    }


def latest_job_completion(jobs: list[dict], name_fragment: str) -> str | None:
    for job in jobs:
        if name_fragment in str(job.get("job_name")) and job.get("status") == "completed":
            return job.get("last_completed_at")
    return None


def next_job(jobs: list[dict]) -> dict | None:
    scheduled = [job for job in jobs if job.get("next_run_after")]
    if not scheduled:
        return None
    return sorted(scheduled, key=lambda item: item.get("next_run_after") or "")[0]


def duration_since(value: str | None) -> float:
    parsed = parse_datetime(value)
    if not parsed:
        return 0.0
    return (datetime.utcnow() - parsed).total_seconds()


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    return value
