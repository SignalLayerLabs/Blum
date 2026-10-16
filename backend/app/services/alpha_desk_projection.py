"""Stored research evidence delivery; current execution plans have a separate lifecycle."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.services.alpha_desk import AlphaDeskService, utc
from app.services.dashboard_snapshots import DashboardSnapshotService

SNAPSHOT_TYPE = 'registered_alpha_desk_summary'


class AlphaDeskProjectionService:
    def publish(self, db: Session) -> dict:
        payload = AlphaDeskService().snapshot(db)
        return DashboardSnapshotService().write(db, SNAPSHOT_TYPE, payload,
            source_modules={'producer':'AlphaDeskProjectionService','policy':'background_evaluation_only'}, ttl_seconds=600)

    def latest(self, db: Session, *, now: datetime | None = None) -> dict:
        now = utc(now or datetime.now(timezone.utc))
        with db.no_autoflush:
            stored = DashboardSnapshotService().latest(db, SNAPSHOT_TYPE, now=now)
        payload = deepcopy(stored.get('payload'))
        generated = utc(payload.get('generated_at')) if isinstance(payload,dict) else None
        status = 'missing' if not payload else 'invalid_clock' if generated is None or generated > now else stored['status']
        if status in {'missing','invalid_clock'}:
            return {'status':'UNAVAILABLE','snapshot_status':status,'generated_at':payload.get('generated_at') if isinstance(payload,dict) else None,
                'read_at':now.isoformat(),'registered_count':None,'markets':{},'journal':[],
                'warnings':['No valid stored Alpha Desk evaluation is available. This read does not start evaluation.']}
        for market in payload.get('markets',{}).values():
            market['evaluated_active_count'] = len(market.get('active_calls') or [])
            market['active_calls'] = []
            market['active_calls_current'] = False
        for row in payload.get('journal',[]):
            row['eligibility_evaluated_at'] = payload['generated_at']
            row['active_eligible'] = False
            quote_at = utc(row.get('quote_at'))
            row['quote_age_seconds'] = max(0,(now-quote_at).total_seconds()) if quote_at else None
            if row.get('outcome_status') == 'PENDING':
                row['blockers'] = list(dict.fromkeys([*(row.get('blockers') or []),'CURRENT_STATE_NOT_REVALIDATED']))
        return {**payload,'read_at':now.isoformat(),'snapshot_status':status,
            'snapshot_created_at':stored.get('created_at'),'snapshot_expires_at':stored.get('expires_at'),
            'snapshot_is_stale':bool(stored.get('is_stale')),
            'current_call_policy':'Cached research eligibility is historical. Current entry plans require publication and activation evidence.'}
