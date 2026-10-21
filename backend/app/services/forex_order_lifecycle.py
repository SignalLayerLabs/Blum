"""Persistent native FX orders: a proposal is not an immediate market fill."""

from dataclasses import asdict, replace
from datetime import datetime
from hashlib import sha256
from math import floor

from app.services.forex_risk import common_lot_step

from sqlalchemy import select, desc

from app.models import (
    ForexDecision,
    ForexOrderFill,
    ForexPendingOrder,
    ForexPosition,
    LiveForwardPaperGame,
)
from app.services.forex_broker import BlumForexBrokerProfileService
from app.services.forex_cash_accounting import (
    ForexCashAccounting,
    VERSION,
    convert_cash,
    fresh,
)
from app.services.forex_contracts import ForexDirection, ForexOrderRequest, pair_config
from app.services.forex_execution import BlumForexExecutionSimulator
from app.services.market_clock import utc_naive

TERMINAL = {"FILLED", "CANCELLED", "EXPIRED", "PARTIALLY_FILLED_EXPIRED", "REJECTED"}


class ForexOrderLifecycle:
    def __init__(self, *, brokers=None, execution=None):
        self.brokers = brokers or BlumForexBrokerProfileService()
        self.execution = execution or BlumForexExecutionSimulator()

    def submit(
        self,
        db,
        *,
        decision_id: int,
        order: ForexOrderRequest,
        expires_at: datetime,
        account_id: str | None = None,
        submitted_at: datetime | None = None,
    ):
        decision = db.get(ForexDecision, decision_id)
        payload = asdict(order)
        payload["side"] = order.side.value
        existing = db.scalar(
            select(ForexPendingOrder).where(
                ForexPendingOrder.decision_id == decision_id
            )
        )
        if existing:
            if (
                (account_id is not None and existing.account_id != account_id)
                or existing.payload != payload
                or existing.expires_at != utc_naive(expires_at)
            ):
                raise ValueError("FROZEN_ORDER_CHANGED")
            return existing
        if expires_at <= decision.decision_timestamp:
            raise ValueError("INVALID_ORDER_EXPIRY")
        game = (
            db.scalar(
                select(LiveForwardPaperGame).where(
                    LiveForwardPaperGame.game_id == account_id,
                    LiveForwardPaperGame.status == "active",
                )
            )
            if account_id is not None
            else db.scalar(
                select(LiveForwardPaperGame)
                .where(LiveForwardPaperGame.status == "active")
                .order_by(desc(LiveForwardPaperGame.started_at))
                .limit(1)
            )
        )
        if account_id is not None and game is None:
            raise ValueError("BOUND_PAPER_ACCOUNT_REQUIRED")
        row = ForexPendingOrder(
            account_id=game.game_id if game else None,
            order_uid=f"{decision.decision_uid}:order-v2",
            decision_id=decision.id,
            pair=order.pair,
            decision_at=decision.decision_timestamp,
            submitted_at=utc_naive(submitted_at or datetime.utcnow()),
            expires_at=utc_naive(expires_at),
            requested_lots=order.quantity_lots,
            filled_lots=0,
            remaining_lots=order.quantity_lots,
            payload=payload,
        )
        db.add(row)
        db.flush()
        return row

    def process(self, db, *, order_uid: str, quote, as_of: datetime, quotes=None):
        now = utc_naive(as_of)
        row = db.scalar(
            select(ForexPendingOrder)
            .where(ForexPendingOrder.order_uid == order_uid)
            .with_for_update()
        )
        if row is None:
            raise ValueError("UNKNOWN_ORDER")

        def result(reason=None, new_fills=0):
            if reason and now >= row.expires_at and row.status not in TERMINAL:
                row.status = (
                    "PARTIALLY_FILLED_EXPIRED" if row.filled_lots else "EXPIRED"
                )
            return {
                "order_uid": row.order_uid,
                "status": row.status,
                "reason": reason,
                "new_fills": new_fills,
                "filled_lots": row.filled_lots,
                "remaining_lots": row.remaining_lots,
                "working_lots": 0.0 if row.status in TERMINAL else row.remaining_lots,
            }

        if row.status in TERMINAL:
            return result()
        stamp = utc_naive(quote.timestamp)
        # Delay polling may process a genuine pre-expiry observation; never a later one.
        if stamp >= row.expires_at:
            if now >= row.expires_at:
                row.status = (
                    "PARTIALLY_FILLED_EXPIRED" if row.filled_lots else "EXPIRED"
                )
            return result("ORDER_EXPIRED")
        if stamp <= row.decision_at or (
            row.last_observation_at and stamp <= row.last_observation_at
        ):
            return result("NO_LATER_OBSERVATION")
        if not quote.source or not fresh(quote, now):
            return result("QUOTE_UNAVAILABLE")
        position = db.scalar(
            select(ForexPosition).where(ForexPosition.decision_id == row.decision_id)
        )
        if position and (
            position.status != "OPEN"
            or (position.contract_json.get("accounting") or {}).get("exit_reason")
        ):
            row.status = "CANCELLED"
            return result("POSITION_EXIT_CANCELLED_REMAINDER")
        request = ForexOrderRequest(
            **{
                **row.payload,
                "side": ForexDirection(row.payload["side"]),
                "quantity_lots": row.remaining_lots,
            }
        )
        config = pair_config(row.pair)
        broker = self.brokers.get()
        observations = {**(quotes or {}), row.pair: quote}
        conversion = convert_cash(
            -1.0, config.quote_currency, broker.account_currency, observations, now=now
        )
        notional_conversion = convert_cash(
            -100_000.0,
            config.base_currency,
            broker.account_currency,
            observations,
            now=now,
        )
        if conversion is None or notional_conversion is None:
            return result("ACCOUNT_CONVERSION_UNAVAILABLE")
        row.last_observation_at = stamp
        request = replace(request, account_conversion=conversion)
        if request.order_type == "STOP_LIMIT":
            triggered = (
                quote.ask >= request.stop_price
                if request.side == ForexDirection.LONG
                else quote.bid <= request.stop_price
            )
            if row.stop_activated_at is None:
                if not triggered:
                    return result("STOP_NOT_TRIGGERED")
                row.stop_activated_at = stamp
            request = replace(request, order_type="LIMIT")
        fill = self.execution.submit(request, quote, broker, now=now)
        if fill.fill_price is None or fill.filled_quantity_lots <= 0:
            if now >= row.expires_at:
                row.status = (
                    "PARTIALLY_FILLED_EXPIRED" if row.filled_lots else "EXPIRED"
                )
            return result(fill.rejection_reason or "ORDER_NOT_FILLED")
        valid_geometry = (
            request.stop_price < fill.fill_price < request.target_price
            if request.side == ForexDirection.LONG
            else request.target_price < fill.fill_price < request.stop_price
        )
        if not valid_geometry:
            row.status = "CANCELLED"
            return result("ENTRY_GEOMETRY_INVALIDATED")
        decision = db.get(ForexDecision, row.decision_id)
        approved_risk = float(decision.risk_json.get("risk_amount") or 0.0)
        if approved_risk <= 0:
            row.status = "REJECTED"
            return result("RISK_APPROVAL_UNAVAILABLE")
        used_risk = 0.0
        if position:
            ledger = position.contract_json.get("accounting") or {}
            used_risk = float(ledger.get("initial_risk_account") or 0.0) + float(
                ledger.get("entry_commission") or 0.0
            )
            used_risk += max(
                broker.minimum_commission,
                broker.commission_per_lot_round_trip * position.quantity_lots / 2,
            )
        per_lot_risk = (
            abs(fill.fill_price - request.stop_price) * 100_000 * conversion["rate"]
            + broker.commission_per_lot_round_trip
        )
        step = common_lot_step(config.lot_step, broker.lot_step)
        affordable = (
            floor(max(0.0, approved_risk - used_risk) / per_lot_risk / step + 1e-12)
            * step
        )
        if affordable < max(broker.minimum_lot, config.minimum_lot):
            return result("RISK_BUDGET_EXCEEDED")
        if affordable < fill.filled_quantity_lots - 1e-9:
            fill = self.execution.submit(
                replace(request, quantity_lots=affordable), quote, broker, now=now
            )
            if fill.fill_price is None or fill.filled_quantity_lots <= 0:
                return result("RISK_BUDGET_EXCEEDED")
        lots = fill.filled_quantity_lots
        observation_uid = sha256(
            f"{row.pair}:{quote.source}:{stamp.isoformat()}".encode()
        ).hexdigest()
        fill_uid = sha256(f"{row.order_uid}:{observation_uid}".encode()).hexdigest()
        if db.scalar(
            select(ForexOrderFill.id).where(ForexOrderFill.fill_uid == fill_uid)
        ):
            return result("DUPLICATE_OBSERVATION")
        margin = abs(notional_conversion["amount"]) * lots * broker.margin_requirement
        conversion = {
            **conversion,
            "margin_required": margin,
            "notional_account": abs(notional_conversion["amount"]) * lots,
            "risk_account": abs(fill.fill_price - request.stop_price)
            * 100_000
            * lots
            * conversion["rate"],
            "account_currency": broker.account_currency,
            "at": now.isoformat(),
        }
        if position is None:
            decision = db.get(ForexDecision, row.decision_id)
            position = ForexPosition(
                position_uid=f"fx-position-{decision.id}",
                decision_id=decision.id,
                pair=row.pair,
                strategy_id=decision.strategy_id,
                direction=request.side.value,
                status="OPEN",
                quantity_lots=0,
                entry_price=fill.fill_price,
                stop_price=request.stop_price,
                target_price=request.target_price,
                current_price=fill.fill_price,
                opened_at=stamp,
                last_managed_at=now,
                commission=0,
                margin_used=0,
                contract_json={
                    **decision.proposal_json,
                    "accounting_version": VERSION,
                    "account_currency": broker.account_currency,
                    "account_id": row.account_id,
                    "session": request.session,
                    "broker_profile": broker.profile_name,
                    "liquidity_score": request.liquidity_score,
                    "volatility_score": request.volatility_score,
                    "event_impact": request.event_impact,
                    "accounting": {},
                },
            )
            db.add(position)
            db.flush()
        record = ForexOrderFill(
            fill_uid=fill_uid,
            order_uid=row.order_uid,
            observation_uid=observation_uid,
            market_timestamp=stamp,
            quantity_lots=lots,
            executed_price=fill.fill_price,
            payload={"execution": asdict(fill), "conversion": conversion},
        )
        db.add(record)
        db.flush()
        ForexCashAccounting().apply_fill(
            db,
            fill_uid=fill_uid,
            position_id=position.id,
            delta_lots=lots,
            executed_price=fill.fill_price,
            commission=fill.commission,
            conversion=conversion,
        )
        row.filled_lots = round(row.filled_lots + lots, 8)
        row.remaining_lots = round(max(0, row.requested_lots - row.filled_lots), 8)
        row.status = (
            "FILLED"
            if row.remaining_lots <= 1e-9
            else (
                "PARTIALLY_FILLED_EXPIRED"
                if now >= row.expires_at
                else "PARTIALLY_FILLED"
            )
        )
        decision = db.get(ForexDecision, row.decision_id)
        decision.status = "OPENED"
        decision.execution_json = {
            **asdict(fill),
            "order_uid": row.order_uid,
            "conversion": conversion,
        }
        db.flush()
        return result(new_fills=1)

    def process_batch(self, db, *, quotes: dict, as_of: datetime):
        rows = db.scalars(
            select(ForexPendingOrder)
            .where(ForexPendingOrder.status.in_(["SUBMITTED", "PARTIALLY_FILLED"]))
            .order_by(ForexPendingOrder.id)
            .limit(100)
        ).all()
        results = []
        for row in rows:
            position = db.scalar(
                select(ForexPosition).where(
                    ForexPosition.decision_id == row.decision_id
                )
            )
            if position and (
                position.status != "OPEN"
                or (position.contract_json.get("accounting") or {}).get("exit_reason")
            ):
                row.status = "CANCELLED"
                continue
            quote = quotes.get(row.pair)
            if quote:
                results.append(
                    self.process(
                        db,
                        order_uid=row.order_uid,
                        quote=quote,
                        as_of=as_of,
                        quotes=quotes,
                    )
                )
            elif as_of >= row.expires_at:
                row.status = (
                    "PARTIALLY_FILLED_EXPIRED" if row.filled_lots else "EXPIRED"
                )
        return results
