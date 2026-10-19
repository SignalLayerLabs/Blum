from datetime import datetime, timedelta
import hashlib

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Asset, HyperbolicReplayTrade, ModelVersion, ReplayMarketBar, ReplayStrategyValidation, StrategyMemory
from app.services.hyperbolic_replay import (
    BlumHyperbolicReplayEngine,
    ReplayRunRequest,
    SETUP_REQUIREMENTS,
    _choose_setup,
    _eligible_setups,
    _manage_trade,
)
from app.services.replay_execution import ReplayExecutionModel, ReplayPositionSizer
from app.services.replay_validation import ReplayExperimentService, ReplayLearningFeedbackService, ReplayWalkForwardValidator
from app.services.adaptive_replay_training import _validation_evidence
from app.services.executable_strategy import ExecutableStrategySpec, canonical_strategy_spec


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_asset(db: Session, ticker: str = "NVDA", market: str = "USA") -> Asset:
    asset = Asset(
        ticker=ticker,
        name=ticker,
        category="Stock",
        sector="Technology",
        country=market,
        asset_type="Stock",
        currency="USD" if market == "USA" else "EUR",
        exchange="NASDAQ" if market == "USA" else "MIL",
        is_active=True,
    )
    db.add(asset)
    db.flush()
    return asset


def seed_trending_bars(db: Session, asset: Asset, timeframe: str, start: datetime, count: int, minutes: int, step: float = 0.4) -> None:
    for index in range(count):
        close = 100.0 + index * step
        db.add(
            ReplayMarketBar(
                asset_id=asset.id,
                source_symbol=asset.ticker,
                normalized_symbol=asset.ticker,
                market=asset.country,
                timeframe=timeframe,
                bar_timestamp=start + timedelta(minutes=minutes * index),
                open=close - 0.2,
                high=close + 0.5,
                low=close - 0.6,
                close=close,
                volume=1_000_000 + index * 10_000,
                provider="fixture",
                acquired_at=datetime.utcnow(),
                data_quality_score=95.0,
                source_metadata={"source": "test"},
            )
        )
    db.commit()


def test_execution_costs_differ_between_liquid_us_and_less_liquid_europe():
    model = ReplayExecutionModel()
    us = model.profile(market="USA", asset_type="Stock", liquidity_score=90, session="regular")
    europe = model.profile(market="ITALY", asset_type="Stock", liquidity_score=35, session="regular")

    assert europe.total_round_trip_bps > us.total_round_trip_bps


@pytest.mark.parametrize(
    ("open_price", "high", "low", "close", "expected_price", "expected_reason"),
    (
        (90.0, 94.0, 88.0, 91.0, 90.0, "stop"),
        (100.0, 104.0, 95.0, 102.0, 98.0, "stop"),
        (100.0, 112.0, 95.0, 110.0, 98.0, "stop"),
        (115.0, 118.0, 114.0, 116.0, 110.0, "target"),
        (None, 104.0, 95.0, 100.0, 98.0, "stop"),
    ),
)
def test_replay_long_exit_uses_gap_open_and_conservative_trigger_ordering(
    open_price, high, low, close, expected_price, expected_reason
):
    bar = ReplayMarketBar(
        bar_timestamp=datetime(2024, 1, 3, 16),
        open=open_price, high=high, low=low, close=close,
    )

    exit_bar, exit_price, reason = _manage_trade([bar], 0, stop=98.0, target=110.0)

    assert exit_bar is bar
    assert exit_price == expected_price
    assert reason == expected_reason


def test_position_size_decreases_when_quality_or_liquidity_falls():
    sizer = ReplayPositionSizer(max_risk_fraction=0.01)
    high = sizer.size(
        capital=10_000,
        entry=100,
        stop=96,
        atr=2,
        liquidity_score=90,
        confidence=70,
        edge_score=70,
        data_quality=95,
        regime_alignment=80,
    )
    low = sizer.size(
        capital=10_000,
        entry=100,
        stop=96,
        atr=2,
        liquidity_score=30,
        confidence=70,
        edge_score=70,
        data_quality=45,
        regime_alignment=35,
    )

    assert low.units < high.units
    assert low.risk_amount <= high.risk_amount


def test_replay_signal_precedes_entry_and_never_uses_future_feature_bars():
    with setup_db() as db:
        asset = seed_asset(db)
        start = datetime(2025, 1, 1)
        seed_trending_bars(db, asset, "1d", start, count=80, minutes=1440)
        result = BlumHyperbolicReplayEngine().run_cycle(
            db,
            ReplayRunRequest(asset_ids=[asset.id], max_assets=1, max_trades=4, fetch_missing=False),
        )
        trades = db.scalars(select(HyperbolicReplayTrade).order_by(HyperbolicReplayTrade.id)).all()

    assert result["trades_generated"] == 4
    assert result["trades_validated"] == 4
    assert result["lookahead_violations"] == 0
    for trade in trades:
        assert trade.entry_timestamp > trade.decision_timestamp
        assert max(trade.decision_payload["feature_bar_timestamps"]) <= trade.decision_timestamp.isoformat()
        assert all(
            max(timestamps) <= trade.decision_timestamp.isoformat()
            for timestamps in trade.decision_payload["context_bar_timestamps"].values()
            if timestamps
        )
        assert [transition["state"] for transition in trade.decision_payload["state_transitions"]] == [
            "REPLAY_CANDIDATE",
            "REPLAY_OPEN",
            "REPLAY_CLOSED",
            "REPLAY_EVALUATED",
        ]
        assert trade.evidence_type == "REPLAY_EVIDENCE"


def test_replaying_same_asset_window_does_not_duplicate_learning_evidence():
    with setup_db() as db:
        asset = seed_asset(db)
        seed_trending_bars(db, asset, "1d", datetime(2025, 1, 1), count=80, minutes=1440)
        first = BlumHyperbolicReplayEngine().run_cycle(
            db,
            ReplayRunRequest(asset_ids=[asset.id], max_assets=1, max_trades=100, fetch_missing=False),
        )
        second = BlumHyperbolicReplayEngine().run_cycle(
            db,
            ReplayRunRequest(asset_ids=[asset.id], max_assets=1, max_trades=100, fetch_missing=False),
        )
        count = db.scalar(select(func.count(HyperbolicReplayTrade.id)))

    assert first["trades_generated"] > 4
    assert second["trades_generated"] == 0
    assert count == first["trades_generated"]
    assert any(blocker["code"] == "NO_NEW_REPLAY_EVIDENCE" for blocker in second["blockers"])


def test_priority_market_keeps_forex_in_each_bounded_replay_slice():
    with setup_db() as db:
        us_assets = [seed_asset(db, ticker=f"US{index}", market="USA") for index in range(5)]
        fx_assets = [seed_asset(db, ticker=ticker, market="FOREX") for ticker in ("EURUSD=X", "GBPUSD=X")]
        db.commit()
        us_identity = [(asset.id, asset.ticker) for asset in us_assets]
        fx_identity = [(asset.id, asset.ticker) for asset in fx_assets]
        engine = BlumHyperbolicReplayEngine()

        first = engine.run_cycle(
            db,
            ReplayRunRequest(
                markets=["USA", "FOREX"],
                priority_markets=("FOREX",),
                max_assets=3,
                max_trades=1,
                fetch_missing=False,
            ),
        )
        second = engine.run_cycle(
            db,
            ReplayRunRequest(
                markets=["USA", "FOREX"],
                priority_markets=("FOREX",),
                after_asset_id=first["next_cursor"]["asset_id"],
                market_cursors=first["next_cursor"]["market_cursors"],
                max_assets=3,
                max_trades=1,
                fetch_missing=False,
            ),
        )

    assert first["assets_selected"] == [us_identity[0][1], us_identity[1][1], fx_identity[0][1]]
    assert first["next_cursor"] == {
        "asset_id": us_identity[1][0],
        "market_cursors": {"FOREX": fx_identity[0][0]},
    }
    assert second["assets_selected"] == [us_identity[2][1], us_identity[3][1], fx_identity[1][1]]
    assert second["next_cursor"] == {
        "asset_id": us_identity[3][0],
        "market_cursors": {"FOREX": fx_identity[1][0]},
    }


def test_full_multi_timeframe_replay_uses_daily_context_and_one_minute_execution():
    with setup_db() as db:
        asset = seed_asset(db)
        start = datetime(2025, 1, 1)
        seed_trending_bars(db, asset, "1d", start - timedelta(days=60), count=80, minutes=1440)
        seed_trending_bars(db, asset, "15m", start - timedelta(hours=10), count=80, minutes=15)
        seed_trending_bars(db, asset, "5m", start - timedelta(hours=3), count=80, minutes=5)
        seed_trending_bars(db, asset, "1m", start, count=80, minutes=1)
        result = BlumHyperbolicReplayEngine().run_cycle(
            db,
            ReplayRunRequest(asset_ids=[asset.id], max_assets=1, max_trades=3, fetch_missing=False),
        )
        trade = db.scalar(select(HyperbolicReplayTrade).order_by(HyperbolicReplayTrade.id))

    assert result["timeframes_used"] == ["1d", "15m", "5m", "1m"]
    assert trade is not None
    assert trade.setup_type == "intraday_breakout"
    assert trade.timeframe == "1m"
    assert set(trade.decision_payload["context_bar_timestamps"]) == {"1d", "15m", "5m", "1m"}
    assert trade.decision_payload["multi_timeframe_confirmation"]["confirmed"] is True
    assert all(
        timestamp <= trade.decision_timestamp.isoformat()
        for timestamps in trade.decision_payload["context_bar_timestamps"].values()
        for timestamp in timestamps
    )


def test_full_multi_timeframe_replay_exercises_distinct_intraday_strategies():
    with setup_db() as db:
        asset = seed_asset(db)
        start = datetime(2025, 1, 1)
        seed_trending_bars(db, asset, "1d", start - timedelta(days=60), count=80, minutes=1440)
        seed_trending_bars(db, asset, "15m", start - timedelta(hours=10), count=80, minutes=15)
        seed_trending_bars(db, asset, "5m", start - timedelta(hours=3), count=80, minutes=5)
        seed_trending_bars(db, asset, "1m", start, count=80, minutes=1)

        BlumHyperbolicReplayEngine().run_cycle(
            db,
            ReplayRunRequest(asset_ids=[asset.id], max_assets=1, max_trades=4, fetch_missing=False),
        )
        setup_types = set(db.scalars(select(HyperbolicReplayTrade.setup_type)).all())

    assert {"intraday_breakout", "intraday_trend"}.issubset(setup_types)


def test_distinct_strategy_fingerprints_can_replay_the_same_asset_window():
    with setup_db() as db:
        asset = seed_asset(db)
        start = datetime(2025, 1, 1)
        seed_trending_bars(db, asset, "1d", start - timedelta(days=60), count=80, minutes=1440)
        seed_trending_bars(db, asset, "15m", start - timedelta(hours=10), count=80, minutes=15)
        seed_trending_bars(db, asset, "5m", start - timedelta(hours=3), count=80, minutes=5)
        seed_trending_bars(db, asset, "1m", start, count=80, minutes=1)
        canonical = canonical_strategy_spec("intraday_breakout")
        alternative = ExecutableStrategySpec.from_payload(
            {**canonical.to_payload(), "target_r_multiple": 2.5}
        )

        result = BlumHyperbolicReplayEngine().run_cycle(
            db,
            ReplayRunRequest(
                asset_ids=[asset.id],
                max_assets=1,
                max_trades=4,
                fetch_missing=False,
                strategy_specs=(canonical.to_payload(), alternative.to_payload()),
            ),
        )
        trades = db.scalars(
            select(HyperbolicReplayTrade).order_by(HyperbolicReplayTrade.decision_timestamp, HyperbolicReplayTrade.id)
        ).all()

    assert result["trades_generated"] == 4
    assert {row.strategy_fingerprint for row in trades} == {
        canonical.fingerprint,
        alternative.fingerprint,
    }
    assert all(row.decision_payload["executable_strategy"]["strategy_fingerprint"] == row.strategy_fingerprint for row in trades)
    assert all(
        max(row.decision_payload["signal_evidence"]["feature_bar_timestamps"])
        <= row.decision_timestamp.isoformat()
        for row in trades
    )


def test_replay_budget_is_distributed_across_assets_instead_of_exhausted_by_first_ticker():
    with setup_db() as db:
        first = seed_asset(db, "AAPL")
        second = seed_asset(db, "MSFT")
        start = datetime(2025, 1, 1)
        seed_trending_bars(db, first, "1d", start, count=80, minutes=1440)
        seed_trending_bars(db, second, "1d", start, count=80, minutes=1440)

        BlumHyperbolicReplayEngine().run_cycle(
            db,
            ReplayRunRequest(asset_ids=[first.id, second.id], max_assets=2, max_trades=4, fetch_missing=False),
        )
        evidence_by_ticker = dict(
            db.execute(
                select(HyperbolicReplayTrade.ticker, func.count(HyperbolicReplayTrade.id))
                .group_by(HyperbolicReplayTrade.ticker)
            ).all()
        )

    assert evidence_by_ticker == {"AAPL": 2, "MSFT": 2}


def test_higher_timeframe_contradiction_blocks_intraday_breakout():
    with setup_db() as db:
        asset = seed_asset(db)
        start = datetime(2025, 1, 1)
        seed_trending_bars(db, asset, "1d", start - timedelta(days=60), count=80, minutes=1440, step=-0.4)
        seed_trending_bars(db, asset, "15m", start - timedelta(hours=10), count=80, minutes=15)
        seed_trending_bars(db, asset, "5m", start - timedelta(hours=3), count=80, minutes=5)
        seed_trending_bars(db, asset, "1m", start, count=80, minutes=1)
        result = BlumHyperbolicReplayEngine().run_cycle(
            db,
            ReplayRunRequest(asset_ids=[asset.id], max_assets=1, max_trades=3, fetch_missing=False),
        )

    assert result["trades_generated"] == 0
    assert any(blocker["code"] == "NO_NEW_REPLAY_EVIDENCE" for blocker in result["blockers"])


def test_daily_replay_continues_and_intraday_gaps_are_reported():
    with setup_db() as db:
        asset = seed_asset(db, "ENI.MI", "ITALY")
        seed_trending_bars(db, asset, "1d", datetime(2025, 1, 1), count=60, minutes=1440)
        result = BlumHyperbolicReplayEngine().run_cycle(
            db,
            ReplayRunRequest(asset_ids=[asset.id], max_assets=1, max_trades=2, fetch_missing=False),
        )

    assert result["timeframes_used"] == ["1d"]
    assert result["trades_generated"] == 2
    assert {row["timeframe"] for row in result["blockers"] if row["code"] == "COVERAGE_INCOMPLETE"} == {"15m", "5m", "1m"}


def test_setup_requirements_include_mean_reversion_without_fake_one_minute_data():
    assert SETUP_REQUIREMENTS["mean_reversion"] == ("15m", "5m")
    assert _choose_setup({"15m", "5m"}) == ("mean_reversion", "5m")


def test_eligible_setups_returns_every_strategy_supported_by_available_timeframes():
    eligible = _eligible_setups({"1d", "15m", "5m", "1m"})

    assert eligible[:2] == [
        ("intraday_breakout", "1m"),
        ("intraday_trend", "5m"),
    ]
    assert ("swing_breakout", "1d") in eligible


def test_replay_computes_benchmark_excess_only_from_synchronized_stored_bars():
    with setup_db() as db:
        asset = seed_asset(db)
        benchmark = seed_asset(db, "SPY", "USA")
        start = datetime(2025, 1, 1)
        seed_trending_bars(db, asset, "1d", start, count=80, minutes=1440)
        seed_trending_bars(db, benchmark, "1d", start, count=80, minutes=1440)
        BlumHyperbolicReplayEngine().run_cycle(
            db,
            ReplayRunRequest(asset_ids=[asset.id], max_assets=1, max_trades=1, fetch_missing=False),
        )
        trade = db.scalar(select(HyperbolicReplayTrade).where(HyperbolicReplayTrade.asset_id == asset.id))

    assert trade is not None
    assert trade.benchmark_excess is not None
    assert trade.decision_payload["benchmark_ticker"] == "SPY"
    assert trade.decision_payload["benchmark_status"] == "available"


def validation_fixture(**overrides) -> dict:
    payload = {
        "sample_size": 500,
        "markets": ["USA", "GERMANY"],
        "windows": [{"id": "w1"}, {"id": "w2"}, {"id": "w3"}],
        "benchmark_excess": 4.2,
        "expectancy_r": 0.22,
        "max_drawdown": -9.0,
        "overfitting_score": 18.0,
        "stability_score": 72.0,
    }
    payload.update(overrides)
    return payload


def test_experiment_grid_is_bounded():
    variants = ReplayExperimentService(max_experiments=5).bounded_variants(
        {"setup_type": "swing_breakout", "market": "USA", "timeframes": ["1d"]}
    )
    assert 1 <= len(variants) <= 5
    assert {"holding_period", "timeframe_combination", "regime_filter"}.issubset(variants[0])


def test_replay_experiment_identity_is_stable_across_processes():
    variant = {
        "setup_type": "swing_breakout",
        "market": "USA",
        "timeframes": ["1d"],
        "entry_trigger": "close_breakout",
        "stop_method": "atr_1_5",
        "target_method": "two_r",
        "confidence_threshold": 60.0,
        "risk_reward_threshold": 1.5,
    }
    training_window = {"start": "2025-01-01", "end": "2025-06-30"}
    identity = "|".join(
        [
            variant["setup_type"],
            variant["market"],
            variant["entry_trigger"],
            variant["stop_method"],
            variant["target_method"],
            training_window["start"],
        ]
    )
    expected = f"replay-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]}"

    with setup_db() as db:
        first = ReplayExperimentService().persist(
            db,
            variant,
            training_window=training_window,
            validation_window={"start": "2025-07-01", "end": "2025-12-31"},
        )
        second = ReplayExperimentService().persist(
            db,
            variant,
            training_window=training_window,
            validation_window={"start": "2025-07-01", "end": "2025-12-31"},
        )

    assert first.experiment_id == expected
    assert second.id == first.id


def test_strategy_cannot_promote_below_300_validated_trades():
    result = ReplayWalkForwardValidator().verdict(validation_fixture(sample_size=299))
    assert result["verdict"] == "NEEDS_MORE_EVIDENCE"


def test_strategy_requires_multiple_markets_and_windows():
    one_market = ReplayWalkForwardValidator().verdict(validation_fixture(markets=["USA"]))
    one_window = ReplayWalkForwardValidator().verdict(validation_fixture(windows=[{"id": "w1"}]))
    assert one_market["verdict"] == "REJECTED_UNSTABLE"
    assert one_window["verdict"] == "REJECTED_UNSTABLE"


def test_walk_forward_evidence_exposes_risk_adjusted_metrics_and_regime_dependency():
    with setup_db() as db:
        asset = seed_asset(db)
        seed_trending_bars(db, asset, "1d", datetime(2025, 1, 1), count=90, minutes=1440)
        BlumHyperbolicReplayEngine().run_cycle(
            db,
            ReplayRunRequest(asset_ids=[asset.id], max_assets=1, max_trades=6, fetch_missing=False),
        )
        trades = db.scalars(select(HyperbolicReplayTrade).order_by(HyperbolicReplayTrade.decision_timestamp)).all()
        evidence = _validation_evidence(trades)

    assert {"average_r", "win_rate", "profit_factor", "sharpe_proxy", "sortino_proxy", "regime_dependency"}.issubset(evidence)
    assert evidence["sample_size"] == len(trades)
    assert evidence["benchmark_status"] == "missing"


def test_evaluated_replay_updates_strategy_memory_with_replay_evidence():
    with setup_db() as db:
        asset = seed_asset(db)
        seed_trending_bars(db, asset, "1d", datetime(2025, 1, 1), count=60, minutes=1440)
        BlumHyperbolicReplayEngine().run_cycle(
            db,
            ReplayRunRequest(asset_ids=[asset.id], max_assets=1, max_trades=1, fetch_missing=False),
        )
        trade = db.scalar(select(HyperbolicReplayTrade))
        result = ReplayLearningFeedbackService().apply_evaluated_trade(db, trade)
        memory = db.scalar(select(StrategyMemory).where(StrategyMemory.memory_key == result["memory_key"]))

    assert memory is not None
    assert memory.evidence["evidence_type"] == "REPLAY_EVIDENCE"
    assert memory.sample_count == 1


def test_model_version_is_not_promoted_without_measured_out_of_sample_improvement():
    with setup_db() as db:
        validation = ReplayStrategyValidation(
            setup_type="swing_breakout",
            sample_size=500,
            markets_json=["USA", "GERMANY"],
            windows_json=[{"id": "w1"}, {"id": "w2"}],
            metrics_json={
                "out_of_sample_improvement": True,
                "out_of_sample_score": 0.0,
                "candidate_weights": {"momentum": 0.4},
            },
            overfitting_score=15.0,
            verdict="PROMOTED_TO_PAPER",
            explanation="fixture",
        )
        db.add(validation)
        db.flush()
        result = ReplayLearningFeedbackService().apply_validation(db, validation)
        versions = db.scalar(select(func.count(ModelVersion.id)))

    assert result["status"] == "not_promoted"
    assert versions == 0
