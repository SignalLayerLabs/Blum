"""Execution boundary tests, independent of strategy approval."""

from dataclasses import replace
from datetime import timedelta

import pytest

from app.services.forex_broker import BlumForexBrokerProfileService
from app.services.forex_contracts import ForexDirection, ForexOrderRequest, ForexQuote
from app.services.forex_execution import BlumForexExecutionSimulator
from test_forex_trader_core import NOW
from test_alpha_desk import db, forex_source


def order():
    return ForexOrderRequest(
        "EURUSD=X",
        ForexDirection.LONG,
        "MARKET",
        0.01,
        1.10,
        stop_price=1.095,
        target_price=1.12,
    )


@pytest.mark.parametrize(
    "bid,ask", [(float("nan"), 1.1), (1.1, float("inf")), (True, 1.1)]
)
def test_non_finite_or_boolean_quotes_are_not_market_prices(bid, ask):
    with pytest.raises(ValueError, match="quote"):
        ForexQuote(bid, ask, NOW, "test")


@pytest.mark.parametrize("age,reason", [(181, "STALE_QUOTE"), (-1, "FUTURE_QUOTE")])
@pytest.mark.parametrize("closing", [False, True])
def test_execution_requires_an_observation_at_or_before_now_within_the_freshness_budget(
    age, reason, closing
):
    simulator = BlumForexExecutionSimulator()
    quote = ForexQuote(1.09995, 1.10005, NOW - timedelta(seconds=age), "test")
    broker = BlumForexBrokerProfileService().get()
    result = (
        simulator.close(order(), quote, broker, reason="TIME_STOP", now=NOW)
        if closing
        else simulator.submit(order(), quote, broker, now=NOW)
    )
    assert result.status == "REJECTED"
    assert result.rejection_reason == reason
    assert result.fill_price is None and result.filled_quantity_lots == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"side": ForexDirection.WATCH},
        {"quantity_lots": float("nan")},
        {"quantity_lots": float("inf")},
        {"theoretical_price": -1},
    ],
)
def test_invalid_order_cannot_create_a_fill(changes):
    simulator = BlumForexExecutionSimulator()
    quote = ForexQuote(1.09995, 1.10005, NOW, "test")
    result = simulator.submit(
        replace(order(), **changes),
        quote,
        BlumForexBrokerProfileService().get(),
        now=NOW,
    )
    assert result.status == "REJECTED"
    assert result.rejection_reason == "INVALID_ORDER"
    assert result.fill_price is None and result.filled_quantity_lots == 0


def test_a_rejected_close_does_not_become_a_completed_trade(db):
    from app.models import ForexLearningEvidence
    from app.services.forex_trader import BlumForexPositionManagerAgent
    from sqlalchemy import select

    decision, position = forex_source(db)
    position.quantity_lots = 0.01
    manager = BlumForexPositionManagerAgent()
    manager.brokers._profiles["paper_eu_30x"] = replace(
        manager.brokers.get(), minimum_lot=0.05
    )
    now = position.opened_at + timedelta(minutes=31)
    quote = ForexQuote(1.1100, 1.1101, now, "test")
    value = manager.manage(db, {"EURUSD=X": quote}, now=now)
    assert value["trades_closed"] == 0
    assert (
        position.status == "OPEN"
        and position.closed_at is None
        and position.exit_price is None
    )
    assert db.scalar(select(ForexLearningEvidence)) is None
