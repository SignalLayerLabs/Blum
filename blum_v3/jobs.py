"""Recoverable, leased jobs; expired owners cannot acknowledge another worker's job."""
from datetime import timedelta
import json
from uuid import uuid4
from sqlalchemy import select,insert,update

from .domain import encode,now,utc
from .storage import Repository,jobs

KINDS={'research','confirmation','history','paper_step','paper_cycle'}


class JobService:
    def __init__(self,repository: Repository,*,clock=now): self.repository=repository;self.clock=clock

    def enqueue(self,kind,payload,*,key):
        if kind not in KINDS: raise ValueError('unknown_job_type')
        content=dict(kind=kind,input=payload)
        with self.repository.transaction() as conn:
            previous=self.repository.replay_command(conn,'jobs',key,content)
            if previous is not None: return previous
            value=dict(id=uuid4().hex,kind=kind,input=payload,status='QUEUED',created_at=self.clock().isoformat(),attempt=0,
                lease_token=None,lease_until=None,owner=None,result=None,error=None)
            conn.execute(insert(jobs).values(id=value['id'],payload=encode(value),status='QUEUED',available_at=self.clock().isoformat()))
            self.repository.remember(conn,'jobs',key,content,value)
            return value

    def get(self,job_id):
        with self.repository.engine.connect() as conn: raw=conn.scalar(select(jobs.c.payload).where(jobs.c.id==job_id))
        if raw is None: raise KeyError('job_not_found')
        return json.loads(raw)

    def list(self):
        with self.repository.engine.connect() as conn: rows=list(conn.scalars(select(jobs.c.payload).order_by(jobs.c.available_at.desc()).limit(100)))
        return [json.loads(row) for row in rows]

    def claim(self,owner,*,lease_seconds=900):
        with self.repository.transaction() as conn:
            query=select(jobs).where(jobs.c.status.in_(['QUEUED','RUNNING']),jobs.c.available_at<=self.clock().isoformat()).order_by(jobs.c.available_at).with_for_update(skip_locked=True)
            for row in conn.execute(query).mappings():
                value=json.loads(row['payload'])
                if value['attempt']>=3:
                    value.update(status='FAILED',error='retry_limit_exceeded')
                    conn.execute(update(jobs).where(jobs.c.id==value['id']).values(payload=encode(value),status='FAILED'))
                    continue
                value.update(status='RUNNING',owner=owner,attempt=value['attempt']+1,lease_token=uuid4().hex,
                    lease_until=(self.clock()+timedelta(seconds=lease_seconds)).isoformat())
                conn.execute(update(jobs).where(jobs.c.id==value['id']).values(payload=encode(value),status='RUNNING',available_at=value['lease_until']))
                return value
        return None

    def finish(self,job_id,lease_token,result=None,*,error=None):
        with self.repository.transaction() as conn:
            raw=conn.scalar(select(jobs.c.payload).where(jobs.c.id==job_id).with_for_update())
            if raw is None: raise KeyError('job_not_found')
            value=json.loads(raw)
            if value['status']!='RUNNING' or value['lease_token']!=lease_token or utc(value['lease_until'])<=self.clock(): raise ValueError('lease_lost')
            value.update(status='FAILED' if error else 'SUCCEEDED',result=result,error=error,finished_at=self.clock().isoformat())
            conn.execute(update(jobs).where(jobs.c.id==job_id).values(payload=encode(value),status=value['status']))
            return value

    def cancel(self,job_id):
        with self.repository.transaction() as conn:
            raw=conn.scalar(select(jobs.c.payload).where(jobs.c.id==job_id).with_for_update())
            if raw is None: raise KeyError('job_not_found')
            value=json.loads(raw)
            if value['status'] in {'QUEUED','RUNNING'}:
                value.update(status='CANCELED',finished_at=self.clock().isoformat())
                conn.execute(update(jobs).where(jobs.c.id==job_id).values(payload=encode(value),status='CANCELED'))
            return value
