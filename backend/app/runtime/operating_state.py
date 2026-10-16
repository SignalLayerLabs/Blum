"""Small public read model of persisted worker observations, without commands."""
from __future__ import annotations

from datetime import datetime
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import BackgroundJobState, ForexTraderCycle, ForexTraderRuntimeState


def _iso(value):
    return value.isoformat() if value else None


def _age(value: datetime | None, now: datetime) -> float | None:
    return (now - value).total_seconds() if value else None


def _codes(values) -> list[str]:
    # Provider errors and arbitrary log messages never enter this public projection.
    return list(dict.fromkeys(value for value in (values or []) if isinstance(value, str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}', value)))[:20]


class OperatingStateService:
    def read(self, db: Session, *, now: datetime | None = None) -> dict:
        now = now or datetime.utcnow()
        settings = get_settings()
        names = ('intraday_paper_trading', 'paper_execution_lifecycle', 'live_forward_paper_trading')
        with db.no_autoflush:
            runtime = db.scalar(select(ForexTraderRuntimeState).where(ForexTraderRuntimeState.runtime_key == 'default').limit(1))
            cycle = db.scalar(select(ForexTraderCycle).where(ForexTraderCycle.completed_at.is_not(None), ForexTraderCycle.status != 'RUNNING').order_by(ForexTraderCycle.completed_at.desc(), ForexTraderCycle.id.desc()).limit(1))
            latest_ids = select(func.max(BackgroundJobState.id)).where(BackgroundJobState.job_name.in_(names)).group_by(BackgroundJobState.job_name)
            jobs = db.scalars(select(BackgroundJobState).where(BackgroundJobState.id.in_(latest_ids)).limit(len(names))).all()
        latest_jobs = {}
        for job in jobs:
            latest_jobs.setdefault(job.job_name, job)

        workers = []
        for name, enabled, minutes in (
            (names[0], settings.intraday_paper_enabled, settings.intraday_paper_minutes),
            (names[1], settings.intraday_paper_enabled, settings.paper_execution_lifecycle_minutes),
            (names[2], settings.live_trading_game_enabled, settings.market_refresh_minutes),
        ):
            job = latest_jobs.get(name)
            observed_at = max(filter(None, (job.last_started_at, job.last_completed_at)), default=None) if job else None
            age = _age(observed_at, now)
            recent = age is not None and -5 <= age <= max(180, minutes * 180)
            status = 'DISABLED' if not enabled or (job and not job.enabled) else 'UNOBSERVED' if not job else 'ERROR' if job.status in {'failed', 'error'} else 'CLOCK_INCONSISTENT' if age is not None and age < -5 else 'STALE_OBSERVATION' if not recent else str(job.status).upper()
            workers.append({'name': name, 'enabled': enabled, 'status': status,
                            'last_started_at': _iso(job.last_started_at) if job else None,
                            'last_completed_at': _iso(job.last_completed_at) if job else None,
                            'next_run_after': _iso(job.next_run_after) if job else None,
                            'recent_observation': bool(recent), 'has_error': bool(job and job.error_message)})

        age = _age(runtime.heartbeat_at, now) if runtime else None
        recent = age is not None and -5 <= age <= max(180, settings.forex_trader_minutes * 180)
        desired = runtime.desired_state if runtime else None
        status = 'DISABLED' if not settings.forex_trader_enabled else 'UNOBSERVED' if not runtime else desired if desired in {'PAUSED', 'EMERGENCY_STOP'} else 'CLOCK_INCONSISTENT' if age is not None and age < -5 else 'STALE_HEARTBEAT' if not recent else runtime.scheduler_status
        return {
            'generated_at': now.isoformat(), 'mode': 'paper_research',
            'markets': {
                'equity': {'workers': workers, 'policy': 'Worker observations do not establish an executed trade or a fresh market quote.'},
                'forex': {
                    'enabled': settings.forex_trader_enabled, 'desired_state': desired, 'status': status,
                    'worker_observed_alive': bool(settings.forex_trader_enabled and recent),
                    'heartbeat_at': _iso(runtime.heartbeat_at) if runtime else None,
                    'heartbeat_age_seconds': age,
                    'next_run_after': _iso(runtime.next_run_after) if runtime else None,
                    'consecutive_failures': runtime.consecutive_failures if runtime else None,
                    'active_blockers': _codes(cycle.blockers) if cycle else [],
                    'last_completed_cycle': None if not cycle else {
                        'cycle_id': cycle.cycle_uid, 'status': cycle.status,
                        'started_at': _iso(cycle.started_at), 'completed_at': _iso(cycle.completed_at),
                        'pairs_scanned': len(cycle.pairs_scanned or []),
                        'orders': len(cycle.orders_json or []), 'fills': len(cycle.fills_json or []),
                        'closures': len(cycle.closed_trades or []),
                    },
                },
            },
            'policy': 'Read-only persisted observations. No cycle, initialization, provider call or job is triggered by this read.',
        }
