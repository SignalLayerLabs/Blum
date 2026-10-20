from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import ForexPosition
from app.services.forex_contracts import ForexDirection, ForexOrderRequest, ForexQuote
from test_forex_trader_core import db, NOW
from test_alpha_desk import forex_source


def pending(db, *, pair="EURUSD=X", quantity=0.02, expiry_minutes=5):
    from app.services.forex_order_lifecycle import ForexOrderLifecycle

    decision, old = forex_source(db)
    db.delete(old)
    db.flush()
    decision.pair = pair
    decision.decision_timestamp = NOW
    decision.risk_json = {"risk_amount": 20.0, "margin_required": 2000 / 30}
    decision.proposal_json = {"expected_holding_minutes": 30, "account_currency": "EUR"}
    mid = {"EURUSD=X": 1.1, "USDJPY=X": 150.0, "AUDJPY=X": 100.0}[pair]
    distance = 0.005 if pair == "EURUSD=X" else 0.1
    request = ForexOrderRequest(
        pair,
        ForexDirection.LONG,
        "MARKET",
        quantity,
        mid,
        mid - distance,
        mid + 4 * distance,
        session="LONDON",
        liquidity_score=0.9,
        volatility_score=0.5,
    )
    service = ForexOrderLifecycle()
    service.brokers._profiles["paper_eu_30x"] = replace(
        service.brokers.get(), maximum_immediate_fill_lots=0.01
    )
    row = service.submit(
        db,
        decision_id=decision.id,
        order=request,
        expires_at=NOW + timedelta(minutes=expiry_minutes),
    )
    return service, row


def test_forex_waits_for_a_real_later_quote_and_deduplicates_partial_fill(db):
    service, row = pending(db)
    quote = ForexQuote(1.09995, 1.10005, NOW, "fixture")
    assert (
        service.process(db, order_uid=row.order_uid, quote=quote, as_of=NOW)[
            "new_fills"
        ]
        == 0
    )
    later = replace(quote, timestamp=NOW + timedelta(minutes=1))
    first = service.process(
        db, order_uid=row.order_uid, quote=later, as_of=later.timestamp
    )
    position = db.scalar(select(ForexPosition))
    assert first["new_fills"] == 1 and position.status == "OPEN"
    assert position.quantity_lots == 0.01 and row.remaining_lots == 0.01
    again = service.process(
        db,
        order_uid=row.order_uid,
        quote=later,
        as_of=later.timestamp + timedelta(seconds=1),
    )
    assert again["new_fills"] == 0 and position.quantity_lots == 0.01


def test_forex_expiry_cancels_remainder_without_erasing_filled_exposure(db):
    service, row = pending(db, expiry_minutes=2)
    quote = ForexQuote(1.09995, 1.10005, NOW + timedelta(minutes=1), "fixture")
    service.process(db, order_uid=row.order_uid, quote=quote, as_of=quote.timestamp)
    result = service.process(
        db,
        order_uid=row.order_uid,
        quote=replace(quote, timestamp=NOW + timedelta(minutes=3)),
        as_of=NOW + timedelta(minutes=3),
    )
    assert result["status"] == "PARTIALLY_FILLED_EXPIRED"
    assert db.scalar(select(ForexPosition)).quantity_lots == 0.01


def test_forex_requires_observed_account_conversion_for_cross_pair(db):
    service, row = pending(db, pair="AUDJPY=X")
    result = service.process(
        db,
        order_uid=row.order_uid,
        quote=ForexQuote(100, 100.01, NOW + timedelta(minutes=1), "fixture"),
        as_of=NOW + timedelta(minutes=1),
    )
    assert result["reason"] == "ACCOUNT_CONVERSION_UNAVAILABLE"
    assert db.scalar(select(ForexPosition)) is None


@pytest.mark.parametrize(
    "pair,mid", [("EURUSD=X", 1.1), ("USDJPY=X", 150.0), ("AUDJPY=X", 100.0)]
)
def test_forex_fill_uses_timestamped_pair_units_and_account_cash(db, pair, mid):
    from app.models import LiveForwardPaperGame
    from app.services.forex_cash_accounting import ForexCashAccounting

    game = LiveForwardPaperGame(
        game_id="fx-account",
        current_capital=10_000,
        starting_capital=10_000,
        cash=10_000,
        configuration={"account_currency": "EUR"},
    )
    db.add(game)
    db.flush()
    service, row = pending(db, pair=pair)
    at = NOW + timedelta(minutes=1)
    quotes = {
        "EURUSD=X": ForexQuote(1.09995, 1.10005, at, "fixture"),
        "USDJPY=X": ForexQuote(149.99, 150.01, at, "fixture"),
        "EURJPY=X": ForexQuote(164.99, 165.01, at, "fixture"),
    }
    quote = ForexQuote(mid - 0.00005, mid + 0.00005, at, "fixture")
    service.process(db, order_uid=row.order_uid, quote=quote, as_of=at, quotes=quotes)
    position = db.scalar(select(ForexPosition))
    assert position.quantity_lots == 0.01
    assert game.cash + game.exposure == pytest.approx(10_000 - position.commission)
    before = game.cash
    service.process(db, order_uid=row.order_uid, quote=quote, as_of=at, quotes=quotes)
    assert game.cash == before
    assert (
        position.contract_json["accounting"]["entry_conversions"][0]["at"]
        == at.isoformat()
    )


def test_forex_gap_does_not_open_beyond_the_frozen_exit_geometry(db):
    service, row = pending(db)
    at = NOW + timedelta(minutes=1)
    result = service.process(
        db,
        order_uid=row.order_uid,
        quote=ForexQuote(1.13, 1.1301, at, "fixture"),
        as_of=at,
    )
    assert result["new_fills"] == 0
    assert result["reason"] == "ENTRY_GEOMETRY_INVALIDATED"
    assert db.scalar(select(ForexPosition)) is None


def test_forex_order_keeps_its_account_when_another_game_becomes_active(db):
    from app.models import LiveForwardPaperGame

    original = LiveForwardPaperGame(
        game_id="original",
        current_capital=10_000,
        cash=10_000,
        started_at=NOW,
        configuration={"account_currency": "EUR"},
    )
    db.add(original)
    db.flush()
    service, row = pending(db)
    newer = LiveForwardPaperGame(
        game_id="newer",
        current_capital=20_000,
        cash=20_000,
        started_at=NOW + timedelta(seconds=1),
        configuration={"account_currency": "EUR"},
    )
    db.add(newer)
    db.flush()
    at = NOW + timedelta(minutes=1)
    service.process(
        db,
        order_uid=row.order_uid,
        quote=ForexQuote(1.09995, 1.10005, at, "fixture"),
        as_of=at,
    )
    assert original.cash < 10_000
    assert newer.cash == 20_000


def test_open_forex_nav_includes_cash_margin_and_costed_unrealized_result(db):
    from app.models import LiveForwardPaperGame
    from app.services.forex_trader import BlumForexPositionManagerAgent
    from app.services.forex_cash_accounting import ForexCashAccounting

    game = LiveForwardPaperGame(
        game_id="nav",
        starting_capital=10_000,
        current_capital=10_000,
        cash=10_000,
        configuration={"account_currency": "EUR"},
    )
    db.add(game)
    db.flush()
    service, row = pending(db)
    at = NOW + timedelta(minutes=1)
    quote = ForexQuote(1.09995, 1.10005, at, "fixture")
    service.process(db, order_uid=row.order_uid, quote=quote, as_of=at)
    BlumForexPositionManagerAgent().manage(db, {"EURUSD=X": quote}, now=at)
    report = ForexCashAccounting().reconcile(db, account_id="nav", as_of=at)
    # 1000 base units, 0.8? actual observed spread=1 pip plus 0.12 pip each way;
    # EUR .03 entry + .03 modeled exit commission, USD -.124 converts at debit bid.
    assert report["status"] == "RECONCILED"
    assert report["nav"] == pytest.approx(
        10_000 - 0.06 - 0.124 / 1.09995, abs=1e-7, rel=0
    )


def test_pending_order_reserves_margin_and_risk_capacity_before_fill(db):
    from app.models import LiveForwardPaperGame, ForexDecision
    from app.services.forex_trader import BlumForexTraderCore

    game = LiveForwardPaperGame(
        game_id="risk-account",
        current_capital=10_000,
        cash=10_000,
        configuration={"account_currency": "EUR"},
    )
    db.add(game)
    db.flush()
    service, row = pending(db)
    decision = db.get(ForexDecision, row.decision_id)
    decision.risk_json = {"margin_required": 2000 / 30, "risk_amount": 10}
    db.flush()
    state = BlumForexTraderCore._portfolio_state(db)
    assert state.used_margin == pytest.approx(2000 / 30)
    assert len(state.pending_orders) == 1
    assert state.open_positions == ()


def test_stale_quote_cannot_keep_an_expired_order_reserved(db):
    service, row = pending(db, expiry_minutes=2)
    result = service.process(
        db,
        order_uid=row.order_uid,
        quote=ForexQuote(1.09995, 1.10005, NOW, "fixture"),
        as_of=NOW + timedelta(minutes=10),
    )
    assert result["status"] == "EXPIRED"


def test_stop_closes_only_filled_lots_and_cancels_pending_remainder(db):
    from app.models import LiveForwardPaperGame
    from app.services.forex_trader import BlumForexPositionManagerAgent

    game = LiveForwardPaperGame(
        game_id="stop-account",
        current_capital=10_000,
        cash=10_000,
        configuration={"account_currency": "EUR"},
    )
    db.add(game)
    db.flush()
    service, row = pending(db)
    at = NOW + timedelta(minutes=1)
    service.process(
        db,
        order_uid=row.order_uid,
        quote=ForexQuote(1.09995, 1.10005, at, "fixture"),
        as_of=at,
    )
    later = at + timedelta(minutes=1)
    quote = ForexQuote(1.094, 1.0941, later, "fixture")
    BlumForexPositionManagerAgent().manage(db, {"EURUSD=X": quote}, now=later)
    service.process_batch(db, quotes={"EURUSD=X": quote}, as_of=later)
    position = db.scalar(select(ForexPosition))
    assert position.status == "CLOSED" and position.quantity_lots == 0.01
    assert row.status == "CANCELLED" and row.filled_lots == 0.01
    cash = game.cash
    service.process_batch(db, quotes={"EURUSD=X": quote}, as_of=later)
    assert game.cash == cash


def test_margin_stop_out_liquidates_only_available_quantity_and_keeps_protection(db):
    from app.models import LiveForwardPaperGame
    from app.services.forex_trader import BlumForexPositionManagerAgent

    game = LiveForwardPaperGame(
        game_id="margin-account",
        current_capital=10_000,
        cash=10_000,
        configuration={"account_currency": "EUR"},
    )
    db.add(game)
    db.flush()
    service, row = pending(db, quantity=0.04)
    service.brokers._profiles["paper_eu_30x"] = replace(
        service.brokers.get(), maximum_immediate_fill_lots=0.02
    )
    at = NOW + timedelta(minutes=1)
    quote = ForexQuote(1.09995, 1.10005, at, "fixture")
    service.process(db, order_uid=row.order_uid, quote=quote, as_of=at)
    position = db.scalar(select(ForexPosition))
    # Other realized account losses leave EUR20 equity against EUR66.67 margin.
    game.current_capital = 20
    game.cash = 20 - game.exposure
    manager = BlumForexPositionManagerAgent()
    manager.brokers._profiles["paper_eu_30x"] = replace(
        manager.brokers.get(), maximum_immediate_fill_lots=0.01
    )
    later = at + timedelta(seconds=1)
    quote = replace(quote, timestamp=later)
    result = manager.manage(db, {"EURUSD=X": quote}, now=later)
    assert result["trades_closed"] == 0
    service.process_batch(db, quotes={"EURUSD=X": quote}, as_of=later)
    assert row.status == "CANCELLED"
    assert position.contract_json["accounting"]["exit_reason"] == "MARGIN_STOP_OUT"
    assert position.contract_json["accounting"][
        "remaining_quantity_lots"
    ] == pytest.approx(0.01)
    assert position.status == "OPEN"
    cash = game.cash
    manager.manage(db, {"EURUSD=X": quote}, now=later)
    assert game.cash == cash


def test_later_quote_cannot_exceed_the_approved_cash_risk_budget(db):
    from app.models import ForexDecision

    service, row = pending(db)
    decision = db.get(ForexDecision, row.decision_id)
    decision.risk_json = {"risk_amount": 9.1, "margin_required": 2000 / 30}
    db.flush()
    at = NOW + timedelta(minutes=1)
    result = service.process(
        db,
        order_uid=row.order_uid,
        quote=ForexQuote(1.10995, 1.11005, at, "fixture"),
        as_of=at,
    )
    assert result["new_fills"] == 0
    assert result["reason"] == "RISK_BUDGET_EXCEEDED"
    assert db.scalar(select(ForexPosition)) is None
