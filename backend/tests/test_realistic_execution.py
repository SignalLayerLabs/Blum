from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import PaperExecutionFill, PaperExecutionOrder
from app.services.realistic_execution import (
    ExecutionMarketBar,
    ExecutionOrderRequest,
    RealisticExecutionEngine,
)
from app.services.paper_execution_lifecycle import PaperOrderLifecycleService

NOW = datetime(2026, 7, 15, 14, 30)


def order(**overrides) -> ExecutionOrderRequest:
    payload = {
        "order_key": "order-1",
        "ticker": "NVDA",
        "side": "BUY",
        "order_type": "LIMIT",
        "decision_timestamp": NOW,
        "theoretical_price": 100.0,
        "quantity": 100.0,
        "limit_price": 100.0,
        "stop_price": 98.0,
        "target_price": 104.0,
        "max_participation_rate": 0.1,
        "commission_bps": 1.0,
        "latency_bars": 0,
        "currency": "USD",
        "account_currency": "USD",
    }
    payload.update(overrides)
    return ExecutionOrderRequest(**payload)


def bar(minutes: int, **overrides) -> ExecutionMarketBar:
    payload = {
        "timestamp": NOW + timedelta(minutes=minutes),
        "open": 100.4,
        "high": 100.8,
        "low": 99.8,
        "close": 100.2,
        "volume": 500.0,
        "spread_bps": 4.0,
        "volatility_bps": 25.0,
        "session": "regular",
        "is_halted": False,
    }
    payload.update(overrides)
    return ExecutionMarketBar(**payload)


def test_order_never_fills_from_decision_or_earlier_bar() -> None:
    engine = RealisticExecutionEngine()
    result = engine.evaluate(order(), [bar(-1), bar(0)])

    assert result.status == "SUBMITTED"
    assert result.fills == ()
    assert result.reason == "NO_LATER_EXECUTABLE_BAR"


def test_limit_order_remains_unfilled_without_cross() -> None:
    result = RealisticExecutionEngine().evaluate(
        order(limit_price=99.0), [bar(1, low=99.2)]
    )

    assert result.status == "SUBMITTED"
    assert result.filled_quantity == 0
    assert result.reason == "ORDER_NOT_FILLED"


def test_partial_fill_respects_volume_participation() -> None:
    result = RealisticExecutionEngine().evaluate(
        order(quantity=100), [bar(1, volume=500, low=99.5)]
    )

    assert result.status == "PARTIALLY_FILLED"
    assert result.filled_quantity == 50
    assert result.remaining_quantity == 50
    assert result.average_fill_price <= 100.0
    assert result.costs.total_cost > 0


def test_otc_quote_capacity_can_fill_zero_reported_volume_without_affecting_exchange_orders() -> (
    None
):
    engine = RealisticExecutionEngine()
    forex = engine.evaluate(
        order(
            order_key="forex-order",
            ticker="EURUSD=X",
            quantity=10,
            liquidity_basis="otc_quote_capacity",
            quote_capacity_units=1_000,
        ),
        [bar(1, volume=0, low=99.5)],
    )
    exchange = engine.evaluate(
        order(order_key="exchange-order", quantity=10),
        [bar(1, volume=0, low=99.5)],
    )

    assert forex.status == "FILLED"
    assert forex.filled_quantity == 10
    assert forex.fills[0].participation_rate == 0.01
    assert exchange.status == "SUBMITTED"
    assert exchange.reason == "ORDER_NOT_FILLED"


def test_multiple_later_bars_can_complete_partial_order() -> None:
    result = RealisticExecutionEngine().evaluate(
        order(quantity=100),
        [bar(1, volume=500, low=99.5), bar(2, volume=600, low=99.4)],
    )

    assert result.status == "FILLED"
    assert result.filled_quantity == 100
    assert len(result.fills) == 2


def test_missing_fx_rate_blocks_cross_currency_fill() -> None:
    result = RealisticExecutionEngine().evaluate(
        order(account_currency="EUR", currency="USD", fx_rate=None), [bar(1)]
    )

    assert result.status == "REJECTED"
    assert result.reason == "FX_RATE_UNAVAILABLE"


def test_cross_currency_fill_records_fx_spread_cost() -> None:
    result = RealisticExecutionEngine().evaluate(
        order(
            account_currency="EUR",
            currency="USD",
            fx_rate=1.08,
            fx_spread_bps=6.0,
            quantity=10,
        ),
        [bar(1, low=99.5, volume=10_000)],
    )

    assert result.status == "FILLED"
    assert result.costs.fx_cost > 0


def test_short_order_requires_borrow_rate_evidence() -> None:
    result = RealisticExecutionEngine().evaluate(
        order(
            side="SHORT", order_type="MARKET", limit_price=None, borrow_rate_bps=None
        ),
        [bar(1)],
    )

    assert result.status == "REJECTED"
    assert result.reason == "BORROW_RATE_UNAVAILABLE"


def test_short_fill_records_borrow_cost_for_expected_holding_period() -> None:
    result = RealisticExecutionEngine().evaluate(
        order(
            side="SHORT",
            order_type="MARKET",
            limit_price=None,
            borrow_rate_bps=365.0,
            expected_holding_days=2.0,
            quantity=10,
        ),
        [bar(1, volume=10_000)],
    )

    assert result.status == "FILLED"
    assert result.costs.borrow_cost > 0


def test_order_does_not_fill_in_disallowed_session() -> None:
    result = RealisticExecutionEngine().evaluate(
        order(order_type="MARKET", limit_price=None, allowed_sessions=("regular",)),
        [bar(1, session="opening_auction")],
    )

    assert result.status == "SUBMITTED"
    assert result.reason == "NO_ALLOWED_SESSION_BAR"


def test_halted_bar_is_not_an_executable_fill() -> None:
    result = RealisticExecutionEngine().evaluate(
        order(order_type="MARKET", limit_price=None),
        [bar(1, is_halted=True)],
    )

    assert result.status == "SUBMITTED"
    assert result.reason == "MARKET_HALTED"


def test_low_liquidity_increases_dynamic_slippage() -> None:
    liquid = RealisticExecutionEngine().evaluate(
        order(quantity=10, liquidity_score=95.0),
        [bar(1, volume=10_000, low=99.5)],
    )
    illiquid = RealisticExecutionEngine().evaluate(
        order(order_key="order-illiquid", quantity=10, liquidity_score=20.0),
        [bar(1, volume=10_000, low=99.5)],
    )

    assert illiquid.fills[0].slippage_bps > liquid.fills[0].slippage_bps


def test_gap_through_stop_uses_first_later_executable_open() -> None:
    engine = RealisticExecutionEngine()
    result = engine.evaluate_exit(
        side="LONG",
        quantity=10,
        entry_price=100.0,
        stop_price=98.0,
        target_price=104.0,
        decision_timestamp=NOW,
        bars=[bar(1, open=96.0, high=97.0, low=95.5, close=96.5)],
    )

    assert result.status == "CLOSED"
    assert result.reason == "STOP_HIT"
    assert result.average_fill_price < 98.0
    assert result.costs.gap_cost > 0


def test_same_bar_stop_and_target_uses_conservative_stop_ordering() -> None:
    result = RealisticExecutionEngine().evaluate_exit(
        side="LONG",
        quantity=10,
        entry_price=100.0,
        stop_price=98.0,
        target_price=104.0,
        decision_timestamp=NOW,
        bars=[bar(1, open=100.0, high=105.0, low=97.0, close=102.0)],
    )

    assert result.status == "CLOSED"
    assert result.reason == "STOP_HIT"


def test_execution_ledger_deduplicates_orders_and_fills() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        row = PaperExecutionOrder(
            order_uid="paper-order-1",
            duplicate_key="paper-order-key",
            ticker="NVDA",
            side="BUY",
            order_type="LIMIT",
            status="SUBMITTED",
            decision_timestamp=NOW,
            submitted_at=NOW,
            theoretical_price=100.0,
            requested_quantity=10.0,
            remaining_quantity=10.0,
        )
        db.add(row)
        db.flush()
        db.add(
            PaperExecutionFill(
                order_id=row.id,
                fill_uid="fill-1",
                market_timestamp=NOW + timedelta(minutes=1),
                quantity=5.0,
                reference_price=99.9,
                executed_price=100.0,
            )
        )
        db.commit()
        db.add(
            PaperExecutionOrder(
                order_uid="paper-order-2",
                duplicate_key="paper-order-key",
                ticker="NVDA",
                side="BUY",
                order_type="LIMIT",
                status="SUBMITTED",
                decision_timestamp=NOW,
                submitted_at=NOW,
                theoretical_price=100.0,
                requested_quantity=10.0,
                remaining_quantity=10.0,
            )
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("duplicate execution order was accepted")


def test_paper_order_lifecycle_is_idempotent_and_uses_later_bars() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        service = PaperOrderLifecycleService()
        created = service.submit(db, order(quantity=100))
        duplicate = service.submit(db, order(quantity=100))
        assert created.id == duplicate.id
        assert created.status == "SUBMITTED"

        first = service.process_order(
            db, created, [bar(0), bar(1, volume=500, low=99.5)]
        )
        repeated = service.process_order(db, created, [bar(1, volume=500, low=99.5)])
        second = service.process_order(db, created, [bar(2, volume=600, low=99.4)])
        fills = db.scalars(
            select(PaperExecutionFill).where(PaperExecutionFill.order_id == created.id)
        ).all()

    assert first["status"] == "PARTIALLY_FILLED"
    assert repeated["new_fills"] == 0
    assert second["status"] == "FILLED"
    assert len(fills) == 2
    assert created.theoretical_price == 100.0
    assert created.average_fill_price is not None
    assert all(
        fill.spread_cost + fill.slippage_cost + fill.commission_cost > 0
        for fill in fills
    )


def test_partial_fill_opens_at_expiry_and_cancels_only_remainder() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        service = PaperOrderLifecycleService()
        created = service.submit(
            db, order(quantity=100), expires_at=NOW + timedelta(minutes=2)
        )
        result = service.process_order(
            db, created, [bar(1, volume=500, low=99.5)], now=NOW + timedelta(minutes=2)
        )

    assert result["status"] == "PARTIALLY_FILLED_EXPIRED"
    assert result["filled_quantity"] == 50
    assert result["remaining_quantity"] == 50
    assert result["rejection_reason"] == "PARTIAL_FILL_REMAINDER_CANCELLED"


def test_paper_lifecycle_persists_execution_assumptions_and_costs() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        service = PaperOrderLifecycleService()
        created = service.submit(
            db,
            order(
                quantity=10,
                account_currency="EUR",
                currency="USD",
                fx_rate=1.08,
                fx_spread_bps=5.0,
                liquidity_score=40.0,
                liquidity_basis="otc_quote_capacity",
                quote_capacity_units=1_000.0,
                allowed_sessions=("regular", "closing_auction"),
            ),
        )
        result = service.process_order(db, created, [bar(1, low=99.5, volume=0)])
        fill = db.scalar(
            select(PaperExecutionFill).where(PaperExecutionFill.order_id == created.id)
        )

    assert result["status"] == "FILLED"
    assert created.order_payload["fx_spread_bps"] == 5.0
    assert created.order_payload["liquidity_score"] == 40.0
    assert created.order_payload["liquidity_basis"] == "otc_quote_capacity"
    assert created.order_payload["quote_capacity_units"] == 1_000.0
    assert created.order_payload["allowed_sessions"] == ["regular", "closing_auction"]
    assert fill.fx_cost > 0
    assert fill.fill_payload["account_currency"] == "EUR"
    assert fill.fill_payload["liquidity_basis"] == "otc_quote_capacity"


def test_lifecycle_excludes_future_and_post_expiry_bars() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        service = PaperOrderLifecycleService()
        expired = service.submit(
            db,
            order(order_key="expired", quantity=10),
            expires_at=NOW + timedelta(minutes=5),
        )
        result = service.process_order(
            db, expired, [bar(6)], now=NOW + timedelta(minutes=10)
        )
        assert result["filled_quantity"] == 0
        assert result["status"] == "EXPIRED"
        future = service.submit(db, order(order_key="future", quantity=10))
        result = service.process_order(
            db, future, [bar(10)], now=NOW + timedelta(minutes=2)
        )
        assert result["filled_quantity"] == 0


def test_expiry_excludes_boundary_but_allows_delayed_processing_of_earlier_bar() -> (
    None
):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        service = PaperOrderLifecycleService()
        row = service.submit(
            db, order(quantity=100), expires_at=NOW + timedelta(minutes=2)
        )
        result = service.process_order(
            db,
            row,
            [bar(1, volume=100), bar(2, volume=10000)],
            now=NOW + timedelta(minutes=4),
        )
        assert result["filled_quantity"] == 10
        assert result["remaining_quantity"] == 90
        assert result["status"] == "PARTIALLY_FILLED_EXPIRED"


def test_stop_limit_activation_survives_restart() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        row = PaperOrderLifecycleService().submit(
            db,
            order(order_type="STOP_LIMIT", stop_price=100, limit_price=99, quantity=10),
        )
        first = PaperOrderLifecycleService().process_order(
            db,
            row,
            [bar(1, open=101, high=102, low=100.5, close=101)],
            now=NOW + timedelta(minutes=1),
        )
        assert first["new_fills"] == 0
        db.commit()
        order_id = row.id
    with Session(engine) as db:
        row = db.get(PaperExecutionOrder, order_id)
        result = PaperOrderLifecycleService().process_order(
            db,
            row,
            [bar(2, open=98.5, high=99.5, low=98, close=99)],
            now=NOW + timedelta(minutes=2),
        )
        assert result["status"] == "FILLED"
        assert row.average_fill_price <= 99
        assert (
            row.order_payload["stop_activated_at"]
            == (NOW + timedelta(minutes=1)).isoformat()
        )


def test_gap_execution_obeys_limit_and_observed_prices() -> None:
    result = RealisticExecutionEngine().evaluate(
        order(
            order_type="STOP_LIMIT", stop_price=100, limit_price=100.005, quantity=10
        ),
        [bar(1, open=110, high=111, low=109, close=110)],
    )
    assert result.fills == ()
    stopped = RealisticExecutionEngine().evaluate(
        order(order_type="STOP", stop_price=100, quantity=10),
        [bar(1, open=110, high=111, low=109, close=110)],
    )
    assert stopped.fills[0].reference_price == 110
    assert stopped.fills[0].executed_price >= 110


def test_stop_limit_ambiguous_intrabar_path_withholds_fill() -> None:
    result = RealisticExecutionEngine().evaluate(
        order(order_type="STOP_LIMIT", stop_price=101, limit_price=100, quantity=10),
        [bar(1, open=99, low=98, high=102, close=100.5)],
    )
    assert result.fills == ()


def test_latency_not_reset_on_poll() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        service = PaperOrderLifecycleService()
        row = service.submit(db, order(latency_bars=2, quantity=10))
        for minute in (1, 2):
            assert (
                service.process_order(
                    db, row, [bar(minute)], now=NOW + timedelta(minutes=minute)
                )["new_fills"]
                == 0
            )
            assert (
                service.process_order(
                    db, row, [bar(minute)], now=NOW + timedelta(minutes=minute)
                )["new_fills"]
                == 0
            )
        third = service.process_order(db, row, [bar(3)], now=NOW + timedelta(minutes=3))
        assert third["status"] == "FILLED"


def test_lifecycle_rejects_bar_acquired_after_as_of() -> None:
    from dataclasses import replace

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        row = PaperOrderLifecycleService().submit(db, order(quantity=10))
        late = replace(bar(1), available_at=NOW + timedelta(minutes=5))
        result = PaperOrderLifecycleService().process_order(
            db, row, [late], now=NOW + timedelta(minutes=2)
        )
        assert result["new_fills"] == 0


def test_lifecycle_accepts_aware_as_of_without_reinterpreting_utc() -> None:
    from datetime import timezone

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        row = PaperOrderLifecycleService().submit(
            db, order(quantity=10), expires_at=NOW + timedelta(minutes=5)
        )
        result = PaperOrderLifecycleService().process_order(
            db,
            row,
            [bar(1)],
            now=(NOW + timedelta(minutes=2)).replace(tzinfo=timezone.utc),
        )
        assert result["status"] == "FILLED"
