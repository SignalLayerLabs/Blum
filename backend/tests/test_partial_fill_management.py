"""A first fill is real exposure even while most of its order is unfilled."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import (
    LiveForwardPaperGame,
    LiveForwardPaperTrade,
    PaperExecutionOrder,
    ReplayMarketBar,
)
from app.services.intraday_paper_engine import BlumIntradayPaperEngine
from test_live_intraday_paper_engine import (
    NOW,
    setup_db,
    seed_asset,
    seed_validation,
    seed_complete_stack,
)


def partial_case(db):
    asset = seed_asset(db)
    seed_validation(db)
    seed_complete_stack(db, asset)
    clock = {"now": NOW}
    engine = BlumIntradayPaperEngine(
        now_provider=lambda: clock["now"], refresh_missing=False, account_currency="USD"
    )
    engine.run_once(db, trigger="partial-test", assets=[asset])
    trade = db.scalar(select(LiveForwardPaperTrade))
    order = db.scalar(select(PaperExecutionOrder))
    game = db.get(LiveForwardPaperGame, trade.game_id)
    game.cash = game.current_capital = game.starting_capital = 100_000
    order.requested_quantity = order.remaining_quantity = 100
    order.expires_at = NOW + timedelta(minutes=15)
    order.order_payload = {
        **order.order_payload,
        "max_participation_rate": 0.1,
        "liquidity_score": 100,
        "latency_bars": 0,
    }
    db.commit()
    return engine, clock, asset, trade, order, game


def add_bar(db, asset, minute, *, low, price, volume=100):
    db.add(
        ReplayMarketBar(
            asset_id=asset.id,
            source_symbol=asset.ticker,
            normalized_symbol=asset.ticker,
            market="USA",
            timeframe="1m",
            bar_timestamp=NOW + timedelta(minutes=minute),
            acquired_at=NOW + timedelta(minutes=minute + 2),
            open=price,
            high=price + 0.1,
            low=low,
            close=price,
            volume=volume,
            provider="fixture",
            data_quality_score=95,
            source_metadata={},
        )
    )
    db.commit()


def test_first_partial_fill_is_accounted_and_protected_before_remainder():
    with setup_db() as db:
        engine, clock, asset, trade, order, game = partial_case(db)
        price = order.theoretical_price
        add_bar(db, asset, 1, low=price - 0.05, price=price)
        clock["now"] = NOW + timedelta(minutes=3)
        engine.run_execution_once(db)
        assert order.filled_quantity == 10 and order.remaining_quantity == 90
        assert trade.status == "OPEN" and trade.position_size == 10
        assert game.open_positions == 1
        assert game.exposure == pytest.approx(trade.notional_value)
        assert game.cash + game.exposure == pytest.approx(100_000)
        add_bar(
            db,
            asset,
            3,
            low=trade.stop_loss - 0.2,
            price=trade.stop_loss + 0.1,
            volume=10000,
        )
        clock["now"] = NOW + timedelta(minutes=5)
        engine.run_execution_once(db)
        assert trade.status == "CLOSED"
        assert trade.position_size == 10
        assert order.status == "CANCELLED"
        assert order.filled_quantity == 10
        assert game.open_positions == 0 and game.exposure == 0
        settled = game.cash
        engine.run_execution_once(db)
        assert game.cash == settled


def test_additional_fills_apply_only_incremental_cash_and_weighted_entry():
    with setup_db() as db:
        engine, clock, asset, trade, order, game = partial_case(db)
        price = order.theoretical_price
        add_bar(db, asset, 1, low=price - 0.05, price=price)
        clock["now"] = NOW + timedelta(minutes=3)
        engine.run_execution_once(db)
        add_bar(db, asset, 2, low=price - 0.06, price=price - 0.01)
        clock["now"] = NOW + timedelta(minutes=4)
        engine.run_execution_once(db)
        assert order.filled_quantity == 20 and trade.position_size == 20
        assert game.open_positions == 1
        assert game.cash + trade.notional_value == pytest.approx(100_000)
        assert game.exposure == pytest.approx(trade.notional_value)
        assert trade.ledger_trade_id is not None


def test_entry_commission_is_cash_immediately_and_net_pnl_reconciles_once():
    from app.models import PaperExecutionFill

    with setup_db() as db:
        engine, clock, asset, trade, order, game = partial_case(db)
        order.order_payload = {**order.order_payload, "commission_bps": 5.0}
        trade.execution_costs = {
            **trade.execution_costs,
            "commission_bps": 5.0,
            "spread_bps": 2.0,
            "slippage_bps": 1.0,
            "liquidity_penalty_bps": 0.0,
            "one_way_bps": 7.0,
        }
        price = order.theoretical_price
        add_bar(db, asset, 1, low=price - 0.05, price=price)
        clock["now"] = NOW + timedelta(minutes=3)
        engine.run_execution_once(db)
        entry_fee = db.scalar(select(PaperExecutionFill.commission_cost))
        assert entry_fee > 0
        assert game.cash + game.exposure == pytest.approx(100_000 - entry_fee)
        entry = trade.entry_price
        add_bar(db, asset, 3, low=trade.stop_loss - 0.2, price=trade.stop_loss + 0.1)
        clock["now"] = NOW + timedelta(minutes=5)
        engine.run_execution_once(db)
        assert trade.exit_price == pytest.approx(
            trade.stop_loss * 0.9998, abs=1e-8, rel=0
        )
        exit_fee = trade.exit_price * 10 * 0.0005
        expected_net = (trade.exit_price - entry) * 10 - entry_fee - exit_fee
        assert trade.net_pnl_eur == pytest.approx(expected_net, abs=1e-6)
        assert game.cash == pytest.approx(100_000 + expected_net, abs=1e-6)
