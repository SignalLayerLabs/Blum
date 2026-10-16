from __future__ import annotations

from datetime import datetime, timedelta
import pytest

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    DashboardSnapshot,
    ForexDecision,
    ForexLearningEvidence,
    ForexPosition,
    ForexTraderCycle,
    LiveForwardPaperGame,
    LiveForwardPaperTrade,
)
from app.services.unified_paper_trading import UnifiedPaperTradingProjectionService
from app.engine.brain.trader_brain import TraderBrainService
from app.services.central_brain_runtime import SnapshotProducerService


NOW = datetime(2026, 7, 22, 12, 0)


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_game(db: Session) -> LiveForwardPaperGame:
    game = LiveForwardPaperGame(
        game_id="unified-paper-test",
        status="active",
        starting_capital=100.0,
        current_capital=115.0,
        cash=115.0,
        benchmark_ticker="SPY",
    )
    db.add(game)
    db.flush()
    return game


def seed_standard_trade(db: Session, game: LiveForwardPaperGame) -> LiveForwardPaperTrade:
    trade = LiveForwardPaperTrade(
        trade_uid="paper-standard-1",
        duplicate_key="paper-standard-1-key",
        game_id=game.id,
        ticker="NVDA",
        asset_name="Nvidia",
        asset_type="Stock",
        setup_type="momentum_breakout",
        market="us_equity",
        status="CLOSED",
        decision_timestamp=NOW - timedelta(hours=4),
        opened_at=NOW - timedelta(hours=3),
        closed_at=NOW - timedelta(hours=1),
        entry_price=100.0,
        exit_price=110.0,
        stop_loss=95.0,
        target_1=110.0,
        position_size=1.0,
        net_pnl_eur=10.0,
        gross_pnl_eur=10.5,
        r_multiple=2.0,
        excess_return_vs_benchmark=0.04,
        benchmark_return_same_period=0.06,
        outcome_label="win",
        evidence_type="PAPER_FORWARD",
        lesson_learned="Breakout confirmation held.",
    )
    db.add(trade)
    db.flush()
    return trade


def seed_intraday_forex_paper_trade(
    db: Session,
    game: LiveForwardPaperGame,
) -> LiveForwardPaperTrade:
    trade = LiveForwardPaperTrade(
        trade_uid="paper-intraday-forex-1",
        duplicate_key="paper-intraday-forex-1-key",
        game_id=game.id,
        ticker="EURJPY=X",
        asset_name="EUR/JPY",
        asset_type="Forex",
        setup_type="forex_momentum_scalp",
        side="LONG",
        accounting_status="VALID",
        accounting_version="paper-forward-direction-v2",
        market="FOREX",
        status="CLOSED",
        decision_timestamp=NOW - timedelta(hours=4),
        opened_at=NOW - timedelta(hours=3),
        closed_at=NOW - timedelta(hours=1),
        entry_price=170.0,
        exit_price=170.2,
        stop_loss=169.9,
        target_1=170.2,
        position_size=1.0,
        net_pnl_eur=2.0,
        gross_pnl_eur=2.2,
        r_multiple=2.0,
        evidence_type="INTRADAY_PAPER_FORWARD",
        trading_mode="intraday_paper",
        outcome_label="win",
    )
    db.add(trade)
    db.flush()
    return trade


def seed_forex_cycle(db: Session) -> ForexTraderCycle:
    cycle = ForexTraderCycle(
        cycle_uid="fx-cycle-unified",
        cycle_key="fx-cycle-unified-key",
        status="COMPLETED",
        session="LONDON",
        started_at=NOW - timedelta(hours=3),
        completed_at=NOW - timedelta(hours=2),
        configuration_hash="a" * 64,
        data_coverage_hash="b" * 64,
    )
    db.add(cycle)
    db.flush()
    return cycle


def seed_forex_decision(
    db: Session,
    cycle: ForexTraderCycle,
    *,
    uid: str,
    pair: str,
    status: str,
    blockers: list[str] | None = None,
    confidence: float = 74.0,
) -> ForexDecision:
    decision = ForexDecision(
        decision_uid=uid,
        cycle_id=cycle.id,
        pair=pair,
        strategy_id="fx-breakout-v1",
        status=status,
        direction="LONG",
        decision_timestamp=NOW - timedelta(hours=2),
        blockers=blockers or [],
        proposal_json={
            "setup_family": "momentum_breakout",
            "entry": 1.10,
            "stop": 1.095,
            "target": 1.11,
            "expected_r": 2.0,
            "confidence": confidence,
            "confidence_components": {
                "setup_confidence": 82.0,
                "data_confidence": 80.0,
                "strategy_confidence": 44.0,
                "execution_confidence": 71.0,
                "decision_confidence": 65.0,
            },
            "actionability_status": "BLOCKED" if blockers else "ACTIONABLE",
        },
        evidence_type="PAPER_FORWARD_FOREX",
    )
    db.add(decision)
    db.flush()
    return decision


def test_forex_confidence_is_normalized_to_dashboard_scale():
    with setup_db() as db:
        seed_game(db)
        cycle = seed_forex_cycle(db)
        normalized = seed_forex_decision(
            db,
            cycle,
            uid="fx-normalized-confidence",
            pair="EURUSD=X",
            status="REJECTED",
            blockers=["STRATEGY_NOT_READY"],
            confidence=0.55,
        )
        percent = seed_forex_decision(
            db,
            cycle,
            uid="fx-percent-confidence",
            pair="GBPUSD=X",
            status="REJECTED",
            blockers=["NO_NET_EDGE"],
            confidence=74.0,
        )
        db.commit()

        payload = UnifiedPaperTradingProjectionService().build(db)
        rows = {row["source_trade_id"]: row for row in payload["trades"]}

        assert rows[normalized.id]["confidence"] == 55.0
        assert rows[percent.id]["confidence"] == 74.0
        assert rows[normalized.id]["confidence_components"]["setup_confidence"] == 82.0
        assert rows[normalized.id]["actionability_status"] == "BLOCKED"


def seed_forex_position(
    db: Session,
    decision: ForexDecision,
    *,
    status: str,
    net_pnl: float,
    realized_r: float | None,
    suffix: str,
) -> ForexPosition:
    position = ForexPosition(
        position_uid=f"fx-position-{suffix}",
        decision_id=decision.id,
        pair=decision.pair,
        strategy_id=decision.strategy_id,
        direction=decision.direction,
        status=status,
        quantity_lots=0.01,
        entry_price=1.10,
        stop_price=1.095,
        target_price=1.11,
        current_price=1.106,
        exit_price=1.106 if status == "CLOSED" else None,
        opened_at=NOW - timedelta(hours=2),
        closed_at=NOW - timedelta(minutes=30) if status == "CLOSED" else None,
        exit_reason="TARGET_HIT" if status == "CLOSED" else None,
        gross_pnl=net_pnl + 0.5,
        net_pnl=net_pnl,
        realized_r=realized_r,
        spread_cost=0.2,
        slippage_cost=0.1,
        commission=0.2,
        margin_used=36.0,
        contract_json={
            "session": "LONDON",
            "regime": "trend_up",
            "setup_family": "momentum_breakout",
            "unrealized_net_pnl": net_pnl if status == "OPEN" else None,
            "current_r": 0.6 if status == "OPEN" else realized_r,
            "account_currency": "EUR",
        },
    )
    db.add(position)
    db.flush()
    return position


def test_projection_combines_standard_and_forex_without_double_counting():
    with setup_db() as db:
        game = seed_game(db)
        standard = seed_standard_trade(db, game)
        cycle = seed_forex_cycle(db)
        opened_decision = seed_forex_decision(db, cycle, uid="fx-opened", pair="EURUSD=X", status="OPENED")
        forex = seed_forex_position(db, opened_decision, status="CLOSED", net_pnl=5.0, realized_r=1.0, suffix="closed")
        db.add(
            ForexLearningEvidence(
                decision_id=opened_decision.id,
                position_id=forex.id,
                strategy_id=forex.strategy_id,
                pair=forex.pair,
                outcome="WIN",
                expected_result=2.0,
                realized_result=1.0,
                difference=-1.0,
                lesson="Costs reduced the expected edge.",
                evidence_strength=0.8,
                evidence_type="PAPER_FORWARD_FOREX",
                payload_json={"benchmark_excess": 0.02},
            )
        )
        rejected = seed_forex_decision(
            db,
            cycle,
            uid="fx-rejected",
            pair="GBPUSD=X",
            status="REJECTED",
            blockers=["NO_NET_EDGE"],
        )
        db.commit()

        payload = UnifiedPaperTradingProjectionService().build(db, limit=50)

        assert {row["trade_id"] for row in payload["trades"]} == {
            f"paper:{standard.id}",
            f"forex:{forex.id}",
            f"forex-decision:{rejected.id}",
        }
        assert payload["counts"]["aggregate"]["closed"] == 2
        assert payload["counts"]["aggregate"]["decisions_rejected"] == 1
        assert payload["metrics"]["aggregate"]["realized_pnl"] == 15.0
        assert payload["metrics"]["aggregate"]["win_rate"] == 1.0
        assert payload["metrics"]["aggregate"]["average_r"] == 1.5
        assert payload["metrics"]["aggregate"]["benchmark_excess"] == 0.03
        assert payload["metrics"]["by_market"]["forex"]["realized_pnl"] == 5.0
        assert payload["metrics"]["by_market"]["standard"]["realized_pnl"] == 10.0


def test_intraday_forex_paper_trade_is_classified_by_asset_not_execution_lane():
    with setup_db() as db:
        game = seed_game(db)
        equity = seed_standard_trade(db, game)
        forex = seed_intraday_forex_paper_trade(db, game)
        db.commit()

        payload = UnifiedPaperTradingProjectionService().build(db)
        rows = {row["trade_id"]: row for row in payload["trades"]}

        assert rows[f"paper:{equity.id}"]["market_group"] == "standard"
        assert rows[f"paper:{equity.id}"]["trading_lane"] == "standard"
        assert rows[f"paper:{forex.id}"]["market_group"] == "forex"
        assert rows[f"paper:{forex.id}"]["trading_lane"] == "intraday"
        assert payload["counts"]["by_market"]["equities"]["closed"] == 1
        assert payload["metrics"]["by_market"]["equities"]["realized_pnl"] == 10.0
        assert payload["counts"]["by_market"]["forex"]["closed"] == 1
        assert payload["metrics"]["by_market"]["forex"]["realized_pnl"] == 2.0
        assert payload["counts"]["aggregate"]["closed"] == 2
        assert payload["metrics"]["aggregate"]["realized_pnl"] == 12.0


def test_visible_projection_reserves_capacity_for_each_market_group():
    with setup_db() as db:
        statements: list[str] = []
        event.listen(
            db.get_bind(),
            "before_cursor_execute",
            lambda _conn, _cursor, statement, _parameters, _context, _many: statements.append(statement),
        )
        game = seed_game(db)
        standard = seed_standard_trade(db, game)
        standard.closed_at = NOW - timedelta(days=2)
        standard.opened_at = NOW - timedelta(days=2, hours=1)
        standard.decision_timestamp = NOW - timedelta(days=2, hours=2)
        cycle = seed_forex_cycle(db)
        for index in range(60):
            seed_forex_decision(
                db,
                cycle,
                uid=f"fx-volume-{index}",
                pair="EURUSD=X",
                status="REJECTED",
                blockers=["STRATEGY_NOT_READY"],
                confidence=0.55,
            )
        db.commit()

        payload = UnifiedPaperTradingProjectionService().build(db, limit=50)

        assert len(payload["trades"]) == 50
        assert f"paper:{standard.id}" in {row["trade_id"] for row in payload["trades"]}
        assert any(row["market_group"] == "forex" for row in payload["trades"])
        assert payload["pagination"]["total"] == 61
        assert payload["counts"]["aggregate"]["decisions_rejected"] == 60
        unbounded_decision_reads = [
            statement
            for statement in statements
            if "FROM forex_decisions ORDER BY forex_decisions.created_at DESC" in statement
            and "LIMIT" not in statement.upper()
        ]
        assert unbounded_decision_reads == []


def test_closed_trade_history_is_not_evicted_by_newer_skipped_candidates():
    with setup_db() as db:
        game = seed_game(db)
        closed = seed_standard_trade(db, game)
        closed.closed_at = NOW - timedelta(days=3)
        closed.opened_at = NOW - timedelta(days=3, hours=1)
        closed.decision_timestamp = NOW - timedelta(days=3, hours=2)
        for index in range(60):
            db.add(
                LiveForwardPaperTrade(
                    trade_uid=f"paper-skipped-{index}",
                    duplicate_key=f"paper-skipped-key-{index}",
                    game_id=game.id,
                    ticker=f"SKIP{index}",
                    asset_type="Stock",
                    setup_type="avoid_no_edge",
                    market="us_equity",
                    status="SKIPPED",
                    decision_timestamp=NOW + timedelta(minutes=index),
                    entry_price=100.0 + index,
                    stop_loss=95.0 + index,
                    target_1=110.0 + index,
                    evidence_type="PAPER_FORWARD",
                )
            )
        db.commit()

        payload = UnifiedPaperTradingProjectionService().build(db, limit=25)

        assert f"paper:{closed.id}" not in {row["trade_id"] for row in payload["trades"]}
        assert [row["trade_id"] for row in payload["recently_closed"]] == [f"paper:{closed.id}"]
        assert payload["recently_closed"][0]["net_pnl_eur"] == 10.0
        assert payload["counts"]["aggregate"]["total"] == 61
        assert payload["counts"]["aggregate"]["candidates"] == 60
        assert payload["candidate_pagination"]["total"] == 60
        assert payload["recently_closed_pagination"] == {
            "limit": 25,
            "returned": 1,
            "total": 1,
        }


def test_expired_unfilled_order_is_terminal_evidence_not_candidate_or_closed_trade():
    with setup_db() as db:
        game = seed_game(db)
        db.add(
            LiveForwardPaperTrade(
                trade_uid="paper-expired-unfilled",
                duplicate_key="paper-expired-unfilled-key",
                game_id=game.id,
                ticker="XOM",
                asset_type="Stock",
                setup_type="intraday_breakout",
                market="us_equity",
                status="EXPIRED",
                decision_timestamp=NOW - timedelta(hours=2),
                closed_at=NOW - timedelta(hours=1),
                entry_price=None,
                exit_price=None,
                net_pnl_eur=None,
                outcome_label="ORDER_NOT_FILLED",
                close_reason="ORDER_NOT_FILLED",
                evidence_type="INTRADAY_PAPER_FORWARD",
                trading_mode="intraday_paper",
            )
        )
        db.commit()

        payload = UnifiedPaperTradingProjectionService().build(db)
        counts = payload["counts"]["by_market"]["equities"]

        assert counts["total"] == 1
        assert counts["candidates"] == 0
        assert counts["closed"] == 0
        assert counts["terminal_outcomes"] == 1
        assert counts["no_fill_outcomes"] == 1
        assert payload["metrics"]["by_market"]["equities"]["sample_size"] == 0
        assert payload["recently_closed_pagination"]["total"] == 1


def test_executed_closures_remain_visible_when_new_unfilled_orders_dominate_history():
    with setup_db() as db:
        game = seed_game(db)
        filled = seed_standard_trade(db, game)
        for index in range(8):
            db.add(LiveForwardPaperTrade(
                trade_uid=f'unfilled-{index}', duplicate_key=f'unfilled-{index}', game_id=game.id,
                ticker='XLP', asset_name='XLP', asset_type='ETF', market='us_equity', setup_type='test',
                status='EXPIRED', decision_timestamp=NOW, closed_at=NOW, opened_at=None,
                position_size=0, entry_price=None, net_pnl_eur=None,
            ))
        db.commit()
        value = UnifiedPaperTradingProjectionService().build(db, limit=2)
        assert [row['source_trade_id'] for row in value.get('executed_closures', [])] == [filled.id]
        assert len(value['unfilled_orders']) == 2
        assert all(row['net_pnl'] is None for row in value['unfilled_orders'])


def test_native_forex_projection_uses_frozen_currency_and_nested_valuation():
    with setup_db() as db:
        cycle = seed_forex_cycle(db)
        decision = seed_forex_decision(db, cycle, uid='usd-open', pair='EURUSD=X', status='APPROVED')
        position = seed_forex_position(db, decision, status='OPEN', net_pnl=2.5, realized_r=None, suffix='usd-open')
        position.contract_json = {'account_currency': 'USD', 'valuation': {'unrealized_net_pnl': 3.75, 'current_r': 0.5}}
        db.commit()
        value = UnifiedPaperTradingProjectionService().build(db)['open_positions'][0]
        assert value.get('pnl_currency') == 'USD'
        assert value['unrealized_pnl'] == 3.75
        assert value['r_multiple'] == 0.5


def test_forex_net_cost_treats_negative_swap_as_a_charge():
    with setup_db() as db:
        cycle = seed_forex_cycle(db)
        decision = seed_forex_decision(db, cycle, uid='swap-close', pair='EURUSD=X', status='APPROVED')
        position = seed_forex_position(db, decision, status='CLOSED', net_pnl=4.8, realized_r=1.0, suffix='swap-close')
        position.gross_pnl = 5.5
        position.swap_accrued = -0.2
        db.commit()
        value = UnifiedPaperTradingProjectionService().build(db)['executed_closures'][0]
        assert abs(value['costs']['total'] - (value['gross_pnl'] - value['net_pnl'])) < 1e-8


def test_non_eur_forex_amount_is_not_mislabeled_as_eur():
    with setup_db() as db:
        cycle = seed_forex_cycle(db)
        decision = seed_forex_decision(db, cycle, uid='usd-close', pair='EURUSD=X', status='APPROVED')
        position = seed_forex_position(db, decision, status='CLOSED', net_pnl=5, realized_r=1.0, suffix='usd-close')
        position.contract_json = {'account_currency': 'USD'}
        db.commit()
        value = UnifiedPaperTradingProjectionService().build(db)['recently_closed'][0]
        assert value['net_pnl_eur'] is None
        assert value['gross_pnl_eur'] is None
        assert value['net_pnl'] == 5


def test_market_monetary_metrics_do_not_pool_different_account_currencies():
    with setup_db() as db:
        game = seed_game(db)
        paper = seed_intraday_forex_paper_trade(db, game)
        paper.net_pnl_eur = 10
        cycle = seed_forex_cycle(db)
        decision = seed_forex_decision(db, cycle, uid='mixed-currency', pair='EURUSD=X', status='APPROVED')
        position = seed_forex_position(db, decision, status='CLOSED', net_pnl=-5, realized_r=-1, suffix='mixed-currency')
        position.contract_json = {'account_currency':'USD'}
        db.commit()
        metrics = UnifiedPaperTradingProjectionService().build(db)['metrics']['by_market']['forex']
        assert metrics['realized_pnl'] is None
        assert metrics['profit_factor'] is None
        assert metrics['max_drawdown'] is None
        assert metrics['pnl_currency'] is None
        assert metrics['realized_pnl_by_currency'] == {'EUR':10, 'USD':-5}
        assert metrics['win_rate'] == 0.5


@pytest.mark.parametrize('status', ['OPEN', 'CLOSED'])
def test_intraday_paper_currency_comes_from_its_frozen_account_contract(status):
    with setup_db() as db:
        game = seed_game(db)
        trade = seed_intraday_forex_paper_trade(db, game)
        trade.frozen_decision_payload = {'accounting':{'account_currency':'USD'}}
        trade.status = status
        if status == 'OPEN':
            trade.closed_at = None
            trade.exit_price = None
            trade.net_pnl_eur = None
            trade.unrealized_pnl = 2
        db.commit()
        row = UnifiedPaperTradingProjectionService().build(db)['open_positions' if status == 'OPEN' else 'executed_closures'][0]
        assert row['pnl_currency'] == 'USD'
        assert row['unrealized_pnl' if status == 'OPEN' else 'net_pnl'] == 2
        assert row['net_pnl_eur'] is None


def test_conflicting_account_contracts_leave_money_currency_unverified():
    with setup_db() as db:
        game = seed_game(db)
        trade = seed_intraday_forex_paper_trade(db, game)
        trade.frozen_decision_payload = {'accounting':{'account_currency':'USD'}}
        trade.execution_costs = {'accounting':{'account_currency':'EUR'}}
        db.commit()
        row = UnifiedPaperTradingProjectionService().build(db)['executed_closures'][0]
        assert row['pnl_currency'] is None
        assert row['net_pnl_eur'] is None


def test_open_forex_position_affects_only_unrealized_metrics():
    with setup_db() as db:
        seed_game(db)
        cycle = seed_forex_cycle(db)
        decision = seed_forex_decision(db, cycle, uid="fx-open-only", pair="USDJPY=X", status="OPENED")
        seed_forex_position(db, decision, status="OPEN", net_pnl=2.5, realized_r=None, suffix="open")
        db.commit()

        payload = UnifiedPaperTradingProjectionService().build(db)

        assert payload["counts"]["aggregate"]["open"] == 1
        assert payload["counts"]["aggregate"]["closed"] == 0
        assert payload["metrics"]["aggregate"]["realized_pnl"] is None
        assert payload["metrics"]["aggregate"]["unrealized_pnl"] == 2.5


def test_partial_execution_is_open_exposure_with_unrealized_result():
    with setup_db() as db:
        game = seed_game(db)
        trade = seed_standard_trade(db, game)
        trade.status = 'PARTIALLY_FILLED'
        trade.closed_at = None
        trade.exit_price = None
        trade.net_pnl_eur = None
        trade.unrealized_pnl = 2.5
        db.commit()
        payload = UnifiedPaperTradingProjectionService().build(db)
        assert payload['counts']['by_market']['equities']['open'] == 1
        assert payload['metrics']['by_market']['equities']['unrealized_pnl'] == 2.5
        assert payload['open_positions'][0]['source_trade_id'] == trade.id
        assert payload["metrics"]["aggregate"]["win_rate"] is None


def test_latest_is_snapshot_only_and_detail_is_source_aware():
    with setup_db() as db:
        game = seed_game(db)
        standard = seed_standard_trade(db, game)
        cycle = seed_forex_cycle(db)
        decision = seed_forex_decision(db, cycle, uid="fx-detail", pair="EURJPY=X", status="OPENED")
        forex = seed_forex_position(db, decision, status="CLOSED", net_pnl=-2.0, realized_r=-1.0, suffix="detail")
        db.commit()
        service = UnifiedPaperTradingProjectionService()

        missing = service.latest(db)
        assert missing["snapshot_status"] == "missing"
        assert db.scalar(select(func.count(DashboardSnapshot.id))) == 0

        service.publish(db)
        snapshot_count = db.scalar(select(func.count(DashboardSnapshot.id)))
        latest = service.latest(db)
        assert latest["snapshot_status"] == "ready"
        assert db.scalar(select(func.count(DashboardSnapshot.id))) == snapshot_count

        paper_detail = service.detail(db, "paper_forward", standard.id)
        forex_detail = service.detail(db, "forex_trader", forex.id)
        rejected = seed_forex_decision(db, cycle, uid="fx-detail-rejected", pair="GBPJPY=X", status="REJECTED")
        db.commit()
        rejected_detail = service.detail(db, "forex_decision", rejected.id)
        assert paper_detail["trade"]["trade_id"] == f"paper:{standard.id}"
        assert forex_detail["trade"]["trade_id"] == f"forex:{forex.id}"
        assert forex_detail["decision"]["decision_uid"] == "fx-detail"
        assert rejected_detail["trade"]["trade_id"] == f"forex-decision:{rejected.id}"
        assert rejected_detail["events"][0]["event_type"] == "DECISION_RECORDED"


def test_forex_evidence_reaches_alpha_and_brain_from_same_snapshot():
    with setup_db() as db:
        seed_game(db)
        cycle = seed_forex_cycle(db)
        decision = seed_forex_decision(db, cycle, uid="fx-brain", pair="EURUSD=X", status="OPENED")
        position = seed_forex_position(db, decision, status="CLOSED", net_pnl=4.0, realized_r=1.25, suffix="brain")
        db.add(
            ForexLearningEvidence(
                decision_id=decision.id,
                position_id=position.id,
                strategy_id=position.strategy_id,
                pair=position.pair,
                outcome="WIN",
                realized_result=1.25,
                lesson="Forex edge survived execution costs.",
                evidence_strength=0.8,
                evidence_type="PAPER_FORWARD_FOREX",
                payload_json={"benchmark_excess": 0.01, "benchmark_return": 0.02},
            )
        )
        db.commit()
        UnifiedPaperTradingProjectionService().publish(db)

        alpha = TraderBrainService().alpha(db)
        brain = TraderBrainService().brain(db)

        assert alpha["evidence_split"]["forex_paper_forward"]["sample_size"] == 1
        assert alpha["evidence_split"]["forex_paper_forward"]["realized_pnl"] == 4.0
        assert alpha["combined_paper_forward_performance"]["counts"]["closed"] == 1
        assert brain["paper_trading_performance"]["metrics"]["realized_pnl"] == 4.0


def test_runtime_warmup_can_produce_unified_snapshot_without_trading_side_effects():
    with setup_db() as db:
        game = seed_game(db)
        trade = seed_standard_trade(db, game)
        db.commit()

        result = SnapshotProducerService().produce(db, "unified_paper_trading_summary")
        source_count = db.scalar(select(func.count(LiveForwardPaperTrade.id)))
        latest = UnifiedPaperTradingProjectionService().latest(db)

        assert result["status"] == "ready"
        assert source_count == 1
        assert latest["trades"][0]["trade_id"] == f"paper:{trade.id}"
