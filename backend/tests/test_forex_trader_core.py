from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import (
    LiveForwardPaperGame,
    Asset,
    FinancialModelVote,
    ForexDecision,
    ForexLearningEvidence,
    ForexPolicyState,
    ForexPolicyUpdate,
    ForexPosition,
    ForexTraderCycle,
    ReplayMarketBar,
)
from app.services.forex_agents import (
    BlumForexContrarianRiskAgent,
    BlumForexMacroAgent,
    BlumForexMarketContextAgent,
    BlumForexPriceActionAgent,
    BlumForexScalpingExpertAgent,
)
from app.services.executable_strategy import ExecutableStrategySpec
from app.services.forex_strategy_signal import PRICE_FEATURE_SCHEMA_HASH
from app.services.forex_broker import BlumForexBrokerProfileService
from app.services.forex_contracts import (
    AgentMarketInput,
    ForexDirection,
    ForexOrderRequest,
    ForexQuote,
    ForexReadiness,
    ForexStrategyEvidence,
    MarketFrame,
    pair_config,
)
from app.services.forex_execution import BlumForexExecutionSimulator
from app.services.forex_learning import BlumForexLearningEngine
from app.services.forex_risk import BlumForexPortfolioRiskEngine, ForexPortfolioState
from app.services.forex_trader import (
    BlumForexTraderCore,
    BlumForexTradingScheduler,
    ForexMarketDataRefreshService,
    ForexStrategyRepository,
    ForexTraderSnapshotService,
)
from app.services.trading_ml.forex_history import ForexHistoricalDatasetService
from test_forex_historical_dataset import SOURCE_URL, _write_dataset
from app.main import app


NOW = datetime(2026, 7, 22, 9, 15)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    try:
        yield session
    finally:
        session.close()


def frames(*, direction: str = "LONG", stale_1m: bool = False) -> dict[str, MarketFrame]:
    slope = 1 if direction == "LONG" else -1
    output = {}
    for timeframe, minutes, size in (("1h", 60, 40), ("15m", 15, 40), ("5m", 5, 40), ("1m", 1, 40)):
        closes = tuple(1.1000 + slope * index * 0.00008 for index in range(size))
        timestamp = NOW - timedelta(minutes=10 if timeframe == "1m" and stale_1m else 0)
        output[timeframe] = MarketFrame(
            timeframe=timeframe,
            market_timestamp=timestamp - timedelta(minutes={"1h":60,"15m":15,"5m":5,"1m":1}[timeframe] + 1),
            acquired_at=timestamp,
            provider="test",
            opens=closes,
            highs=tuple(value + 0.00015 for value in closes),
            lows=tuple(value - 0.00015 for value in closes),
            closes=closes,
            quality_score=0.95,
            bar_timestamps=tuple(timestamp - timedelta(minutes={"1h":60,"15m":15,"5m":5,"1m":1}[timeframe] * (size - i) + 1) for i in range(size)),
            volumes=(100.0,) * size,
        )
    return output


def market_input(
    *,
    direction: str = "LONG",
    spread_pips: float = 0.8,
    stale_1m: bool = False,
    news: str = "LOW_IMPACT",
    event_at: datetime | None = None,
) -> AgentMarketInput:
    last = frames(direction=direction, stale_1m=stale_1m)
    mid = last["1m"].closes[-1]
    pip = pair_config("EURUSD=X").pip_size
    return AgentMarketInput(
        pair="EURUSD=X",
        as_of=NOW,
        frames=last,
        quote=ForexQuote(bid=mid - spread_pips * pip / 2, ask=mid + spread_pips * pip / 2, timestamp=NOW, source="test"),
        session="LONDON",
        macro_event_impact=news,
        macro_event_timestamp=event_at,
        liquidity_score=0.9,
        volatility_score=0.7,
    )


def strategy(*, news_strategy: bool = False) -> ForexStrategyEvidence:
    spec = ExecutableStrategySpec(
        schema_version="executable-strategy-v1", family="intraday_scalping", setup_type="intraday_breakout",
        required_timeframes=("1h", "15m", "5m", "1m"), execution_timeframe="1m",
        entry_rule="breakout_close", lookback=10, minimum_relative_volume=0.0,
        higher_timeframe_min_trend=0.0, atr_period=14, stop_atr_multiple=1.5,
        minimum_stop_percent=0.0, target_r_multiple=2.5, trailing_atr_multiple=1.2,
        maximum_holding_bars=30, market_filter="FOREX",
    )
    return ForexStrategyEvidence(
        strategy_id="fx-breakout-v1",
        readiness=ForexReadiness.PAPER_TRADE_ELIGIBLE,
        sample_size=120,
        net_expectancy_r=0.25,
        replay_forward_decay=0.15,
        currency_concentration=0.45,
        is_news_strategy=news_strategy,
        executable_strategy=spec.to_payload(), strategy_fingerprint=spec.fingerprint,
        required_feature_schema_hash=PRICE_FEATURE_SCHEMA_HASH, holding_horizon_bars=30,
    )


def test_empty_registry_stays_research_only_until_replay_validates_a_strategy(db):
    strategies = ForexStrategyRepository().load(db, ["EURUSD=X"])

    assert strategies == {}
    assert db.scalar(select(ForexPosition)) is None


def test_empty_registry_cannot_promote_reinforcement_memory_without_replay_validation(db):
    db.add(
        ForexPolicyState(
            policy_key="forex-exploration-bootstrap-v1|LONDON|trend_up|momentum_breakout|LONG",
            strategy_id="forex-exploration-bootstrap-v1",
            session="LONDON",
            regime="trend_up",
            setup_family="momentum_breakout",
            direction="LONG",
            sample_size=40,
            q_value=0.35,
            reward_sum=14.0,
            reward_sq_sum=8.0,
            evidence_grade="POLICY_ELIGIBLE",
            confidence_adjustment=0.041,
        )
    )
    db.commit()

    assert ForexStrategyRepository().load(db, ["EURUSD=X"]) == {}


def test_negative_global_bootstrap_policy_is_quarantined_instead_of_renamed(db):
    db.add(
        ForexPolicyState(
            policy_key="STRATEGY|forex-exploration-bootstrap-v1|ALL|ALL|ALL|ALL",
            strategy_id="forex-exploration-bootstrap-v1",
            session="ALL",
            regime="ALL",
            setup_family="ALL",
            direction="ALL",
            sample_size=20,
            q_value=-0.35,
            reward_sum=-7.0,
            reward_sq_sum=5.0,
            evidence_grade="POLICY_ELIGIBLE",
            confidence_adjustment=-0.041,
        )
    )
    db.commit()

    strategies = ForexStrategyRepository().load(
        db,
        ["EURUSD=X", "GBPUSD=X"],
    )

    assert strategies == {}


def test_forward_gate_quarantines_non_positive_strategy_after_30_closed_trades(db):
    db.add_all(
        ForexLearningEvidence(
            strategy_id="losing-forward-strategy",
            pair="EURUSD=X",
            outcome="LOSS",
            realized_result=-0.4,
            lesson="Forward strategy lost after costs.",
            evidence_strength=0.8,
            evidence_type="PAPER_FORWARD_FOREX",
            payload_json={"evidence_lane": "certified_paper"},
        )
        for _ in range(30)
    )
    db.commit()

    gate = BlumForexLearningEngine().forward_gate(
        db,
        {"losing-forward-strategy"},
    )

    assert gate.status == "QUARANTINED"
    assert gate.sample_size == 30
    assert gate.net_expectancy_r == pytest.approx(-0.4)
    assert gate.blockers == ("NON_POSITIVE_FORWARD_EXPECTANCY",)


def strategy_with_memory(*, grade: str, adjustment: float) -> ForexStrategyEvidence:
    base = strategy()
    return ForexStrategyEvidence(
        strategy_id=base.strategy_id,
        readiness=base.readiness,
        sample_size=base.sample_size,
        net_expectancy_r=base.net_expectancy_r,
        replay_forward_decay=base.replay_forward_decay,
        currency_concentration=base.currency_concentration,
        executable_strategy=base.executable_strategy, strategy_fingerprint=base.strategy_fingerprint,
        required_feature_schema_hash=base.required_feature_schema_hash, holding_horizon_bars=base.holding_horizon_bars,
        contextual_memory={
            "cells": [
                {
                    "status": grade,
                    "session": "LONDON",
                    "regime": "trend",
                    "setup_family": "momentum_breakout",
                    "sample_size": 40,
                    "confidence_adjustment": adjustment,
                    "explanation": "Validated replay context",
                }
            ]
        },
    )


def test_required_pair_universe_and_agent_boundaries():
    assert pair_config("EURUSD=X").pip_size == 0.0001
    assert pair_config("EURUSD=X").minimum_lot == 0.01
    assert pair_config("EURUSD=X").price_precision == 5
    assert pair_config("USDJPY=X").pip_size == 0.01
    assert pair_config("USDJPY=X").minimum_lot == 0.01
    assert pair_config("USDJPY=X").price_precision == 3
    assert pair_config("EURCHF=X").supported_timeframes == ("1h", "15m", "5m", "1m")
    assert len(pair_config.all()) == 12
    assert all(not hasattr(agent, "open_trade") for agent in (
        BlumForexMarketContextAgent(), BlumForexPriceActionAgent(), BlumForexMacroAgent(),
        BlumForexScalpingExpertAgent(), BlumForexContrarianRiskAgent(),
    ))


@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
def test_valid_trade_uses_directional_bid_ask_and_costs(direction):
    inputs = market_input(direction=direction)
    context = BlumForexMarketContextAgent().analyze(inputs)
    price_action = BlumForexPriceActionAgent().analyze(inputs)
    macro = BlumForexMacroAgent().analyze(inputs)
    proposal = BlumForexScalpingExpertAgent().propose(inputs, context, price_action, macro, strategy())
    assert proposal.direction == ForexDirection(direction)
    broker = BlumForexBrokerProfileService().get("paper_eu_30x")
    result = BlumForexExecutionSimulator().submit(
        ForexOrderRequest.from_proposal(proposal, quantity_lots=0.01), inputs.quote, broker, now=NOW
    )
    expected = inputs.quote.ask if direction == "LONG" else inputs.quote.bid
    assert result.status == "FILLED"
    assert result.fill_price >= expected if direction == "LONG" else result.fill_price <= expected
    assert result.total_cost > 0
    assert result.spread_source == "QUOTED"
    assert result.state_history == ("CREATED", "SUBMITTED", "ACKNOWLEDGED", "FILLED")
    assert result.execution_latency_ms > 0


def test_spread_news_and_stale_data_block_trades():
    for inputs, expected in (
        (market_input(spread_pips=20), "SPREAD_TOO_WIDE"),
        (market_input(news="HIGH_IMPACT"), "NEWS_WINDOW_BLOCKED"),
        (market_input(stale_1m=True), "STALE_DATA"),
    ):
        outcome = BlumForexTraderCore().evaluate_input(inputs, strategy=strategy())
        assert expected in outcome.blockers
        assert outcome.approved is False

    promoted_news = BlumForexTraderCore().evaluate_input(
        market_input(news="HIGH_IMPACT"), strategy=strategy(news_strategy=True)
    )
    assert "NEWS_WINDOW_BLOCKED" not in promoted_news.blockers
    outside_window = BlumForexTraderCore().evaluate_input(
        market_input(news="HIGH_IMPACT", event_at=NOW - timedelta(hours=2)),
        strategy=strategy(),
    )
    assert "NEWS_WINDOW_BLOCKED" not in outside_window.blockers


def test_stale_veto_preserves_analytical_confidence_components():
    outcome = BlumForexTraderCore().evaluate_input(
        market_input(stale_1m=True),
        strategy=strategy(),
    )

    assert outcome.approved is False
    assert "STALE_DATA" in outcome.blockers
    assert outcome.proposal.actionability_status == "BLOCKED"


def test_only_eligible_contextual_memory_changes_confidence() -> None:
    inputs = market_input()
    baseline = BlumForexTraderCore().evaluate_input(inputs, strategy=strategy())
    learning_only = BlumForexTraderCore().evaluate_input(
        inputs,
        strategy=strategy_with_memory(grade="LEARNING_ONLY", adjustment=0.08),
    )
    eligible = BlumForexTraderCore().evaluate_input(
        inputs,
        strategy=strategy_with_memory(grade="CONTEXT_ELIGIBLE", adjustment=0.08),
    )

    assert learning_only.proposal.confidence == baseline.proposal.confidence
    assert eligible.proposal.confidence == pytest.approx(baseline.proposal.confidence + 0.08)
    assert eligible.proposal.confidence_components["contextual_memory_adjustment"] == 8.0
    assert eligible.proposal.knowledge_context["status"] == "CONTEXT_ELIGIBLE"


def test_historical_forex_knowledge_is_bounded_and_audited_in_decision(
    tmp_path,
) -> None:
    source = tmp_path / "forex.csv"
    artifact = tmp_path / "forex_historical_knowledge.json"
    _write_dataset(source)
    service = ForexHistoricalDatasetService(
        source_path=source,
        source_url=SOURCE_URL,
        license_name="CC BY-SA 4.0",
        source_version="1",
        sample_weight=0.25,
    )
    bundle = service.prepare()
    service.write_knowledge(bundle, artifact)
    core = BlumForexTraderCore(historical_knowledge_path=artifact)

    baseline = BlumForexTraderCore(
        historical_knowledge_path=tmp_path / "missing.json"
    ).evaluate_input(market_input(), strategy=strategy())
    learned = core.evaluate_input(market_input(), strategy=strategy())

    history = learned.proposal.knowledge_context["historical_forex"]
    assert history["status"] == "AVAILABLE"
    assert history["sample_size"] >= 10
    assert abs(learned.proposal.confidence - baseline.proposal.confidence) <= 0.030001
    assert (
        learned.proposal.confidence_components["historical_knowledge_adjustment"]
        == pytest.approx(history["confidence_adjustment"] * 100.0)
    )


def test_replay_memory_uses_session_wildcard_and_setup_alias() -> None:
    base = strategy()
    learned = ForexStrategyEvidence(
        strategy_id=base.strategy_id,
        readiness=base.readiness,
        sample_size=base.sample_size,
        net_expectancy_r=base.net_expectancy_r,
        replay_forward_decay=base.replay_forward_decay,
        currency_concentration=base.currency_concentration,
        executable_strategy=base.executable_strategy, strategy_fingerprint=base.strategy_fingerprint,
        required_feature_schema_hash=base.required_feature_schema_hash, holding_horizon_bars=base.holding_horizon_bars,
        contextual_memory={
            "cells": [
                {
                    "status": "CONTEXT_ELIGIBLE",
                    "session": "UNKNOWN",
                    "regime": "trend",
                    "setup_family": "intraday_breakout",
                    "sample_size": 50,
                    "confidence_adjustment": 0.05,
                }
            ]
        },
    )

    baseline = BlumForexTraderCore().evaluate_input(market_input(), strategy=base)
    outcome = BlumForexTraderCore().evaluate_input(market_input(), strategy=learned)

    assert outcome.proposal.confidence == pytest.approx(baseline.proposal.confidence + 0.05)


def test_contextual_memory_cannot_bypass_hard_veto() -> None:
    outcome = BlumForexTraderCore().evaluate_input(
        market_input(stale_1m=True),
        strategy=strategy_with_memory(grade="CONTEXT_ELIGIBLE", adjustment=0.08),
    )

    assert outcome.approved is False
    assert "STALE_DATA" in outcome.blockers
    assert outcome.proposal.actionability_status == "BLOCKED"
    assert outcome.proposal.confidence > 0
    assert outcome.proposal.confidence_components["setup_confidence"] == pytest.approx(82.0)
    assert outcome.proposal.confidence_components["data_confidence"] == 0.0
    assert outcome.proposal.confidence_components["decision_confidence"] > 0.0


def test_hierarchical_policy_backs_off_to_strategy_loss_memory() -> None:
    base = strategy()
    learned = ForexStrategyEvidence(
        strategy_id=base.strategy_id,
        readiness=base.readiness,
        sample_size=base.sample_size,
        net_expectancy_r=base.net_expectancy_r,
        replay_forward_decay=base.replay_forward_decay,
        currency_concentration=base.currency_concentration,
        executable_strategy=base.executable_strategy, strategy_fingerprint=base.strategy_fingerprint,
        required_feature_schema_hash=base.required_feature_schema_hash, holding_horizon_bars=base.holding_horizon_bars,
        contextual_memory={
            "cells": [
                {
                    "source": "reinforcement_policy",
                    "policy_scope": "STRATEGY",
                    "status": "POLICY_ELIGIBLE",
                    "session": "ALL",
                    "regime": "ALL",
                    "setup_family": "ALL",
                    "direction": "ALL",
                    "sample_size": 12,
                    "q_value": -1.0,
                    "confidence_adjustment": -0.08,
                    "failure_causes": {"STOP_HIT": 9, "TIME_STOP": 3},
                }
            ]
        },
    )

    baseline = BlumForexTraderCore().evaluate_input(market_input(), strategy=base)
    outcome = BlumForexTraderCore().evaluate_input(market_input(), strategy=learned)

    assert outcome.proposal.confidence == pytest.approx(
        baseline.proposal.confidence - 0.08
    )
    assert outcome.proposal.knowledge_context["policy_trace"][0]["policy_scope"] == "STRATEGY"
    assert outcome.proposal.knowledge_context["dominant_failure_cause"] == "STOP_HIT"
    assert "POLICY_NEGATIVE_EDGE" in outcome.blockers
    assert outcome.approved is False


def test_specialized_policy_dominates_broad_parent_only_when_eligible() -> None:
    base = strategy()
    learned = ForexStrategyEvidence(
        strategy_id=base.strategy_id,
        readiness=base.readiness,
        sample_size=base.sample_size,
        net_expectancy_r=base.net_expectancy_r,
        replay_forward_decay=base.replay_forward_decay,
        currency_concentration=base.currency_concentration,
        executable_strategy=base.executable_strategy, strategy_fingerprint=base.strategy_fingerprint,
        required_feature_schema_hash=base.required_feature_schema_hash, holding_horizon_bars=base.holding_horizon_bars,
        contextual_memory={
            "cells": [
                {
                    "source": "reinforcement_policy",
                    "policy_scope": "STRATEGY",
                    "status": "POLICY_ELIGIBLE",
                    "session": "ALL",
                    "regime": "ALL",
                    "setup_family": "ALL",
                    "direction": "ALL",
                    "sample_size": 40,
                    "q_value": -0.3,
                    "confidence_adjustment": -0.04,
                },
                {
                    "source": "reinforcement_policy",
                    "policy_scope": "FULL_CONTEXT",
                    "status": "POLICY_ELIGIBLE",
                    "session": "LONDON",
                    "regime": "trend",
                    "setup_family": "momentum_breakout",
                    "direction": "LONG",
                    "sample_size": 30,
                    "q_value": 0.5,
                    "confidence_adjustment": 0.06,
                },
            ]
        },
    )

    baseline = BlumForexTraderCore().evaluate_input(market_input(), strategy=base)
    outcome = BlumForexTraderCore().evaluate_input(market_input(), strategy=learned)

    assert outcome.proposal.confidence > baseline.proposal.confidence
    assert outcome.proposal.knowledge_context["confidence_adjustment"] > 0
    assert [row["policy_scope"] for row in outcome.proposal.knowledge_context["policy_trace"]] == [
        "STRATEGY",
        "FULL_CONTEXT",
    ]
    assert "POLICY_NEGATIVE_EDGE" not in outcome.blockers


def test_strategy_confidence_is_sample_aware_without_changing_actionability_gate():
    inputs = market_input()
    mature = strategy()
    thin = ForexStrategyEvidence(
        strategy_id="thin-fx-breakout",
        readiness=ForexReadiness.TRAINING_SIGNAL,
        sample_size=5,
        net_expectancy_r=0.25,
    )

    mature_outcome = BlumForexTraderCore().evaluate_input(inputs, strategy=mature)
    thin_outcome = BlumForexTraderCore().evaluate_input(inputs, strategy=thin)

    assert mature_outcome.proposal.confidence_components["strategy_confidence"] > thin_outcome.proposal.confidence_components["strategy_confidence"]
    assert thin_outcome.approved is False
    assert "STRATEGY_NOT_READY" in thin_outcome.blockers
    assert thin_outcome.proposal.actionability_status == "BLOCKED"


def test_risk_netting_daily_loss_and_max_positions():
    engine = BlumForexPortfolioRiskEngine()
    proposal = BlumForexTraderCore().evaluate_input(market_input(), strategy=strategy()).proposal
    concentrated = ForexPortfolioState(
        equity=10_000,
        daily_realized_pnl=-50,
        open_positions=(
            {"pair": "GBPUSD=X", "direction": "LONG", "notional": 20_000},
            {"pair": "USDCHF=X", "direction": "SHORT", "notional": 20_000},
        ),
    )
    reduced = engine.evaluate(proposal, concentrated, replace(BlumForexBrokerProfileService().get("paper_eu_30x"), account_currency="USD"))
    assert reduced.decision in {"APPROVE_REDUCED_SIZE", "REJECT_CURRENCY_EXPOSURE"}

    assert engine.evaluate(proposal, ForexPortfolioState(equity=10_000, daily_realized_pnl=-200), replace(BlumForexBrokerProfileService().get("paper_eu_30x"), account_currency="USD")).decision == "REJECT_DAILY_LOSS"
    maxed = ForexPortfolioState(equity=10_000, open_positions=tuple({"pair": f"P{i}", "direction": "LONG", "notional": 1000} for i in range(4)))
    assert engine.evaluate(proposal, maxed, replace(BlumForexBrokerProfileService().get("paper_eu_30x"), account_currency="USD")).decision == "REJECT_MAX_POSITIONS"


def test_stop_gap_through_and_swap_are_realistic():
    broker = BlumForexBrokerProfileService().get("paper_eu_30x")
    simulator = BlumForexExecutionSimulator()
    request = ForexOrderRequest(
        pair="EURUSD=X", side=ForexDirection.LONG, order_type="STOP", quantity_lots=0.01,
        theoretical_price=1.1000, stop_price=1.0950, target_price=1.1100,
    )
    quote = ForexQuote(bid=1.0938, ask=1.0940, timestamp=NOW, source="gap")
    stopped = simulator.close(request, quote, broker, reason="STOP_HIT", now=NOW)
    assert stopped.fill_price < request.stop_price
    assert stopped.fill_price <= quote.bid
    assert simulator.accrue_swap(request, broker, nights=2, weekday=2) == pytest.approx(broker.swap_long["EURUSD=X"] * 4 * 0.01)


def test_execution_slippage_is_dynamic_and_evidence_bound():
    broker = BlumForexBrokerProfileService().get("paper_eu_30x")
    quote = ForexQuote(bid=1.1000, ask=1.1001, timestamp=NOW, source="test")
    liquid = ForexOrderRequest(
        pair="EURUSD=X", side=ForexDirection.LONG, order_type="MARKET",
        quantity_lots=0.01, theoretical_price=1.10005,
        session="LONDON_NEW_YORK_OVERLAP", liquidity_score=0.95,
        volatility_score=0.25, event_impact="LOW_IMPACT",
    )
    stressed = ForexOrderRequest(
        pair="EURUSD=X", side=ForexDirection.LONG, order_type="MARKET",
        quantity_lots=0.01, theoretical_price=1.10005,
        session="NEW_YORK", liquidity_score=0.35,
        volatility_score=0.9, event_impact="HIGH_IMPACT",
    )
    simulator = BlumForexExecutionSimulator()
    liquid_fill = simulator.submit(liquid, quote, broker, now=NOW)
    stressed_fill = simulator.submit(stressed, quote, broker, now=NOW)
    assert stressed_fill.slippage_pips > liquid_fill.slippage_pips
    assert stressed_fill.fill_price > liquid_fill.fill_price
    assert stressed_fill.execution_assumptions["liquidity_score"] == 0.35


def test_rotating_market_refresh_hydrates_the_complete_strict_stack(db, monkeypatch):
    db.add(Asset(
        ticker="EURUSD=X",
        name="EUR/USD",
        category="Forex",
        sector="Currencies",
        country="Global",
        asset_type="Forex",
        is_active=True,
    ))
    db.commit()
    calls = []

    class Coverage:
        status = "READY"
        rows_available = 40
        provider = "test"
        blockers = []

    service = ForexMarketDataRefreshService()
    monkeypatch.setattr(
        service.data,
        "ensure_coverage",
        lambda db, *, asset, timeframe, start, end: calls.append(timeframe) or Coverage(),
    )
    result = service.refresh(db, now=NOW)
    assert result["status"] == "READY"
    assert calls == ["1h", "15m", "5m", "1m"]
    assert [row["timeframe"] for row in result["refreshed"][0]["timeframes"]] == calls


def test_forex_refresh_covers_freshness_budget_and_prioritizes_oldest_pairs(db, monkeypatch):
    assets = []
    for index, pair in enumerate(pair_config.all()):
        asset = Asset(
            ticker=pair.ticker,
            name=pair.display,
            category="Forex",
            sector="Currencies",
            country="Global",
            asset_type="Forex",
            is_active=True,
        )
        db.add(asset)
        db.flush()
        assets.append(asset)
        db.add(
            ReplayMarketBar(
                asset_id=asset.id,
                source_symbol=asset.ticker,
                normalized_symbol=asset.ticker,
                market="FOREX",
                timeframe="1m",
                bar_timestamp=NOW - timedelta(minutes=12 - index),
                open=1.0,
                high=1.0,
                low=1.0,
                close=1.0,
                volume=1.0,
                provider="test",
                acquired_at=NOW,
                data_quality_score=95.0,
                source_metadata={},
            )
        )
    db.commit()
    refreshed_assets = []

    class Coverage:
        status = "READY"
        rows_available = 40
        provider = "test"
        blockers = []

    service = ForexMarketDataRefreshService()
    monkeypatch.setattr(
        service.data,
        "ensure_coverage",
        lambda db, *, asset, timeframe, start, end: refreshed_assets.append(asset.ticker) or Coverage(),
    )

    result = service.refresh(db, now=NOW)

    selected = list(dict.fromkeys(refreshed_assets))
    assert len(selected) >= 4
    assert selected[:4] == [asset.ticker for asset in assets[:4]]
    assert result["freshness_budget_minutes"] == 3
    assert result["minimum_pairs_required"] == 4


def test_rejected_forex_decision_is_not_labeled_as_learning_before_counterfactual_matures(db):
    core = BlumForexTraderCore()
    result = core.run_cycle(db, inputs=[market_input(spread_pips=20)], strategies={"EURUSD=X": strategy()}, now=NOW)
    assert result["candidates_rejected"] == 1
    assert db.scalar(select(ForexDecision)).status == "REJECTED"
    assert db.scalar(select(ForexLearningEvidence)) is None
    assert result["learning_events"] == []
    before = db.query(ForexTraderCycle).count()
    snapshot = ForexTraderSnapshotService().read(db, now=NOW)
    assert snapshot["exact_reason_if_no_trade_is_open"]
    assert db.query(ForexTraderCycle).count() == before


def test_repeated_unchanged_rejection_is_not_persisted_inside_cooldown(db):
    core = BlumForexTraderCore()
    inputs = [market_input(spread_pips=20)]

    core.run_cycle(db, inputs=inputs, strategies={"EURUSD=X": strategy()}, now=NOW, cycle_key="reject-1")
    core.run_cycle(
        db,
        inputs=inputs,
        strategies={"EURUSD=X": strategy()},
        now=NOW + timedelta(minutes=1),
        cycle_key="reject-2",
    )

    assert db.query(ForexDecision).count() == 1
    latest_cycle = db.scalar(
        select(ForexTraderCycle).where(ForexTraderCycle.cycle_key == "reject-2")
    )
    assert latest_cycle.rejected_candidates == [
        {
            "pair": "EURUSD=X",
            "blockers": ["SPREAD_TOO_WIDE", "NO_NET_EDGE"],
            "deduplicated": True,
        }
    ]


def test_scheduler_monitors_only_outside_permitted_entry_sessions(db):
    result = BlumForexTradingScheduler().run_once(
        db,
        now=NOW.replace(hour=3),
        inputs=[replace(market_input(), session="ASIA")],
        strategies={"EURUSD=X": strategy()},
        cycle_key="asia-monitor-only",
    )

    assert result["status"] == "MONITOR_ONLY"
    assert result["blockers"] == ["SESSION_NOT_ALLOWED"]
    assert db.query(ForexDecision).count() == 0


def test_scheduler_decides_after_market_acquisition_instead_of_cycle_start(db, monkeypatch):
    from app.services import forex_trader

    clock = [NOW]

    class ClockMeta(type):
        def __instancecheck__(cls, value):
            return isinstance(value, datetime)

    class CycleClock(datetime, metaclass=ClockMeta):
        @classmethod
        def utcnow(cls):
            return clock[0]

    scheduler = BlumForexTradingScheduler()
    acquired_at = NOW + timedelta(seconds=2)

    def refresh(session, *, now):
        clock[0] = NOW + timedelta(seconds=3)
        return {'status': 'READY', 'refreshed': [], 'blockers': []}

    def load(session, *, now, limit):
        market = market_input()
        return [replace(market, as_of=now, frames={key: replace(frame, acquired_at=acquired_at) for key, frame in market.frames.items()})], []

    monkeypatch.setattr(forex_trader, 'datetime', CycleClock)
    monkeypatch.setattr(scheduler.refresh, 'refresh', refresh)
    monkeypatch.setattr(scheduler.market_inputs, 'load', load)
    scheduler.run_once(db, strategies={'EURUSD=X': strategy()}, cycle_key='post-acquisition')

    decision = db.scalar(select(ForexDecision))
    assert decision is not None
    assert decision.decision_timestamp >= acquired_at


def test_readiness_promotion_degradation_and_terminal_only_learning(db):
    learner = BlumForexLearningEngine()
    evidence = [
        {"outcome": "WIN" if index % 2 == 0 else "LOSS", "net_r": 1.2 if index % 2 == 0 else -0.5,
         "pair": "EURUSD=X" if index % 3 else "GBPUSD=X", "session": "LONDON" if index % 2 else "NEW_YORK",
         "regime": "trend" if index % 4 else "range", "benchmark_excess": 0.15}
        for index in range(100)
    ]
    promoted = learner.assess_readiness(strategy(), evidence)
    assert promoted.level == ForexReadiness.ALPHA_SIGNAL_ELIGIBLE
    degraded = learner.assess_readiness(strategy(), [{**row, "net_r": -1.0, "outcome": "LOSS"} for row in evidence])
    assert degraded.level in {ForexReadiness.DEGRADED, ForexReadiness.SUSPENDED}
    assert learner.record_outcome(db, decision_id=None, outcome="OPEN", payload={}) is None


def test_closed_forex_trade_persists_bounded_reinforcement_reward(db):
    row = BlumForexLearningEngine().record_outcome(
        db,
        decision_id=None,
        outcome="WIN",
        payload={
            "strategy_id": "forex-exploration-bootstrap-v1",
            "pair": "EURUSD=X",
            "realized_result": 0.8,
            "benchmark_excess": 0.01,
            "evidence_strength": 0.8,
        },
    )

    assert row is not None
    assert row.payload_json["reinforcement_reward_r"] == pytest.approx(0.9)
    assert row.payload_json["policy_update_eligible"] is True


def test_alpha_readiness_rejects_replay_decay_concentration_and_active_blockers():
    learner = BlumForexLearningEngine()
    evidence = [
        {"outcome": "WIN", "net_r": 0.4, "pair": "EURUSD=X" if index % 2 else "GBPUSD=X",
         "session": "LONDON" if index % 2 else "NEW_YORK", "regime": "trend" if index % 3 else "range",
         "benchmark_excess": 0.1}
        for index in range(100)
    ]
    weak = ForexStrategyEvidence(
        "weak-forward", ForexReadiness.PAPER_TRADE_ELIGIBLE, 300, 0.2,
        replay_forward_decay=0.8, currency_concentration=0.9,
        active_blockers=("DATA_QUALITY_BLOCK",),
    )
    assessment = learner.assess_readiness(weak, evidence)
    assert assessment.level != ForexReadiness.ALPHA_SIGNAL_ELIGIBLE
    assert {"REPLAY_FORWARD_DECAY", "CURRENCY_CONCENTRATION", "ACTIVE_STRATEGY_BLOCKER"}.issubset(assessment.blockers)


def test_risk_sizing_reduces_for_drawdown_weak_evidence_and_pair_correlation():
    engine = BlumForexPortfolioRiskEngine()
    proposal = BlumForexTraderCore().evaluate_input(market_input(), strategy=strategy()).proposal
    broker = replace(BlumForexBrokerProfileService().get("paper_eu_30x"), account_currency="USD")
    clean = engine.evaluate(proposal, ForexPortfolioState(equity=10_000), broker)
    stressed = engine.evaluate(
        proposal,
        ForexPortfolioState(equity=10_000, drawdown_percent=8.0, pair_correlations={"EURUSD=X": 0.92}),
        broker,
    )
    assert stressed.quantity_lots < clean.quantity_lots
    assert "CORRELATION_LIMIT" in stressed.blockers
    assert stressed.risk_percent < clean.risk_percent


def test_core_cycle_is_idempotent_and_recovers_incomplete_cycle(db):
    db.add(LiveForwardPaperGame(game_id="native-funded-fixture", starting_capital=1000, current_capital=1000, cash=1000, configuration={"account_currency":"EUR"}))
    db.flush()
    core = BlumForexTraderCore()
    first = core.run_cycle(db, inputs=[market_input()], strategies={"EURUSD=X": strategy()}, now=NOW, cycle_key="fixed")
    second = core.run_cycle(db, inputs=[market_input()], strategies={"EURUSD=X": strategy()}, now=NOW, cycle_key="fixed")
    assert first["cycle_id"] == second["cycle_id"]
    assert db.query(ForexTraderCycle).count() == 1
    from app.models import ForexPendingOrder
    assert db.query(ForexPendingOrder).count() == 1
    assert db.query(ForexPosition).count() == 0

    interrupted = ForexTraderCycle(
        cycle_uid="interrupted", cycle_key="interrupted", status="RUNNING",
        started_at=NOW - timedelta(minutes=3), pairs_scanned=[], configuration_hash="a" * 64,
        data_coverage_hash="b" * 64,
    )
    db.add(interrupted)
    db.commit()
    recovered = core.run_cycle(db, inputs=[], strategies={}, now=NOW, cycle_key="interrupted")
    assert recovered["status"] == "DEGRADED"
    assert "RECOVERED_INTERRUPTED_CYCLE" in recovered["blockers"]


@pytest.mark.parametrize("direction", ["LONG"])
def test_complete_trade_lifecycle_persists_net_outcome(direction, db):
    db.add(LiveForwardPaperGame(game_id="native-funded-fixture", starting_capital=1000, current_capital=1000, cash=1000, configuration={"account_currency":"EUR"}))
    db.flush()
    core = BlumForexTraderCore()
    opened = core.run_cycle(db, inputs=[market_input(direction=direction)], strategies={"EURUSD=X": strategy()}, now=NOW, cycle_key=f"life-{direction}")
    assert opened["trades_opened"] == 0
    original = market_input(direction=direction)
    fill_time = NOW + timedelta(seconds=1)
    advanced = core.run_cycle(db, inputs=[replace(original, as_of=fill_time, quote=replace(original.quote, timestamp=fill_time))], strategies={}, now=fill_time, cycle_key=f"fill-{direction}")
    assert advanced["trades_opened"] == 1
    vote = db.scalar(select(FinancialModelVote))
    assert vote is not None
    assert vote.advisor_key == "finrobot"
    assert vote.direct_action_allowed is False
    position = db.scalar(select(ForexPosition))
    spread = 0.00008
    if direction == "LONG":
        quote = ForexQuote(bid=position.target_price + 0.0001, ask=position.target_price + 0.0001 + spread, timestamp=NOW + timedelta(minutes=1), source="test")
    else:
        quote = ForexQuote(bid=position.target_price - 0.0001 - spread, ask=position.target_price - 0.0001, timestamp=NOW + timedelta(minutes=1), source="test")
    managed = core.manager.manage(db, {"EURUSD=X": quote}, now=NOW + timedelta(minutes=1))
    db.commit()
    assert managed["trades_closed"] == 1
    assert position.status == "CLOSED"
    assert position.net_pnl < position.gross_pnl
    assert position.contract_json["valuation"]["unrealized_net_pnl"] is not None
    assert position.contract_json["valuation"]["current_r"] is not None
    evidence = db.scalar(select(ForexLearningEvidence).where(ForexLearningEvidence.position_id == position.id))
    assert evidence.outcome == "WIN"
    policy = db.scalar(select(ForexPolicyState))
    assert policy is not None
    assert policy.sample_size == 1
    updates = db.scalars(select(ForexPolicyUpdate)).all()
    assert {row.policy_scope for row in updates} == {
        "STRATEGY",
        "SETUP",
        "REGIME_SETUP",
        "FULL_CONTEXT",
    }
    db.refresh(vote)
    assert vote.outcome_evaluated is True
    assert vote.reward_contribution == pytest.approx(evidence.payload_json["reinforcement_reward_r"])


def test_api_contract_and_scheduler_controls_are_persistent(db):
    routes = {(route.path, method) for route in app.routes for method in getattr(route, "methods", set())}
    assert ("/api/forex-trader/snapshot", "GET") in routes
    for path in ("run-cycle", "start", "pause", "resume", "emergency-stop"):
        assert (f"/api/forex-trader/{path}", "POST") in routes
    scheduler = BlumForexTradingScheduler()
    assert scheduler.pause(db)["desired_state"] == "PAUSED"
    assert scheduler.resume(db)["desired_state"] == "RUNNING"
    first = scheduler.run_once(db, now=NOW, inputs=[market_input()], strategies={"EURUSD=X": strategy()}, cycle_key="scheduler-fixed")
    second = scheduler.run_once(db, now=NOW, inputs=[market_input()], strategies={"EURUSD=X": strategy()}, cycle_key="scheduler-fixed")
    assert first["cycle_id"] == second["cycle_id"]
    assert second["idempotent"] is True
