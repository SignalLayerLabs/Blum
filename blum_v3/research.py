"""Immutable hypotheses, complete trial registry and separately opened confirmation."""
from __future__ import annotations

import json
from uuid import uuid4
from sqlalchemy import select,insert,update

from .domain import encode,identity,now,utc
from .storage import Repository,experiments,families,consumed_holdouts
from .holdout import economic_identity,confirmation_window,overlaps,claims
from .replay import ReplayConfig,run_replay
from .evaluation import paired_interval,score_returns
from .learning import evaluate_challengers


class ResearchService:
    def __init__(self,repository: Repository): self.repository=repository

    def create(self,dataset_id: str,config: dict,*,family_id: str,key: str,hypothesis: str='Frozen trend hypothesis'):
        source=self.repository.dataset(dataset_id);settings=ReplayConfig.model_validate(config)
        if len(source.bars)<30: raise ValueError('minimum_history_is_thirty_accepted_bars')
        if len(source.bars)>2500:raise ValueError('maximum_history_is_2500_bars_import_a_bounded_window')
        if not family_id.strip() or len(family_id)>100: raise ValueError('family_identity_required')
        split=int(len(source.bars)*0.8)
        frozen=dict(dataset_id=dataset_id,config=settings.model_dump(mode='json'),family_id=family_id,hypothesis=hypothesis,
            split_index=split,source_market=source.instrument.market,application_version='3.0.0')
        with self.repository.transaction() as conn:
            self.repository.lock_research(conn,economic_identity(source.instrument))
            previous=self.repository.replay_command(conn,'experiments',key,frozen)
            if previous is not None: return previous
            window=confirmation_window(source,split)
            if any(overlaps(window,claim) for claim in claims(conn)):
                raise ValueError('confirmation_already_opened_requires_new_independent_data')
            prior_values=[json.loads(raw) for raw in conn.scalars(select(experiments.c.payload))]
            if any(v['frozen']['dataset_id']==dataset_id and v['holdout']['opened'] for v in prior_values):
                raise ValueError('confirmation_already_opened_requires_new_independent_data')
            family=conn.scalar(select(families.c.payload).where(families.c.id==family_id).with_for_update())
            if family:
                value=json.loads(family)
                if value['sealed']: raise ValueError('family_sealed_after_confirmation')
                if value['market']!=source.instrument.market: raise ValueError('market_family_mismatch')
            else: conn.execute(insert(families).values(id=family_id,payload=encode(dict(market=source.instrument.market,sealed=False))))
            prior_values=[json.loads(raw) for raw in conn.scalars(select(experiments.c.payload))]
            result=dict(id=uuid4().hex,created_at=now().isoformat(),frozen=frozen,frozen_hash=identity(frozen),status='REGISTERED',
                holdout=dict(opened=False,first_available_at=source.bars[split].available_at.isoformat(),bars=len(source.bars)-split),report=None,confirmation=None)
            conn.execute(insert(experiments).values(id=result['id'],payload=encode(result),status='REGISTERED'))
            total=1+sum(v['frozen']['family_id']==family_id for v in prior_values)
            result['family_trial_count']=total
            conn.execute(update(experiments).where(experiments.c.id==result['id']).values(payload=encode(result)))
            for prior in prior_values:
                if prior['frozen']['family_id']!=family_id:continue
                prior['family_trial_count']=total
                if prior['report'] is not None:
                    prior['report']['paired_interval']=dict(status='STALE',reason='family_registry_changed',family_trials=total,lower_percent=None,upper_percent=None)
                conn.execute(update(experiments).where(experiments.c.id==prior['id']).values(payload=encode(prior)))
            self.repository.remember(conn,'experiments',key,frozen,result)
            return result

    def get(self,experiment_id):
        with self.repository.engine.connect() as conn:
            raw=conn.scalar(select(experiments.c.payload).where(experiments.c.id==experiment_id))
        if raw is None: raise KeyError('experiment_not_found')
        value=json.loads(raw)
        if identity(value['frozen'])!=value['frozen_hash']: raise ValueError('frozen_experiment_integrity_failure')
        return value

    def list(self):
        with self.repository.engine.connect() as conn: ids=list(conn.scalars(select(experiments.c.id)))
        return [self.get(i) for i in ids]

    def _store(self,value):
        source=self.repository.dataset(value['frozen']['dataset_id'])
        with self.repository.transaction() as conn:
            self.repository.lock_research(conn,economic_identity(source.instrument))
            conn.execute(select(families.c.id).where(families.c.id==value['frozen']['family_id']).with_for_update()).first()
            current=json.loads(conn.scalar(select(experiments.c.payload).where(experiments.c.id==value['id']).with_for_update()))
            if current['holdout']['opened'] and not value['holdout']['opened']:value['holdout']=current['holdout']
            if current.get('confirmation') is not None and value.get('confirmation') is None:value['confirmation']=current['confirmation'];value['status']=current['status']
            total=sum(json.loads(raw)['frozen']['family_id']==value['frozen']['family_id'] for raw in conn.scalars(select(experiments.c.payload)))
            if value.get('family_trial_count')!=total and value.get('report') is not None:
                value['report']['paired_interval']=dict(status='STALE',reason='family_registry_changed',family_trials=total,lower_percent=None,upper_percent=None)
            value['family_trial_count']=total
            conn.execute(update(experiments).where(experiments.c.id==value['id']).values(payload=encode(value),status=value['status']))

    def run(self,experiment_id,*,progress=None):
        value=self.get(experiment_id)
        if value['report'] is not None:
            if value['report'].get('paired_interval',{}).get('status')=='STALE':
                value['report']['paired_interval']=paired_interval(value['report']['curve'],value['report']['benchmark']['curve'],trials=value['family_trial_count'])
                self._store(value)
            return value
        frozen=value['frozen'];source=self.repository.dataset(frozen['dataset_id']);end=frozen['split_index']
        development=source.model_copy(update=dict(dataset_id=identity(dict(parent=source.dataset_id,range=[0,end])),bars=source.bars[:end]))
        report=run_replay(development,ReplayConfig.model_validate(frozen['config']),progress=progress)
        trial_count=sum(v['frozen']['family_id']==frozen['family_id'] for v in self.list())
        report.update(parent_dataset_id=source.dataset_id,partition='development',statistics=score_returns(report['curve']),
            paired_interval=paired_interval(report['curve'],report['benchmark']['curve'],trials=trial_count),
            learning=evaluate_challengers(development))
        value.update(report=report,status='DEVELOPMENT_COMPLETE',family_trial_count=trial_count)
        self._store(value)
        return value

    def confirm(self,experiment_id,*,progress=None):
        value=self.run(experiment_id,progress=progress)
        if value['confirmation'] is not None:return value
        frozen=value['frozen'];source=self.repository.dataset(frozen['dataset_id']);start=frozen['split_index']
        # Seal the family before opening any confirmation observation. New tuning requires a new family and independent data.
        with self.repository.transaction() as conn:
            self.repository.lock_research(conn,economic_identity(source.instrument))
            raw=conn.scalar(select(families.c.payload).where(families.c.id==frozen['family_id']).with_for_update())
            window=confirmation_window(source,start)
            existing=claims(conn)
            for claim in existing:
                if not overlaps(window,claim) or claim['experiment_id']==experiment_id:continue
                if claim['family_id']!=frozen['family_id'] or utc(value['created_at'])>utc(claim['opened_at']):
                    raise ValueError('confirmation_already_opened_requires_new_independent_data')
            if not any(claim['experiment_id']==experiment_id for claim in existing):
                claim=window|dict(experiment_id=experiment_id,family_id=frozen['family_id'],opened_at=now().isoformat())
                conn.execute(insert(consumed_holdouts).values(id=identity(claim),payload=encode(claim)))
            family=json.loads(raw);family['sealed']=True
            conn.execute(update(families).where(families.c.id==frozen['family_id']).values(payload=encode(family)))
            value['holdout']['opened']=True;value['holdout']['opened_at']=now().isoformat();value['status']='CONFIRMATION_OPEN'
            conn.execute(update(experiments).where(experiments.c.id==experiment_id).values(payload=encode(value),status=value['status']))
        holdout=source.model_copy(update=dict(dataset_id=identity(dict(parent=source.dataset_id,range=[start,len(source.bars)])),bars=source.bars[start:]))
        value['confirmation']=run_replay(holdout,ReplayConfig.model_validate(frozen['config']),progress=progress)
        value['confirmation'].update(parent_dataset_id=source.dataset_id,partition='confirmation',
            learning='Frozen strategies only; no fitting or candidate selection on this partition.')
        value['holdout']['opened']=True;value['holdout']['opened_at']=now().isoformat();value['status']='CONFIRMED_HISTORICAL'
        self._store(value)
        return value
