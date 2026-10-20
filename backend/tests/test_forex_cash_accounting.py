"""Cashflow expectations use base units, actual bid/ask fills and cash charges."""

from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import ForexLearningEvidence, LiveForwardPaperGame
from app.services.forex_contracts import ForexQuote
from app.services.forex_trader import BlumForexPositionManagerAgent
from test_alpha_desk import db, forex_source, NOW


def cash_position(db, side="LONG", *, quantity=0.01, pair="EURUSD=X"):
    decision, position = forex_source(db)
    position.pair = pair
    position.direction = side
    position.quantity_lots = quantity
    position.opened_at = NOW
    position.entry_price = 1.100062 if side == "LONG" else 1.119938
    position.stop_price = 1.095 if side == "LONG" else 1.125
    position.target_price = 1.30 if side == "LONG" else 0.90
    position.commission = 0.03
    position.spread_cost = 0.045
    position.slippage_cost = 0.011
    position.margin_used = 30
    position.contract_json = {
        "accounting_version": "forex-cashflow-v2",
        "account_currency": "EUR",
        "entry": 1.10 if side == "LONG" else 1.12,
        "session": "LONDON",
        "liquidity_score": 0.9,
        "volatility_score": 0.5,
        "event_impact": "LOW_IMPACT",
        "expected_holding_minutes": 30,
        "accounting": {
            "version": "forex-cashflow-v2",
            "original_quantity_lots": quantity,
            "remaining_quantity_lots": quantity,
            "entry_commission": 0.03,
            "initial_risk_account": 5,
            "initial_margin": 30,
            "entry_notional_account": 1000,
            "closes": [],
            "posted_net": 0,
            "swap_remaining": 0,
            "swap_date": NOW.date().isoformat(),
        },
    }
    db.flush()
    return position


@pytest.mark.parametrize("side,end", [("LONG", 1.12), ("SHORT", 1.10)])
def test_closed_cash_pnl_uses_executable_fills_and_current_conversion_without_double_spread(
    db, side, end
):
    position = cash_position(db, side)
    now = NOW + timedelta(minutes=31)
    quote = ForexQuote(end - 0.00005, end + 0.00005, now, "test-feed")
    result = BlumForexPositionManagerAgent().manage(db, {"EURUSD=X": quote}, now=now)
    assert result["trades_closed"] == 1
    quote_profit = (
        (position.exit_price - position.entry_price)
        * 1000
        * (1 if side == "LONG" else -1)
    )
    # Positive USD P/L buys EUR at the ask; fees are already EUR cash.
    expected_gross = quote_profit / quote.ask
    assert position.gross_pnl == pytest.approx(expected_gross)
    assert position.net_pnl == pytest.approx(expected_gross - 0.06)
    assert position.contract_json["accounting"]["reconciled"] is True


def test_partial_close_keeps_remaining_exposure_and_waits_for_a_new_quote(db):
    position = cash_position(db, quantity=0.02)
    db.add(
        LiveForwardPaperGame(
            game_id="cash-game",
            current_capital=1000,
            cash=1000,
            exposure=30,
            open_positions=1,
        )
    )
    db.flush()
    manager = BlumForexPositionManagerAgent()
    manager.brokers._profiles["paper_eu_30x"] = replace(
        manager.brokers.get(), maximum_immediate_fill_lots=0.01
    )
    now = NOW + timedelta(minutes=31)
    quote = ForexQuote(1.11995, 1.12005, now, "test-feed")
    first = manager.manage(db, {"EURUSD=X": quote}, now=now)
    assert first["trades_closed"] == 0
    assert position.status == "OPEN" and position.closed_at is None
    assert position.contract_json["accounting"][
        "remaining_quantity_lots"
    ] == pytest.approx(0.01)
    assert position.margin_used == pytest.approx(15)
    assert db.scalar(select(ForexLearningEvidence)) is None
    cash = db.scalar(select(LiveForwardPaperGame)).cash
    manager.manage(db, {"EURUSD=X": quote}, now=now + timedelta(seconds=1))
    assert len(position.contract_json["accounting"]["closes"]) == 1
    assert db.scalar(select(LiveForwardPaperGame)).cash == cash
    later = now + timedelta(minutes=1)
    second = manager.manage(
        db, {"EURUSD=X": ForexQuote(1.12095, 1.12105, later, "test-feed")}, now=later
    )
    assert second["trades_closed"] == 1 and position.status == "CLOSED"
    assert len(position.contract_json["accounting"]["closes"]) == 2
    assert db.scalar(select(LiveForwardPaperGame)).cash == pytest.approx(
        1000 + position.net_pnl
    )
    assert db.scalar(select(LiveForwardPaperGame)).exposure == 0
    assert db.scalar(select(LiveForwardPaperGame)).open_positions == 0


def test_missing_conversion_does_not_prevent_an_exit_or_invent_account_cash(db):
    position = cash_position(db, pair="GBPUSD=X")
    db.add(
        LiveForwardPaperGame(
            game_id="pending-game",
            current_capital=1000,
            cash=1000,
            exposure=60,
            open_positions=2,
        )
    )
    db.flush()
    now = NOW + timedelta(minutes=31)
    manager = BlumForexPositionManagerAgent()
    quote = ForexQuote(1.11995, 1.12005, now, "test-feed")
    first = manager.manage(db, {"GBPUSD=X": quote}, now=now)
    assert first["trades_closed"] == 0
    assert position.status == "SETTLEMENT_PENDING"
    assert position.closed_at == now and position.exit_price is not None
    assert position.contract_json["accounting"]["reconciled"] is False
    assert db.scalar(select(ForexLearningEvidence)) is None
    later = now + timedelta(minutes=1)
    final = manager.manage(
        db, {"EURUSD=X": ForexQuote(1.14995, 1.15005, later, "test-feed")}, now=later
    )
    assert final["trades_closed"] == 1 and position.status == "CLOSED"
    usd = (position.exit_price - position.entry_price) * 1000
    assert position.net_pnl == pytest.approx(usd / 1.15005 - 0.06)
    assert position.contract_json["accounting"]["settled_at"] == later.isoformat()
    assert db.scalar(select(LiveForwardPaperGame)).open_positions == 1


def test_negative_native_profit_converts_at_the_debit_side(db):
    position = cash_position(db)
    now = NOW + timedelta(minutes=31)
    quote = ForexQuote(1.08995, 1.09005, now, "test-feed")
    BlumForexPositionManagerAgent().manage(db, {"EURUSD=X": quote}, now=now)
    usd = (position.exit_price - position.entry_price) * 1000
    assert usd < 0
    assert position.net_pnl == pytest.approx(usd / quote.bid - 0.06)


def test_new_core_fills_freeze_a_cash_ledger_at_entry(db):
    from app.services.forex_trader import BlumForexTraderCore
    from app.models import ForexPosition
    from test_forex_trader_core import market_input, strategy, NOW as ENTRY

    db.add(
        LiveForwardPaperGame(
            game_id="entry-game", current_capital=1000, starting_capital=1000, cash=1000
        )
    )
    db.flush()
    core = BlumForexTraderCore()
    result = core.run_cycle(
        db,
        inputs=[market_input()],
        strategies={"EURUSD=X": strategy()},
        now=ENTRY,
        cycle_key="cash-entry",
    )
    assert result["trades_opened"] == 0
    from dataclasses import replace

    initial = market_input()
    later = ENTRY + timedelta(minutes=1)
    result = core.run_cycle(
        db,
        inputs=[
            replace(initial, as_of=later, quote=replace(initial.quote, timestamp=later))
        ],
        strategies={},
        now=later,
        cycle_key="cash-entry-fill",
    )
    assert result["trades_opened"] == 1
    position = db.scalar(select(ForexPosition))
    assert position.contract_json["accounting_version"] == "forex-cashflow-v2"
    ledger = position.contract_json["accounting"]
    assert ledger["original_quantity_lots"] == position.quantity_lots
    assert ledger["remaining_quantity_lots"] == position.quantity_lots
    assert ledger["entry_commission"] == position.commission
    assert ledger["initial_risk_account"] > 0
    assert ledger["closes"] == []
