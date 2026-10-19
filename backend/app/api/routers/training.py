from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.engine.facade import BlumEngineFacade


router = APIRouter(tags=["Training Ground"])


@router.get("/trader-brain/training-ground")
@router.get("/api/trader-brain/training-ground")
def training_ground(db: Session = Depends(get_db)) -> dict:
    return BlumEngineFacade().training_snapshot(db)


@router.get("/api/training/snapshot")
def training_snapshot(db: Session = Depends(get_db)) -> dict:
    return BlumEngineFacade().training_snapshot(db)


@router.post("/api/training/accelerate")
def training_accelerate(db: Session = Depends(get_db)) -> dict:
    return BlumEngineFacade().training_acceleration(db)


@router.post("/api/training/run-replay")
def training_run_replay(db: Session = Depends(get_db)) -> dict:
    return BlumEngineFacade().run_training_replay(db)


@router.get("/api/training/curriculum")
def curriculum_snapshot(db: Session = Depends(get_db)) -> dict:
    return BlumEngineFacade().curriculum_snapshot(db)


@router.post("/api/training/curriculum/run")
def curriculum_run(db: Session = Depends(get_db)) -> dict:
    return BlumEngineFacade().run_curriculum(db)
