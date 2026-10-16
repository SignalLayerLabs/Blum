from __future__ import annotations

from datetime import date, datetime, timedelta
import time

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import DashboardSnapshot


class DashboardSnapshotService:
    """Small stale-safe snapshot store for dashboard loading surfaces."""

    def latest(self, db: Session, snapshot_type: str, *, now: datetime | None = None) -> dict:
        row = db.scalar(
            select(DashboardSnapshot)
            .where(DashboardSnapshot.snapshot_type == snapshot_type)
            .order_by(desc(DashboardSnapshot.created_at))
            .limit(1)
        )
        if row is None:
            record_snapshot_cache(snapshot_type, hit=False, status="missing")
            return {
                "status": "missing",
                "snapshot_type": snapshot_type,
                "payload": None,
                "warning": "No dashboard snapshot has been written yet.",
            }
        now = now or datetime.utcnow()
        is_stale = bool(row.is_stale or (row.expires_at is not None and row.expires_at < now))
        record_snapshot_cache(snapshot_type, hit=not is_stale, status="stale" if is_stale else "ready")
        return {
            "status": "stale" if is_stale else "ready",
            "snapshot_type": row.snapshot_type,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "is_stale": is_stale,
            "payload": row.payload_json or {},
            "source_modules": row.source_modules_json or {},
            "missing_sections": getattr(row, "missing_sections_json", None) or [],
            "computation_duration_ms": row.computation_duration_ms,
            "warnings": row.warnings_json or [],
        }

    def write(
        self,
        db: Session,
        snapshot_type: str,
        payload: dict,
        *,
        source_modules: dict | None = None,
        ttl_seconds: int = 300,
        warnings: list[str] | None = None,
        missing_sections: list[str] | None = None,
        computation_duration_ms: float | None = None,
    ) -> dict:
        started = time.perf_counter()
        row = DashboardSnapshot(
            snapshot_type=snapshot_type,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(seconds=max(1, ttl_seconds)),
            payload_json=json_safe(payload),
            source_modules_json=json_safe(source_modules or {}),
            missing_sections_json=json_safe(missing_sections or []),
            is_stale=False,
            computation_duration_ms=computation_duration_ms,
            warnings_json=json_safe(warnings or []),
        )
        if row.computation_duration_ms is None:
            row.computation_duration_ms = round((time.perf_counter() - started) * 1000, 3)
        db.add(row)
        db.commit()
        return self.latest(db, snapshot_type)


def record_snapshot_cache(snapshot_type: str, *, hit: bool, status: str) -> None:
    try:
        from app.services.performance import performance_recorder

        performance_recorder.record_cache_event(
            f"dashboard_snapshot.{snapshot_type}",
            hit=hit,
            metadata={"status": status, "snapshot_type": snapshot_type},
        )
    except Exception:
        pass


def json_safe(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    try:
        import numpy as np

        if isinstance(value, np.generic):
            return json_safe(value.item())
    except Exception:
        pass
    return value
