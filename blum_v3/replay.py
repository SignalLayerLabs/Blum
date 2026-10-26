"""Causal historical replay through the same journal used by paper accounts."""
from datetime import timedelta
from decimal import Decimal as D, ROUND_FLOOR
from typing import Literal

from pydantic import model_validator

from .domain import AcceptedDataset, Contract, RiskProfile, decimal, identity
from .execution import simulate_order
from .orders import ExecutionProfile
from .portfolio import PortfolioService, TERMINAL
from .storage import Repository
from .strategies import target_weight


class ReplayConfig(Contract):
    strategy: Literal['trend','hold','cash'] = 'trend'
    lookback: int = 20
    capital: D = D('10000')
    weight: D = D('0.19')
    execution: ExecutionProfile = ExecutionProfile()
    risk: RiskProfile = RiskProfile()
    benchmark: Literal['passive_allocation','cash_zero_interest_reference'] | None = None

    @model_validator(mode='after')
    def valid(self):
        if not 1<=self.lookback<=500 or not self.capital.is_finite() or self.capital<=0 or not self.weight.is_finite() or not 0<=self.weight<=self.risk.instrument_limit:
            raise ValueError('invalid_replay_configuration')
        return self


def _metrics(curve,capital):
    if not curve or any(row['nav'] is None for row in curve):
        return dict(return_percent=None,max_drawdown_percent=None,path_status='INCOMPLETE')
    navs=[decimal(row['nav']) for row in curve]
    peak=decimal(capital);dd=D(0)
    for nav in navs:
        peak=max(peak,nav);dd=min(dd,nav/peak-1)
    return dict(return_percent=float((navs[-1]/capital-1)*100),max_drawdown_percent=float(dd*100),path_status='COMPLETE')


def _run_lane(dataset: AcceptedDataset, config: ReplayConfig, *, strategy: str,progress=None):
    if len(dataset.bars)<2: raise ValueError('at_least_two_accepted_bars_required')
    clock=[dataset.bars[0].available_at]
    repository=Repository('sqlite:///:memory:')
    service=PortfolioService(repository,clock=lambda:clock[0])
    account=service.open_account(name='Historical research',market=dataset.instrument.market,currency=dataset.instrument.quote_currency,
        cash=config.capital,key='epoch',risk=config.risk.model_dump(mode='json'))['id']
    curve=[];fills=[];decisions=[];exclusions={};waiting={};exposure=[]
    def excluded(reason): exclusions[reason]=exclusions.get(reason,0)+1
    for index,bar in enumerate(dataset.bars):
        if index%32==0 and progress is not None and progress() is False:
            repository.engine.dispose()
            raise InterruptedError('job_no_longer_owned')
        clock[0]=bar.available_at
        state=service.snapshot(account)
        if index>0 and config.execution.financing_bps_per_day is not None:
            held=state['positions'].get(dataset.instrument.symbol)
            if held and decimal(held['quantity'])!=0:
                elapsed=decimal((bar.available_at-dataset.bars[index-1].available_at).total_seconds())/D(86400)
                amount=abs(decimal(held['quantity']))*decimal(held['mark']['price'])*config.execution.financing_bps_per_day*elapsed/D(10000)
                service.apply_financing(account,amount=amount,at=bar.available_at,source_ref=config.execution.source,key=f'financing:{index}')
        for order in list(state['orders'].values()):
            if order['status'] in TERMINAL: continue
            step=waiting.get(order['id'],0)
            result=simulate_order(order,bar,config.execution,eligible_index=step)
            waiting[order['id']]=step+1
            if result.status=='EXPIRED':
                service.cancel_order(account,order['id'],key=f'expire:{index}:{order["id"]}',expired=True)
            elif result.status=='TRIGGERED':
                service.trigger_order(account,order['id'],at=bar.available_at,source_ref=dataset.dataset_id,key=f'trigger:{index}:{order["id"]}')
            elif result.quantity:
                try:
                    service.apply_fill(account,order['id'],quantity=result.quantity,price=result.price,fee=result.fee,at=result.at,fill_id=f'{index}:{order["id"]}')
                    fills.append(dict(index=index,at=result.at.isoformat(),decision_at=order['decision_at'],side=order['side'],quantity=str(result.quantity),
                        price=str(result.price),fee=str(result.fee),liquidity_basis=result.liquidity_basis))
                except ValueError as error:
                    excluded(str(error))
                    service.cancel_order(account,order['id'],key=f'failed:{index}:{order["id"]}')
            else: excluded(result.reason)
        service.mark(account,{dataset.instrument.symbol:dict(price=str(bar.close),at=bar.available_at,source_ref=dataset.dataset_id)},key=f'mark:{index}')
        state=service.snapshot(account);nav=None if state['nav'] is None else decimal(state['nav'])
        curve.append(dict(at=bar.available_at.isoformat(),nav=state['nav'],cash=state['cash']))
        quantity=decimal(state['positions'].get(dataset.instrument.symbol,{}).get('quantity','0'))
        exposure.append(float(abs(quantity)*bar.close/nav) if nav and nav>0 else None)
        weight=target_weight(dataset.bars[:index+1],market=dataset.instrument.market,strategy=strategy,lookback=config.lookback,weight=config.weight)
        decisions.append(dict(at=bar.available_at.isoformat(),target_weight=str(weight),status=state['status']))
        if index==len(dataset.bars)-1 or nav is None or any(o['status'] not in TERMINAL for o in state['orders'].values()): continue
        target=(abs(weight)*nav/bar.close/dataset.instrument.lot_size).to_integral_value(rounding=ROUND_FLOOR)*dataset.instrument.lot_size*(1 if weight>=0 else -1)
        if quantity*target<0: target=D(0) # Close before reversing on a later decision.
        delta=target-quantity
        if delta==0: continue
        # Do not churn one lot around a stable target. An exit is never suppressed.
        if target!=0 and quantity!=0 and abs(delta)*bar.close<nav*D('0.02'): continue
        try:
            ref=(bar.close/dataset.instrument.tick_size).to_integral_value(rounding=ROUND_FLOOR)*dataset.instrument.tick_size
            service.submit_order(account,instrument=dataset.instrument,side='BUY' if delta>0 else 'SELL',quantity=abs(delta),reference_price=ref,
                decision_at=bar.available_at,reference_at=bar.available_at,source_ref=dataset.dataset_id,key=f'decision:{index}',
                expires_at=bar.available_at+timedelta(days=7),reduce_only=quantity*delta<0)
        except ValueError as error: excluded(str(error))
    final=service.snapshot(account)
    result=dict(curve=curve,fills=fills,decisions=decisions,exclusions=exclusions,metrics=_metrics(curve,config.capital),
        fees=final['fees'],final_cash=final['cash'],mean_gross_exposure=sum(v for v in exposure if v is not None)/max(1,sum(v is not None for v in exposure)),
        open_quantity=str(quantity),initial_capital=str(config.capital))
    # Liquidation is an estimate subject to terminal capacity, not a recorded fill.
    terminal=dataset.bars[-1];cap=(terminal.volume or D(0))*config.execution.participation if dataset.instrument.market=='equity' else config.execution.fx_capacity
    if final['nav'] is not None and abs(quantity)<=cap:
        costs=abs(quantity)*terminal.close*(config.execution.spread_bps/2+config.execution.slippage_bps+config.execution.commission_bps)/D(10000)
        result['estimated_liquidation_nav']=str(decimal(final['nav'])-costs)
    else: result['estimated_liquidation_nav']=None
    repository.engine.dispose()
    return result


def run_replay(dataset: AcceptedDataset, config: ReplayConfig, *, stress: bool=True,progress=None) -> dict:
    main=_run_lane(dataset,config,strategy=config.strategy,progress=progress)
    benchmark_name=config.benchmark or ('passive_allocation' if dataset.instrument.market=='equity' else 'cash_zero_interest_reference')
    baseline=_run_lane(dataset,config,strategy='hold' if benchmark_name=='passive_allocation' else 'cash',progress=progress)
    main.update(dataset_id=dataset.dataset_id,market=dataset.instrument.market,currency=dataset.instrument.quote_currency,
        instrument=dataset.instrument.model_dump(mode='json'),config=config.model_dump(mode='json'),
        evidence_tier='MODELED_PAPER',scope='Historical price-return scenario; not prospective or broker execution evidence.',
        benchmark=dict(name=benchmark_name,metrics=baseline['metrics'],curve=baseline['curve'],mean_gross_exposure=baseline['mean_gross_exposure'],
            estimated_liquidation_nav=baseline['estimated_liquidation_nav']),
        qualification=dict(status='EXPERIMENTAL',reasons=['historical_scenario','calendar_weekday_only','financing_not_observed','no_prospective_qualified_outcomes']),
        cost_coverage=dict(execution='modeled',financing='unavailable' if config.execution.financing_bps_per_day is None else 'declared',dividends='excluded_price_returns'),
        stress={})
    a,b=main['estimated_liquidation_nav'],baseline['estimated_liquidation_nav']
    main['metrics']['benchmark_excess_percent']=float((decimal(a)-decimal(b))/config.capital*100) if a is not None and b is not None else None
    if stress:
        profile=config.execution
        doubled=profile.model_copy(update=dict(spread_bps=profile.spread_bps*2,slippage_bps=profile.slippage_bps*2,commission_bps=profile.commission_bps*2,minimum_commission=profile.minimum_commission*2))
        main['stress']['2x_costs']=_run_lane(dataset,config.model_copy(update={'execution':doubled}),strategy=config.strategy,progress=progress)['metrics']
        delayed=profile.model_copy(update={'latency_bars':profile.latency_bars+1})
        main['stress']['extra_interval']=_run_lane(dataset,config.model_copy(update={'execution':delayed}),strategy=config.strategy,progress=progress)['metrics']
    main['fingerprint']=identity(dict(dataset_id=dataset.dataset_id,config=config,curve=main['curve'],fills=main['fills'],benchmark=main['benchmark']))
    return main
