from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.engine.facade import BlumEngineFacade


router = APIRouter(tags=["Alpha"])


@router.get("/api/alpha/desk")
def alpha_desk(db: Session = Depends(get_db)) -> dict:
    return BlumEngineFacade().alpha_desk_snapshot(db)


@router.get("/trader-brain/alpha")
@router.get("/api/trader-brain/alpha")
def alpha(db: Session = Depends(get_db)) -> dict:
    return BlumEngineFacade().alpha_snapshot(db)


@router.get("/api/alpha/snapshot")
def alpha_snapshot(db: Session = Depends(get_db)) -> dict:
    return BlumEngineFacade().alpha_snapshot(db)
