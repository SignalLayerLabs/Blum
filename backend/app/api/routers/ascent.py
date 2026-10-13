"""Read-only observatory and explicit, authenticated research execution."""

from hmac import compare_digest
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.services.ascent.engine import AscentEvolutionEngine


router = APIRouter(prefix="/api/ascent", tags=["ASCENT"])


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    market_family: Literal["equity", "forex"] = "equity"
    evidence_lane: Literal["REPLAY_EVIDENCE", "PAPER_FORWARD_FOREX"] = "REPLAY_EVIDENCE"
    generation_uid: str | None = None


@router.get("/status")
def ascent_status(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)) -> dict:
    return AscentEvolutionEngine().snapshot(db, limit=limit)


@router.post("/run")
def ascent_run(request: ResearchRequest, db: Session = Depends(get_db),
               admin_key: str = Header(default="", alias="X-BLUM-Admin-Key")) -> dict:
    settings = get_settings()
    if not settings.ascent_admin_key or not compare_digest(admin_key, settings.ascent_admin_key):
        raise HTTPException(status_code=403, detail="ASCENT administrative authorization required")
    if not settings.ascent_enabled:
        raise HTTPException(status_code=409, detail="ASCENT is disabled")
    try:
        return AscentEvolutionEngine().run_once(db, market_family=request.market_family,
            evidence_lane=request.evidence_lane, generation_uid=request.generation_uid)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
