"""Prospective paper stepping consumes newly observable bars and frozen decisions."""
from datetime import timedelta
from decimal import Decimal as D,ROUND_FLOOR
import json
from uuid import uuid4
from sqlalchemy import select,insert,update

from .domain import Instrument,decimal,encode,identity,now,utc
from .execution import simulate_order
from .orders import ExecutionProfile
from .portfolio import PortfolioService,TERMINAL
from .storage import Repository,subscriptions
from .research import ResearchService
from .replay import ReplayConfig
from .strategies import target_weight
from .conversion import resolve_conversion
from .orders import conversion_rate


class PaperService:
    def __init__(self,repository: Repository,*,clock=now):
        self.repository=repository;self.clock=clock;self.portfolios=PortfolioService(repository,clock=clock)

    def step(self,account_id,dataset_id,*,profile: dict | None=None,progress=None):
        source=self.repository.dataset(dataset_id);settings=ExecutionProfile.model_validate(profile or {})
        state=self.portfolios.snapshot(account_id)
        if state['market']!=source.instrument.market: raise ValueError('market_family_mismatch')
        fills=0;exclusions={}
        for bar in source.bars:
            if progress is not None and progress() is False:raise InterruptedError('job_no_longer_owned')
            if bar.available_at>self.clock() or bar.available_at<=utc(state['epoch']): continue
            state=self.portfolios.snapshot(account_id)
            relevant=[o for o in state['orders'].values() if o['status'] not in TERMINAL and o['instrument']['symbol']==source.instrument.symbol and bar.timestamp>utc(o['decision_at'])]
            bar_id=identity(dict(instrument=source.instrument,bar=bar))
            for order in relevant:
                fill_id=identity(dict(order=order['id'],bar=bar_id))
                if fill_id in order.get('fill_ids',[]):continue
                effective=utc(order.get('triggered_at',order['decision_at']))
                eligible_index=sum(b.timestamp>effective for b in source.bars if b.available_at<bar.available_at)
                outcome=simulate_order(order,bar,settings,eligible_index=eligible_index)
                if outcome.status=='EXPIRED': self.portfolios.cancel_order(account_id,order['id'],key='expire:'+order['id']+bar_id,expired=True)
                elif outcome.status=='TRIGGERED':self.portfolios.trigger_order(account_id,order['id'],at=bar.available_at,source_ref=bar_id,key='trigger:'+order['id']+bar_id)
                elif outcome.quantity:
                    try:
                        fx=resolve_conversion(self.repository,source.instrument,state['currency'],outcome.at)
                        self.portfolios.apply_fill(account_id,order['id'],quantity=outcome.quantity,price=outcome.price,fee=outcome.fee,at=outcome.at,
                            fill_id=fill_id,fx=fx)
                        fills+=1
                    except ValueError as error: exclusions[str(error)]=exclusions.get(str(error),0)+1
                else: exclusions[outcome.reason]=exclusions.get(outcome.reason,0)+1
            current=self.portfolios.snapshot(account_id)
            position=current['positions'].get(source.instrument.symbol)
            if position and (not position.get('mark') or utc(position['mark']['at'])<=bar.available_at):
                try:fx=resolve_conversion(self.repository,source.instrument,current['currency'],bar.available_at)
                except ValueError:fx=None
                self.portfolios.mark(account_id,{source.instrument.symbol:dict(price=str(bar.close),at=bar.available_at,source_ref=bar_id,fx=fx)},key='paper-mark:'+bar_id)
        return dict(account_id=account_id,dataset_id=dataset_id,fills=fills,exclusions=exclusions,
            scope='MODELED_PAPER; future execution requires new observations after the frozen decision.',
            portfolio=self.portfolios.snapshot(account_id))

    def subscribe(self,account_id,experiment_id,*,key):
        experiment=ResearchService(self.repository).get(experiment_id)
        if experiment['report'] is None: raise ValueError('completed_research_experiment_required')
        state=self.portfolios.snapshot(account_id)
        source=self.repository.dataset(experiment['frozen']['dataset_id'])
        if state['market']!=source.instrument.market: raise ValueError('market_family_mismatch')
        payload=dict(account_id=account_id,experiment_id=experiment_id)
        with self.repository.transaction(account_id) as conn:
            previous=self.repository.replay_command(conn,'paper-subscriptions',key,payload)
            if previous is not None:return previous
            value=dict(id=uuid4().hex,**payload,instrument=source.instrument.model_dump(mode='json'),
                dataset_id=source.dataset_id,config=experiment['frozen']['config'],created_at=self.clock().isoformat(),
                last_decision_at=None,status='ACTIVE',qualification='EXPERIMENTAL_MODELED_PAPER')
            conn.execute(insert(subscriptions).values(id=value['id'],payload=encode(value)))
            self.repository.remember(conn,'paper-subscriptions',key,payload,value)
            return value

    def list(self):
        with self.repository.engine.connect() as conn: return [json.loads(row) for row in conn.scalars(select(subscriptions.c.payload))]

    def cycle(self,*,progress=None):
        results=[];available=self.repository.list_datasets()
        for sub in self.list():
            if sub['status']!='ACTIVE':continue
            candidates=[d for d in available if d['instrument']==sub['instrument'] and d['last']]
            if not candidates:continue
            dataset_id=max(candidates,key=lambda d:d['last'])['dataset_id'];source=self.repository.dataset(dataset_id)
            config=ReplayConfig.model_validate(sub['config'])
            result=self.step(sub['account_id'],dataset_id,profile=config.execution.model_dump(mode='json'),progress=progress)
            visible=tuple(b for b in source.bars if b.available_at<=self.clock())
            if not visible:continue
            bar=visible[-1]
            if bar.available_at<=utc(sub['created_at']) or (sub['last_decision_at'] and bar.available_at<=utc(sub['last_decision_at'])):
                results.append(result);continue
            account=self.portfolios.snapshot(sub['account_id']);nav=account['nav']
            if nav is not None and not any(o['status'] not in TERMINAL for o in account['orders'].values()):
                target=target_weight(visible,market=source.instrument.market,strategy=config.strategy,lookback=config.lookback,weight=config.weight)
                qty=decimal(account['positions'].get(source.instrument.symbol,{}).get('quantity','0'))
                try:
                    fx=resolve_conversion(self.repository,source.instrument,account['currency'],self.clock())
                    rate=conversion_rate(source.instrument,account['currency'],fx,self.clock())
                except ValueError:
                    result['decision_blocker']='missing_conversion';results.append(result);continue
                desired=(abs(target)*decimal(nav)/(bar.close*rate)/source.instrument.lot_size).to_integral_value(rounding=ROUND_FLOOR)*source.instrument.lot_size*(1 if target>=0 else -1)
                if qty*desired<0:desired=D(0)
                delta=desired-qty
                if delta:
                    try:
                        self.portfolios.submit_order(sub['account_id'],instrument=source.instrument,side='BUY' if delta>0 else 'SELL',quantity=abs(delta),
                            reference_price=(bar.close/source.instrument.tick_size).to_integral_value(rounding=ROUND_FLOOR)*source.instrument.tick_size,
                            decision_at=self.clock(),reference_at=bar.available_at,source_ref=dataset_id,key='strategy:'+identity(dict(subscription=sub['id'],bar=bar)),
                            reduce_only=qty*delta<0,expires_at=self.clock()+timedelta(days=7),fx=fx)
                    except ValueError as error:result['decision_blocker']=str(error)
            sub.update(last_decision_at=bar.available_at.isoformat(),dataset_id=dataset_id)
            with self.repository.transaction() as conn:conn.execute(update(subscriptions).where(subscriptions.c.id==sub['id']).values(payload=encode(sub)))
            results.append(result)
        return results
