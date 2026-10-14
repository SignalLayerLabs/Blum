"""Prospective call registration and bounded, market-separated evidence reads.

The registry proves what this deployment recorded, not external data correctness
or competitor superiority. It never upgrades legacy records into forward calls.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
import math
import random

from sqlalchemy import desc, func, select

from app.core.release import source_revision, source_content_hash
from app.models import AlphaCallRegistration, ForexDecision, ForexPosition, LiveForwardPaperTrade
from app.services.paper_forward_direction import is_forex_identity, normalize_side, paper_trade_evidence_is_eligible, validate_trade_plan
from app.services.persistence import database_persistence_status

WINDOW = 2000
METHODOLOGY = 'prospective-alpha-desk-v1'


def utc(value):
    if isinstance(value,str):
        try:
            value=datetime.fromisoformat(value.replace('Z','+00:00'))
        except ValueError:
            return None
    if isinstance(value,date) and not isinstance(value,datetime):
        value=datetime.combine(value,datetime.min.time())
    if not isinstance(value,datetime):
        return None
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def number(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)):
        return None
    return float(value) if math.isfinite(value) else None


def mapping(value):
    return value if isinstance(value,dict) else {}


def provider_name(value):
    return isinstance(value,str) and bool(value.strip())


def safe_json(value):
    if isinstance(value,dict): return {str(k):safe_json(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [safe_json(v) for v in value]
    if isinstance(value,(datetime,date)): return value.isoformat()
    if isinstance(value,float) and not math.isfinite(value): return {'invalid_number':str(value)}
    return value


def digest(value):
    return hashlib.sha256(json.dumps(safe_json(value),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def manifest(source):
    if isinstance(source,LiveForwardPaperTrade):
        return safe_json({'source_uid':'paper:'+source.trade_uid,'asset':source.ticker,
            'direction':source.side,'decision_at':source.decision_timestamp,
            'market':source.market,'asset_type':source.asset_type,'benchmark':source.benchmark_ticker,
            'expected_net_edge':source.net_expectancy_bps,
            'model':source.model_version_used,'inputs':source.frozen_decision_payload or {}})
    if isinstance(source,ForexDecision):
        return safe_json({'source_uid':'forex:'+source.decision_uid,'asset':source.pair,
            'direction':source.direction,'decision_at':source.decision_timestamp,
            'model':source.strategy_id,'inputs':source.input_snapshot or {},
            'proposal':source.proposal_json or {},'risk':source.risk_json or {}})
    raise ValueError('UNSUPPORTED_ALPHA_SOURCE')


class AlphaCallRegistry:
    def register(self,db,source,*,registered_at=None):
        db.flush()
        frozen=manifest(source)
        uid=frozen['source_uid']
        sha=digest(frozen)
        existing=db.scalar(select(AlphaCallRegistration).where(AlphaCallRegistration.source_uid==uid))
        if existing:
            if existing.manifest_sha256!=sha:
                raise ValueError('FROZEN_CALL_CHANGED')
            return existing
        now=utc(registered_at or datetime.now(timezone.utc))
        decision=utc(source.decision_timestamp)
        if decision is None or decision>now:
            raise ValueError('INVALID_REGISTRATION_TIME')
        if isinstance(source,LiveForwardPaperTrade) and (source.closed_at is not None or source.status in {'CLOSED','EXPIRED','INVALIDATED'}):
            raise ValueError('RETROSPECTIVE_REGISTRATION_FORBIDDEN')
        if isinstance(source,ForexDecision) and db.scalar(select(ForexPosition.id).where(
            ForexPosition.decision_id==source.id,ForexPosition.closed_at.is_not(None)).limit(1)):
            raise ValueError('RETROSPECTIVE_REGISTRATION_FORBIDDEN')
        forex=isinstance(source,ForexDecision) or is_forex_identity(ticker=source.ticker,market=source.market,asset_type=source.asset_type)
        record=AlphaCallRegistration(source_uid=uid,source_type='forex' if isinstance(source,ForexDecision) else 'paper',
            source_id=source.id,market='forex' if forex else 'equity',asset=frozen['asset'],decision_at=decision,
            registered_at=now,source_revision=source_revision(),source_content_hash=source_content_hash(),manifest_json=frozen,manifest_sha256=sha)
        db.add(record)
        db.flush()
        return record


def provenance(record):
    frozen=mapping(record.manifest_json)
    inputs=mapping(frozen.get('inputs'))
    decision=utc(record.decision_at)
    blockers=[]
    if not isinstance(frozen.get('inputs'),dict): blockers.append('INVALID_INPUT_SHAPE')
    if (utc(record.registered_at)-decision).total_seconds()>300:
        blockers.append('REGISTRATION_DELAY')
    if record.source_type=='forex':
        quote=mapping(inputs.get('quote'))
        stamp=utc(quote.get('timestamp'))
        provider=quote.get('source')
        bid,ask=number(quote.get('bid')),number(quote.get('ask'))
        if bid is None or ask is None or bid<=0 or ask<bid:
            blockers.append('INVALID_QUOTE')
        availability=[utc(inputs.get('as_of'))]
        frames=mapping(inputs.get('timeframes'))
        if not frames: blockers.append('MISSING_PROVENANCE')
        availability += [utc(frame.get('acquired_at')) for frame in frames.values() if isinstance(frame,dict)]
        limit=180
    else:
        context=mapping(inputs.get('price_context'))
        stamp=utc(context.get('market_timestamp') or context.get('latest_date'))
        provider=context.get('provider')
        availability=[utc(context.get('available_at'))]
        limit=180 if record.market=='forex' else 96*3600
        price=number(context.get('latest_price'))
        if price is None or price<=0: blockers.append('INVALID_QUOTE')
        quality=number(context.get('data_quality_score'))
        if quality is None or not 70<=quality<=100: blockers.append('LOW_DATA_QUALITY')
    if not provider_name(provider) or stamp is None or not availability or any(value is None for value in availability):
        blockers.append('MISSING_PROVENANCE')
    if stamp is not None and decision is not None:
        if stamp>decision: blockers.append('FUTURE_INPUT')
        elif (decision-stamp).total_seconds()>limit: blockers.append('STALE_AT_DECISION')
    if any(value is not None and value>decision for value in availability): blockers.append('FUTURE_INPUT')
    if record.source_type=='forex':
        for frame in frames.values():
            if not isinstance(frame,dict):
                blockers.append('MISSING_PROVENANCE')
                continue
            timestamp=utc(frame.get('market_timestamp'))
            if timestamp is None or not provider_name(frame.get('provider')): blockers.append('MISSING_PROVENANCE')
            elif timestamp>decision: blockers.append('FUTURE_INPUT')
            quality=number(frame.get('quality_score'))
            if quality is None or not 70<=quality<=100: blockers.append('LOW_DATA_QUALITY')
    return list(dict.fromkeys(blockers)),stamp,limit


def paired_interval(rows):
    groups=defaultdict(list)
    for row in rows:
        if number(row.get('excess')) is not None:
            groups[str(row['date'])].append(float(row['excess']))
    values=[v for group in groups.values() for v in group]
    result={'observations':len(values),'dates':len(groups),'assets':len({r['asset'] for r in rows}),
        'mean':sum(values)/len(values) if values else None,'lower_95':None,'upper_95':None,
        'positive_sample':False,'method':'closure-date cluster bootstrap; no multiple-testing correction'}
    if len(groups)<2: return result
    blocks=[(sum(v),len(v)) for v in groups.values()]
    rng=random.Random(3407)
    draws=[]
    for _ in range(800):
        selected=rng.choices(blocks,k=len(blocks))
        draws.append(sum(v for v,n in selected)/sum(n for v,n in selected))
    draws.sort()
    result['lower_95'],result['upper_95']=draws[19],draws[779]
    result['positive_sample']=len(values)>=100 and len(groups)>=30 and result['assets']>=3 and result['lower_95']>0
    return result


class AlphaDeskService:
    def snapshot(self,db,*,now=None):
        now=utc(now or datetime.now(timezone.utc))
        records=list(db.scalars(select(AlphaCallRegistration).order_by(desc(AlphaCallRegistration.registered_at),desc(AlphaCallRegistration.id)).limit(WINDOW)))
        paper_ids=[r.source_id for r in records if r.source_type=='paper']
        forex_ids=[r.source_id for r in records if r.source_type=='forex']
        papers={r.id:r for r in db.scalars(select(LiveForwardPaperTrade).where(LiveForwardPaperTrade.id.in_(paper_ids)))} if paper_ids else {}
        decisions={r.id:r for r in db.scalars(select(ForexDecision).where(ForexDecision.id.in_(forex_ids)))} if forex_ids else {}
        positions=defaultdict(list)
        if forex_ids:
            for row in db.scalars(select(ForexPosition).where(ForexPosition.decision_id.in_(forex_ids))): positions[row.decision_id].append(row)
        journal=[]
        for record in records:
            source=papers.get(record.source_id) if record.source_type=='paper' else decisions.get(record.source_id)
            rows=positions[record.source_id] if record.source_type=='forex' else []
            journal.append(self._call(record,source,rows,now))
        markets={key:self._market([r for r in journal if r['market']==key]) for key in ('equity','forex')}
        total=int(db.scalar(select(func.count(AlphaCallRegistration.id))) or 0)
        persistence=database_persistence_status()
        return {'status':'READY','methodology_version':METHODOLOGY,'generated_at':now.isoformat(),
            'registered_count':total,'window':{'limit':WINDOW,'evaluated':len(records),'truncated':total>WINDOW},
            'markets':markets,'journal':journal[:40],
            'durability':{'mode':persistence['mode'],
                'strict_no_reset_mode':persistence['strict_no_reset_mode'],
                'zero_loss_restart_guaranteed':False,
                'note':'Durability depends on the configured database and recovery policy; this read model does not certify zero-loss restarts.'},
            'policy':'Prospective registration only. Markets remain separate. Sample evidence has no production-promotion authority. Confidence is heuristic. Competitor superiority is unverified.'}

    def _call(self,record,source,positions,now):
        blockers,stamp,ttl=provenance(record)
        if utc(record.registered_at)>now: blockers.append('FUTURE_REGISTRATION')
        frozen=mapping(record.manifest_json)
        if digest(frozen)!=record.manifest_sha256: blockers.append('REGISTRY_INTEGRITY_FAILED')
        if source is None: blockers.append('SOURCE_MISSING')
        elif digest(manifest(source))!=record.manifest_sha256: blockers.append('SOURCE_CHANGED')
        position=positions[0] if len(positions)==1 else None
        if len(positions)>1: blockers.append('AMBIGUOUS_POSITION')
        trade=source if record.source_type=='paper' else position
        status=str(getattr(trade,'status',None) or getattr(source,'status','MISSING')).upper()
        closed_at=utc(getattr(trade,'closed_at',None))
        entry=number(getattr(trade,'entry_price',None))
        exit_price=number(getattr(trade,'exit_price',None))
        opened=utc(getattr(trade,'opened_at',None))
        side=normalize_side(frozen.get('direction'))
        inputs=mapping(frozen.get('inputs'))
        plan=mapping(inputs.get('trade_plan')) or mapping(frozen.get('proposal'))
        stop=number(plan.get('stop_price') or plan.get('stop_loss') or plan.get('invalidation_level') or plan.get('stop'))
        target=number(plan.get('target_1') or plan.get('target'))
        planned_entry=number(plan.get('entry_price') or plan.get('entry') or mapping(inputs.get('price_context')).get('latest_price'))
        try:
            validate_trade_plan(side,entry=planned_entry,stop=stop,targets=[target])
        except (ValueError,TypeError):
            blockers.append('INVALID_PLAN')
        net_r=number(getattr(trade,'r_multiple',None) if record.source_type=='paper' else getattr(trade,'realized_r',None))
        contract=mapping(getattr(trade,'contract_json',None)) if record.source_type=='forex' else {}
        notional=number(getattr(trade,'notional_value',None) if record.source_type=='paper' else contract.get('notional_value'))
        net=number(getattr(trade,'net_pnl_eur',None) if record.source_type=='paper' else getattr(trade,'net_pnl',None))
        gross=number(getattr(trade,'gross_pnl_eur',None) if record.source_type=='paper' else getattr(trade,'gross_pnl',None))
        cost_fields=('spread_cost','slippage_cost','commission_cost') if record.source_type=='paper' else ('spread_cost','slippage_cost','commission','swap_accrued')
        parts=[number(getattr(trade,k,None)) for k in cost_fields]
        costs=(sum(parts) if record.source_type=='paper' else sum(parts[:3])-parts[3]) if all(v is not None for v in parts) else None
        stored_cost=number(getattr(trade,'costs_paid',None)) if record.source_type=='paper' else costs
        benchmark=number(getattr(trade,'benchmark_return_same_period',None)) if record.source_type=='paper' else None
        outcome='PENDING'
        realized=False
        paired=None
        net_return=None
        if status=='CLOSED':
            outcome='CLOSED'
            quantity=number(getattr(trade,'position_size',None) if record.source_type=='paper' else getattr(trade,'quantity_lots',None))
            if quantity is None or quantity<=0: blockers.append('MISSING_FILL')
            if closed_at is None or closed_at>now or opened is None or opened<utc(record.decision_at) or closed_at<=opened or closed_at<=utc(record.registered_at): blockers.append('NON_CAUSAL_OUTCOME')
            if entry is None or exit_price is None or entry<=0 or exit_price<=0 or side is None or net is None or gross is None or costs is None or stored_cost is None:
                blockers.append('INVALID_ACCOUNTING')
            elif any(value<0 for value in parts[:3]): blockers.append('INVALID_ACCOUNTING')
            elif not math.isclose(gross-net,costs,rel_tol=1e-6,abs_tol=1e-5) or not math.isclose(costs,stored_cost,rel_tol=1e-6,abs_tol=1e-5): blockers.append('COST_RECONCILIATION_FAILED')
            if record.source_type=='paper' and source is not None and not paper_trade_evidence_is_eligible(source): blockers.append('INVALID_ACCOUNTING')
            realized=not blockers
            if realized and notional is not None and notional>0:
                holding=(exit_price/entry-1)*(1 if side=='LONG' else -1)
                if math.isclose(gross,holding*notional,rel_tol=1e-4,abs_tol=1e-5):
                    net_return=net/notional*100
                    paired=net_return-benchmark if benchmark is not None else None
                else: blockers.append('NOTIONAL_RETURN_MISMATCH')
            if realized and paired is None: blockers.append('MISSING_PAIRED_BENCHMARK')
        elif status in {'EXPIRED','INVALIDATED','REJECTED','SKIPPED','BLOCKED','NO_TRADE'}:
            outcome='NO_FILL'
        else:
            if stamp is not None and (now-stamp).total_seconds()>ttl: blockers.append('QUOTE_STALE_NOW')
        expected=number(frozen.get('expected_net_edge')) if record.source_type=='paper' else number(mapping(frozen.get('proposal')).get('expected_net_pips'))
        if outcome=='PENDING' and expected is None: blockers.append('NO_STORED_EDGE_ESTIMATE')
        return {'source_uid':record.source_uid,'market':record.market,'asset':record.asset,
            'status':status,'outcome_status':outcome,'direction':side,'decision_at':record.decision_at.isoformat(),
            'registered_at':record.registered_at.isoformat(),'source_revision':record.source_revision,
            'source_content_hash':record.source_content_hash,
            'input_sha256':record.manifest_sha256,'provider':mapping(inputs.get('quote')).get('source') if record.source_type=='forex' else mapping(inputs.get('price_context')).get('provider'),
            'quote_at':stamp.isoformat() if stamp else None,'quote_age_seconds':max(0,(now-stamp).total_seconds()) if stamp else None,
            'entry':entry,'stop':stop,'target':target,'model':frozen.get('model'),
            'confidence':number((mapping(frozen.get('proposal')) or inputs).get('confidence')),
            'confidence_semantics':'HEURISTIC_NOT_PROBABILITY','expected_net_edge':expected,
            'edge_units':'bps' if record.source_type=='paper' else 'pips',
            'qualified_closed':realized,'net_pnl':net if realized else None,'net_r':net_r if realized else None,
            'net_return_percent':net_return,'paired_excess_percent':paired,'closed_at':closed_at.isoformat() if closed_at else None,
            'active_eligible':outcome=='PENDING' and not blockers and expected is not None and expected>0,
            'blockers':list(dict.fromkeys(blockers))}

    @staticmethod
    def _market(rows):
        closed=[r for r in rows if r['qualified_closed']]
        paired=[{'asset':r['asset'],'date':r['closed_at'][:10],'excess':r['paired_excess_percent']} for r in closed if r['paired_excess_percent'] is not None]
        interval=paired_interval(paired)
        active=sorted([r for r in rows if r['active_eligible']],key=lambda r:r['expected_net_edge'],reverse=True)[:10]
        exclusions=Counter(b for r in rows for b in r['blockers'])
        returns=[r['net_return_percent'] for r in closed if r['net_return_percent'] is not None]
        return {'registered':len(rows),'qualified_closed':len(closed),'paired_sample':len(paired),
            'observed_net_pnl':sum(r['net_pnl'] for r in closed) if closed else None,
            'mean_net_return_percent':sum(returns)/len(returns) if returns else None,
            'mean_paired_excess_percent':interval['mean'],'paired_interval':interval,
            'verdict':'POSITIVE_PAIRED_SAMPLE' if interval['positive_sample'] else 'INSUFFICIENT_EVIDENCE',
            'active_calls':active,'exclusions':dict(exclusions),'closed_coverage':{'assets':interval['assets'],'dates':interval['dates']}}
