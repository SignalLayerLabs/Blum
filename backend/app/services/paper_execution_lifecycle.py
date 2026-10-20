from __future__ import annotations

from datetime import datetime
import hashlib
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import (
    LiveForwardPaperTrade,
    LiveForwardPaperTradeEvent,
    PaperExecutionFill,
    PaperExecutionOrder,
    StrategyCandidateVariant,
)
from app.services.market_clock import utc_naive
from app.services.realistic_execution import (
    ExecutionMarketBar,
    ExecutionOrderRequest,
    RealisticExecutionEngine,
)


class PaperOrderLifecycleService:
    def __init__(self, engine: RealisticExecutionEngine | None = None):
        self.engine = engine or RealisticExecutionEngine()

    def submit(
        self,
        db: Session,
        request: ExecutionOrderRequest,
        *,
        paper_trade_id: int | None = None,
        replay_trade_id: int | None = None,
        validation_id: int | None = None,
        candidate_id: int | None = None,
        expires_at: datetime | None = None,
    ) -> PaperExecutionOrder:
        existing = db.scalar(select(PaperExecutionOrder).where(PaperExecutionOrder.duplicate_key == request.order_key))
        if existing is not None:
            return existing
        if candidate_id is None and validation_id is not None:
            candidate_id = db.scalar(
                select(StrategyCandidateVariant.id)
                .where(
                    StrategyCandidateVariant.validation_id == validation_id,
                    StrategyCandidateVariant.is_champion.is_(True),
                )
                .limit(1)
            )
        row = PaperExecutionOrder(
            order_uid=f"order-{request.decision_timestamp.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:10]}",
            duplicate_key=request.order_key,
            paper_trade_id=paper_trade_id,
            replay_trade_id=replay_trade_id,
            validation_id=validation_id,
            candidate_id=candidate_id,
            ticker=request.ticker,
            side=request.side.upper(),
            order_type=request.order_type.upper(),
            status="SUBMITTED",
            decision_timestamp=request.decision_timestamp,
            submitted_at=datetime.utcnow(),
            expires_at=expires_at,
            theoretical_price=request.theoretical_price,
            requested_quantity=request.quantity,
            filled_quantity=0.0,
            remaining_quantity=request.quantity,
            limit_price=request.limit_price,
            stop_price=request.stop_price,
            target_price=request.target_price,
            currency=request.currency,
            account_currency=request.account_currency,
            fx_rate=request.fx_rate,
            order_payload={
                "max_participation_rate": request.max_participation_rate,
                "commission_bps": request.commission_bps,
                "latency_bars": request.latency_bars,
                "fx_spread_bps": request.fx_spread_bps,
                "liquidity_score": request.liquidity_score,
                "liquidity_basis": request.liquidity_basis,
                "quote_capacity_units": request.quote_capacity_units,
                "allowed_sessions": list(request.allowed_sessions),
                "borrow_rate_bps": request.borrow_rate_bps,
                "expected_holding_days": request.expected_holding_days,
                "frozen_decision_timestamp": request.decision_timestamp.isoformat(),
            },
        )
        db.add(row)
        db.flush()
        if paper_trade_id is not None:
            self._event(db, paper_trade_id, "PAPER_ORDER_SUBMITTED", request.decision_timestamp, request.theoretical_price, "Approved candidate submitted to realistic execution.", {"order_id": row.id, "order_uid": row.order_uid})
        return row

    def process_order(
        self,
        db: Session,
        order: PaperExecutionOrder,
        bars: list[ExecutionMarketBar],
        *,
        now: datetime | None = None,
    ) -> dict:
        if order.status in {
            "FILLED",
            "PARTIALLY_FILLED_EXPIRED",
            "REJECTED",
            "EXPIRED",
            "CANCELLED",
        }:
            return self._summary(order, new_fills=0)
        existing_fills = db.scalars(
            select(PaperExecutionFill)
            .where(PaperExecutionFill.order_id == order.id)
            .order_by(PaperExecutionFill.market_timestamp, PaperExecutionFill.id)
        ).all()
        current_time = utc_naive(now or datetime.utcnow())
        last_fill_at = (
            existing_fills[-1].market_timestamp
            if existing_fills
            else order.decision_timestamp
        )
        payload = dict(order.order_payload or {})
        request = ExecutionOrderRequest(
            order_key=order.duplicate_key,
            ticker=order.ticker,
            side=order.side,
            order_type=order.order_type,
            decision_timestamp=last_fill_at,
            theoretical_price=order.theoretical_price,
            quantity=max(0.0, float(order.remaining_quantity or 0.0)),
            limit_price=order.limit_price,
            stop_price=order.stop_price,
            target_price=order.target_price,
            max_participation_rate=float(payload.get("max_participation_rate") or 0.05),
            commission_bps=float(payload.get("commission_bps") or 0.0),
            latency_bars=(
                int(
                    payload.get(
                        "latency_bars_remaining", payload.get("latency_bars") or 0
                    )
                )
                if not existing_fills
                else 0
            ),
            stop_activated_at=(
                datetime.fromisoformat(payload["stop_activated_at"])
                if payload.get("stop_activated_at")
                else None
            ),
            last_observation_at=(
                datetime.fromisoformat(payload["last_observation_at"])
                if payload.get("last_observation_at")
                else None
            ),
            currency=order.currency,
            account_currency=order.account_currency,
            fx_rate=order.fx_rate,
            fx_spread_bps=float(payload.get("fx_spread_bps") or 0.0),
            liquidity_score=float(
                payload.get("liquidity_score")
                if payload.get("liquidity_score") is not None
                else 100.0
            ),
            liquidity_basis=str(payload.get("liquidity_basis") or "reported_volume"),
            quote_capacity_units=(
                float(payload["quote_capacity_units"])
                if payload.get("quote_capacity_units") is not None
                else None
            ),
            allowed_sessions=tuple(payload.get("allowed_sessions") or ["regular"]),
            borrow_rate_bps=(
                float(payload["borrow_rate_bps"])
                if payload.get("borrow_rate_bps") is not None
                else None
            ),
            expected_holding_days=float(payload.get("expected_holding_days") or 0.0),
        )
        from app.services.market_clock import eligible_bar, bar_available_at

        eligible = [
            bar
            for bar in bars
            if eligible_bar(
                bar,
                decision_at=order.decision_timestamp,
                as_of=current_time,
                mode="execution",
            )
            and (order.expires_at is None or bar_available_at(bar) < order.expires_at)
        ]
        decision = self.engine.evaluate(request, eligible)
        order.order_payload = {
            **payload,
            "stop_activated_at": (
                decision.stop_activated_at.isoformat()
                if decision.stop_activated_at
                else None
            ),
            "last_observation_at": (
                decision.last_observation_at.isoformat()
                if decision.last_observation_at
                else None
            ),
            "latency_bars_remaining": decision.latency_bars_remaining,
        }

        new_fills = 0
        for fill in decision.fills:
            fill_uid = self._fill_uid(
                order.id, fill.timestamp, fill.quantity, fill.executed_price
            )
            if (
                db.scalar(
                    select(PaperExecutionFill.id).where(
                        PaperExecutionFill.fill_uid == fill_uid
                    )
                )
                is not None
            ):
                continue
            notional = abs(fill.reference_price * fill.quantity) / float(
                order.fx_rate or 1.0
            )
            fx_cost = (
                notional * request.fx_spread_bps / 10_000.0
                if order.currency != order.account_currency
                else 0.0
            )
            borrow_cost = (
                notional
                * float(request.borrow_rate_bps or 0.0)
                / 10_000.0
                * request.expected_holding_days
                / 365.0
                if order.side in {"SHORT", "SELL_SHORT"}
                else 0.0
            )
            db.add(
                PaperExecutionFill(
                    order_id=order.id,
                    fill_uid=fill_uid,
                    market_timestamp=fill.timestamp,
                    quantity=fill.quantity,
                    reference_price=fill.reference_price,
                    executed_price=fill.executed_price,
                    spread_bps=fill.spread_bps,
                    slippage_bps=fill.slippage_bps,
                    commission_bps=fill.commission_bps,
                    spread_cost=notional * fill.spread_bps / 20_000.0,
                    slippage_cost=notional * fill.slippage_bps / 10_000.0,
                    commission_cost=notional * fill.commission_bps / 10_000.0,
                    fx_cost=fx_cost,
                    borrow_cost=borrow_cost,
                    participation_rate=fill.participation_rate,
                    fill_payload={
                        "execution_model": "realistic_execution_v1",
                        "estimated_costs": True,
                        "currency": order.currency,
                        "account_currency": order.account_currency,
                        "fx_rate": order.fx_rate,
                        "liquidity_score": request.liquidity_score,
                        "liquidity_basis": request.liquidity_basis,
                        "quote_capacity_units": request.quote_capacity_units,
                        "session": next(
                            (
                                bar.session
                                for bar in bars
                                if bar.timestamp == fill.timestamp
                            ),
                            None,
                        ),
                    },
                )
            )
            new_fills += 1
        db.flush()
        all_fills = db.scalars(
            select(PaperExecutionFill)
            .where(PaperExecutionFill.order_id == order.id)
            .order_by(PaperExecutionFill.market_timestamp, PaperExecutionFill.id)
        ).all()
        filled_quantity = sum(float(fill.quantity) for fill in all_fills)
        order.filled_quantity = round(filled_quantity, 8)
        order.remaining_quantity = round(
            max(0.0, float(order.requested_quantity) - filled_quantity), 8
        )
        order.average_fill_price = (
            round(
                sum(
                    float(fill.executed_price) * float(fill.quantity)
                    for fill in all_fills
                )
                / filled_quantity,
                8,
            )
            if filled_quantity > 0
            else None
        )
        expired = bool(order.expires_at and current_time >= order.expires_at)
        if order.remaining_quantity <= 1e-9:
            order.status = "FILLED"
        elif filled_quantity > 0:
            order.status = "PARTIALLY_FILLED_EXPIRED" if expired else "PARTIALLY_FILLED"
            order.rejection_reason = (
                "PARTIAL_FILL_REMAINDER_CANCELLED" if expired else None
            )
        elif decision.status == "REJECTED":
            order.status = "REJECTED"
            order.rejection_reason = decision.reason
        elif expired:
            order.status = "EXPIRED"
            order.rejection_reason = "ORDER_NOT_FILLED"
        else:
            order.status = "SUBMITTED"
            order.rejection_reason = (
                decision.reason
                if decision.reason
                not in {"NO_LATER_EXECUTABLE_BAR", "ORDER_NOT_FILLED"}
                else None
            )
        order.updated_at = datetime.utcnow()
        if order.paper_trade_id is not None and new_fills:
            self._project_trade(db, order, all_fills)
        db.flush()
        return self._summary(order, new_fills=new_fills)

    def process_batch(
        self,
        db: Session,
        bars_by_ticker: dict[str, list[ExecutionMarketBar]],
        *,
        limit: int = 50,
        now: datetime | None = None,
    ) -> dict:
        orders = db.scalars(
            select(PaperExecutionOrder)
            .where(PaperExecutionOrder.status.in_(["SUBMITTED", "PARTIALLY_FILLED"]))
            .order_by(PaperExecutionOrder.submitted_at, PaperExecutionOrder.id)
            .limit(max(1, min(200, int(limit))))
        ).all()
        results = [self.process_order(db, order, bars_by_ticker.get(order.ticker, []), now=now) for order in orders]
        db.commit()
        return {
            "status": "COMPLETED",
            "orders_processed": len(results),
            "filled": sum(1 for row in results if row["status"] == "FILLED"),
            "partially_filled": sum(1 for row in results if row["status"] == "PARTIALLY_FILLED"),
            "partial_remainder_cancelled": sum(1 for row in results if row["status"] == "PARTIALLY_FILLED_EXPIRED"),
            "expired": sum(1 for row in results if row["status"] == "EXPIRED"),
            "new_fills": sum(int(row["new_fills"]) for row in results),
        }

    def _project_trade(self, db: Session, order: PaperExecutionOrder, fills: list[PaperExecutionFill]) -> None:
        trade = db.get(LiveForwardPaperTrade, order.paper_trade_id)
        if trade is None:
            return
        total_quantity = sum(float(fill.quantity) for fill in fills)
        average = sum(float(fill.executed_price) * float(fill.quantity) for fill in fills) / max(total_quantity, 1e-9)
        total_spread = sum(float(fill.spread_cost) for fill in fills)
        total_slippage = sum(float(fill.slippage_cost) for fill in fills)
        total_commission = sum(float(fill.commission_cost) for fill in fills)
        total_fx = sum(float(fill.fx_cost) for fill in fills)
        total_borrow = sum(float(fill.borrow_cost) for fill in fills)
        total_gap = sum(float(fill.gap_cost) for fill in fills)
        trade.entry_price = round(average, 8)
        trade.position_size = round(total_quantity, 8)
        trade.opened_at = min(fill.market_timestamp for fill in fills)
        trade.entry_date = trade.opened_at.date()
        trade.status = "OPEN" if order.status in {"FILLED", "PARTIALLY_FILLED_EXPIRED"} else "PARTIALLY_FILLED"
        trade.spread_cost = round(total_spread, 8)
        trade.slippage_cost = round(total_slippage, 8)
        trade.commission_cost = round(total_commission, 8)
        trade.costs_paid = round(total_spread + total_slippage + total_commission + total_fx + total_borrow + total_gap, 8)
        trade.execution_costs = {
            **dict(trade.execution_costs or {}),
            "execution_model": "realistic_execution_v1",
            "order_id": order.id,
            "theoretical_price": order.theoretical_price,
            "average_fill_price": order.average_fill_price,
            "fill_count": len(fills),
            "spread_cost": trade.spread_cost,
            "slippage_cost": trade.slippage_cost,
            "commission_cost": trade.commission_cost,
            "fx_cost": round(total_fx, 8),
            "borrow_cost": round(total_borrow, 8),
            "gap_cost": round(total_gap, 8),
        }
        latest = max(fill.market_timestamp for fill in fills)
        self._event(db, trade.id, "PAPER_ORDER_FILLED" if order.status == "FILLED" else "PAPER_ORDER_PARTIALLY_FILLED", latest, trade.entry_price, "Order fill projected to paper trade.", {"order_id": order.id, "filled_quantity": total_quantity, "remaining_quantity": order.remaining_quantity})

    @staticmethod
    def _event(db: Session, trade_id: int, event_type: str, timestamp: datetime, price: float | None, reason: str, payload: dict) -> None:
        existing = db.scalar(
            select(LiveForwardPaperTradeEvent.id).where(
                LiveForwardPaperTradeEvent.paper_trade_id == trade_id,
                LiveForwardPaperTradeEvent.event_type == event_type,
                LiveForwardPaperTradeEvent.event_timestamp == timestamp,
            )
        )
        if existing is None:
            db.add(LiveForwardPaperTradeEvent(paper_trade_id=trade_id, event_timestamp=timestamp, event_type=event_type, price_used=price, reason=reason, payload=payload))

    @staticmethod
    def _fill_uid(order_id: int, timestamp: datetime, quantity: float, price: float) -> str:
        raw = f"{order_id}|{timestamp.isoformat()}|{quantity:.8f}|{price:.8f}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _summary(order: PaperExecutionOrder, *, new_fills: int) -> dict:
        return {
            "order_id": order.id,
            "order_uid": order.order_uid,
            "status": order.status,
            "theoretical_price": order.theoretical_price,
            "average_fill_price": order.average_fill_price,
            "filled_quantity": order.filled_quantity,
            "remaining_quantity": order.remaining_quantity,
            "new_fills": new_fills,
            "rejection_reason": order.rejection_reason,
        }


def execution_reality_snapshot(db: Session) -> dict:
    status_rows = db.execute(select(PaperExecutionOrder.status, func.count(PaperExecutionOrder.id)).group_by(PaperExecutionOrder.status)).all()
    counts = {str(status): int(count) for status, count in status_rows}
    fills = db.scalars(select(PaperExecutionFill).order_by(desc(PaperExecutionFill.market_timestamp)).limit(500)).all()
    total_costs = sum(float(row.spread_cost) + float(row.slippage_cost) + float(row.commission_cost) + float(row.fx_cost) + float(row.borrow_cost) + float(row.gap_cost) for row in fills)
    latest = fills[0].market_timestamp.isoformat() if fills else None
    return {
        "status": "READY" if counts else "NO_EXECUTION_ORDERS",
        "orders": counts,
        "fill_count": len(fills),
        "total_execution_costs": round(total_costs, 8),
        "average_execution_cost": round(total_costs / len(fills), 8) if fills else None,
        "latest_fill_at": latest,
        "primary_blocker": "NO_PROMOTED_INTRADAY_STRATEGY" if not counts else None,
        "policy": "Orders and fills are persisted; no fill exists without a later executable market observation.",
    }
