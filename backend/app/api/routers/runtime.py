from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.release import source_revision
from app.core.database import get_db
from app.runtime.facade import BlumRuntimeFacade
from app.services.central_brain_runtime import CentralBrainRuntime, LearningHealthService, SnapshotProducerService, SnapshotWatchdogService
from app.services.dashboard_snapshots import DashboardSnapshotService
from app.services.learning_summary import LearningSummaryService


settings = get_settings()
router = APIRouter(tags=["Runtime"])


@router.get("/api/runtime/release")
def runtime_release() -> dict:
    return {"version": settings.app_version, "source_revision": source_revision(),
            "mode": "paper_research", "github": "https://github.com/SignalLayerLabs/Blum"}


@router.get("/brain/runtime-state")
def brain_runtime_state(db: Session = Depends(get_db)) -> dict:
    return CentralBrainRuntime().state(db)


@router.get("/engine/status")
@router.get("/api/engine/status")
def engine_status(db: Session = Depends(get_db)) -> dict:
    from app.engine.facade import BlumEngineFacade

    return BlumEngineFacade().status(db)


@router.get("/engine/contracts")
@router.get("/api/engine/contracts")
def engine_contracts() -> dict:
    from app.engine.facade import BlumEngineFacade

    return BlumEngineFacade().contract()


@router.get("/engine/agents")
@router.get("/api/engine/agents")
def engine_agents(
    agent: list[str] | None = Query(default=None),
    limit: int = Query(default=8, ge=1, le=20),
    db: Session = Depends(get_db),
) -> dict:
    from app.engine.facade import BlumEngineFacade

    return BlumEngineFacade().agent_evidence(db, agents=agent, limit=limit)


@router.get("/runtime/status")
@router.get("/api/runtime/status")
def runtime_status(db: Session = Depends(get_db)) -> dict:
    return BlumRuntimeFacade().status(db)


@router.get("/runtime/contracts")
@router.get("/api/runtime/contracts")
def runtime_contracts() -> dict:
    return BlumRuntimeFacade().contract()


@router.get("/snapshots/health")
def snapshots_health(db: Session = Depends(get_db)) -> dict:
    return SnapshotWatchdogService().health(db, queue_rebuild=False)


@router.post("/snapshots/produce")
def snapshots_produce(
    snapshot_type: str | None = Query(default=None),
    max_items: int = Query(default=settings.blum_autonomous_max_items_per_job, ge=1, le=50),
    db: Session = Depends(get_db),
) -> dict:
    if snapshot_type:
        return SnapshotProducerService().produce(db, snapshot_type)
    return SnapshotProducerService().produce_many(db, max_items=max_items)


@router.get("/learning/health")
def learning_health(db: Session = Depends(get_db)) -> dict:
    snapshot_health = SnapshotWatchdogService().health(db, queue_rebuild=False)
    return LearningHealthService().health(db, snapshot_health=snapshot_health)


@router.get("/api/learning-intelligence/summary")
def learning_intelligence_summary(db: Session = Depends(get_db)) -> dict:
    return LearningSummaryService().summary(db)


@router.get("/api/dashboard-snapshots/{snapshot_type}")
def dashboard_snapshot(snapshot_type: str, db: Session = Depends(get_db)) -> dict:
    return DashboardSnapshotService().latest(db, snapshot_type=snapshot_type)


@router.get("/api/runtime/execution-kernel")
def execution_kernel_snapshot(db: Session = Depends(get_db)) -> dict:
    from app.services.deterministic_execution.snapshot import DeterministicExecutionSnapshotService

    return DeterministicExecutionSnapshotService().latest(db)


@router.get("/api/engine/decision-council")
def decision_council_snapshot(db: Session = Depends(get_db)) -> dict:
    from app.services.decision_council import DecisionCouncilSnapshotService

    return DecisionCouncilSnapshotService().latest(db)


@router.get("/api/engine/decision-council/runs/{run_id}")
def decision_council_run(run_id: int, db: Session = Depends(get_db)) -> dict:
    from app.services.decision_council import DecisionCouncilSnapshotService

    return DecisionCouncilSnapshotService().run_detail(db, run_id)
