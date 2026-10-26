"""Transactional paper portfolios. The accepted journal and projection commit together."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal as D
import json
from typing import Callable
from uuid import uuid4

from sqlalchemy import insert, select, update

from .domain import Instrument, RiskProfile, decimal, encode, identity, now, utc
from .orders import conversion_rate, aligned
from .storage import Repository, accounts, events

TERMINAL = {'FILLED', 'CANCELED', 'EXPIRED', 'REJECTED'}
MONEY_QUANTUM=D('0.00000001')


def reserved(state: dict) -> D:
    return sum((decimal(o['reserved']) for o in state['orders'].values() if o['status'] not in TERMINAL), D(0))


def value_portfolio(state: dict, as_of: datetime) -> D | None:
    value = decimal(state['cash'])
    for position in state['positions'].values():
        quantity = decimal(position['quantity'])
        if quantity == 0:
            continue
        mark = position.get('mark')
        if not mark:
            return None
        age = (as_of - utc(mark['at'])).total_seconds()
        if age < 0 or age > 3*86400:
            return None
        instrument = Instrument.model_validate(position['instrument'])
        try:
            rate = conversion_rate(instrument, state['currency'], mark.get('fx'), as_of)
        except ValueError:
            return None
        value += quantity * decimal(mark['price']) * rate
    return value


class PortfolioService:
    def __init__(self, repository: Repository, *, clock: Callable[[], datetime] = now):
        self.repository = repository
        self.clock = clock

    def open_account(self, *, name: str, market: str, currency: str, cash,
                     key: str, risk: dict | None = None, opened_at=None) -> dict:
        amount = decimal(cash)
        if amount <= 0 or amount > D('1000000000000'):
            raise ValueError('positive_opening_cash_required')
        if market not in {'equity','forex'} or not currency.isalpha() or len(currency) != 3 or not name.strip():
            raise ValueError('invalid_account')
        profile = RiskProfile.model_validate(risk or {})
        timestamp = utc(opened_at) if opened_at else utc(self.clock())
        if timestamp > self.clock():
            raise ValueError('future_epoch')
        payload = dict(name=name.strip(),market=market,currency=currency.upper(),cash=amount,risk=profile)
        if opened_at is not None:
            payload['opened_at'] = timestamp
        with self.repository.transaction() as conn:
            replay = self.repository.replay_command(conn,'accounts',key,payload)
            if replay is not None: return replay
            state = dict(id=uuid4().hex,name=name.strip(),market=market,currency=currency.upper(),
                epoch=timestamp.isoformat(),cash=str(amount),opening_cash=str(amount),risk=profile.model_dump(mode='json'),
                positions={},orders={},fees='0',realized_pnl='0',high_water=str(amount),day_open_nav=str(amount),
                day=timestamp.date().isoformat(),status='READY',version=0,last_event='',marks=[])
            conn.execute(insert(accounts).values(id=state['id'],payload=encode(state),version=0))
            self._persist(conn,state,'ACCOUNT_OPENED',payload,[dict(book='cash',amount=str(amount),currency=state['currency']),dict(book='capital',amount=str(-amount),currency=state['currency'])])
            result = json.loads(encode(state))
            self.repository.remember(conn,'accounts',key,payload,result)
            return result

    def _state(self, conn, account_id) -> dict:
        raw=conn.scalar(select(accounts.c.payload).where(accounts.c.id==account_id))
        if raw is None: raise KeyError('account_not_found')
        return json.loads(raw)

    def _persist(self, conn, state, kind, payload, postings=()):
        for currency in {p['currency'] for p in postings}:
            if sum((decimal(p['amount']) for p in postings if p['currency']==currency),D(0)) != 0:
                raise ValueError('unbalanced_journal')
        state['version'] += 1
        event=dict(account_id=state['id'],sequence=state['version'],kind=kind,
            at=self.clock().isoformat(),payload=payload,postings=list(postings),previous=state['last_event'])
        event['id']=identity(event)
        state['last_event']=event['id']
        conn.execute(insert(events).values(id=event['id'],account_id=state['id'],sequence=state['version'],payload=encode(event)))
        conn.execute(update(accounts).where(accounts.c.id==state['id']).values(payload=encode(state),version=state['version']))

    def _change(self, account_id, key, payload, kind, operation,*,fingerprint_payload=None):
        command=payload if fingerprint_payload is None else fingerprint_payload
        with self.repository.transaction(account_id) as conn:
            replay=self.repository.replay_command(conn,account_id,key,command)
            if replay is not None: return replay
            state=self._state(conn,account_id)
            result,postings=operation(state)
            event_payload=(dict(payload)|{'reason':result['reason']}) if kind=='ORDER_REJECTED' else payload
            self._persist(conn,state,kind,event_payload,postings)
            result=json.loads(encode(result))
            self.repository.remember(conn,account_id,key,command,result)
            return result

    def replay_submission(self,account_id,key,payload):
        with self.repository.engine.connect() as conn:result=self.repository.replay_command(conn,account_id,key,payload)
        if result is not None and result.get('status')=='REJECTED':raise ValueError(result['reason'])
        return result

    def submit_order(self, account_id: str, *, instrument: Instrument, side: str, quantity,
                     reference_price, decision_at, key: str, reference_at, source_ref: str,
                     kind='MARKET', limit_price=None, stop_price=None, expires_at=None,
                     reduce_only=False, fx=None,request_payload=None) -> dict:
        if request_payload is not None:
            previous=self.replay_submission(account_id,key,request_payload)
            if previous is not None:return previous
        qty,price=decimal(quantity),decimal(reference_price)
        decision,observed=utc(decision_at),utc(reference_at)
        if qty<=0: raise ValueError('positive_quantity_required')
        if price<=0: raise ValueError('positive_price_required')
        if decision>self.clock(): raise ValueError('future_decision')
        age=(decision-observed).total_seconds()
        if age<0: raise ValueError('future_reference')
        if age>3*86400: raise ValueError('stale_reference')
        if not source_ref: raise ValueError('source_reference_required')
        if not aligned(qty,instrument.lot_size): raise ValueError('quantity_increment')
        if not aligned(price,instrument.tick_size): raise ValueError('price_increment')
        if side not in {'BUY','SELL'} or kind not in {'MARKET','LIMIT','STOP','STOP_LIMIT'}:
            raise ValueError('invalid_order_type')
        for value in [limit_price,stop_price]:
            if value is not None and (decimal(value)<=0 or not aligned(decimal(value),instrument.tick_size)):
                raise ValueError('invalid_order_price')
        if kind in {'LIMIT','STOP_LIMIT'} and limit_price is None: raise ValueError('limit_price_required')
        if kind in {'STOP','STOP_LIMIT'} and stop_price is None: raise ValueError('stop_price_required')
        expiry=utc(expires_at) if expires_at else None
        if expiry and expiry<=decision: raise ValueError('invalid_expiry')
        payload=dict(instrument=instrument,side=side,quantity=qty,reference_price=price,decision_at=decision,
            reference_at=observed,source_ref=source_ref,kind=kind,limit_price=limit_price,stop_price=stop_price,
            expires_at=expiry,reduce_only=reduce_only,fx=fx)
        def submit(state):
            if state['market']!=instrument.market: raise ValueError('market_family_mismatch')
            if decision<utc(state['epoch']): raise ValueError('decision_before_account_epoch')
            rate=conversion_rate(instrument,state['currency'],fx,decision)
            nav=value_portfolio(state,decision)
            position=state['positions'].get(instrument.symbol)
            if position is not None and Instrument.model_validate(position['instrument'])!=instrument:
                raise ValueError('instrument_contract_conflict')
            if any(o['status'] not in TERMINAL and o['instrument']['symbol']==instrument.symbol and Instrument.model_validate(o['instrument'])!=instrument for o in state['orders'].values()):
                raise ValueError('instrument_contract_conflict')
            current=decimal(position['quantity']) if position else D(0)
            delta=qty if side=='BUY' else -qty
            reducing=current*delta<0 and qty<=abs(current)
            if not reducing and (nav is None or nav<=0):raise ValueError('unavailable_nav')
            if reduce_only and not reducing: raise ValueError('reduce_only_would_increase_risk')
            pending_reduction=sum((decimal(o['remaining']) for o in state['orders'].values()
                if o['status'] not in TERMINAL and o['instrument']['symbol']==instrument.symbol and o['side']==side),D(0))
            if reducing and qty+pending_reduction>abs(current): raise ValueError('quantity_already_reserved_for_exit')
            if instrument.market=='equity' and current+delta<0: raise ValueError('equity_short_disabled')
            risk=RiskProfile.model_validate(state['risk'])
            if not reducing:
                if state['status']!='READY': raise ValueError('account_not_open_for_risk')
                high=decimal(state['high_water']);day=decimal(state['day_open_nav'])
                if nav<high*(1-risk.drawdown_limit) or nav<day*(1-risk.daily_loss_limit): raise ValueError('loss_limit')
                exposure=qty*price*rate
                pending=[o for o in state['orders'].values() if o['status'] not in TERMINAL and not o['reduce_only']]
                same=sum((decimal(o['remaining'])*decimal(o['reference_price'])*decimal(o['conversion_rate']) for o in pending if o['instrument']['symbol']==instrument.symbol),D(0))
                if abs(current)*price*rate+same+exposure>nav*risk.instrument_limit: raise ValueError('instrument_limit')
                gross=sum((abs(decimal(p['quantity']))*decimal(p['mark']['price'])*conversion_rate(Instrument.model_validate(p['instrument']),state['currency'],p['mark'].get('fx'),decision)
                    for p in state['positions'].values() if decimal(p['quantity'])!=0),D(0))
                pending_gross=sum((decimal(o['remaining'])*decimal(o['reference_price'])*decimal(o['conversion_rate']) for o in pending),D(0))
                if gross+pending_gross+exposure>nav*risk.gross_limit: raise ValueError('gross_limit')
            reserve=D(0) if reducing else qty*price*rate*D('1.02')
            if reserve>decimal(state['cash'])-reserved(state): raise ValueError('insufficient_available_cash')
            order=dict(id=uuid4().hex,account_id=account_id,instrument=instrument.model_dump(mode='json'),side=side,
                quantity=str(qty),remaining=str(qty),filled='0',reference_price=str(price),decision_at=decision.isoformat(),
                reference_at=observed.isoformat(),source_ref=source_ref,kind=kind,limit_price=None if limit_price is None else str(limit_price),
                stop_price=None if stop_price is None else str(stop_price),expires_at=expiry.isoformat() if expiry else None,
                reduce_only=bool(reducing),conversion_rate=str(rate),fx=fx,status='ACCEPTED',reserved=str(reserve))
            state['orders'][order['id']]=order
            return order,[]
        try:result=self._change(account_id,key,payload,'ORDER_ACCEPTED',submit,fingerprint_payload=request_payload)
        except ValueError as error:
            reason=str(error)
            if reason not in {'market_family_mismatch','decision_before_account_epoch','missing_conversion','stale_or_future_conversion','unavailable_nav',
                'reduce_only_would_increase_risk','quantity_already_reserved_for_exit','equity_short_disabled','account_not_open_for_risk','loss_limit','instrument_limit','gross_limit','insufficient_available_cash','instrument_contract_conflict'}:raise
            def reject(state):
                denied=json.loads(encode(payload))|dict(id=uuid4().hex,account_id=account_id,status='REJECTED',reason=reason,
                    reserved='0',remaining=str(qty),filled='0',conversion_rate='0')
                state['orders'][denied['id']]=denied
                return denied,[]
            self._change(account_id,key,payload,'ORDER_REJECTED',reject,fingerprint_payload=request_payload)
            raise
        if result['status']=='REJECTED':raise ValueError(result['reason'])
        return result

    def cancel_order(self, account_id, order_id, *, key, expired=False):
        def cancel(state):
            if order_id not in state['orders']: raise KeyError('order_not_found')
            order=state['orders'][order_id]
            if order['status'] not in TERMINAL:
                order['status']='EXPIRED' if expired else 'CANCELED';order['reserved']='0'
            return order,[]
        return self._change(account_id,key,dict(order_id=order_id,expired=expired),'ORDER_CANCELED',cancel)

    def apply_fill(self, account_id, order_id, *, quantity,price,fee,at,fill_id,fx=None,liquidity_key=None,capacity=None):
        qty,px,cost=decimal(quantity),decimal(price),decimal(fee); timestamp=utc(at)
        if qty<=0 or px<=0 or cost<0: raise ValueError('invalid_fill')
        payload=dict(order_id=order_id,quantity=qty,price=px,fee=cost,at=timestamp,fx=fx,liquidity_key=liquidity_key,capacity=capacity)
        def fill(state):
            if order_id not in state['orders']: raise KeyError('order_not_found')
            order=state['orders'][order_id]
            if order['status'] in TERMINAL: raise ValueError('order_terminal')
            if timestamp<=utc(order['decision_at']) or timestamp>self.clock(): raise ValueError('invalid_execution_clock')
            if order['expires_at'] and timestamp>utc(order['expires_at']): raise ValueError('order_expired')
            remaining=decimal(order['remaining'])
            if qty>remaining: raise ValueError('fill_exceeds_remaining_quantity')
            if liquidity_key is not None:
                if capacity is None or decimal(capacity)<0:raise ValueError('invalid_observation_capacity')
                usage=state.setdefault('liquidity_usage',{}).get(liquidity_key,dict(quantity='0',capacity=str(capacity)))
                if decimal(usage['capacity'])!=decimal(capacity):raise ValueError('observation_capacity_profile_changed')
                if decimal(usage['quantity'])+qty>decimal(capacity):raise ValueError('observation_capacity_exhausted')
                state['liquidity_usage'][liquidity_key]=dict(quantity=str(decimal(usage['quantity'])+qty),capacity=str(capacity))
            instrument=Instrument.model_validate(order['instrument'])
            if not aligned(qty,instrument.lot_size) or not aligned(px,instrument.tick_size): raise ValueError('fill_increment')
            rate=conversion_rate(instrument,state['currency'],fx,timestamp)
            if order['kind'] in {'LIMIT','STOP_LIMIT'}:
                limit=decimal(order['limit_price'])
                if (order['side']=='BUY' and px>limit) or (order['side']=='SELL' and px<limit): raise ValueError('limit_price_violation')
            delta=qty if order['side']=='BUY' else -qty
            notional=(qty*px*rate).quantize(MONEY_QUANTUM)
            account_fee=(cost*rate).quantize(MONEY_QUANTUM)
            cash_delta=-(notional if delta>0 else -notional)-account_fee
            release=decimal(order['reserved'])*qty/remaining
            if decimal(state['cash'])+cash_delta < reserved(state)-release: raise ValueError('fill_exceeds_available_cash')
            position=state['positions'].get(instrument.symbol,dict(instrument=instrument.model_dump(mode='json'),quantity='0',average_cost='0',mark=None))
            if Instrument.model_validate(position['instrument'])!=instrument:raise ValueError('instrument_contract_conflict')
            old=decimal(position['quantity']); avg=decimal(position['average_cost']); new=old+delta
            old_book=decimal(position.get('book_value',str(old*avg)))
            if order['reduce_only'] and (old*delta>=0 or qty>abs(old)): raise ValueError('reduce_only_position_changed')
            base_price=px*rate
            closed=min(abs(old),qty) if old*delta<0 else D(0)
            closed_book=(abs(old_book)*closed/abs(old)).quantize(MONEY_QUANTUM) if old else D(0)
            closed_proceeds=(closed*base_price).quantize(MONEY_QUANTUM)
            realized=(closed_proceeds-closed_book)*(1 if old>0 else -1)
            book_delta=(notional if delta>0 else -notional)+realized
            new_book=old_book+book_delta
            new_avg=new_book/new if new else D(0)
            actually_reducing=old*delta<0 and qty<=abs(old)
            if not actually_reducing:
                if state['status']!='READY':raise ValueError('account_not_open_for_risk')
                if (self.clock()-timestamp).total_seconds()>3*86400:raise ValueError('fill_risk_stale_observation')
                projected_cash=decimal(state['cash'])+cash_delta
                other_values=[]
                for symbol,other in state['positions'].items():
                    if symbol==instrument.symbol or decimal(other['quantity'])==0:continue
                    mark=other.get('mark')
                    if not mark or not 0<=(timestamp-utc(mark['at'])).total_seconds()<=3*86400:raise ValueError('fill_risk_unavailable_mark')
                    other_values.append(decimal(other['quantity'])*decimal(mark['price'])*conversion_rate(Instrument.model_validate(other['instrument']),state['currency'],mark.get('fx'),timestamp))
                projected_nav=projected_cash+new*base_price+sum(other_values,D(0))
                risk=RiskProfile.model_validate(state['risk'])
                pre_fill_nav=decimal(state['cash'])+old*base_price+sum(other_values,D(0))
                high=max(decimal(state['high_water']),pre_fill_nav)
                day_base=decimal(state['marks'][-1]['nav']) if state['day']!=timestamp.date().isoformat() and state['marks'] else decimal(state['day_open_nav'])
                if projected_nav<=high*(1-risk.drawdown_limit) or projected_nav<=day_base*(1-risk.daily_loss_limit):raise ValueError('fill_risk_loss_limit')
                pending_same=D(0);pending_gross=D(0)
                for pending in state['orders'].values():
                    if pending['status'] in TERMINAL or pending['reduce_only']:continue
                    remainder=decimal(pending['remaining'])-(qty if pending['id']==order_id else D(0))
                    exposure=remainder*decimal(pending['reference_price'])*decimal(pending['conversion_rate'])
                    pending_gross+=exposure
                    if pending['instrument']['symbol']==instrument.symbol:pending_same+=exposure
                if projected_nav<=0 or abs(new)*base_price+pending_same>projected_nav*risk.instrument_limit or abs(new)*base_price+sum(map(abs,other_values),D(0))+pending_gross>projected_nav*risk.gross_limit:
                    raise ValueError('fill_risk_limit')
            position.update(quantity=str(new),average_cost=str(new_avg),book_value=str(new_book),financing_clock=timestamp.isoformat(),mark=dict(price=str(px),at=timestamp.isoformat(),source_ref=fill_id,fx=fx))
            state['positions'][instrument.symbol]=position
            state['cash']=str(decimal(state['cash'])+cash_delta)
            state['fees']=str(decimal(state['fees'])+account_fee)
            state['realized_pnl']=str(decimal(state['realized_pnl'])+realized)
            order.update(remaining=str(remaining-qty),filled=str(decimal(order['filled'])+qty),reserved=str(decimal(order['reserved'])-release),
                status='FILLED' if qty==remaining else 'PARTIALLY_FILLED')
            order.setdefault('fill_ids',[]).append(fill_id)
            postings=[dict(book=book,amount=str(amount),currency=state['currency']) for book,amount in
                [('cash',cash_delta),('inventory:'+instrument.symbol,book_delta),('fees',account_fee),('realized_pnl',-realized)]]
            return dict(order=order,cash=state['cash'],realized_pnl=str(realized)),postings
        return self._change(account_id,'fill:'+fill_id,payload,'FILL_RECORDED',fill)

    def trigger_order(self,account_id,order_id,*,at,source_ref,key):
        timestamp=utc(at)
        def trigger(state):
            order=state['orders'].get(order_id)
            if order is None:raise KeyError('order_not_found')
            if order['status'] in TERMINAL or order['kind'] not in {'STOP','STOP_LIMIT'}:raise ValueError('order_not_triggerable')
            if timestamp<=utc(order['decision_at']) or timestamp>self.clock() or not source_ref:raise ValueError('invalid_trigger_clock')
            original=order['kind']
            order.update(kind='LIMIT' if original=='STOP_LIMIT' else 'MARKET',original_kind=original,triggered_at=timestamp.isoformat())
            return order,[]
        return self._change(account_id,key,dict(order_id=order_id,at=timestamp,source_ref=source_ref),'STOP_LIMIT_TRIGGERED',trigger)

    def apply_financing(self,account_id,*,amount,at,source_ref,key,instrument=None,accrual_start=None):
        cost=decimal(amount).quantize(MONEY_QUANTUM);timestamp=utc(at)
        def finance(state):
            if timestamp<utc(state['epoch']) or timestamp>self.clock() or not source_ref:raise ValueError('invalid_financing_clock')
            if instrument is not None:
                position=state['positions'].get(instrument.symbol)
                if position is None or Instrument.model_validate(position['instrument'])!=instrument:raise ValueError('instrument_contract_conflict')
                previous=utc(position.get('financing_clock',position['mark']['at']))
                if accrual_start is None or previous!=utc(accrual_start) or timestamp<=previous:raise ValueError('financing_accrual_conflict')
                position['financing_clock']=timestamp.isoformat()
            state['cash']=str(decimal(state['cash'])-cost)
            state['financing']=str(decimal(state.get('financing','0'))+cost)
            if decimal(state['cash'])<reserved(state):state['status']='HALTED'
            postings=[dict(book='cash',amount=str(-cost),currency=state['currency']),dict(book='financing',amount=str(cost),currency=state['currency'])]
            return dict(cash=state['cash'],financing=state['financing']),postings
        return self._change(account_id,key,dict(amount=cost,at=timestamp,source_ref=source_ref,instrument=instrument,accrual_start=accrual_start),'FINANCING_RECORDED',finance)

    def mark(self,account_id,marks: dict,*,key):
        def apply(state):
            for symbol,mark in marks.items():
                px=decimal(mark['price']);at=utc(mark['at'])
                if px<=0 or at>self.clock() or not mark.get('source_ref'): raise ValueError('invalid_mark')
                if symbol not in state['positions']: continue
                prior=state['positions'][symbol].get('mark')
                if prior and at<utc(prior['at']): raise ValueError('backward_mark')
                state['positions'][symbol]['mark']=dict(price=str(px),at=at.isoformat(),source_ref=mark['source_ref'],fx=mark.get('fx'))
            nav=value_portfolio(state,self.clock())
            if nav is not None:
                today=self.clock().date().isoformat()
                if state['day']!=today:
                    state['day']=today
                    state['day_open_nav']=state['marks'][-1]['nav'] if state['marks'] else state['opening_cash']
                state['high_water']=str(max(nav,decimal(state['high_water'])))
                risk=RiskProfile.model_validate(state['risk'])
                if nav<=decimal(state['high_water'])*(1-risk.drawdown_limit) or nav<=decimal(state['day_open_nav'])*(1-risk.daily_loss_limit):
                    state['status']='HALTED'
                state['marks'].append(dict(at=self.clock().isoformat(),nav=str(nav)))
            return dict(nav=None if nav is None else str(nav),status=state['status']),[]
        return self._change(account_id,key,marks,'PORTFOLIO_MARKED',apply)

    def snapshot(self,account_id):
        with self.repository.engine.connect() as conn: state=self._state(conn,account_id)
        nav=value_portfolio(state,self.clock())
        state.update(nav=None if nav is None else str(nav),reserved_cash=str(reserved(state)),
            available_cash=str(decimal(state['cash'])-reserved(state)),evidence_tier='MODELED_PAPER',
            estimated_liquidation_nav=None,valuation_status='COMPLETE' if nav is not None else 'MISSING_OR_STALE_MARK',
            drawdown=None if nav is None else str(nav/decimal(state['high_water'])-1))
        return state

    def list_accounts(self):
        with self.repository.engine.connect() as conn: ids=list(conn.scalars(select(accounts.c.id)))
        return [self.snapshot(value) for value in ids]

    def journal(self,account_id):
        with self.repository.engine.connect() as conn:
            return [json.loads(row) for row in conn.scalars(select(events.c.payload).where(events.c.account_id==account_id).order_by(events.c.sequence))]
