from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    Asset,
    HyperbolicReplayRun,
    HyperbolicReplayTrade,
    PaperExecutionOrder,
    ReplayStrategyValidation,
    StrategyCandidateVariant,
    StrategyFactoryRun,
    StrategyPromotionEvent,
    StrategyValidationFold,
)
from app.services.alpha_strategy_factory import (
    AlphaStrategyFactory,
    ChampionChallengerRegistry,
    StrategyFamilyRegistry,
    strategy_factory_snapshot,
)
from app.services.executable_strategy import ExecutableStrategySpec
from app.services.strategy_factory_statistics import (
    backtest_overfitting_probability,
    benjamini_hochberg,
    block_bootstrap_interval,
    build_purged_folds,
    evaluate_strategy_robustness,
)
from app.services.paper_execution_lifecycle import execution_reality_snapshot
from app.services.promoted_strategy_registry import BlumPromotedStrategyRegistry
from app.services.strategy_promotion_frontier import StrategyPromotionFrontierService
from app.services.worker_runtime import WORKER_DEFINITIONS


def test_purged_walk_forward_excludes_overlap_and_embargo() -> None:
    start = datetime(2024, 1, 1)
    timestamps = [start + timedelta(days=index) for index in range(120)]

    folds = build_purged_folds(timestamps, n_splits=3, purge_bars=5, embargo_bars=3)

    assert len(folds) == 3
    for fold in folds:
        assert fold.train_indices
        assert fold.validation_indices
        assert max(fold.train_indices) <= min(fold.validation_indices) - 6
        assert fold.embargo_end_index == min(119, max(fold.validation_indices) + 3)
        assert set(fold.train_indices).isdisjoint(fold.validation_indices)


def test_intraday_strategy_factory_generates_forex_specific_hypotheses() -> None:
    rows = StrategyFamilyRegistry().variants("intraday_scalping", max_variants=64, seed=7)
    forex_rows = [row for row in rows if row["market_filter"] == "forex_only"]

    assert forex_rows
    assert all(row["executable_strategy"]["market_filter"] == "forex_only" for row in forex_rows)
    assert all(row["executable_strategy"]["minimum_relative_volume"] == 0.0 for row in forex_rows)
    assert all(row["executable_strategy"]["minimum_stop_percent"] == 0.0005 for row in forex_rows)
    assert all(row["benchmark_ticker"] == "UUP" for row in forex_rows)


def test_small_factory_budget_reserves_a_forex_replay_hypothesis() -> None:
    rows = StrategyFamilyRegistry().variants("intraday_scalping", max_variants=2, seed=7)
    forex_rows = [row for row in rows if row["market_filter"] == "forex_only"]

    assert len(rows) == 2
    assert len(forex_rows) == 1
    assert forex_rows[0]["timeframe_stack"] == ["1h", "15m", "5m", "1m"]
    assert "forex" in forex_rows[0]["asset_class"]
    assert forex_rows[0]["benchmark_ticker"] == "UUP"


def test_block_bootstrap_interval_is_seeded_and_conservative() -> None:
    values = [0.15, 0.25, 0.1, 0.35, -0.05, 0.3] * 60

    first = block_bootstrap_interval(values, iterations=400, block_size=5, seed=17)
    second = block_bootstrap_interval(values, iterations=400, block_size=5, seed=17)

    assert first == second
    assert first.lower < first.mean < first.upper
    assert first.lower > 0


def test_multiple_testing_correction_rejects_raw_only_false_positive() -> None:
    adjusted = benjamini_hochberg([0.005, 0.03, 0.04, 0.2, 0.8], false_discovery_rate=0.05)

    assert adjusted[0].raw_p_value == 0.005
    assert adjusted[0].adjusted_p_value == 0.025
    assert adjusted[0].significant is True
    assert adjusted[1].significant is False
    assert adjusted[2].significant is False


def test_backtest_overfitting_probability_penalizes_rank_reversals() -> None:
    stable = backtest_overfitting_probability([(1, 1), (1, 1), (2, 2), (1, 2)], variants=8)
    unstable = backtest_overfitting_probability([(1, 8), (1, 7), (2, 8), (1, 6)], variants=8)

    assert stable < unstable
    assert unstable >= 0.75


def strong_evidence(**overrides):
    evidence = {
        "sample_size": 360,
        "returns_r": [0.4, -0.2, 0.8, 0.1, 0.5, -0.1] * 60,
        "benchmark_excess_returns": [0.3, -0.1, 0.6, 0.1, 0.4, -0.05] * 60,
        "markets": ["USA", "GERMANY"],
        "tickers": ["AAPL", "MSFT", "SAP", "NVDA"],
        "regimes": ["risk_on", "range_bound", "risk_off"],
        "windows": [{"id": "w1"}, {"id": "w2"}, {"id": "w3"}],
        "max_drawdown": -9.0,
        "raw_p_value": 0.001,
        "adjusted_p_value": 0.01,
        "multiple_testing_significant": True,
        "overfitting_probability": 0.15,
        "deflated_sharpe_probability": 0.97,
        "stability_by_window": [72.0, 78.0, 75.0],
        "stability_by_market": [70.0, 74.0],
        "stability_by_regime": [68.0, 73.0, 71.0],
        "asset_pnl_contributions": {"AAPL": 0.28, "MSFT": 0.25, "SAP": 0.23, "NVDA": 0.24},
        "cost_coverage": 1.0,
        "data_quality_score": 92.0,
        "complexity": 5,
    }
    evidence.update(overrides)
    return evidence


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_strategy_factory_persistence_is_deduplicated_and_auditable() -> None:
    with setup_db() as db:
        run = StrategyFactoryRun(run_uid="factory-1", hypothesis_family="momentum", generation_seed=7, status="RUNNING")
        db.add(run)
        db.flush()
        candidate = StrategyCandidateVariant(
            factory_run_id=run.id,
            fingerprint="candidate-fingerprint",
            family="momentum",
            setup_type="momentum_breakout",
            specification_json={"entry": "close_breakout"},
            lifecycle_state="VALIDATING",
        )
        db.add(candidate)
        db.flush()
        db.add(
            StrategyValidationFold(
                candidate_id=candidate.id,
                fold_number=1,
                train_start=datetime(2023, 1, 1),
                train_end=datetime(2023, 6, 1),
                validation_start=datetime(2023, 6, 8),
                validation_end=datetime(2023, 9, 1),
                purge_bars=5,
                embargo_bars=3,
                train_count=120,
                validation_count=60,
            )
        )
        db.add(
            StrategyPromotionEvent(
                candidate_id=candidate.id,
                registry_key="momentum:USA:Stock:1d-15m-5m-1m",
                event_type="PROMOTED",
                reason="all gates passed",
                reversible=True,
            )
        )
        db.commit()

        db.add(
            StrategyCandidateVariant(
                factory_run_id=run.id,
                fingerprint="candidate-fingerprint",
                family="momentum",
                setup_type="momentum_breakout",
            )
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("duplicate candidate fingerprint was accepted")


def test_299_trades_cannot_promote() -> None:
    result = evaluate_strategy_robustness(strong_evidence(sample_size=299))

    assert result.verdict == "NEEDS_MORE_EVIDENCE"
    assert "300" in result.reason


def test_costs_and_concentration_receive_distinct_rejections() -> None:
    costs = evaluate_strategy_robustness(
        strong_evidence(returns_r=[-0.1, -0.2, 0.05] * 120, benchmark_excess_returns=[-0.2] * 360)
    )
    concentrated = evaluate_strategy_robustness(
        strong_evidence(asset_pnl_contributions={"NVDA": 0.82, "AAPL": 0.08, "MSFT": 0.1})
    )

    assert costs.verdict == "REJECTED_COSTS"
    assert concentrated.verdict == "REJECTED_CONCENTRATION"


def test_strong_multi_market_evidence_can_promote() -> None:
    result = evaluate_strategy_robustness(strong_evidence())

    assert result.verdict == "PROMOTED_TO_PAPER"
    assert result.sample_size == 360
    assert result.bootstrap_lower_bound > 0
    assert result.net_expectancy_r > 0
    assert result.benchmark_excess > 0


def test_zero_overfitting_and_zero_adjusted_p_value_remain_valid_measurements() -> None:
    result = evaluate_strategy_robustness(
        strong_evidence(
            overfitting_probability=0.0,
            adjusted_p_value=0.0,
            multiple_testing_significant=True,
        )
    )

    assert result.overfitting_probability == 0.0
    assert result.verdict == "PROMOTED_TO_PAPER"


def test_initial_strategy_family_registry_is_complete_and_bounded() -> None:
    registry = StrategyFamilyRegistry()

    assert set(registry.names()) == {
        "momentum",
        "trend_following",
        "breakout",
        "pullback",
        "mean_reversion",
        "volatility_expansion",
        "earnings_news_reaction",
        "relative_strength",
        "cross_sectional_ranking",
        "intraday_scalping",
    }
    first = registry.variants("intraday_scalping", max_variants=24, seed=11)
    second = registry.variants("intraday_scalping", max_variants=24, seed=11)
    assert first == second
    assert len(first) == 24
    assert all(
        row["timeframe_stack"] == (["1h", "15m", "5m", "1m"] if row["market_filter"] == "forex_only" else ["1d", "15m", "5m", "1m"])
        for row in first
    )
    assert {row["setup_type"] for row in first} == {"intraday_breakout", "intraday_trend"}
    assert {row["regime_filter"] for row in first} == {
        "all",
        "trend_up_only",
        "range_bound_only",
        "trend_down_only",
    }
    assert {row.get("market_filter", "all") for row in first} == {
        "all",
        "usa_only",
        "europe_only",
        "forex_only",
    }
    assert all(row["evidence_binding"] == "hyperbolic_replay_v1" for row in first)


def test_intraday_factory_variants_are_distinct_executable_strategies() -> None:
    rows = StrategyFamilyRegistry().variants("intraday_scalping", max_variants=24, seed=11)

    executable = [ExecutableStrategySpec.from_payload(row["executable_strategy"]) for row in rows]

    assert len({row.fingerprint for row in executable}) == 24
    assert all(row["strategy_fingerprint"] == spec.fingerprint for row, spec in zip(rows, executable))
    assert {spec.entry_rule for spec in executable} == {"breakout_close", "trend_continuation"}
    assert len({spec.target_r_multiple for spec in executable}) > 1
    assert len({spec.stop_atr_multiple for spec in executable}) > 1
    assert all(
        spec.higher_timeframe_min_trend < 0.0
        for spec in executable
        if spec.regime_filter == "trend_down_only"
    )


@pytest.mark.parametrize(
    ("family", "setup_type", "required_timeframes", "execution_timeframe", "entry_rule"),
    (
        ("breakout", "swing_breakout", ["1d"], "1d", "breakout_close"),
        ("pullback", "pullback", ["1d", "15m"], "15m", "pullback_to_mean"),
        ("mean_reversion", "mean_reversion", ["15m", "5m"], "5m", "mean_reversion_deviation"),
    ),
)
def test_implemented_factory_families_expose_their_actual_execution_contract(
    family, setup_type, required_timeframes, execution_timeframe, entry_rule
) -> None:
    rows = StrategyFamilyRegistry().variants(family, max_variants=24, seed=11)
    executable_rows = [row for row in rows if row["evidence_binding"] == "hyperbolic_replay_v1"]

    assert len(executable_rows) == 16
    assert all(row.get("executable_strategy") for row in executable_rows)
    assert len({row["strategy_fingerprint"] for row in executable_rows}) == 16
    for row in executable_rows:
        spec = ExecutableStrategySpec.from_payload(row["executable_strategy"])
        assert row["timeframe_stack"] == required_timeframes
        assert row["strategy_fingerprint"] == spec.fingerprint
        assert row["executable_strategy"] == {
            "schema_version": "executable-strategy-v1",
            "family": family,
            "setup_type": setup_type,
            "required_timeframes": required_timeframes,
            "execution_timeframe": execution_timeframe,
            "entry_rule": entry_rule,
            "lookback": 10,
            "minimum_relative_volume": 0.0,
            "higher_timeframe_min_trend": 0.0,
            "atr_period": 14,
            "stop_atr_multiple": 1.0,
            "minimum_stop_percent": 0.01,
            "target_r_multiple": 2.0,
            "trailing_atr_multiple": 1.2,
            "maximum_holding_bars": 20,
            "regime_filter": row["regime_filter"],
            "market_filter": row.get("market_filter", "all"),
            "strategy_fingerprint": spec.fingerprint,
        }
    research_rows = [row for row in rows if row["evidence_binding"] == "not_implemented"]
    assert len(research_rows) == 8
    assert all("executable_strategy" not in row for row in research_rows)
    assert all("strategy_fingerprint" not in row for row in research_rows)


def test_daily_factory_candidate_reaches_research_frontier_without_promotion() -> None:
    with setup_db() as db:
        first = AlphaStrategyFactory().run_once(
            db, families=["breakout"], max_variants_per_family=1, seed=7, trigger="test"
        )
        second = AlphaStrategyFactory().run_once(
            db, families=["breakout"], max_variants_per_family=1, seed=7, trigger="test"
        )
        plan = StrategyPromotionFrontierService().research_plan(db, limit=1, seed=7)
        candidate = db.query(StrategyCandidateVariant).one()

        assert len(plan["specs"]) == 1
        spec = ExecutableStrategySpec.from_payload(plan["specs"][0])
        assert spec.setup_type == "swing_breakout"
        assert spec.required_timeframes == ("1d",)
        assert spec.execution_timeframe == "1d"
        assert candidate.fingerprint == spec.fingerprint
        assert candidate.timeframe_stack == ["1d"]
        assert candidate.is_champion is False
        assert candidate.final_verdict == "NEEDS_MORE_EVIDENCE"
        assert db.query(StrategyPromotionEvent).count() == 0

    assert first["new_candidates"] == 1
    assert first["promoted_to_paper"] == 0
    assert second["new_candidates"] == 0


def test_factory_run_is_idempotent_and_reports_missing_evidence() -> None:
    with setup_db() as db:
        factory = AlphaStrategyFactory()
        first = factory.run_once(db, families=["momentum"], max_variants_per_family=2, seed=5, trigger="test")
        second = factory.run_once(db, families=["momentum"], max_variants_per_family=2, seed=5, trigger="test")
        snapshot = strategy_factory_snapshot(db)

    assert first["variants_examined"] == 2
    assert first["rejection_counts"]["NEEDS_MORE_EVIDENCE"] == 2
    assert second["new_candidates"] == 0
    assert snapshot["examined_variants"] == 2
    assert snapshot["promoted_to_paper"] == 0


def test_candidate_evidence_requires_the_exact_replay_timeframe_stack() -> None:
    with setup_db() as db:
        asset = Asset(
            ticker="AAPL",
            name="Apple",
            category="Stock",
            sector="Technology",
            industry="Consumer Electronics",
            asset_type="Stock",
            country="USA",
            currency="USD",
            exchange="NASDAQ",
            is_active=True,
        )
        replay_run = HyperbolicReplayRun(run_id="replay-stack-test", status="COMPLETED")
        factory_run = StrategyFactoryRun(
            run_uid="factory-stack-test",
            hypothesis_family="intraday_scalping",
            generation_seed=1,
            status="RUNNING",
        )
        db.add_all([asset, replay_run, factory_run])
        db.flush()
        candidate = StrategyCandidateVariant(
            factory_run_id=factory_run.id,
            fingerprint="intraday-trend-full-stack",
            family="intraday_scalping",
            setup_type="intraday_trend",
            timeframe_stack=["1d", "15m", "5m", "1m"],
            specification_json={"evidence_binding": "hyperbolic_replay_v1"},
        )
        db.add(candidate)
        for index, required_timeframes in enumerate(
            (["1d", "15m", "5m"], ["1d", "15m", "5m", "1m"])
        ):
            db.add(
                HyperbolicReplayTrade(
                    run_id=replay_run.id,
                    asset_id=asset.id,
                    ticker=asset.ticker,
                    market="USA",
                    setup_type="intraday_trend",
                    timeframe="5m",
                    state="REPLAY_EVALUATED",
                    decision_timestamp=datetime(2025, 1, 1) + timedelta(minutes=index),
                    r_multiple=0.2 + index,
                    data_quality_score=95.0,
                    decision_payload={"required_timeframes": required_timeframes},
                    execution_payload={"cost_profile": {"round_trip_bps": 4.0}},
                )
            )
        db.flush()

        evidence = AlphaStrategyFactory._candidate_evidence(db, candidate)
        previous_validation = ReplayStrategyValidation(
            setup_type="intraday_trend",
            sample_size=2,
            verdict="NEEDS_MORE_EVIDENCE",
            explanation="Legacy validation counted an incompatible timeframe stack.",
        )
        db.add(previous_validation)
        db.flush()
        candidate.validation_id = previous_validation.id
        db.flush()
        requires_revalidation = AlphaStrategyFactory._has_new_evidence(db, candidate)

    assert evidence["sample_size"] == 1
    assert evidence["returns_r"] == [1.2]
    assert requires_revalidation is True


def test_candidate_evidence_cannot_borrow_results_from_another_strategy_fingerprint() -> None:
    with setup_db() as db:
        asset = Asset(
            ticker="NVDA",
            name="NVIDIA",
            category="Stock",
            sector="Technology",
            asset_type="Stock",
            country="USA",
            currency="USD",
            exchange="NASDAQ",
            is_active=True,
        )
        replay_run = HyperbolicReplayRun(run_id="fingerprint-isolation", status="COMPLETED")
        factory_run = StrategyFactoryRun(
            run_uid="fingerprint-isolation-factory",
            hypothesis_family="intraday_scalping",
            generation_seed=1,
            status="RUNNING",
        )
        db.add_all([asset, replay_run, factory_run])
        db.flush()
        strategies = StrategyFamilyRegistry().variants("intraday_scalping", max_variants=2, seed=7)
        selected = strategies[0]
        candidate = StrategyCandidateVariant(
            factory_run_id=factory_run.id,
            fingerprint=selected["strategy_fingerprint"],
            family="intraday_scalping",
            setup_type=selected["setup_type"],
            timeframe_stack=selected["timeframe_stack"],
            specification_json=selected,
        )
        db.add(candidate)
        for index, (fingerprint, r_multiple) in enumerate(
            ((selected["strategy_fingerprint"], 0.7), (strategies[1]["strategy_fingerprint"], -0.9))
        ):
            db.add(
                HyperbolicReplayTrade(
                    run_id=replay_run.id,
                    asset_id=asset.id,
                    ticker=asset.ticker,
                    market="USA",
                    setup_type=selected["setup_type"],
                    strategy_fingerprint=fingerprint,
                    timeframe="1m",
                    state="REPLAY_EVALUATED",
                    decision_timestamp=datetime(2025, 1, 1) + timedelta(minutes=index),
                    r_multiple=r_multiple,
                    data_quality_score=95.0,
                    decision_payload={"required_timeframes": selected["timeframe_stack"], "regime": "trend_up"},
                    execution_payload={"cost_profile": {"round_trip_bps": 4.0}},
                )
            )
        db.flush()

        evidence = AlphaStrategyFactory._candidate_evidence(db, candidate)

    assert evidence["sample_size"] == 1
    assert evidence["returns_r"] == [0.7]


def test_candidate_evidence_applies_only_point_in_time_regime_filter() -> None:
    with setup_db() as db:
        asset = Asset(
            ticker="NVDA",
            name="NVIDIA",
            category="Stock",
            sector="Technology",
            asset_type="Stock",
            country="USA",
            currency="USD",
            exchange="NASDAQ",
            is_active=True,
        )
        replay_run = HyperbolicReplayRun(run_id="regime-filter-run", status="COMPLETED")
        factory_run = StrategyFactoryRun(
            run_uid="regime-filter-factory",
            hypothesis_family="intraday_scalping",
            generation_seed=1,
            status="RUNNING",
        )
        db.add_all([asset, replay_run, factory_run])
        db.flush()
        candidate = StrategyCandidateVariant(
            factory_run_id=factory_run.id,
            fingerprint="intraday-trend-up-only",
            family="intraday_scalping",
            setup_type="intraday_trend",
            timeframe_stack=["1d", "15m", "5m", "1m"],
            specification_json={
                "evidence_binding": "hyperbolic_replay_v1",
                "regime_filter": "trend_up_only",
            },
        )
        db.add(candidate)
        for index, (regime, r_multiple) in enumerate(
            (("trend_up", 0.8), ("range_bound", -0.4), ("trend_down", -0.7))
        ):
            db.add(
                HyperbolicReplayTrade(
                    run_id=replay_run.id,
                    asset_id=asset.id,
                    ticker=asset.ticker,
                    market="USA",
                    setup_type="intraday_trend",
                    timeframe="5m",
                    state="REPLAY_EVALUATED",
                    decision_timestamp=datetime(2025, 1, 1) + timedelta(minutes=index),
                    r_multiple=r_multiple,
                    benchmark_excess=r_multiple / 2,
                    data_quality_score=95.0,
                    decision_payload={
                        "required_timeframes": ["1d", "15m", "5m", "1m"],
                        "regime": regime,
                    },
                    execution_payload={"cost_profile": {"round_trip_bps": 4.0}},
                )
            )
        db.flush()

        evidence = AlphaStrategyFactory._candidate_evidence(db, candidate)

    assert evidence["sample_size"] == 1
    assert evidence["returns_r"] == [0.8]
    assert evidence["benchmark_excess_returns"] == [0.4]
    assert evidence["regimes"] == ["trend_up"]
    assert evidence["regime_filter"] == "trend_up_only"


def test_candidate_evidence_applies_only_point_in_time_market_filter() -> None:
    with setup_db() as db:
        asset = Asset(
            ticker="AAPL",
            name="Apple",
            category="Stock",
            sector="Technology",
            asset_type="Stock",
            country="USA",
            currency="USD",
            exchange="NASDAQ",
            is_active=True,
        )
        replay_run = HyperbolicReplayRun(run_id="market-filter-run", status="COMPLETED")
        factory_run = StrategyFactoryRun(
            run_uid="market-filter-factory",
            hypothesis_family="intraday_scalping",
            generation_seed=1,
            status="RUNNING",
        )
        db.add_all([asset, replay_run, factory_run])
        db.flush()
        candidate = StrategyCandidateVariant(
            factory_run_id=factory_run.id,
            fingerprint="intraday-breakout-usa-only",
            family="intraday_scalping",
            setup_type="intraday_breakout",
            timeframe_stack=["1d", "15m", "5m", "1m"],
            specification_json={
                "evidence_binding": "hyperbolic_replay_v1",
                "regime_filter": "all",
                "market_filter": "usa_only",
            },
        )
        db.add(candidate)
        for index, (market, r_multiple) in enumerate(
            (("United States", 0.7), ("USA", 0.5), ("Germany", -0.8), ("Italy", -0.6))
        ):
            db.add(
                HyperbolicReplayTrade(
                    run_id=replay_run.id,
                    asset_id=asset.id,
                    ticker=asset.ticker,
                    market=market,
                    setup_type="intraday_breakout",
                    timeframe="1m",
                    state="REPLAY_EVALUATED",
                    decision_timestamp=datetime(2025, 2, 1) + timedelta(minutes=index),
                    r_multiple=r_multiple,
                    benchmark_excess=r_multiple / 2,
                    data_quality_score=95.0,
                    decision_payload={
                        "required_timeframes": ["1d", "15m", "5m", "1m"],
                        "regime": "trend_up",
                    },
                    execution_payload={"cost_profile": {"round_trip_bps": 4.0}},
                )
            )
        db.flush()

        evidence = AlphaStrategyFactory._candidate_evidence(db, candidate)

    assert evidence["sample_size"] == 2
    assert evidence["returns_r"] == [0.7, 0.5]
    assert evidence["markets"] == ["USA", "United States"]
    assert evidence["market_filter"] == "usa_only"


def test_factory_does_not_persist_fold_timestamps_inside_json_metrics() -> None:
    with setup_db() as db:
        strategy_fingerprint = StrategyFamilyRegistry().variants(
            "intraday_scalping", max_variants=1, seed=7
        )[0]["strategy_fingerprint"]
        asset = Asset(
            ticker="MSFT",
            name="Microsoft",
            category="Stock",
            sector="Technology",
            asset_type="Stock",
            country="USA",
            currency="USD",
            exchange="NASDAQ",
            is_active=True,
        )
        replay_run = HyperbolicReplayRun(run_id="json-safe-factory-run", status="COMPLETED")
        db.add_all([asset, replay_run])
        db.flush()
        for index in range(12):
            db.add(
                HyperbolicReplayTrade(
                    run_id=replay_run.id,
                    asset_id=asset.id,
                    ticker=asset.ticker,
                    market="USA",
                    setup_type="intraday_breakout",
                    strategy_fingerprint=strategy_fingerprint,
                    timeframe="1m",
                    state="REPLAY_EVALUATED",
                    decision_timestamp=datetime(2025, 1, 1) + timedelta(minutes=index),
                    r_multiple=0.2,
                    benchmark_excess=0.1,
                    data_quality_score=95.0,
                    decision_payload={
                        "required_timeframes": ["1d", "15m", "5m", "1m"],
                        "regime": "trend_up",
                    },
                    execution_payload={"cost_profile": {"round_trip_bps": 4.0}},
                )
            )
        db.commit()

        result = AlphaStrategyFactory().run_once(
            db,
            families=["intraday_scalping"],
            max_variants_per_family=1,
            seed=7,
            trigger="test",
        )
        validation = db.query(ReplayStrategyValidation).one()

    assert result["status"] == "COMPLETED"
    assert "timestamps" not in validation.metrics_json
    assert "returns_r" not in validation.metrics_json
    assert "benchmark_excess_returns" not in validation.metrics_json


def test_factory_exposes_positive_partial_stability_as_experimental_challenger(monkeypatch) -> None:
    monkeypatch.setattr("app.services.promoted_strategy_registry.settings.intraday_experimental_min_samples", 50)
    with setup_db() as db:
        strategy_fingerprint = StrategyFamilyRegistry().variants(
            "intraday_scalping", max_variants=1, seed=7
        )[0]["strategy_fingerprint"]
        asset = Asset(
            ticker="NVDA",
            name="NVIDIA",
            category="Stock",
            sector="Technology",
            asset_type="Stock",
            country="USA",
            currency="USD",
            exchange="NASDAQ",
            is_active=True,
        )
        replay_run = HyperbolicReplayRun(run_id="partial-stability-run", status="COMPLETED")
        db.add_all([asset, replay_run])
        db.flush()
        returns = [0.3] * 50 + [0.2] * 50 + [-0.05] * 50
        for index, r_multiple in enumerate(returns):
            db.add(
                HyperbolicReplayTrade(
                    run_id=replay_run.id,
                    asset_id=asset.id,
                    ticker=asset.ticker,
                    market="United States",
                    setup_type="intraday_breakout",
                    strategy_fingerprint=strategy_fingerprint,
                    timeframe="1m",
                    state="REPLAY_EVALUATED",
                    decision_timestamp=datetime(2025, 3, 1) + timedelta(minutes=index),
                    r_multiple=r_multiple,
                    benchmark_excess=0.05,
                    data_quality_score=95.0,
                    net_pnl=r_multiple,
                    decision_payload={
                        "required_timeframes": ["1d", "15m", "5m", "1m"],
                        "regime": "trend_up",
                    },
                    execution_payload={"cost_profile": {"round_trip_bps": 4.0}},
                )
            )
        db.commit()

        AlphaStrategyFactory().run_once(
            db,
            families=["intraday_scalping"],
            max_variants_per_family=1,
            seed=7,
            trigger="test",
        )
        validation = db.query(ReplayStrategyValidation).one()
        experimental = BlumPromotedStrategyRegistry().list_experimental(
            db,
            market="USA",
            asset_class="Stock",
        )

    assert validation.verdict == "NEEDS_MORE_EVIDENCE"
    assert validation.metrics_json["stability_score"] == 0.0
    assert validation.metrics_json["experimental_stability_score"] >= 50.0
    assert [row.validation_id for row in experimental] == [validation.id]


def test_multi_family_factory_run_uses_bounded_index_key_and_preserves_full_selection() -> None:
    with setup_db() as db:
        families = list(StrategyFamilyRegistry().names())

        AlphaStrategyFactory().run_once(db, families=families, max_variants_per_family=1, seed=7, trigger="test")
        run = db.query(StrategyFactoryRun).one()

    assert len(run.hypothesis_family) <= 80
    assert run.hypothesis_family.startswith("multi_family:")
    assert run.budgets_json["selected_families"] == families


def test_factory_folds_group_trades_that_share_a_decision_timestamp() -> None:
    with setup_db() as db:
        run = StrategyFactoryRun(run_uid="duplicate-time-run", hypothesis_family="momentum", generation_seed=7, status="RUNNING")
        db.add(run)
        db.flush()
        candidate = StrategyCandidateVariant(
            factory_run_id=run.id,
            fingerprint="duplicate-time-candidate",
            family="momentum",
            setup_type="momentum_breakout",
            timeframe_stack=["1d", "15m", "5m", "1m"],
        )
        db.add(candidate)
        db.flush()
        start = datetime(2024, 1, 1)
        timestamps = [start + timedelta(days=index) for index in range(40) for _ in range(2)]

        AlphaStrategyFactory._persist_folds(db, candidate, {"timestamps": timestamps})
        folds = db.query(StrategyValidationFold).filter_by(candidate_id=candidate.id).all()

    assert len(folds) == 3
    assert all(fold.train_end < fold.validation_start for fold in folds)


def test_champion_challenger_promotion_is_reversible_and_audited() -> None:
    with setup_db() as db:
        run = StrategyFactoryRun(run_uid="champion-run", hypothesis_family="momentum", generation_seed=1, status="COMPLETED")
        db.add(run)
        db.flush()
        candidates = []
        validations = []
        for index in (1, 2):
            validation = ReplayStrategyValidation(
                setup_type="momentum_breakout",
                sample_size=400,
                markets_json=["USA", "GERMANY"],
                windows_json=[{"id": "w1"}, {"id": "w2"}],
                metrics_json=strong_evidence(),
                overfitting_score=15.0,
                verdict="PROMOTED_TO_PAPER",
                explanation="all gates passed",
            )
            db.add(validation)
            db.flush()
            candidate = StrategyCandidateVariant(
                factory_run_id=run.id,
                validation_id=validation.id,
                fingerprint=f"champion-{index}",
                family="momentum",
                setup_type="momentum_breakout",
                market="USA",
                asset_class="Stock",
                timeframe_stack=["1d", "15m", "5m", "1m"],
                final_verdict="PROMOTED_TO_PAPER",
            )
            db.add(candidate)
            db.flush()
            candidates.append(candidate)
            validations.append(validation)

        registry = ChampionChallengerRegistry()
        first = registry.promote(db, candidates[0], validations[0])
        second = registry.promote(db, candidates[1], validations[1])
        db.commit()
        db.refresh(candidates[0])
        db.refresh(candidates[1])

    assert first["status"] == "promoted"
    assert second["previous_candidate_id"] == candidates[0].id
    assert candidates[0].is_champion is False
    assert candidates[1].is_champion is True
    assert second["reversible"] is True


def test_factory_and_execution_workers_are_independently_registered() -> None:
    assert WORKER_DEFINITIONS["alpha_strategy_factory"].queue_name == "strategy_research"
    assert WORKER_DEFINITIONS["paper_execution_lifecycle"].queue_name == "paper_execution"


def test_factory_and_execution_snapshots_are_read_only() -> None:
    with setup_db() as db:
        before_runs = db.query(StrategyFactoryRun).count()
        before_orders = db.query(PaperExecutionOrder).count()
        factory = strategy_factory_snapshot(db)
        execution = execution_reality_snapshot(db)
        after_runs = db.query(StrategyFactoryRun).count()
        after_orders = db.query(PaperExecutionOrder).count()

    assert factory["status"] == "NO_FACTORY_RUNS"
    assert execution["status"] == "NO_EXECUTION_ORDERS"
    assert (before_runs, before_orders) == (after_runs, after_orders)
