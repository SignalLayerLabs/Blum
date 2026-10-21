"""Catch native execution silently substituting a generic strategy for replay."""

from dataclasses import replace
from datetime import timedelta

import pytest

from app.services.executable_strategy import (
    ExecutableStrategySpec,
    StrategySignalEvaluator,
)
from app.services.forex_agents import (
    BlumForexMacroAgent,
    BlumForexMarketContextAgent,
    BlumForexPriceActionAgent,
    BlumForexScalpingExpertAgent,
)
from app.services.forex_contracts import ForexDirection
from app.services.forex_trader import BlumForexTraderCore
from test_forex_trader_core import market_input, strategy
from test_executable_strategy import payload
from test_forex_trader_core import db, NOW


def specification(**changes):
    return ExecutableStrategySpec.from_payload(
        payload(
            required_timeframes=["1h", "15m", "5m", "1m"],
            execution_timeframe="1m",
            minimum_relative_volume=0.0,
            minimum_stop_percent=0.0,
            stop_atr_multiple=1.5,
            target_r_multiple=2.5,
            market_filter="FOREX",
            **changes,
        )
    )


def canonical_evidence(spec):
    from app.services.forex_strategy_signal import PRICE_FEATURE_SCHEMA_HASH

    return replace(
        strategy(),
        executable_strategy=spec.to_payload(),
        strategy_fingerprint=spec.fingerprint,
        required_feature_schema_hash=PRICE_FEATURE_SCHEMA_HASH,
        holding_horizon_bars=spec.maximum_holding_bars,
    )


def test_missing_spec_cannot_inherit_legacy_generic_trade_or_certification():
    outcome = BlumForexTraderCore().evaluate_input(
        market_input(), strategy=replace(strategy(), executable_strategy={})
    )
    assert not outcome.approved
    assert "EXECUTABLE_SPEC_UNAVAILABLE" in outcome.blockers
    assert not outcome.proposal.certified_for_copy_readiness


def test_generic_five_ten_pip_agent_is_never_certified_by_scalper():
    market = market_input()
    proposal = BlumForexScalpingExpertAgent().propose(
        market,
        BlumForexMarketContextAgent().analyze(market),
        BlumForexPriceActionAgent().analyze(market),
        BlumForexMacroAgent().analyze(market),
        strategy(),
    )
    assert not proposal.certified_for_copy_readiness


@pytest.mark.parametrize(
    "entry_rule,want",
    [
        ("breakout_close", ForexDirection.LONG),
        ("trend_continuation", ForexDirection.LONG),
        ("mean_reversion_deviation", ForexDirection.WATCH),
    ],
)
def test_rules_use_shared_evaluator_and_exact_geometry(entry_rule, want):
    from app.services.forex_strategy_signal import ForexStrategySignal

    market = with_observed_bars(market_input())
    spec = specification(entry_rule=entry_rule)
    result = ForexStrategySignal().evaluate(market, strategy=canonical_evidence(spec))
    assert result.direction == want
    assert result.strategy_fingerprint == spec.fingerprint
    if want == ForexDirection.LONG:
        # Every candle has 0.00030 true range; ATR stop=1.5*0.00030.
        midpoint = (market.quote.bid + market.quote.ask) / 2
        assert result.stop_level == pytest.approx(midpoint - 0.00045)
        assert result.target_levels == pytest.approx((midpoint + 0.001125,))
        assert result.expected_holding_minutes == 30
        assert result.maximum_holding_bars == 30
        assert not result.blockers


def with_observed_bars(market):
    frames = {}
    for key, frame in market.frames.items():
        minutes = {"1h": 60, "15m": 15, "5m": 5, "1m": 1}[key]
        stamps = tuple(
            frame.market_timestamp
            - timedelta(minutes=minutes * (len(frame.closes) - i - 1))
            for i in range(len(frame.closes))
        )
        frames[key] = replace(
            frame, bar_timestamps=stamps, volumes=(100.0,) * len(stamps)
        )
    return replace(market, frames=frames)


def test_zero_minimum_stop_roundtrips_without_becoming_one_percent():
    spec = specification()
    assert spec.minimum_stop_percent == 0.0
    assert (
        ExecutableStrategySpec.from_payload(spec.to_payload()).fingerprint
        == spec.fingerprint
    )


@pytest.mark.parametrize(
    "corruption,reason",
    [
        ("missing_field", "EXECUTABLE_SPEC_INVALID"),
        ("fingerprint", "STRATEGY_FINGERPRINT_MISMATCH"),
        ("schema", "FEATURE_SCHEMA_MISMATCH"),
        ("horizon", "HOLDING_HORIZON_MISMATCH"),
    ],
)
def test_changed_or_incomplete_contract_is_blocked(corruption, reason):
    from app.services.forex_strategy_signal import ForexStrategySignal

    spec = specification()
    evidence = canonical_evidence(spec)
    if corruption == "missing_field":
        changed = dict(evidence.executable_strategy)
        changed.pop("stop_atr_multiple")
        evidence = replace(evidence, executable_strategy=changed)
    elif corruption == "fingerprint":
        evidence = replace(evidence, strategy_fingerprint="0" * 64)
    elif corruption == "schema":
        evidence = replace(evidence, required_feature_schema_hash="unknown")
    else:
        evidence = replace(evidence, holding_horizon_bars=31)
    result = ForexStrategySignal().evaluate(
        with_observed_bars(market_input()), strategy=evidence
    )
    assert result.direction == ForexDirection.ABSTAIN
    assert result.blockers == (reason,)


def test_stop_atr_and_timeframe_horizon_reach_native_proposal():
    from app.services.forex_strategy_signal import ForexStrategySignal

    market = with_observed_bars(market_input())
    spec = replace(
        specification(),
        stop_atr_multiple=2.0,
        maximum_holding_bars=7,
        execution_timeframe="5m",
    )
    result = ForexStrategySignal().evaluate(market, strategy=canonical_evidence(spec))
    proposal = BlumForexScalpingExpertAgent().propose(
        market,
        BlumForexMarketContextAgent().analyze(market),
        result,
        BlumForexMacroAgent().analyze(market),
        canonical_evidence(spec),
    )
    midpoint = (market.quote.bid + market.quote.ask) / 2
    assert proposal.stop == pytest.approx(midpoint - 0.00060)
    assert proposal.expected_holding_minutes == 35
    assert proposal.maximum_holding_bars == 7
    assert proposal.execution_timeframe == "5m"
    assert proposal.strategy_fingerprint == spec.fingerprint
    assert proposal.executable_strategy == spec.to_payload()
    assert proposal.expected_r == pytest.approx(proposal.expected_net_pips / 6.0)


def test_no_invented_timestamps_or_volume_for_validated_contract():
    from app.services.forex_strategy_signal import ForexStrategySignal

    spec = specification()
    market = market_input()
    market = replace(
        market,
        frames={
            key: replace(frame, bar_timestamps=())
            for key, frame in market.frames.items()
        },
    )
    result = ForexStrategySignal().evaluate(market, strategy=canonical_evidence(spec))
    assert result.blockers == ("BAR_PROVENANCE_UNAVAILABLE",)


def test_future_observation_and_invalid_ohlc_do_not_enter_signal():
    from app.services.forex_strategy_signal import ForexStrategySignal

    market = with_observed_bars(market_input())
    frame = market.frames["1m"]
    bad = replace(frame, highs=tuple(v - 0.01 for v in frame.closes))
    result = ForexStrategySignal().evaluate(
        replace(market, frames={**market.frames, "1m": bad}),
        strategy=canonical_evidence(specification()),
    )
    assert result.blockers == ("INVALID_OHLC_CONTEXT",)
    future = replace(frame, acquired_at=market.as_of + timedelta(seconds=1))
    result = ForexStrategySignal().evaluate(
        replace(market, frames={**market.frames, "1m": future}),
        strategy=canonical_evidence(specification()),
    )
    assert result.blockers == ("FUTURE_DATA_DETECTED",)


def test_canonical_long_spec_cannot_be_post_flipped_to_short():
    from app.services.forex_strategy_signal import ForexStrategySignal

    result = ForexStrategySignal().evaluate(
        with_observed_bars(market_input(direction="SHORT")),
        strategy=canonical_evidence(specification()),
    )
    assert result.direction == ForexDirection.WATCH


@pytest.mark.parametrize("stored_spec", [None, ["corrupt"], "corrupt"])
def test_legacy_registry_fallback_is_not_a_validated_forex_contract(db, stored_spec):
    from app.services.forex_trader import ForexStrategyRepository
    from test_live_intraday_paper_engine import seed_validation

    seed_validation(
        db,
        markets=["FOREX"],
        metrics={
            "timeframe_stack": ["1h", "15m", "5m", "1m"],
            "supported_asset_classes": ["Forex"],
            "executable_strategy": stored_spec,
        },
    )
    assert ForexStrategyRepository().load(db, ["EURUSD=X"]) == {}


def test_registry_preserves_frozen_forex_contract(db):
    from app.services.forex_trader import ForexStrategyRepository
    from app.services.forex_strategy_signal import PRICE_FEATURE_SCHEMA_HASH
    from test_live_intraday_paper_engine import seed_validation

    spec = specification()
    seed_validation(
        db,
        markets=["FOREX"],
        metrics={
            "timeframe_stack": ["1h", "15m", "5m", "1m"],
            "supported_asset_classes": ["Forex"],
            "executable_strategy": spec.to_payload(),
            "strategy_fingerprint": spec.fingerprint,
            "required_feature_schema_hash": PRICE_FEATURE_SCHEMA_HASH,
            "holding_horizon_bars": 30,
        },
    )
    evidence = ForexStrategyRepository().load(db, ["EURUSD=X"])["EURUSD=X"]
    assert evidence.executable_strategy == spec.to_payload()
    assert evidence.strategy_fingerprint == spec.fingerprint
    assert evidence.holding_horizon_bars == 30


def test_uncompleted_bar_cannot_trigger_live_signal():
    from app.services.forex_strategy_signal import ForexStrategySignal

    market = with_observed_bars(market_input())
    frame = market.frames["1m"]
    changed = replace(
        frame,
        market_timestamp=market.as_of,
        bar_timestamps=(*frame.bar_timestamps[:-1], market.as_of),
    )
    result = ForexStrategySignal().evaluate(
        replace(market, frames={**market.frames, "1m": changed}),
        strategy=canonical_evidence(specification()),
    )
    assert result.blockers == ("BAR_NOT_AVAILABLE",)


def test_data_hash_covers_stop_geometry_inputs():
    market = market_input()
    frame = market.frames["1m"]
    changed = replace(
        market,
        frames={
            **market.frames,
            "1m": replace(frame, highs=tuple(value + 0.001 for value in frame.highs)),
        },
    )
    assert market.data_hash() != changed.data_hash()


def test_holding_limit_counts_completed_market_bars_not_wall_clock(db):
    from app.models import Asset, ForexPosition, LiveForwardPaperGame, ReplayMarketBar
    from sqlalchemy import select

    core = BlumForexTraderCore()
    market = market_input()
    spec = replace(specification(), maximum_holding_bars=2)
    db.add(
        LiveForwardPaperGame(
            game_id="canonical-horizon",
            starting_capital=1000,
            current_capital=1000,
            cash=1000,
            configuration={"account_currency": "EUR"},
        )
    )
    asset = Asset(
        ticker="EURUSD=X",
        name="EUR/USD",
        category="Forex",
        sector="Currencies",
        country="Global",
        asset_type="Forex",
        is_active=True,
    )
    db.add(asset)
    db.flush()
    core.run_cycle(
        db,
        inputs=[market],
        strategies={market.pair: canonical_evidence(spec)},
        now=NOW,
        cycle_key="horizon-submit",
    )
    filled_at = NOW + timedelta(seconds=1)
    filled = replace(
        market, as_of=filled_at, quote=replace(market.quote, timestamp=filled_at)
    )
    core.run_cycle(
        db, inputs=[filled], strategies={}, now=filled_at, cycle_key="horizon-fill"
    )
    position = db.scalar(select(ForexPosition))
    assert position.contract_json["strategy_fingerprint"] == spec.fingerprint
    later = NOW + timedelta(minutes=10)
    quote = replace(market.quote, timestamp=later)
    core.manager.manage(db, {market.pair: quote}, now=later)
    assert (
        position.status == "OPEN"
    )  # No observed completed bars: no invented time exit.
    for minute in (1, 2):
        db.add(
            ReplayMarketBar(
                asset_id=asset.id,
                source_symbol=asset.ticker,
                normalized_symbol=asset.ticker,
                market="FOREX",
                timeframe="1m",
                bar_timestamp=NOW + timedelta(minutes=minute),
                acquired_at=later,
                open=1.1,
                high=1.11,
                low=1.09,
                close=1.1,
                volume=100,
                provider="fixture",
                data_quality_score=0.95,
                source_metadata={},
            )
        )
    db.flush()
    core.manager.manage(db, {market.pair: quote}, now=later)
    assert position.status == "CLOSED"
    assert position.contract_json["accounting"]["exit_reason"] == "TIME_STOP"
