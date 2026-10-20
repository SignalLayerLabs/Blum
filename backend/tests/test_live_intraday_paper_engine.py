from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.routes import router
from app.core.config import Settings
from app.core.database import Base
from app.models import (
    Asset,
    IntradayNoTradeDecision,
    IntradayPaperRun,
    LearningEvent,
    LiveForwardPaperGame,
    LiveForwardPaperTrade,
    LiveForwardPaperTradeEvent,
    PaperExecutionFill,
    PaperExecutionOrder,
    PriceHistory,
    ReplayMarketBar,
    ReplayStrategyValidation,
    StrategyCandidateVariant,
    StrategyFactoryRun,
    StrategyMemory,
    TradeLearningEvidence,
)
from app.services.intraday_contracts import PAPER_FORWARD_INTRADAY, PAPER_FORWARD_INTRADAY_EXPERIMENTAL
from app.services.executable_strategy import ExecutableStrategySpec, canonical_strategy_spec
from app.services.intraday_market_data import StrictIntradayDataGateway
from app.services.intraday_opportunity import IntradayPortfolioState, BlumIntradayOpportunityEngine, session_name
from app.services.intraday_paper_engine import (
    BlumIntradayPaperEngine,
    IntradayPaperLearningService,
    classify_unfilled_order,
    execution_bar_from_replay,
    intraday_snapshot_summary,
    point_in_time_fx_rate,
)
from app.services.live_forward_paper_trading import LiveForwardPaperTradingService
from app.services.promoted_strategy_registry import BlumPromotedStrategyRegistry
from app.services.replay_execution import ReplayExecutionModel
from app.services.adaptive_replay_training import ReplayTrainingConfig
from app.services import realtime
from app.services import intraday_paper_engine as intraday_module
from app.engine.brain.trader_brain import TraderBrainService


NOW = datetime(2026, 7, 13, 14, 30)


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_asset(db: Session, ticker: str = "NVDA", market: str = "United States") -> Asset:
    row = Asset(
        ticker=ticker,
        name=ticker,
        category="Stock",
        asset_type="Stock",
        sector="Technology",
        country=market,
        exchange="NASDAQ",
        currency="USD",
        is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def seed_validation(
    db: Session,
    *,
    setup_type: str = "intraday_breakout",
    sample_size: int = 500,
    verdict: str = "PROMOTED_TO_PAPER",
    markets: list[str] | None = None,
    metrics: dict | None = None,
    overfitting_score: float = 15.0,
) -> ReplayStrategyValidation:
    factory_run = StrategyFactoryRun(
        run_uid=f"fixture-{setup_type}-{sample_size}-{len(db.new)}",
        hypothesis_family="intraday_scalping",
        generation_seed=7,
        status="COMPLETED",
    )
    db.add(factory_run)
    db.flush()
    default_metrics = {
        "benchmark_excess": 4.0,
        "expectancy_r": 0.25,
        "stability_score": 75.0,
        "walk_forward_score": 70.0,
        "max_drawdown": -8.0,
        "candidate_weights": {"momentum": 0.35},
        "timeframe_stack": ["1d", "15m", "5m", "1m"],
        "entry_rules": {"trigger": "one_minute_breakout"},
        "stop_rules": {"atr_multiple": 1.0},
        "target_rules": {"risk_multiple": 1.8},
        "certification_version": "alpha_strategy_factory_v1",
        "multiple_testing_significant": True,
        "cost_coverage": 1.0,
        "data_quality_score": 90.0,
    }
    row = ReplayStrategyValidation(
        setup_type=setup_type,
        sample_size=sample_size,
        markets_json=markets or ["USA", "GERMANY"],
        windows_json=[{"id": "w1"}, {"id": "w2"}, {"id": "w3"}],
        metrics_json={**default_metrics, **(metrics or {})},
        overfitting_score=overfitting_score,
        verdict=verdict,
        explanation="fixture",
        created_at=NOW,
    )
    db.add(row)
    db.flush()
    db.add(
        StrategyCandidateVariant(
            factory_run_id=factory_run.id,
            validation_id=row.id,
            fingerprint=f"fixture-{setup_type}-{row.id}",
            family="intraday_scalping",
            setup_type=setup_type,
            market="global",
            asset_class="stocks,etfs",
            timeframe_stack=["1d", "15m", "5m", "1m"],
            lifecycle_state="PROMOTED",
            final_verdict=verdict,
            is_champion=verdict == "PROMOTED_TO_PAPER" and sample_size >= 300,
        )
    )
    db.flush()
    return row


def seed_bars(
    db: Session,
    asset: Asset,
    timeframe: str,
    *,
    count: int,
    step: timedelta,
    end: datetime = NOW,
    price_step: float = 0.08,
    volume: float = 2_000_000,
) -> None:
    start = end - step * (count - 1)
    for index in range(count):
        close = 100.0 + index * price_step
        db.add(
            ReplayMarketBar(
                asset_id=asset.id,
                source_symbol=asset.ticker,
                normalized_symbol=asset.ticker,
                market=asset.country,
                timeframe=timeframe,
                bar_timestamp=start + step * index,
                open=close - 0.04,
                high=close + 0.12,
                low=close - 0.10,
                close=close,
                volume=volume,
                provider="fixture",
                acquired_at=NOW,
                data_quality_score=95.0,
                source_metadata={"source": "test"},
            )
        )
    db.commit()


def seed_complete_stack(db: Session, asset: Asset, *, one_minute_end: datetime = NOW) -> None:
    seed_bars(db, asset, "1d", count=80, step=timedelta(days=1), end=NOW)
    seed_bars(db, asset, "15m", count=80, step=timedelta(minutes=15), end=NOW)
    seed_bars(db, asset, "5m", count=80, step=timedelta(minutes=5), end=NOW)
    seed_bars(db, asset, "1m", count=80, step=timedelta(minutes=1), end=one_minute_end)


def test_registry_returns_only_latest_fully_promoted_strategy():
    with setup_db() as db:
        promoted = seed_validation(db)
        seed_validation(db, setup_type="pullback", sample_size=299)
        rows = BlumPromotedStrategyRegistry().list_eligible(db, market="USA", asset_class="Stock")

    assert [row.validation_id for row in rows] == [promoted.id]
    assert rows[0].evidence_type == "WALK_FORWARD_EVIDENCE"
    assert rows[0].timeframe_stack == ("1d", "15m", "5m", "1m")


def test_registry_rejects_unstable_negative_or_overfit_strategy():
    with setup_db() as db:
        seed_validation(db, setup_type="unstable", metrics={"benchmark_excess": 2.0, "expectancy_r": 0.2, "stability_score": 20.0})
        seed_validation(db, setup_type="negative", metrics={"benchmark_excess": -1.0, "expectancy_r": -0.1, "stability_score": 80.0})
        seed_validation(db, setup_type="overfit", overfitting_score=80.0)
        rows = BlumPromotedStrategyRegistry().list_eligible(db, market="USA", asset_class="Stock")

    assert rows == []


def test_registry_accepts_metrics_emitted_by_alpha_strategy_factory():
    with setup_db() as db:
        promoted = seed_validation(
            db,
            metrics={
                "expectancy_r": None,
                "walk_forward_score": None,
                "net_expectancy_r": 0.25,
                "deflated_sharpe_probability": 0.97,
                "stability_score": 74.0,
            },
        )

        rows = BlumPromotedStrategyRegistry().list_eligible(
            db,
            market="USA",
            asset_class="Stock",
        )

    assert [row.validation_id for row in rows] == [promoted.id]
    assert rows[0].metrics["net_expectancy_r"] == 0.25
    assert rows[0].walk_forward_score >= 60.0


def test_registry_exposes_positive_cost_adjusted_challenger_as_experimental_only(monkeypatch):
    monkeypatch.setattr("app.services.promoted_strategy_registry.settings.intraday_experimental_min_samples", 100)
    with setup_db() as db:
        validation = seed_validation(
            db,
            sample_size=150,
            verdict="NEEDS_MORE_EVIDENCE",
            metrics={
                "net_expectancy_r": 0.18,
                "benchmark_excess": 1.5,
                "stability_score": 62.0,
                "multiple_testing_significant": False,
            },
        )

        promoted = BlumPromotedStrategyRegistry().list_eligible(db, market="USA", asset_class="Stock")
        experimental = BlumPromotedStrategyRegistry().list_experimental(db, market="USA", asset_class="Stock")

    assert promoted == []
    assert [row.validation_id for row in experimental] == [validation.id]
    assert experimental[0].metrics["evidence_lane"] == "experimental_paper"
    assert experimental[0].metrics["paper_risk_multiplier"] == 0.25


def test_registry_builds_uncertified_bootstrap_for_evidence_generation():
    strategy = BlumPromotedStrategyRegistry().bootstrap_exploration(
        market="USA",
        asset_class="Stock",
    )

    assert strategy.validation_id is None
    assert strategy.strategy_id == "bootstrap-intraday-breakout-usa-stock-v1"
    assert strategy.metrics["evidence_lane"] == "bootstrap_exploration_paper"
    assert strategy.metrics["paper_risk_multiplier"] <= 0.10
    assert strategy.metrics["certified_for_copy_readiness"] is False
    assert strategy.validated_trade_count == 0


def test_intraday_engine_uses_bootstrap_only_when_no_registry_strategy(monkeypatch):
    monkeypatch.setattr(
        "app.services.intraday_paper_engine.settings.intraday_experimental_paper_enabled",
        True,
    )
    with setup_db() as db:
        asset = seed_asset(db)
        seed_complete_stack(db, asset)
        engine = BlumIntradayPaperEngine(
            refresh_missing=False,
            now_provider=lambda: NOW,
        )

        result = engine.run_once(db, trigger="test", assets=[asset])

        trade = db.scalar(
            select(LiveForwardPaperTrade).where(
                LiveForwardPaperTrade.evidence_type
                == PAPER_FORWARD_INTRADAY_EXPERIMENTAL
            )
        )

    assert result["candidates_approved"] == 1
    assert trade is not None
    assert trade.promoted_validation_id is None
    assert trade.risk_percent <= 0.10
    assert trade.frozen_decision_payload["evidence"][
        "evidence_lane"
    ] == "bootstrap_exploration_paper"


def test_registry_accepts_measured_zero_overfitting_risk(monkeypatch):
    monkeypatch.setattr("app.services.promoted_strategy_registry.settings.intraday_experimental_min_samples", 100)
    with setup_db() as db:
        validation = seed_validation(
            db,
            sample_size=150,
            verdict="NEEDS_MORE_EVIDENCE",
            overfitting_score=0.0,
            metrics={
                "net_expectancy_r": 0.18,
                "benchmark_excess": 1.5,
                "stability_score": 62.0,
                "multiple_testing_significant": False,
            },
        )

        experimental = BlumPromotedStrategyRegistry().list_experimental(
            db,
            market="USA",
            asset_class="Stock",
        )

    assert [row.validation_id for row in experimental] == [validation.id]


def test_registry_does_not_let_newer_ineligible_row_hide_eligible_challenger(monkeypatch):
    monkeypatch.setattr("app.services.promoted_strategy_registry.settings.intraday_experimental_min_samples", 100)
    with setup_db() as db:
        eligible = seed_validation(
            db,
            sample_size=150,
            verdict="NEEDS_MORE_EVIDENCE",
            overfitting_score=10.0,
            metrics={
                "net_expectancy_r": 0.18,
                "benchmark_excess": 1.5,
                "stability_score": 62.0,
                "multiple_testing_significant": False,
            },
        )
        seed_validation(
            db,
            sample_size=10,
            verdict="NEEDS_MORE_EVIDENCE",
            overfitting_score=10.0,
            metrics={
                "net_expectancy_r": -0.1,
                "benchmark_excess": -0.5,
                "stability_score": 0.0,
            },
        )

        experimental = BlumPromotedStrategyRegistry().list_experimental(
            db,
            market="USA",
            asset_class="Stock",
        )

    assert [row.validation_id for row in experimental] == [eligible.id]


def test_experimental_intraday_strategy_uses_reduced_paper_risk(monkeypatch):
    monkeypatch.setattr("app.services.promoted_strategy_registry.settings.intraday_experimental_min_samples", 100)
    with setup_db() as db:
        asset = seed_asset(db)
        seed_validation(
            db,
            sample_size=150,
            verdict="NEEDS_MORE_EVIDENCE",
            metrics={
                "net_expectancy_r": 0.25,
                "benchmark_excess": 2.0,
                "stability_score": 75.0,
                "multiple_testing_significant": False,
            },
        )
        seed_complete_stack(db, asset)
        strategy = BlumPromotedStrategyRegistry().list_experimental(db, market="USA", asset_class="Stock")[0]
        bundle = StrictIntradayDataGateway(refresh_missing=False).load(db, asset=asset, now=NOW)

        decision = BlumIntradayOpportunityEngine().evaluate(
            strategy=strategy,
            data=bundle,
            portfolio=IntradayPortfolioState(capital=10_000.0),
            desk="NasdaqAgent",
            benchmark_ticker="QQQ",
        )

    assert decision.status == "INTRADAY_TRADE_CANDIDATE"
    assert decision.sizing is not None
    assert decision.sizing.risk_percent <= 0.25
    assert decision.evidence["evidence_lane"] == "experimental_paper"


def test_data_gateway_requires_all_four_timeframes_without_fallback():
    with setup_db() as db:
        asset = seed_asset(db)
        seed_bars(db, asset, "1d", count=80, step=timedelta(days=1))
        seed_bars(db, asset, "15m", count=80, step=timedelta(minutes=15))
        seed_bars(db, asset, "5m", count=80, step=timedelta(minutes=5))
        result = StrictIntradayDataGateway(refresh_missing=False).load(db, asset=asset, now=NOW)

    assert result.status == "INTRADAY_DATA_BLOCKED"
    assert "MISSING_1M_DATA" in result.blockers
    assert result.bars["1m"] == ()


def test_data_gateway_rejects_stale_one_minute_data():
    with setup_db() as db:
        asset = seed_asset(db)
        seed_complete_stack(db, asset, one_minute_end=NOW - timedelta(minutes=20))
        result = StrictIntradayDataGateway(refresh_missing=False, max_one_minute_age=timedelta(minutes=3)).load(db, asset=asset, now=NOW)

    assert result.status == "INTRADAY_DATA_BLOCKED"
    assert "STALE_1M_DATA" in result.blockers


def test_opportunity_rejects_expected_move_that_costs_destroy():
    with setup_db() as db:
        asset = seed_asset(db)
        strategy_row = seed_validation(db)
        seed_complete_stack(db, asset)
        strategy = BlumPromotedStrategyRegistry().list_eligible(db, market="USA", asset_class="Stock")[0]
        bundle = StrictIntradayDataGateway(refresh_missing=False).load(db, asset=asset, now=NOW)
        decision = BlumIntradayOpportunityEngine(min_expected_move_bps=500.0).evaluate(
            strategy=strategy,
            data=bundle,
            portfolio=IntradayPortfolioState(capital=10_000.0),
            desk="NasdaqAgent",
            benchmark_ticker="QQQ",
        )

    assert strategy.validation_id == strategy_row.id
    assert decision.status == "INTRADAY_BLOCKED"
    assert decision.reason_code in {"EXPECTED_MOVE_TOO_SMALL", "COSTS_KILL_EDGE"}


def test_paper_opportunity_executes_the_frozen_replay_strategy_contract():
    with setup_db() as db:
        asset = seed_asset(db)
        canonical = canonical_strategy_spec("intraday_breakout")
        executable = ExecutableStrategySpec.from_payload(
            {
                **canonical.to_payload(),
                "lookback": 5,
                "minimum_stop_percent": 0.02,
                "target_r_multiple": 2.5,
            }
        )
        seed_validation(
            db,
            metrics={
                "strategy_fingerprint": executable.fingerprint,
                "executable_strategy": executable.to_payload(),
            },
        )
        seed_complete_stack(db, asset)
        strategy = BlumPromotedStrategyRegistry().list_eligible(db, market="USA", asset_class="Stock")[0]
        bundle = StrictIntradayDataGateway(refresh_missing=False).load(db, asset=asset, now=NOW)

        decision = BlumIntradayOpportunityEngine().evaluate(
            strategy=strategy,
            data=bundle,
            portfolio=IntradayPortfolioState(capital=10_000.0),
            desk="NasdaqAgent",
            benchmark_ticker="QQQ",
        )

    risk_distance = float(decision.entry_price or 0.0) - float(decision.stop_price or 0.0)
    reward_distance = float(decision.target_price or 0.0) - float(decision.entry_price or 0.0)
    assert decision.status == "INTRADAY_TRADE_CANDIDATE", decision.to_dict()
    assert strategy.executable_strategy["strategy_fingerprint"] == executable.fingerprint
    assert decision.evidence["strategy_fingerprint"] == executable.fingerprint
    assert round(reward_distance / risk_distance, 6) == 2.5


def test_intraday_run_persists_evaluable_no_trade_decision() -> None:
    with setup_db() as db:
        asset = seed_asset(db)
        seed_validation(db)
        seed_complete_stack(db, asset)
        engine = BlumIntradayPaperEngine(
            now_provider=lambda: NOW,
            refresh_missing=False,
            account_currency="USD",
            opportunity=BlumIntradayOpportunityEngine(min_expected_move_bps=500.0),
        )

        engine.run_once(db, trigger="test", assets=[asset])
        row = db.scalar(select(IntradayNoTradeDecision).where(IntradayNoTradeDecision.ticker == "NVDA"))

    assert row is not None
    assert row.status == "PENDING"
    assert row.reason_code in {"EXPECTED_MOVE_TOO_SMALL", "COSTS_KILL_EDGE"}


def test_opportunity_rejects_duplicate_open_ticker():
    with setup_db() as db:
        asset = seed_asset(db)
        seed_validation(db)
        seed_complete_stack(db, asset)
        strategy = BlumPromotedStrategyRegistry().list_eligible(db, market="USA", asset_class="Stock")[0]
        bundle = StrictIntradayDataGateway(refresh_missing=False).load(db, asset=asset, now=NOW)
        decision = BlumIntradayOpportunityEngine().evaluate(
            strategy=strategy,
            data=bundle,
            portfolio=IntradayPortfolioState(capital=10_000.0, open_tickers=frozenset({"NVDA"})),
            desk="NasdaqAgent",
            benchmark_ticker="QQQ",
        )

    assert decision.status == "INTRADAY_BLOCKED"
    assert decision.reason_code == "TICKER_CONCENTRATION"


def test_intraday_trade_evidence_constant_is_forward_only():
    assert PAPER_FORWARD_INTRADAY == "PAPER_FORWARD_INTRADAY"
    assert PAPER_FORWARD_INTRADAY != "REPLAY_EVIDENCE"


def test_intraday_discovery_rotates_across_the_stored_asset_universe():
    with setup_db() as db:
        for index in range(25):
            asset = seed_asset(db, ticker=f"T{index:02d}", market="USA")
            db.add(
                PriceHistory(
                    asset_id=asset.id,
                    date=datetime.utcnow().date(),
                    open=100.0,
                    high=101.0,
                    low=99.0,
                    close=100.0,
                    volume=1_000_000,
                    provider="fixture",
                )
            )
        db.commit()
        engine = BlumIntradayPaperEngine(
            now_provider=lambda: NOW,
            refresh_missing=False,
            max_assets=10,
        )

        first = engine.run_once(db, trigger="test")
        second = engine.run_once(db, trigger="test")
        runs = db.scalars(
            select(IntradayPaperRun).order_by(IntradayPaperRun.id)
        ).all()
        first_tickers = set(
            runs[-2].summary_json["asset_discovery"]["selected_tickers"]
        )
        second_tickers = set(
            runs[-1].summary_json["asset_discovery"]["selected_tickers"]
        )

    assert first["assets_checked"] == 10
    assert second["assets_checked"] == 10
    assert len(first_tickers) == 10
    assert len(second_tickers) == 10
    assert first_tickers.isdisjoint(second_tickers)


def test_intraday_trade_persists_strategy_cost_and_lifecycle_metadata():
    with setup_db() as db:
        game = LiveForwardPaperGame(game_id="intraday-test", starting_capital=10_000, current_capital=10_000, cash=10_000)
        db.add(game)
        validation = seed_validation(db)
        validation_id = validation.id
        run = IntradayPaperRun(run_uid="intraday-run-test", trigger="test", status="RUNNING", started_at=NOW)
        db.add(run)
        db.flush()
        trade = LiveForwardPaperTrade(
            trade_uid="intraday-trade-test",
            game_id=game.id,
            ticker="NVDA",
            setup_type="intraday_breakout",
            status="OPEN",
            decision_timestamp=NOW,
            duplicate_key="intraday-test-key",
            trading_mode="INTRADAY_PAPER_FORWARD",
            evidence_type=PAPER_FORWARD_INTRADAY,
            promoted_validation_id=validation.id,
            intraday_run_id=run.id,
            market="USA",
            desk="NasdaqAgent",
            session_name="regular",
            timeframe_stack=["1d", "15m", "5m", "1m"],
            data_timestamps={"1m": NOW.isoformat()},
            execution_costs={"total_round_trip_bps": 5.0},
            net_expectancy_bps=18.0,
            sizing_reason="risk controlled",
            last_managed_bar_at=NOW,
        )
        db.add(trade)
        db.commit()
        stored = db.scalar(select(LiveForwardPaperTrade).where(LiveForwardPaperTrade.trade_uid == "intraday-trade-test"))

    assert stored is not None
    assert stored.evidence_type == PAPER_FORWARD_INTRADAY
    assert stored.timeframe_stack == ["1d", "15m", "5m", "1m"]
    assert stored.promoted_validation_id == validation_id


def test_run_opens_only_promoted_triggered_candidate_with_adverse_fill():
    with setup_db() as db:
        asset = seed_asset(db)
        seed_validation(db)
        seed_complete_stack(db, asset)
        observed_price = db.scalar(
            select(ReplayMarketBar.close)
            .where(ReplayMarketBar.asset_id == asset.id, ReplayMarketBar.timeframe == "1m", ReplayMarketBar.bar_timestamp <= NOW - timedelta(minutes=2))
            .order_by(ReplayMarketBar.bar_timestamp.desc())
            .limit(1)
        )
        clock = {"now": NOW}
        engine = BlumIntradayPaperEngine(now_provider=lambda: clock["now"], refresh_missing=False, account_currency="USD")

        first = engine.run_once(db, trigger="test", assets=[asset])
        second = engine.run_once(db, trigger="test", assets=[asset])
        for minute in (1, 2):
            close = float(observed_price) + 0.02
            db.add(
                ReplayMarketBar(
                    asset_id=asset.id,
                    source_symbol=asset.ticker,
                    normalized_symbol=asset.ticker,
                    market=asset.country,
                    timeframe="1m",
                    bar_timestamp=NOW + timedelta(minutes=minute),
                    open=close,
                    high=close + 0.1,
                    low=float(observed_price) - 0.1,
                    close=close,
                    volume=3_000_000,
                    provider="fixture",
                    acquired_at=NOW + timedelta(minutes=minute),
                    data_quality_score=95.0,
                    source_metadata={"source": "test"},
                )
            )
        db.commit()
        clock["now"] = NOW + timedelta(minutes=4)
        filled = engine.run_once(db, trigger="test", assets=[asset])
        trade = db.scalar(select(LiveForwardPaperTrade).where(LiveForwardPaperTrade.evidence_type == PAPER_FORWARD_INTRADAY))
        execution_order = db.scalar(select(PaperExecutionOrder).where(PaperExecutionOrder.paper_trade_id == trade.id))
        execution_fills = db.scalars(select(PaperExecutionFill).where(PaperExecutionFill.order_id == execution_order.id)).all()
        events = db.scalars(
            select(LiveForwardPaperTradeEvent)
            .where(LiveForwardPaperTradeEvent.paper_trade_id == trade.id)
            .order_by(LiveForwardPaperTradeEvent.id)
        ).all()

    assert first["trades_opened"] == 0
    assert second["trades_opened"] == 0
    assert filled["trades_opened"] == 1
    assert trade is not None
    assert execution_order.theoretical_price == observed_price
    assert execution_order.status == "FILLED"
    assert trade.entry_price is not None
    assert execution_fills
    assert sum(fill.spread_cost + fill.slippage_cost + fill.commission_cost for fill in execution_fills) > 0
    assert trade.frozen_decision_payload["evidence_type"] == PAPER_FORWARD_INTRADAY
    assert trade.frozen_decision_payload["strategy"]["fingerprint"]
    assert trade.frozen_decision_payload["strategy"]["executable_strategy"]["entry_rule"] == "breakout_close"
    assert trade.intraday_metadata["maximum_holding_minutes"] == 20
    assert events[0].event_type == "INTRADAY_TRADE_CANDIDATE"
    assert "INTRADAY_TRADE_OPENED" in [event.event_type for event in events]


def test_lifecycle_uses_only_later_one_minute_bar_and_closes_stop():
    with setup_db() as db:
        asset = seed_asset(db)
        seed_validation(db)
        seed_complete_stack(db, asset)
        clock = {"now": NOW}
        engine = BlumIntradayPaperEngine(now_provider=lambda: clock["now"], refresh_missing=False, account_currency="USD")
        opened = engine.run_once(db, trigger="test", assets=[asset])
        trade = db.scalar(select(LiveForwardPaperTrade).where(LiveForwardPaperTrade.evidence_type == PAPER_FORWARD_INTRADAY))
        frozen_payload = dict(trade.frozen_decision_payload)
        stop = float(trade.stop_loss)

        theoretical = float((trade.intraday_metadata or {})["observed_entry_price"])
        for minute in (1, 2):
            db.add(
                ReplayMarketBar(
                    asset_id=asset.id,
                    source_symbol=asset.ticker,
                    normalized_symbol=asset.ticker,
                    market=asset.country,
                    timeframe="1m",
                    bar_timestamp=NOW + timedelta(minutes=minute),
                    open=theoretical + 0.05,
                    high=theoretical + 0.2,
                    low=theoretical - 0.1,
                    close=theoretical + 0.05,
                    volume=3_000_000,
                    provider="fixture",
                    acquired_at=NOW + timedelta(minutes=minute),
                    data_quality_score=95.0,
                    source_metadata={"source": "test"},
                )
            )
        db.commit()
        clock["now"] = NOW + timedelta(minutes=4)
        filled = engine.run_once(db, trigger="test", assets=[asset])
        db.add(
            ReplayMarketBar(
                asset_id=asset.id,
                source_symbol=asset.ticker,
                normalized_symbol=asset.ticker,
                market=asset.country,
                timeframe="1m",
                bar_timestamp=NOW + timedelta(minutes=3),
                open=stop + 0.2,
                high=stop + 0.3,
                low=stop - 0.2,
                close=stop - 0.1,
                volume=3_000_000,
                provider="fixture",
                acquired_at=clock["now"],
                data_quality_score=95.0,
                source_metadata={"source": "test"},
            )
        )
        db.commit()
        incomplete = engine.run_once(db, trigger="test", assets=[asset])
        assert incomplete["trades_closed"] == 0
        clock["now"] = NOW + timedelta(minutes=5)
        closed = engine.run_once(db, trigger="test", assets=[asset])
        db.refresh(trade)

    assert opened["trades_opened"] == 0
    assert filled["trades_opened"] == 1
    assert closed["trades_closed"] == 1
    assert trade.status == "CLOSED"
    assert trade.close_reason == "STOP_HIT"
    assert trade.last_managed_bar_at == NOW + timedelta(minutes=3)
    assert trade.closed_at == NOW + timedelta(minutes=3)
    assert trade.frozen_decision_payload == frozen_payload
    assert trade.net_pnl_eur < 0


def test_closed_intraday_trade_updates_forward_memory_once_but_open_trade_does_not():
    with setup_db() as db:
        game = LiveForwardPaperGame(game_id="learning", starting_capital=100, current_capital=100, cash=100)
        db.add(game)
        db.flush()
        trade = LiveForwardPaperTrade(
            trade_uid="learning-trade",
            game_id=game.id,
            ticker="NVDA",
            setup_type="intraday_breakout",
            status="OPEN",
            decision_timestamp=NOW,
            duplicate_key="learning-trade-key",
            trading_mode="INTRADAY_PAPER_FORWARD",
            evidence_type=PAPER_FORWARD_INTRADAY,
            market="USA",
            desk="NasdaqAgent",
            session_name="regular",
            timeframe_stack=["1d", "15m", "5m", "1m"],
            entry_price=100.0,
            stop_loss=99.0,
            position_size=1.0,
            frozen_decision_payload={"regime": "trend_up"},
        )
        db.add(trade)
        db.flush()
        learning = IntradayPaperLearningService()
        assert learning.apply_closed_trade(db, trade)["status"] == "not_closed"

        trade.status = "CLOSED"
        trade.closed_at = NOW + timedelta(minutes=20)
        trade.exit_price = 102.0
        trade.net_pnl_eur = 1.9
        trade.r_multiple = 1.9
        trade.excess_return_vs_benchmark = 1.5
        trade.close_reason = "TARGET_HIT"
        first = learning.apply_closed_trade(db, trade)
        second = learning.apply_closed_trade(db, trade)
        evidence_count = len(db.scalars(select(TradeLearningEvidence)).all())
        memory_count = len(db.scalars(select(StrategyMemory)).all())
        event_count = len(db.scalars(select(LearningEvent).where(LearningEvent.event_type == "intraday_paper_trade_closed")).all())

    assert first["status"] == "applied"
    assert second["status"] == "duplicate"
    assert evidence_count == 1
    assert memory_count == 1
    assert event_count == 1


def test_experimental_intraday_trade_learns_without_becoming_certified_evidence():
    with setup_db() as db:
        game = LiveForwardPaperGame(game_id="experimental-learning", starting_capital=100, current_capital=100, cash=100)
        db.add(game)
        db.flush()
        trade = LiveForwardPaperTrade(
            trade_uid="experimental-learning-trade",
            game_id=game.id,
            ticker="AMD",
            setup_type="intraday_breakout",
            status="CLOSED",
            decision_timestamp=NOW,
            closed_at=NOW + timedelta(minutes=20),
            duplicate_key="experimental-learning-key",
            trading_mode="INTRADAY_PAPER_FORWARD",
            evidence_type=PAPER_FORWARD_INTRADAY_EXPERIMENTAL,
            market="USA",
            desk="NasdaqAgent",
            session_name="regular",
            timeframe_stack=["1d", "15m", "5m", "1m"],
            entry_price=100.0,
            exit_price=101.0,
            stop_loss=99.0,
            position_size=0.25,
            net_pnl_eur=0.24,
            r_multiple=1.0,
            close_reason="TARGET_HIT",
            frozen_decision_payload={"regime": "trend_up"},
        )
        db.add(trade)
        db.flush()

        result = IntradayPaperLearningService().apply_closed_trade(db, trade)
        snapshot = intraday_snapshot_summary(db, now=NOW)
        evidence = db.scalar(select(TradeLearningEvidence).where(TradeLearningEvidence.action_taken == f"intraday_trade:{trade.id}"))
        memory = db.scalar(select(StrategyMemory))

    assert result["status"] == "applied"
    assert evidence.supporting_trades_json["evidence_type"] == PAPER_FORWARD_INTRADAY_EXPERIMENTAL
    assert memory.memory_key.startswith("intraday_experimental:")
    assert snapshot["experimental_closed_sample_size"] == 1
    assert snapshot["closed_sample_size"] == 0


def test_intraday_snapshot_is_read_only_and_reports_no_activity_truthfully():
    with setup_db() as db:
        before = len(db.scalars(select(IntradayPaperRun)).all())
        snapshot = intraday_snapshot_summary(db, now=NOW)
        after = len(db.scalars(select(IntradayPaperRun)).all())

    assert before == after == 0
    assert snapshot["status"] == "NO_INTRADAY_RUNS"
    assert snapshot["trades_opened_today"] == 0
    assert snapshot["strategy_registry"]["status"] == "NO_PROMOTED_STRATEGIES"


def test_intraday_run_reports_data_blocked_when_no_eligible_market_data_exists():
    with setup_db() as db:
        result = BlumIntradayPaperEngine(
            now_provider=lambda: NOW,
            refresh_missing=False,
        ).run_once(db, trigger="test", assets=[])
        persisted = db.scalar(select(IntradayPaperRun).where(IntradayPaperRun.run_uid == result["run_id"]))

    assert result["status"] == "DATA_BLOCKED"
    assert persisted is not None
    assert persisted.status == "DATA_BLOCKED"
    assert result["blockers"][0]["reason"] == "NO_DESK_ASSETS_WITH_INTRADAY_DATA"


def test_intraday_discovery_allows_gateway_to_hydrate_assets_without_existing_one_minute_bars(monkeypatch):
    class StubRegistry:
        def __init__(self, *, agents):
            self.agents = agents

        def discover(self, db):
            return SimpleNamespace(
                available_agents=[
                    SimpleNamespace(
                        agent_name="NasdaqAgent",
                        benchmark="QQQ",
                        _eligible_assets=[asset],
                    )
                ]
            )

    with setup_db() as db:
        asset = seed_asset(db)
        monkeypatch.setattr(intraday_module, "MarketDeskRegistry", StubRegistry)
        discovered = BlumIntradayPaperEngine(
            now_provider=lambda: NOW,
            refresh_missing=False,
        )._discover_assets(db)

    assert discovered == [asset]


def test_intraday_discovery_includes_stored_forex_assets(monkeypatch):
    class StubRegistry:
        def __init__(self, *, agents):
            self.agents = agents

        def discover(self, db):
            return SimpleNamespace(
                available_agents=[
                    SimpleNamespace(
                        agent_name="ForexDeskAgent",
                        benchmark="UUP",
                        _eligible_assets=[asset],
                    )
                ]
            )

    with setup_db() as db:
        asset = seed_asset(db, ticker="EURUSD=X", market="Forex")
        asset.asset_type = "Forex"
        asset.category = "Currency"
        monkeypatch.setattr(intraday_module, "MarketDeskRegistry", StubRegistry)
        discovered = BlumIntradayPaperEngine(
            now_provider=lambda: NOW,
            refresh_missing=False,
        )._discover_assets(db)

    assert discovered == [asset]


def test_intraday_discovery_hydrates_forex_without_daily_price_history():
    with setup_db() as db:
        asset = seed_asset(db, ticker="EURUSD=X", market="Forex")
        asset.asset_type = "Forex"
        asset.category = "Currency"
        db.commit()

        discovered = BlumIntradayPaperEngine(
            now_provider=lambda: NOW,
            refresh_missing=True,
        )._discover_assets(db)

    assert asset in discovered


def test_replay_training_includes_forex_market_by_default():
    assert "FOREX" in ReplayTrainingConfig.from_settings().markets


def test_forex_intraday_session_and_execution_costs_are_supported():
    profile = ReplayExecutionModel().profile(
        market="FOREX",
        asset_type="Forex",
        liquidity_score=85.0,
        session=session_name("FOREX", 23),
    )

    assert session_name("FOREX", 0) == "regular"
    assert session_name("FOREX", 23) == "regular"
    assert profile.profile_name == "forex_major_liquid"
    assert 0 < profile.total_round_trip_bps < 10


def test_forex_opportunity_does_not_treat_unreported_volume_as_illiquidity():
    with setup_db() as db:
        asset = seed_asset(db, ticker="EURUSD=X", market="Forex")
        asset.asset_type = "Forex"
        asset.category = "Currency"
        seed_validation(
            db,
            markets=["FOREX"],
            metrics={"supported_asset_classes": ["Forex"]},
        )
        seed_bars(db, asset, "1d", count=80, step=timedelta(days=1), volume=0)
        seed_bars(db, asset, "15m", count=80, step=timedelta(minutes=15), volume=0)
        seed_bars(db, asset, "5m", count=80, step=timedelta(minutes=5), volume=0)
        seed_bars(db, asset, "1m", count=80, step=timedelta(minutes=1), volume=0)
        strategy = BlumPromotedStrategyRegistry().list_eligible(
            db,
            market="FOREX",
            asset_class="Forex",
        )[0]
        bundle = StrictIntradayDataGateway(refresh_missing=False).load(db, asset=asset, now=NOW)

        decision = BlumIntradayOpportunityEngine().evaluate(
            strategy=strategy,
            data=bundle,
            portfolio=IntradayPortfolioState(capital=10_000.0),
            desk="ForexDeskAgent",
            benchmark_ticker="UUP",
            asset_type="Forex",
        )

    assert decision.status == "INTRADAY_TRADE_CANDIDATE"
    assert decision.liquidity_score >= 35.0
    assert decision.evidence["liquidity_method"] == "major_fx_quote_continuity_proxy"


def test_intraday_command_is_post_only_and_settings_are_bounded():
    methods = {
        method
        for route in router.routes
        if getattr(route, "path", None) == "/api/paper-forward/run-intraday"
        for method in (route.methods or set())
    }
    settings = Settings(DATABASE_URL="sqlite:///:memory:")

    assert methods == {"POST"}
    assert settings.intraday_paper_enabled is True
    assert 1 <= settings.intraday_paper_minutes <= 60
    assert settings.intraday_max_runtime_seconds <= 120
    assert settings.paper_execution_account_currency == "EUR"


def test_point_in_time_fx_rate_uses_only_stored_bar_at_or_before_decision() -> None:
    with setup_db() as db:
        fx = seed_asset(db, ticker="EURUSD=X", market="Forex")
        fx.currency = "USD"
        db.add_all(
            [
                ReplayMarketBar(
                    asset_id=fx.id,
                    source_symbol=fx.ticker,
                    normalized_symbol=fx.ticker,
                    market="FOREX",
                    timeframe="1m",
                    bar_timestamp=NOW - timedelta(minutes=1),
                    close=1.08,
                    volume=1_000_000,
                    provider="fixture",
                    acquired_at=NOW,
                    data_quality_score=95.0,
                    source_metadata={},
                ),
                ReplayMarketBar(
                    asset_id=fx.id,
                    source_symbol=fx.ticker,
                    normalized_symbol=fx.ticker,
                    market="FOREX",
                    timeframe="1m",
                    bar_timestamp=NOW + timedelta(minutes=1),
                    close=1.50,
                    volume=1_000_000,
                    provider="fixture",
                    acquired_at=NOW,
                    data_quality_score=95.0,
                    source_metadata={},
                ),
            ]
        )
        db.commit()

        resolved = point_in_time_fx_rate(db, asset_currency="USD", account_currency="EUR", at=NOW)

    assert resolved == 1.08


def test_forex_intraday_lifecycle_reserves_margin_and_books_eur_pnl() -> None:
    with setup_db() as db:
        game = LiveForwardPaperGame(
            game_id="forex-accounting",
            starting_capital=100.0,
            current_capital=100.0,
            cash=100.0,
            exposure=0.0,
        )
        db.add(game)
        db.flush()
        trade = LiveForwardPaperTrade(
            trade_uid="forex-intraday-accounting",
            game_id=game.id,
            ticker="EURJPY=X",
            asset_type="Forex",
            setup_type="intraday_breakout",
            status="OPEN",
            decision_timestamp=NOW,
            entry_date=NOW.date(),
            entry_price=187.0,
            opened_at=NOW,
            stop_loss=186.5,
            target_1=187.5,
            position_size=187.0,
            expected_risk=0.5,
            risk_amount=0.5,
            duplicate_key="forex-intraday-accounting",
            trading_mode="INTRADAY_PAPER_FORWARD",
            evidence_type=PAPER_FORWARD_INTRADAY,
            market="FOREX",
            desk="ForexDeskAgent",
            session_name="regular",
            execution_costs={},
            frozen_decision_payload={"regime": "trend_up"},
            intraday_metadata={
                "accounting_model": "forex_margin_account_v1",
                "account_fx_rate": 187.0,
                "margin_reserved_eur": 187.0 / 30.0,
                "observed_entry_price": 187.0,
            },
        )
        db.add(trade)
        db.flush()
        order = PaperExecutionOrder(
            order_uid="forex-order",
            duplicate_key="forex-order",
            paper_trade_id=trade.id,
            ticker=trade.ticker,
            side="BUY",
            order_type="LIMIT",
            status="FILLED",
            decision_timestamp=NOW,
            submitted_at=NOW,
            theoretical_price=187.0,
            requested_quantity=187.0,
            filled_quantity=187.0,
            remaining_quantity=0.0,
            average_fill_price=187.0,
            currency="JPY",
            account_currency="EUR",
            fx_rate=187.0,
        )
        db.add(order)
        db.flush()
        engine = BlumIntradayPaperEngine(
            now_provider=lambda: NOW,
            refresh_missing=False,
        )

        engine._account_filled_order(db, game=game, trade=trade, order=order)
        margin = 187.0 / 30.0
        assert trade.notional_value == pytest.approx(187.0)
        assert game.cash == pytest.approx(100.0 - margin)
        assert game.exposure == pytest.approx(margin)

        bar = ReplayMarketBar(
            asset_id=None,
            source_symbol=trade.ticker,
            normalized_symbol=trade.ticker,
            market="FOREX",
            timeframe="1m",
            bar_timestamp=NOW + timedelta(minutes=1),
            open=187.2,
            high=187.3,
            low=187.1,
            close=187.2,
            volume=0,
            provider="fixture",
            acquired_at=NOW,
            data_quality_score=95.0,
            source_metadata={},
        )
        engine._close_trade(
            db,
            game=game,
            trade=trade,
            bar=bar,
            raw_exit=187.2,
            reason="TIME_STOP",
        )

    assert trade.net_pnl_eur == pytest.approx(0.2)
    assert game.current_capital == pytest.approx(100.2)
    assert game.cash == pytest.approx(100.2)
    assert game.exposure == 0.0


def test_replay_bar_execution_adapter_preserves_halt_and_auction_metadata() -> None:
    with setup_db() as db:
        asset = seed_asset(db)
        row = ReplayMarketBar(
            asset_id=asset.id,
            source_symbol=asset.ticker,
            normalized_symbol=asset.ticker,
            market="USA",
            timeframe="1m",
            bar_timestamp=NOW,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=1_000,
            provider="fixture",
            acquired_at=NOW,
            data_quality_score=95.0,
            source_metadata={"is_halted": True, "market_session": "closing_auction"},
        )

        adapted = execution_bar_from_replay(row, spread_bps=4.0)

    assert adapted.is_halted is True
    assert adapted.session == "closing_auction"


def test_unfilled_order_outcome_distinguishes_missed_and_decayed_signals() -> None:
    missed = [
        SimpleNamespace(high=105.0, low=100.5, close=104.0),
    ]
    decayed = [
        SimpleNamespace(high=100.2, low=98.5, close=99.0),
    ]

    assert classify_unfilled_order(theoretical_price=100.0, target_price=104.0, bars=missed) == "MISSED_OPPORTUNITY"
    assert classify_unfilled_order(theoretical_price=100.0, target_price=104.0, bars=decayed) == "SIGNAL_DECAY_BEFORE_ENTRY"
    assert classify_unfilled_order(theoretical_price=100.0, target_price=104.0, bars=[]) == "ORDER_NOT_FILLED"


def test_intraday_overnight_position_is_carried_only_when_explicitly_enabled() -> None:
    with setup_db() as db:
        game = LiveForwardPaperGame(game_id="overnight", starting_capital=100, current_capital=100, cash=90)
        db.add(game)
        db.flush()
        trade = LiveForwardPaperTrade(
            trade_uid="overnight-trade",
            game_id=game.id,
            ticker="NVDA",
            setup_type="intraday_breakout",
            status="OPEN",
            decision_timestamp=NOW,
            opened_at=NOW,
            entry_price=100.0,
            stop_loss=95.0,
            target_1=110.0,
            position_size=0.1,
            duplicate_key="overnight-trade-key",
        )
        next_day = ReplayMarketBar(
            asset_id=seed_asset(db, ticker="OVERNIGHT-ASSET").id,
            source_symbol="NVDA",
            normalized_symbol="NVDA",
            market="USA",
            timeframe="1m",
            bar_timestamp=NOW + timedelta(days=1),
            open=101.0,
            high=102.0,
            low=100.0,
            close=101.5,
            volume=1_000,
            provider="fixture",
            acquired_at=NOW,
            data_quality_score=95.0,
            source_metadata={},
        )

        forced = BlumIntradayPaperEngine(refresh_missing=False, account_currency="USD", allow_overnight=False)._exit_for_bar(trade, next_day)
        carried = BlumIntradayPaperEngine(
            refresh_missing=False,
            account_currency="USD",
            allow_overnight=True,
            max_holding_minutes=3_000,
        )._exit_for_bar(trade, next_day)

    assert forced[0] == "MARKET_CLOSE"
    assert carried == (None, None)


def test_scheduler_runs_intraday_worker_independently(monkeypatch):
    observed = {}

    class StubEngine:
        def run_once(self, db, *, trigger):
            observed["db"] = db
            observed["trigger"] = trigger
            return {"status": "COMPLETED"}

    sentinel_db = object()
    monkeypatch.setattr(realtime, "BlumIntradayPaperEngine", StubEngine)
    monkeypatch.setattr(realtime, "_run_job", lambda name, work: observed.update(name=name, result=work(sentinel_db)))

    realtime.run_intraday_paper_trading_job()

    assert observed == {"name": "intraday_paper_trading", "db": sentinel_db, "trigger": "scheduled", "result": {"status": "COMPLETED"}}


def test_paper_snapshot_embeds_read_only_intraday_summary():
    with setup_db() as db:
        payload = LiveForwardPaperTradingService().snapshot_payload(db)

    assert payload["intraday"]["status"] == "NO_INTRADAY_RUNS"
    assert payload["intraday"]["evidence_type"] == PAPER_FORWARD_INTRADAY


def test_alpha_keeps_closed_intraday_evidence_separate_from_generic_paper_forward():
    with setup_db() as db:
        game = LiveForwardPaperGame(game_id="alpha-intraday", starting_capital=100, current_capital=102, cash=102, realized_pl=2)
        db.add(game)
        db.flush()
        db.add(
            LiveForwardPaperTrade(
                trade_uid="alpha-intraday-trade",
                game_id=game.id,
                ticker="NVDA",
                setup_type="intraday_breakout",
                status="CLOSED",
                decision_timestamp=NOW,
                decision_date=NOW.date(),
                opened_at=NOW,
                closed_at=NOW + timedelta(minutes=30),
                entry_price=100,
                exit_price=102,
                position_size=1,
                net_pnl_eur=1.9,
                gross_pnl_eur=2.0,
                pnl_percent=1.9,
                r_multiple=1.9,
                benchmark_return_same_period=0.5,
                excess_return_vs_benchmark=1.4,
                outcome_label="win",
                duplicate_key="alpha-intraday-key",
                trading_mode="INTRADAY_PAPER_FORWARD",
                evidence_type=PAPER_FORWARD_INTRADAY,
                timeframe_stack=["1d", "15m", "5m", "1m"],
                costs_paid=0.1,
                holding_minutes=30,
            )
        )
        db.commit()
        snapshot = TraderBrainService().alpha(db)

    intraday = snapshot["evidence_split"]["intraday_paper_forward"]
    assert intraday["sample_size"] == 1
    assert intraday["costs_paid"] == 0.1
    assert intraday["average_holding_minutes"] == 30
    assert snapshot["evidence_split"]["paper_forward"]["sample_size"] == 0
