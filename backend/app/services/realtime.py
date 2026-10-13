from __future__ import annotations

from datetime import datetime, timedelta
import threading
import time
import traceback

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app.analyst.hf_training_runtime import BlumHFTrainingService
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.ingestion.news_ingestor import NewsIngestor
from app.models import Asset, BackgroundJobState
from app.services.accuracy import run_accuracy_audit
from app.services.blum_financial_model import run_model_learning_cycle
from app.services.central_brain_runtime import BrainEventBus, BackgroundJobStateService, SnapshotProducerService, SnapshotWatchdogService
from app.services.data_continuity import repair_data_gaps
from app.services.etf import update_etf_trends
from app.services.fundamentals import update_fundamentals
from app.services.financial_brain_learning import run_learning_cycle
from app.services.ipo import update_ipo_radar
from app.services.learning_loop import LearningLoopService
from app.services.learning_intelligence import BlumTradingPowerScoreService
from app.services.macro import update_macro_snapshots
from app.services.market_data import MarketDataService
from app.services.performance import performance_recorder
from app.services.pipeline import PipelineService
from app.services.research_planner import AutonomousResearchPlanner
from app.services.trading_game import TradingGameSimulator
from app.services.live_forward_paper_trading import LiveForwardPaperTradingService
from app.services.intraday_paper_engine import BlumIntradayPaperEngine
from app.services.forex_trader import BlumForexTradingScheduler
from app.services.trading_ml.worker import TradingMLLearningWorker
from app.services.ascent.engine import AscentEvolutionEngine
from app.services.alpha_strategy_factory import AlphaStrategyFactory
from app.services.worker_runtime import runtime_worker_coordinator
from app.services.adaptive_replay_training import BlumAdaptiveTrainingController, refresh_strategy_factory_state
from app.services.deterministic_execution.worker import DeterministicExecutionWorker
from app.services.decision_council import DecisionCouncilWorker, EvidenceBoundDecisionCouncil
from app.signals.engine import SignalEngine


settings = get_settings()
_scheduler: BackgroundScheduler | None = None
_state_lock = threading.RLock()
_state = {
    "started": False,
    "running": False,
    "running_count": 0,
    "running_jobs": {},
    "last_started_at": None,
    "last_completed_at": None,
    "last_job": None,
    "last_status": "idle",
    "last_error": "",
    "last_result": {},
    "current_stage": None,
    "stage_started_at": None,
    "stage_completed_at": None,
    "completed_stages": [],
    "stage_results": {},
}


def start_realtime_services() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    with SessionLocal() as db:
        BackgroundJobStateService().recover_interrupted(db, archive_failed=True)
    _scheduler = BackgroundScheduler(timezone="UTC")
    if settings.enable_live_startup and settings.startup_run_full_autonomous:
        threading.Thread(target=run_startup_pipeline, daemon=True).start()
    elif settings.enable_live_startup:
        threading.Thread(target=run_startup_snapshot_warmup, daemon=True).start()
    _add_interval_job(run_runtime_snapshot_watchdog, minutes=5, job_id="runtime_snapshot_watchdog", delay_seconds=45, jitter_seconds=10)
    _add_interval_job(run_snapshot_refresh_job, minutes=10, job_id="snapshot_producer", delay_seconds=105, jitter_seconds=20)
    _add_interval_job(run_brain_evidence_projection_job, minutes=10, job_id="brain_evidence_projector", delay_seconds=195, jitter_seconds=20)
    if settings.decision_council_enabled:
        _add_interval_job(
            run_evidence_decision_council_job,
            minutes=settings.decision_council_minutes,
            job_id="evidence_decision_council",
            delay_seconds=225,
            jitter_seconds=20,
        )
    if settings.enable_autonomous_engine:
        _add_interval_job(run_autonomous_engine_job, minutes=settings.autonomous_cycle_minutes, job_id="autonomous_research_engine", delay_seconds=180, jitter_seconds=45)
    _add_interval_job(run_news_refresh, minutes=settings.news_refresh_minutes, job_id="news_refresh", delay_seconds=240, jitter_seconds=30)
    _add_interval_job(run_market_refresh, minutes=settings.market_refresh_minutes, job_id="market_refresh", delay_seconds=360, jitter_seconds=45)
    if settings.live_trading_game_enabled:
        _add_interval_job(run_live_forward_paper_trading_job, minutes=settings.market_refresh_minutes, job_id="live_forward_paper_trading", delay_seconds=390, jitter_seconds=45)
    if settings.blum_nautilus_enabled:
        _add_interval_job(
            run_deterministic_execution_job,
            minutes=10,
            job_id="deterministic_execution_core",
            delay_seconds=450,
            jitter_seconds=20,
        )
    if settings.intraday_paper_enabled:
        _add_interval_job(run_intraday_paper_trading_job, minutes=settings.intraday_paper_minutes, job_id="intraday_paper_trading", delay_seconds=420, jitter_seconds=15)
        _add_interval_job(
            run_paper_execution_lifecycle_job,
            minutes=settings.paper_execution_lifecycle_minutes,
            job_id="paper_execution_lifecycle",
            delay_seconds=435,
            jitter_seconds=10,
        )
    if settings.forex_trader_enabled:
        _add_interval_job(
            run_forex_trader_job,
            minutes=settings.forex_trader_minutes,
            job_id="autonomous_forex_trader",
            delay_seconds=75,
            jitter_seconds=5,
        )
    _add_interval_job(run_data_gap_repair, minutes=settings.data_gap_repair_minutes, job_id="data_gap_repair", delay_seconds=480, jitter_seconds=45)
    _add_interval_job(run_accuracy_audit_job, minutes=settings.accuracy_audit_minutes, job_id="accuracy_audit", delay_seconds=600, jitter_seconds=45)
    _add_interval_job(run_macro_refresh, minutes=settings.macro_refresh_minutes, job_id="macro_refresh", delay_seconds=720, jitter_seconds=45)
    _add_interval_job(run_fundamentals_refresh, minutes=settings.fundamentals_refresh_minutes, job_id="fundamentals_refresh", delay_seconds=840, jitter_seconds=45)
    _add_interval_job(run_ipo_refresh, minutes=settings.ipo_refresh_minutes, job_id="ipo_refresh", delay_seconds=960, jitter_seconds=45)
    if settings.ascent_enabled and settings.ascent_scheduler_enabled:
        _add_interval_job(run_ascent_research_job, minutes=settings.ascent_interval_minutes,
            job_id="blum_ascent_research", delay_seconds=600, jitter_seconds=30)
    if settings.hf_training_scheduler_enabled or settings.hf_dataset_snapshot_enabled:
        _add_interval_job(
            run_hf_training_supervisor_job,
            minutes=settings.hf_training_supervisor_minutes,
            job_id="blum_hf_training_supervisor",
            delay_seconds=300,
            jitter_seconds=60,
        )
    if settings.enable_learning_loop:
        if settings.replay_training_enabled:
            _add_interval_job(
                run_hyperbolic_replay_training_job,
                minutes=settings.replay_training_minutes,
                job_id="hyperbolic_replay_training",
                delay_seconds=210,
                jitter_seconds=30,
            )
            if settings.strategy_factory_enabled:
                _add_interval_job(
                    run_alpha_strategy_factory_job,
                    minutes=settings.strategy_factory_minutes,
                    job_id="alpha_strategy_factory",
                    delay_seconds=300,
                    jitter_seconds=30,
                )
        _schedule_learning_jobs()
    _scheduler.start()
    runtime_worker_coordinator.mark_scheduler_started()
    with _state_lock:
        _state["started"] = True


def stop_realtime_services() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
    runtime_worker_coordinator.mark_scheduler_stopped()


def realtime_status() -> dict:
    runtime_snapshot = runtime_worker_coordinator.snapshot()
    with _state_lock:
        payload = dict(_state)
    payload.update(
        {
            "started": bool(payload.get("started") or runtime_snapshot.get("started")),
            "running": bool(runtime_snapshot.get("running")),
            "running_count": runtime_snapshot.get("running_count", 0),
            "running_jobs": runtime_snapshot.get("running_jobs", {}),
            "last_started_at": runtime_snapshot.get("last_started_at") or payload.get("last_started_at"),
            "last_completed_at": runtime_snapshot.get("last_completed_at") or payload.get("last_completed_at"),
            "last_job": runtime_snapshot.get("last_job") or payload.get("last_job"),
            "last_status": runtime_snapshot.get("last_status") or payload.get("last_status"),
            "last_error": runtime_snapshot.get("last_error") or payload.get("last_error"),
            "last_result": runtime_snapshot.get("last_result") or payload.get("last_result"),
            "worker_registry": runtime_snapshot.get("worker_registry", []),
            "runtime_policy": runtime_snapshot.get("policy"),
        }
    )
    payload["scheduled_jobs"] = scheduled_jobs()
    return payload


def _add_interval_job(func, *, minutes: int, job_id: str, delay_seconds: int, jitter_seconds: int = 0) -> None:
    if _scheduler is None:
        return
    _scheduler.add_job(
        func,
        "interval",
        minutes=max(1, int(minutes)),
        id=job_id,
        replace_existing=True,
        max_instances=1,
        next_run_time=datetime.utcnow() + timedelta(seconds=max(0, delay_seconds)),
        jitter=max(0, jitter_seconds),
    )


def _schedule_learning_jobs() -> None:
    """Schedule independent learning lanes instead of one blocking mega-cycle."""

    if settings.professional_learning_enabled:
        cadence = settings.professional_learning_minutes
        jobs = [
            (run_professional_financial_brain_job, "financial_brain_learning", 150),
            (run_professional_model_learning_job, "blum_financial_model_cycle", 510),
            (run_professional_point_in_time_job, "blum_point_in_time_learning_loop", 870),
        ]
        if settings.trading_game_enabled:
            jobs.append((run_professional_trading_game_job, "blum_trading_game", 1230))
        for func, job_id, delay_seconds in jobs:
            _add_interval_job(
                func,
                minutes=cadence,
                job_id=job_id,
                delay_seconds=delay_seconds,
                jitter_seconds=30,
            )
        if settings.trading_ml_enabled:
            _add_interval_job(
                run_trading_ml_learning_job,
                minutes=settings.trading_ml_worker_minutes,
                job_id="trading_ml_learning",
                delay_seconds=1590,
                jitter_seconds=30,
            )
        return

    _add_interval_job(run_learning_cycle_job, minutes=settings.learning_loop_minutes, job_id="financial_brain_learning", delay_seconds=1020, jitter_seconds=45)
    _add_interval_job(run_blum_model_cycle_job, minutes=settings.blum_model_cycle_minutes, job_id="blum_financial_model_cycle", delay_seconds=1080, jitter_seconds=45)
    _add_interval_job(run_blum_learning_loop_job, minutes=settings.learning_loop_minutes, job_id="blum_point_in_time_learning_loop", delay_seconds=1140, jitter_seconds=45)
    if settings.trading_game_enabled:
        _add_interval_job(run_trading_game_job, minutes=settings.learning_loop_minutes, job_id="blum_trading_game", delay_seconds=1200, jitter_seconds=45)
    if settings.trading_ml_enabled:
        _add_interval_job(
            run_trading_ml_learning_job,
            minutes=settings.trading_ml_worker_minutes,
            job_id="trading_ml_learning",
            delay_seconds=1260,
            jitter_seconds=30,
        )


def scheduled_jobs() -> list[dict]:
    if _scheduler is None:
        return []
    jobs = []
    for job in _scheduler.get_jobs():
        jobs.append(
            {
                "id": job.id,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            }
        )
    return sorted(jobs, key=lambda item: item["id"])


def run_startup_pipeline() -> None:
    if settings.enable_autonomous_engine:
        _run_job(
            "autonomous_startup",
            lambda db: AutonomousResearchEngine(progress_callback=_update_stage_progress).run_cycle(db, trigger="startup"),
        )
        return

    def work(db):
        pipeline = PipelineService().run(db, limit=settings.startup_pipeline_limit, period=settings.historical_price_period)
        learning = run_learning_cycle(db, limit=settings.max_update_assets * 6) if settings.enable_learning_loop else {}
        model_learning = run_model_learning_cycle(db, limit=settings.blum_model_cycle_limit) if settings.enable_learning_loop else {}
        point_in_time_learning = LearningLoopService().run_batch(db, batch_size=min(settings.learning_batch_size, 25), trigger="startup") if settings.enable_learning_loop else {}
        trading_game = TradingGameSimulator().run(db, batch_size=min(settings.trading_game_batch_size, 40)) if settings.trading_game_enabled else {}
        return {"pipeline": pipeline, "financial_brain_learning": learning, "blum_financial_model": model_learning, "blum_learning_loop": point_in_time_learning, "trading_game": trading_game}

    _run_job("startup_pipeline", work)


def run_startup_snapshot_warmup() -> None:
    def work(db):
        health = SnapshotWatchdogService().health(db, queue_rebuild=True)
        snapshots = SnapshotProducerService().produce_many(db, max_items=startup_snapshot_warmup_budget())
        return {"snapshot_health": health, "snapshots": snapshots, "policy": "startup_light_mode"}

    _run_job("startup_snapshot_warmup", work)


def startup_snapshot_warmup_budget() -> int:
    """Warm every critical snapshot after API startup without page-triggered work."""

    from app.services.central_brain_runtime import CRITICAL_SNAPSHOT_TYPES

    configured_limit = max(1, settings.blum_autonomous_max_items_per_job)
    return min(configured_limit, len(CRITICAL_SNAPSHOT_TYPES))


def run_runtime_snapshot_watchdog() -> None:
    _run_job("runtime_snapshot_watchdog", lambda db: SnapshotWatchdogService().health(db, queue_rebuild=True))


def run_snapshot_refresh_job() -> None:
    _run_job("snapshot_producer", lambda db: SnapshotProducerService().produce_many(db, max_items=settings.blum_autonomous_max_items_per_job))


def run_news_refresh() -> None:
    _run_job("news_refresh", lambda db: NewsIngestor().update_news(db, lookback_hours=72, limit_per_feed=35))


def refresh_market_intelligence(db) -> dict:
    """Refresh market-derived state without invoking any learning subsystem."""

    tickers, slice_state = market_refresh_asset_slice(db)
    if not tickers:
        return {
            "market_update": {"status": "no_active_assets", "updated_assets": 0},
            "signal_run": {"status": "no_active_assets", "created": 0},
            "etf_update": update_etf_trends(db),
            "slice": slice_state,
        }
    batch_size = len(tickers)
    return {
        "market_update": MarketDataService().update_prices(
            db,
            tickers=tickers,
            period=settings.refresh_price_period,
            limit=batch_size,
            provider_validation_limit=settings.market_provider_validation_max_items,
        ),
        "signal_run": SignalEngine().run(db, tickers=tickers, limit=batch_size),
        "etf_update": update_etf_trends(db),
        "slice": slice_state,
    }


def market_refresh_asset_slice(db) -> tuple[list[str], dict]:
    state = db.scalar(
        select(BackgroundJobState).where(
            BackgroundJobState.job_name == "market_refresh",
            BackgroundJobState.stage_name == "default",
        )
    )
    cursor = dict(state.cursor_json or {}) if state else {}
    last_asset_id = int(cursor.get("last_asset_id") or 0)
    batch_limit = max(
        1,
        min(
            settings.max_update_assets,
            settings.blum_autonomous_max_items_per_job,
            settings.market_refresh_max_items_per_job,
        ),
    )

    def rows_after(asset_id: int):
        return db.execute(
            select(Asset.id, Asset.ticker)
            .where(Asset.is_active.is_(True), Asset.id > asset_id)
            .order_by(Asset.id)
            .limit(batch_limit + 1)
        ).all()

    rows = rows_after(last_asset_id)
    if not rows and last_asset_id:
        last_asset_id = 0
        rows = rows_after(0)
    selected = rows[:batch_limit]
    has_more = len(rows) > batch_limit
    next_asset_id = int(selected[-1].id) if selected and has_more else 0
    tickers = [str(row.ticker) for row in selected]
    BackgroundJobStateService().heartbeat(
        db,
        "market_refresh",
        items_processed=len(tickers),
        cursor={"last_asset_id": next_asset_id},
    )
    return tickers, {
        "batch_size": len(tickers),
        "batch_limit": batch_limit,
        "previous_asset_id": last_asset_id,
        "next_asset_id": next_asset_id,
        "has_more": has_more,
        "policy": "Bounded resumable market slice; the cursor rotates across every active asset.",
    }


def run_market_refresh() -> None:
    _run_job("market_refresh", refresh_market_intelligence)


def run_data_gap_repair() -> None:
    _run_job("data_gap_repair", lambda db: repair_data_gaps(db, limit=settings.max_update_assets))


def run_accuracy_audit_job() -> None:
    _run_job("accuracy_audit", lambda db: run_accuracy_audit(db, limit=settings.max_update_assets))


def run_macro_refresh() -> None:
    _run_job("macro_refresh", lambda db: update_macro_snapshots(db))


def run_fundamentals_refresh() -> None:
    _run_job("fundamentals_refresh", lambda db: update_fundamentals(db, limit=min(settings.max_update_assets, 24)))


def run_ipo_refresh() -> None:
    def work(db):
        return update_ipo_radar(db, limit_per_form=45)

    _run_job("ipo_refresh", work)


def run_learning_cycle_job() -> None:
    _run_job("financial_brain_learning", lambda db: run_learning_cycle(db, limit=settings.max_update_assets * 6))


def run_blum_model_cycle_job() -> None:
    _run_job("blum_financial_model_cycle", lambda db: run_model_learning_cycle(db, limit=settings.blum_model_cycle_limit))


def run_blum_learning_loop_job() -> None:
    _run_job("blum_point_in_time_learning_loop", lambda db: LearningLoopService().run_batch(db, batch_size=settings.learning_batch_size, trigger="scheduled"))


def run_trading_game_job() -> None:
    _run_job("blum_trading_game", lambda db: TradingGameSimulator().run(db, batch_size=settings.trading_game_batch_size))


def professional_learning_batch_size() -> int:
    return max(
        1,
        min(
            settings.professional_learning_batch_size,
            settings.learning_batch_size,
            settings.blum_autonomous_max_items_per_job,
        ),
    )


def run_professional_financial_brain_job() -> None:
    batch_size = professional_learning_batch_size()
    _run_job(
        "financial_brain_learning",
        lambda db: run_learning_cycle(db, limit=max(20, min(settings.max_update_assets * 2, batch_size * 4))),
    )


def run_professional_model_learning_job() -> None:
    batch_size = professional_learning_batch_size()
    _run_job(
        "blum_financial_model_cycle",
        lambda db: run_model_learning_cycle(
            db,
            limit=max(20, min(settings.blum_model_cycle_limit, batch_size * 4)),
            backup=False,
        ),
    )


def run_professional_point_in_time_job() -> None:
    batch_size = professional_learning_batch_size()
    _run_job(
        "blum_point_in_time_learning_loop",
        lambda db: LearningLoopService().run_batch(
            db,
            batch_size=batch_size,
            trigger="professional_continuous",
            sniper_simulation_limit=0,
        ),
    )


def run_professional_trading_game_job() -> None:
    batch_size = professional_learning_batch_size()
    trading_batch = max(3, min(settings.trading_game_batch_size, max(3, batch_size // 2)))
    _run_job("blum_trading_game", lambda db: TradingGameSimulator().run(db, batch_size=trading_batch))


def run_hf_training_supervisor_job() -> None:
    _run_job("blum_hf_training_supervisor", lambda db: BlumHFTrainingService().supervise(db))


def run_ascent_research_job() -> None:
    if not (settings.ascent_enabled and settings.ascent_scheduler_enabled):
        return
    _run_job("blum_ascent_research", lambda db: AscentEvolutionEngine().run_once(db))


def run_live_forward_paper_trading_job() -> None:
    _run_job("live_forward_paper_trading", lambda db: advance_live_forward_paper_trading(db))


def run_deterministic_execution_job() -> None:
    _run_job(
        "deterministic_execution_core",
        lambda db: DeterministicExecutionWorker().run(
            db,
            max_items=settings.blum_nautilus_max_items_per_job,
            max_seconds=settings.blum_nautilus_max_job_seconds,
        ),
    )


def run_evidence_decision_council_job() -> None:
    _run_job(
        "evidence_decision_council",
        lambda db: DecisionCouncilWorker(
            EvidenceBoundDecisionCouncil(
                min_evidence_sources=settings.decision_council_min_evidence_sources,
                min_memory_samples=settings.decision_council_min_memory_samples,
            )
        ).run(
            db,
            max_items=settings.decision_council_max_items,
            max_seconds=min(120, settings.blum_autonomous_max_seconds_per_job),
            manage_state=False,
        ),
    )


def advance_live_forward_paper_trading(db, service: LiveForwardPaperTradingService | None = None) -> dict:
    service = service or LiveForwardPaperTradingService()
    scan = service.run_once(db)
    if not settings.paper_forward_lifecycle_enabled:
        return {"status": scan.get("status", "ok"), "scan": scan, "lifecycle": {"status": "disabled"}}
    lifecycle = service.run_lifecycle(db)
    return {
        "status": "ok" if scan.get("status") != "error" and lifecycle.get("status") != "error" else "degraded",
        "scan": scan,
        "lifecycle": lifecycle,
    }


def run_brain_evidence_projection_job() -> None:
    _run_job(
        "brain_evidence_projector",
        lambda db: BlumTradingPowerScoreService().persist_if_evidence_changed(db),
    )


def run_intraday_paper_trading_job() -> None:
    _run_job("intraday_paper_trading", lambda db: BlumIntradayPaperEngine().run_once(db, trigger="scheduled"))


def run_forex_trader_job() -> None:
    _run_job("autonomous_forex_trader", lambda db: BlumForexTradingScheduler().run_once(db))


def run_trading_ml_learning_job() -> None:
    _run_job("trading_ml_learning", lambda db: TradingMLLearningWorker().run_once(db, "scheduled"))


def run_paper_execution_lifecycle_job() -> None:
    _run_job("paper_execution_lifecycle", lambda db: BlumIntradayPaperEngine().run_execution_once(db, trigger="scheduled"))


def run_alpha_strategy_factory_job() -> None:
    def work(db):
        factory = AlphaStrategyFactory().run_once(
            db,
            max_variants_per_family=settings.strategy_factory_max_variants_per_family,
            seed=settings.strategy_factory_seed,
            trigger="scheduled",
        )
        snapshot = refresh_strategy_factory_state(db)
        return {"factory": factory, "snapshot_status": snapshot.get("status")}

    _run_job(
        "alpha_strategy_factory",
        work,
    )


def run_professional_learning_cycle_job() -> None:
    """Backward-compatible bounded entry point for one point-in-time slice."""

    run_professional_point_in_time_job()


def run_hyperbolic_replay_training_job() -> None:
    def work(db):
        from app.services.forex_evidence_academy import ForexEvidenceAcademyService

        academy = ForexEvidenceAcademyService().run_background_slice(
            db,
            max_assignments=max(2, min(12, settings.replay_max_experiments_per_cycle)),
        )
        training = BlumAdaptiveTrainingController().run_once(db, trigger="scheduled")
        brain_evidence = BlumTradingPowerScoreService().persist_if_evidence_changed(db)
        return {"forex_academy": academy, "training": training, "brain_evidence": brain_evidence}

    _run_job("hyperbolic_replay_training", work)


def run_autonomous_engine_job() -> None:
    _run_job(
        "autonomous_research_engine",
        lambda db: {
            "status": "ok",
            "research_plan": AutonomousResearchPlanner().generate(db, persist=True),
            "policy": "The autonomous planner selects research. Market, learning, trading and snapshot work run in independent workers.",
        },
    )


def _update_stage_progress(progress: dict) -> None:
    with _state_lock:
        _state["current_stage"] = progress.get("stage")
        _state["stage_started_at"] = progress.get("stage_started_at")
        _state["stage_completed_at"] = progress.get("stage_completed_at")
        _state["completed_stages"] = progress.get("completed_stages", [])
        _state["stage_results"] = _compact_payload(progress.get("stage_results", {}))


def _returned_job_failure(result) -> tuple[str, str] | None:
    if not isinstance(result, dict):
        return None
    status = str(result.get("status") or "").strip().lower()
    if status not in {"error", "failed", "degraded"}:
        return None
    detail = (
        result.get("error_message")
        or result.get("error")
        or result.get("reason")
        or result.get("explanation")
        or f"job returned status={status}"
    )
    return status, str(detail)


def _run_job(job_name: str, work):
    max_items = runtime_worker_coordinator.definition(job_name).max_items
    acquired, worker_state = runtime_worker_coordinator.begin(job_name, max_items=max_items)
    if not acquired:
        perf_started_at = datetime.utcnow()
        performance_recorder.record_background_task(
            job_name,
            0.0,
            {"status": "deferred", "reason": worker_state.get("reason"), "blocking_job": worker_state.get("blocking_job")},
            perf_started_at,
        )
        with SessionLocal() as db:
            BrainEventBus().publish(
                db,
                "module_deferred",
                job_name,
                status="deferred",
                payload=worker_state,
            )
        return
    with _state_lock:
        _state["running"] = True
        _state["running_jobs"] = runtime_worker_coordinator.snapshot().get("running_jobs", {})
        _state["running_count"] = len(_state["running_jobs"])
        _state["last_started_at"] = datetime.utcnow().isoformat()
        _state["last_job"] = job_name
        _state["last_status"] = "running"
        _state["last_error"] = ""
        _state["current_stage"] = None
        _state["stage_started_at"] = None
        _state["stage_completed_at"] = None
        _state["completed_stages"] = []
        _state["stage_results"] = {}
    perf_started_at = datetime.utcnow()
    perf_started = time.perf_counter()
    perf_status = "ok"
    perf_error = ""
    try:
        with SessionLocal() as db:
            BackgroundJobStateService().start(db, job_name, max_items=max_items)
        with SessionLocal() as db:
            result = work(db)
            duration_ms = (time.perf_counter() - perf_started) * 1000
            returned_failure = _returned_job_failure(result)
            if returned_failure:
                returned_status, returned_error = returned_failure
                perf_status = "error"
                perf_error = returned_error
                BackgroundJobStateService().fail(
                    db,
                    job_name,
                    duration_ms=duration_ms,
                    error_message=returned_error,
                )
            else:
                BackgroundJobStateService().complete(
                    db,
                    job_name,
                    duration_ms=duration_ms,
                    payload=_compact_payload(result or {}),
                )
        compact_result = _compact_payload(result or {})
        with _state_lock:
            _state["last_completed_at"] = datetime.utcnow().isoformat()
            _state["last_status"] = returned_status if returned_failure else "ok"
            _state["last_error"] = returned_error if returned_failure else ""
            _state["last_result"] = compact_result
        if returned_failure:
            runtime_worker_coordinator.fail(
                job_name,
                error=returned_error,
                result=compact_result,
            )
        else:
            runtime_worker_coordinator.complete(job_name, result=compact_result)
    except Exception as exc:
        perf_status = "error"
        perf_error = f"{type(exc).__name__}: {str(exc)}"
        try:
            with SessionLocal() as db:
                BackgroundJobStateService().fail(db, job_name, duration_ms=(time.perf_counter() - perf_started) * 1000, error_message=perf_error)
        except Exception:
            pass
        with _state_lock:
            _state["last_completed_at"] = datetime.utcnow().isoformat()
            _state["last_status"] = "error"
            _state["last_error"] = perf_error
            _state["last_result"] = {"traceback": traceback.format_exc(limit=4)}
        runtime_worker_coordinator.fail(job_name, error=perf_error, result={"traceback": traceback.format_exc(limit=4)})
    finally:
        performance_recorder.record_background_task(
            job_name,
            (time.perf_counter() - perf_started) * 1000,
            {"status": perf_status, "error": perf_error},
            perf_started_at,
        )
        with _state_lock:
            runtime_snapshot = runtime_worker_coordinator.snapshot()
            _state["running_jobs"] = runtime_snapshot.get("running_jobs", {})
            _state["running_count"] = runtime_snapshot.get("running_count", 0)
            _state["running"] = bool(_state["running_jobs"])


def _compact_payload(value, depth: int = 0):
    if depth > 5:
        return "<truncated>"
    if isinstance(value, dict):
        compact = {}
        for key, item in value.items():
            if key in {"sources", "source_diagnostics", "diagnostics"} and isinstance(item, list):
                compact[key] = {
                    "count": len(item),
                    "sample": [_compact_payload(row, depth + 1) for row in item[:8]],
                }
                continue
            if key in {"viewer_status", "parquet_files", "size_summary"} and isinstance(item, dict):
                compact[key] = _compact_dataset_metadata(item)
                continue
            compact[key] = _compact_payload(item, depth + 1)
        return compact
    if isinstance(value, list):
        if len(value) > 12:
            return {"count": len(value), "sample": [_compact_payload(item, depth + 1) for item in value[:12]]}
        return [_compact_payload(item, depth + 1) for item in value]
    if isinstance(value, str) and len(value) > 600:
        return f"{value[:600]}..."
    return value


def _compact_dataset_metadata(value: dict) -> dict:
    output = {}
    if "status" in value:
        output["status"] = value.get("status")
    if "file_count" in value:
        output["file_count"] = value.get("file_count")
    if "sample_files" in value and isinstance(value["sample_files"], list):
        output["sample_files"] = [
            {
                "dataset": item.get("dataset"),
                "config": item.get("config"),
                "split": item.get("split"),
                "filename": item.get("filename"),
                "size": item.get("size"),
            }
            for item in value["sample_files"][:3]
            if isinstance(item, dict)
        ]
    if "size" in value and isinstance(value["size"], dict):
        dataset = value["size"].get("dataset", {})
        if isinstance(dataset, dict):
            output["dataset_size"] = {
                "num_rows": dataset.get("num_rows"),
                "num_bytes_parquet_files": dataset.get("num_bytes_parquet_files"),
            }
    if not output:
        output = _compact_payload({k: v for k, v in value.items() if k != "detail"}, depth=1)
    return output
