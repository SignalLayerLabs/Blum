"""Native outcome identity and historical provenance cannot change on retry."""

from datetime import datetime, timedelta
import pytest
from test_forex_trader_core import db, NOW, market_input, strategy

from app.services.trading_ml.features import TradingMLFeatureBuilder
from test_trading_ml_features import DECISION_AT, equity_prediction, equity_outcome


def test_historical_prediction_created_today_keeps_original_decision_clock_and_lane():
    prediction = equity_prediction()
    prediction.created_at = datetime(2026, 10, 21, 10)
    outcome = equity_outcome(realized_return=2.0)
    outcome.created_at = prediction.created_at
    example = TradingMLFeatureBuilder().from_equity(prediction, outcome)
    assert example.decision_timestamp == DECISION_AT
    assert example.evidence_lane == "REPLAY_EVIDENCE"
    assert example.outcome_timestamp < prediction.created_at


def test_online_information_schema_preserves_legacy_state_and_uses_events(tmp_path):
    from dataclasses import replace
    from app.services.trading_ml.contracts import FeatureSchema
    from app.services.trading_ml.training import OnlineShadowTrainer
    from test_information_model import labeled_rows
    from test_trading_ml_training import examples

    legacy = OnlineShadowTrainer(tmp_path)
    legacy_result = legacy.partial_fit(examples(48))
    information = OnlineShadowTrainer(tmp_path, schema=FeatureSchema.information())
    rows = labeled_rows()
    first = information.partial_fit(rows)
    repeated = information.partial_fit(rows)
    assert first.sample_count == repeated.sample_count == 240
    assert repeated.parameters["new_samples"] == 0
    assert repeated.model_bundle.schema_hash == FeatureSchema.information().hash
    assert legacy.current("equity").sample_count == legacy_result.sample_count == 48
    same_price = rows[0]
    informed = replace(
        same_price, features={**same_price.features, "event_novelty": 2.0}
    )
    probabilities, _ = repeated.model_bundle.predict((same_price, informed))
    assert probabilities[1] > probabilities[0]
    assert first.decision_authority is False


def test_online_v2_rejects_an_unmarked_legacy_example(tmp_path):
    from app.services.trading_ml.contracts import FeatureSchema
    from app.services.trading_ml.training import OnlineShadowTrainer
    from test_trading_ml_training import examples

    with pytest.raises(ValueError, match="INFORMATION_SCHEMA_REQUIRED"):
        OnlineShadowTrainer(tmp_path, schema=FeatureSchema.information()).partial_fit(
            examples()
        )


def native_forex(db, *, close=True):
    from dataclasses import replace
    from sqlalchemy import select
    from app.models import ForexDecision, ForexPosition, LiveForwardPaperGame
    from app.services.forex_trader import BlumForexTraderCore
    from app.services.information.context import OpportunityContextBuilder

    market = market_input()
    context = OpportunityContextBuilder().build(
        db,
        market_family="forex",
        asset_key=market.pair,
        decision_at=NOW,
        price_refs=(
            {
                "source_uid": "fixture:EURUSD",
                "provider": "fixture",
                "timestamp": market.frames["1m"].market_timestamp.isoformat(),
                "available_at": NOW.isoformat(),
                "acquired_at": NOW.isoformat(),
                "close": market.frames["1m"].closes[-1],
                "timeframe": "1m",
            },
        ),
    )
    market = replace(market, information_context=context)
    db.add(
        LiveForwardPaperGame(
            game_id="feedback-funding",
            starting_capital=100_000,
            current_capital=100_000,
            cash=100_000,
            configuration={"account_currency": "EUR"},
        )
    )
    core = BlumForexTraderCore()
    from app.services.information.model import InformationAdvice

    class FrozenFixtureAdvisor:
        def advise(self, *args, **kwargs):
            return InformationAdvice(
                "UNSUPPORTED_SCOPE", model_uid="fixture-checkpoint", model_hash="a" * 64
            )

    core.information_policy.advisor = FrozenFixtureAdvisor()
    core.run_cycle(
        db,
        inputs=[market],
        strategies={market.pair: strategy()},
        now=NOW,
        cycle_key="feedback-submit",
    )
    decision = db.scalar(select(ForexDecision))
    filled_at = NOW + timedelta(seconds=1)
    core.run_cycle(
        db,
        inputs=[
            replace(
                market,
                as_of=filled_at,
                information_context=None,
                quote=replace(market.quote, timestamp=filled_at),
            )
        ],
        strategies={},
        now=filled_at,
        cycle_key="feedback-fill",
    )
    position = db.scalar(select(ForexPosition))
    assert position is not None
    if close:
        exited_at = NOW + timedelta(minutes=1)
        quote = replace(
            market.quote,
            bid=position.target_price + 0.0001,
            ask=position.target_price + 0.00018,
            timestamp=exited_at,
        )
        core.manager.manage(db, {market.pair: quote}, now=exited_at)
        assert position.status == "CLOSED" and position.realized_r is not None
    db.commit()
    return position, context


def test_open_native_exposure_is_not_a_training_outcome(db, tmp_path):
    from app.services.information.feedback import InformationFeedback

    native_forex(db, close=False)
    result = InformationFeedback(artifact_root=tmp_path).project(
        db, as_of=datetime.utcnow() + timedelta(seconds=1)
    )
    assert result["new_examples"] == 0


def test_native_closure_is_enqueued_once_with_frozen_context_and_checkpoint(
    db, tmp_path
):
    from sqlalchemy import select
    from app.models import InformationFeedbackOutbox
    from app.services.information.feedback import InformationFeedback

    position, context = native_forex(db)
    service = InformationFeedback(artifact_root=tmp_path)
    at = datetime.utcnow() + timedelta(seconds=1)
    first = service.project(db, as_of=at)
    db.commit()
    second = service.project(db, as_of=at)
    assert first["new_examples"] == 1 and second["new_examples"] == 0
    records = db.scalars(select(InformationFeedbackOutbox)).all()
    assert len(records) == 1
    assert records[0].source_uid == f"forex_position:{position.position_uid}"
    assert records[0].payload_json["frozen_context"]["hash"] == context.hash
    assert records[0].payload_json["checkpoint_hash"] == "a" * 64
    assert records[0].status == "PENDING"


def test_changed_same_native_uid_is_quarantined_without_relabeling(db, tmp_path):
    from sqlalchemy import select
    from app.models import InformationFeedbackOutbox
    from app.services.information.feedback import InformationFeedback

    position, _ = native_forex(db)
    service = InformationFeedback(artifact_root=tmp_path)
    at = datetime.utcnow() + timedelta(seconds=1)
    service.project(db, as_of=at)
    db.commit()
    record = db.scalar(select(InformationFeedbackOutbox))
    original = record.content_hash
    position.net_pnl *= 0.8
    position.realized_r *= 0.8
    db.commit()
    result = service.project(db, as_of=at)
    assert result["new_examples"] == 0
    assert record.status == "QUARANTINED"
    assert record.content_hash == original
    assert record.conflict_hash != original


def test_publication_crash_resumes_without_duplicate_features_or_learning(
    db, tmp_path, monkeypatch
):
    from app.services.information.feedback import InformationFeedback

    native_forex(db)
    service = InformationFeedback(artifact_root=tmp_path)
    at = datetime.utcnow() + timedelta(seconds=1)
    service.project(db, as_of=at)
    db.commit()
    with monkeypatch.context() as patch:

        def interrupted(*args, **kwargs):
            raise RuntimeError("simulated process failure after feature publication")

        patch.setattr(service.trainer, "partial_fit", interrupted)
        with pytest.raises(RuntimeError, match="simulated process failure"):
            service.publish_pending(db, as_of=at)
    db.rollback()
    restarted = InformationFeedback(artifact_root=tmp_path)
    assert restarted.publish_pending(db, as_of=at)["published"] == 1
    assert restarted.trainer.current("forex").sample_count == 1
    assert restarted.feature_store.scan(market_family="forex").collect().height == 1
    assert restarted.publish_pending(db, as_of=at)["published"] == 0
    assert restarted.trainer.current("forex").sample_count == 1


def test_published_feature_page_reuses_the_exact_online_source_identity(db, tmp_path):
    from app.services.information.feedback import InformationFeedback
    from app.services.trading_ml.worker import _example_from_store_row

    native_forex(db)
    service = InformationFeedback(artifact_root=tmp_path)
    at = datetime.utcnow() + timedelta(minutes=1)
    service.project(db, as_of=at)
    db.commit()
    service.publish_pending(db, as_of=at)
    page = service.feature_store.online_page(
        market_family="forex", cursor=None, limit=10
    )
    example = _example_from_store_row(page["rows"][0])
    result = service.trainer.partial_fit((example,), as_of=at)
    assert result.parameters["new_samples"] == 0
    assert result.sample_count == 1


def test_published_source_conflict_excludes_the_label_and_preserves_old_checkpoint(
    db, tmp_path
):
    from app.services.information.feedback import InformationFeedback

    position, _ = native_forex(db)
    service = InformationFeedback(artifact_root=tmp_path)
    at = datetime.utcnow() + timedelta(minutes=1)
    service.project(db, as_of=at)
    db.commit()
    service.publish_pending(db, as_of=at)
    before = service.feature_store.market_dataset_hash("forex")
    position.net_pnl *= 0.8
    position.realized_r *= 0.8
    db.commit()
    service.project(db, as_of=at)
    db.commit()
    publication = service.publish_pending(db, as_of=at)
    assert publication["model_blocked_markets"] == ["forex"]
    assert service.feature_store.scan(market_family="forex").collect().height == 0
    assert service.feature_store.market_dataset_hash("forex") != before
    assert (
        service.trainer.current("forex").sample_count == 1
    )  # Retained, never silently reset.


def test_reobserving_the_same_conflict_does_not_repeat_invalidation(db, tmp_path):
    from sqlalchemy import select
    from app.models import InformationFeedbackOutbox
    from app.services.information.feedback import InformationFeedback

    position, _ = native_forex(db)
    service = InformationFeedback(artifact_root=tmp_path)
    at = datetime.utcnow() + timedelta(minutes=1)
    service.project(db, as_of=at)
    db.commit()
    position.net_pnl *= 0.8
    db.commit()
    assert service.project(db, as_of=at)["conflicts"] == 1
    db.commit()
    service.publish_pending(db, as_of=at)
    record = db.scalar(select(InformationFeedbackOutbox))
    published_at = record.quarantine_published_at
    position.current_price += 0.000001
    db.commit()
    assert service.project(db, as_of=at)["conflicts"] == 0
    assert record.quarantine_published_at == published_at
    assert record.status == "QUARANTINED"


@pytest.mark.parametrize("missing_cutoff", [False, True])
def test_historical_prediction_does_not_use_future_or_unverifiable_memory(
    db, missing_cutoff
):
    from app.models import ModelVersion, SignalPerformance, StrategyMemory
    from app.services.learning_loop import PredictionEngine, BASE_SIGNAL_WEIGHTS
    from test_learning_feedback_loop import prediction_context

    context = prediction_context()
    past = datetime(2020, 1, 1)
    known = past if missing_cutoff else datetime(2026, 10, 21)
    metadata = (
        {}
        if missing_cutoff
        else {"outcome_cutoff": known.isoformat(), "available_at": known.isoformat()}
    )
    db.add(
        ModelVersion(
            version="future-or-unverifiable",
            model_name="fixture",
            is_active=True,
            weights={**BASE_SIGNAL_WEIGHTS, "sentiment": 0.9},
            training_window=metadata,
            created_at=known,
        )
    )
    db.add(
        SignalPerformance(
            signal_name="trend_structure",
            timeframe="mid",
            market_regime="Bull Expansion",
            sample_count=100,
            reliability_score=90,
            correct_count=90,
            created_at=known,
            updated_at=known,
            evidence=metadata,
        )
    )
    db.add(
        StrategyMemory(
            memory_key="future-memory",
            category="volume_confirmation",
            lesson="fixture",
            conditions={"relative_volume_gt": 1.0},
            sample_count=100,
            positive_count=90,
            reliability_score=90,
            created_at=known,
            updated_at=known,
            evidence=metadata,
        )
    )
    db.commit()
    result = PredictionEngine().predict(context, db=db)
    assert result["model_version_used"] == "base-static"
    assert result["feedback_loop"]["confidence_adjustment"] == 0.0
    assert not result["learning_memory_used"]["signal_performance"]
    assert not result["strategy_memory_used"]["rows"]


@pytest.mark.parametrize("wrong_asset", [False, True])
def test_known_memory_applies_only_to_its_frozen_asset_and_horizon(db, wrong_asset):
    from app.models import SignalPerformance
    from app.services.learning_loop import PredictionEngine
    from test_learning_feedback_loop import prediction_context

    context = {
        **prediction_context(),
        "timeframe": "mid",
        "holding_horizon": 63,
        "setup_type": "legacy_direction_forecast",
        "strategy_fingerprint": "legacy-direction-v1",
    }
    known = datetime(2024, 5, 1)
    db.add(
        SignalPerformance(
            signal_name="trend_structure",
            timeframe="mid",
            market_regime="Bull Expansion",
            sample_count=100,
            correct_count=90,
            reliability_score=90,
            created_at=known,
            updated_at=known,
            evidence={
                "available_at": known.isoformat(),
                "outcome_cutoff": known.isoformat(),
                "scope": {
                    "asset_key": "AAPL" if wrong_asset else "NVDA",
                    "timeframe": "mid",
                    "holding_horizon": 63,
                    "setup_type": "legacy_direction_forecast",
                    "regime": "Bull Expansion",
                    "strategy_fingerprint": "legacy-direction-v1",
                },
            },
        )
    )
    db.commit()
    result = PredictionEngine().predict(context, db=db)
    assert set(result["timeframes"]) == {"mid"}
    assert bool(result["learning_memory_used"]["signal_performance"]) is (
        not wrong_asset
    )
    assert (result["feedback_loop"]["confidence_adjustment"] > 0) is (not wrong_asset)


@pytest.mark.parametrize("updater", ["sniper", "signal_performance"])
def test_repeated_reliability_projection_counts_each_source_once(db, updater):
    from sqlalchemy import select
    from app.models import SignalReliabilityMatrix, SignalPerformance
    from app.services.market_sniper import update_signal_reliability_matrix
    from app.services.learning_loop import StrategyMemoryService
    from test_learning_feedback_loop import prediction_context

    prediction = equity_prediction()
    prediction.prediction_payload = {
        "prediction": {"signal_scores": {"trend_structure": 80.0}}
    }
    outcome = equity_outcome(realized_return=2.0)
    outcome.timeframe, outcome.horizon_days = "short", 21
    outcome.outcome_label, outcome.direction_correct = "correct", True
    db.add_all([prediction, outcome])
    db.commit()
    if updater == "sniper":

        def apply():
            update_signal_reliability_matrix(
                db,
                [(prediction, outcome)],
                [
                    {
                        "prediction_id": prediction.id,
                        "setup_type": "momentum_breakout",
                        "realized_r_multiple": 2.0,
                    }
                ],
            )

        model = SignalReliabilityMatrix
    else:
        context = prediction_context()
        source = {
            "_source_uid": f"prediction_outcome:{outcome.id}",
            "_decision_uid": f"historical_prediction:{prediction.id}",
            "timeframe": "short",
            "horizon_days": 21,
            "realized_return": 2.0,
            "direction_correct": True,
            "outcome_label": "correct",
            "evaluation_date": outcome.evaluation_date.isoformat(),
        }

        def apply():
            StrategyMemoryService().update_signal_performance(
                db, context, prediction.prediction_payload, [source]
            )

        model = SignalPerformance
    apply()
    db.commit()
    apply()
    db.commit()
    rows = db.scalars(select(model)).all()
    assert rows and all(row.sample_count == 1 for row in rows)


def test_other_assets_cannot_hide_eligible_memory_behind_the_query_limit(db):
    from app.models import StrategyMemory
    from app.services.learning_loop import PredictionEngine
    from test_learning_feedback_loop import prediction_context

    context = {
        **prediction_context(),
        "timeframe": "mid",
        "holding_horizon": 63,
        "setup_type": "legacy_direction_forecast",
        "strategy_fingerprint": "legacy-direction-v1",
    }
    known = datetime(2020, 1, 1)
    for index in range(151):
        matching = index == 150
        db.add(
            StrategyMemory(
                memory_key=f"scope-{index}",
                category="volume_confirmation",
                lesson="fixture",
                conditions={"relative_volume_gt": 1.0},
                sample_count=10,
                positive_count=8,
                reliability_score=60 if matching else 95,
                created_at=known,
                updated_at=known,
                evidence={
                    "available_at": known.isoformat(),
                    "outcome_cutoff": known.isoformat(),
                    "scope": {
                        "asset_key": "NVDA" if matching else "AAPL",
                        "timeframe": "mid",
                        "holding_horizon": 63,
                        "setup_type": "legacy_direction_forecast",
                        "regime": "Bull Expansion",
                        "strategy_fingerprint": "legacy-direction-v1",
                    },
                },
            )
        )
    db.commit()
    result = PredictionEngine().predict(context, db=db)
    assert result["strategy_memory_used"]["rows"][0]["memory_key"] == "scope-150"


def native_equity(db):
    from app.models import PaperExecutionOrder
    from app.services.executable_strategy import canonical_strategy_spec
    from app.services.information.context import OpportunityContextBuilder
    from test_alpha_desk import paper, close
    from test_opportunity_context import asset

    asset(db, "SPY", kind="ETF", name="SPDR S&P 500 ETF Trust")
    trade = paper(db, uid="feedback-equity", ticker="SPY")
    context = OpportunityContextBuilder().build(
        db,
        market_family="equity",
        asset_key="SPY",
        decision_at=trade.decision_timestamp,
        price_refs=(
            {
                "source_uid": "fixture:SPY",
                "provider": "fixture",
                "timestamp": (
                    trade.decision_timestamp - timedelta(minutes=2)
                ).isoformat(),
                "available_at": (
                    trade.decision_timestamp - timedelta(minutes=1)
                ).isoformat(),
                "close": 100.0,
                "timeframe": "1m",
            },
        ),
    )
    spec = canonical_strategy_spec("intraday_breakout")
    trade.frozen_decision_payload = {
        **trade.frozen_decision_payload,
        "information_context": context.to_payload(),
        "market": "USA",
        "executable_strategy": spec.to_payload(),
        "strategy_fingerprint": spec.fingerprint,
        "decision_uid": "paper-immutable-decision",
        "evidence_lane": "experimental_paper",
    }
    db.add(
        PaperExecutionOrder(
            order_uid="feedback-filled",
            duplicate_key="feedback-filled",
            paper_trade_id=trade.id,
            ticker="SPY",
            side="LONG",
            order_type="MARKET",
            status="FILLED",
            decision_timestamp=trade.decision_timestamp,
            submitted_at=trade.opened_at,
            theoretical_price=100,
            requested_quantity=1,
            filled_quantity=1,
            remaining_quantity=0,
            average_fill_price=100,
            currency="USD",
            account_currency="EUR",
            fx_rate=1,
        )
    )
    close(trade)
    db.commit()
    return trade, context


def test_equity_native_outcome_preserves_its_lane_and_frozen_contract(db, tmp_path):
    from sqlalchemy import select
    from app.models import InformationFeedbackOutbox
    from app.services.information.feedback import InformationFeedback

    trade, context = native_equity(db)
    service = InformationFeedback(artifact_root=tmp_path)
    assert (
        service.project(db, as_of=datetime.utcnow() + timedelta(minutes=1))[
            "new_examples"
        ]
        == 1
    )
    record = db.scalar(select(InformationFeedbackOutbox))
    assert record.market_family == "equity"
    assert record.payload_json["example"]["evidence_lane"] == "experimental_paper"
    assert record.payload_json["frozen_context"]["hash"] == context.hash
    assert record.payload_json["example"]["realized_net_r"] == 1.8
    assert record.payload_json["cost_breakdown"]["currency"] == "EUR"


def test_small_projection_budget_rotates_markets_despite_new_forex_updates(
    db, tmp_path
):
    from sqlalchemy import select
    from app.models import InformationFeedbackOutbox
    from app.services.information.feedback import InformationFeedback

    position, _ = native_forex(db)
    native_equity(db)
    service = InformationFeedback(artifact_root=tmp_path)
    for _ in range(3):
        position.current_price += (
            0.000001  # A source update with unchanged closed economics.
        )
        db.commit()
        service.project(db, as_of=datetime.utcnow() + timedelta(minutes=1), max_items=1)
        db.commit()
    markets = set(db.scalars(select(InformationFeedbackOutbox.market_family)).all())
    assert markets == {"equity", "forex"}


def test_publication_after_model_commit_can_retry_without_relearning(
    db, tmp_path, monkeypatch
):
    from app.services.information.feedback import InformationFeedback

    native_forex(db)
    service = InformationFeedback(artifact_root=tmp_path)
    at = datetime.utcnow() + timedelta(minutes=1)
    service.project(db, as_of=at)
    db.commit()
    with monkeypatch.context() as patch:

        def crashed_commit():
            raise RuntimeError("simulated final outbox commit failure")

        patch.setattr(db, "commit", crashed_commit)
        with pytest.raises(RuntimeError, match="final outbox commit failure"):
            service.publish_pending(db, as_of=at)
    db.rollback()
    assert service.trainer.current("forex").sample_count == 1
    assert (
        InformationFeedback(artifact_root=tmp_path).publish_pending(db, as_of=at)[
            "published"
        ]
        == 1
    )
    assert service.trainer.current("forex").sample_count == 1


def test_uncommitted_outcome_cannot_publish_external_learning(db, tmp_path):
    from app.services.information.feedback import InformationFeedback

    native_forex(db)
    service = InformationFeedback(artifact_root=tmp_path)
    at = datetime.utcnow() + timedelta(minutes=1)
    service.project(db, as_of=at)
    with pytest.raises(RuntimeError, match="COMMIT_BEFORE_FEEDBACK_PUBLICATION"):
        service.publish_pending(db, as_of=at)
    db.rollback()
    assert not service.feature_store.manifest()["partitions"]


def test_non_usa_equity_does_not_enter_the_usa_model_pool(db, tmp_path):
    from app.services.information.feedback import InformationFeedback

    trade, _ = native_equity(db)
    trade.frozen_decision_payload = {**trade.frozen_decision_payload, "market": "ITALY"}
    db.commit()
    assert (
        InformationFeedback(artifact_root=tmp_path).project(
            db, as_of=datetime.utcnow() + timedelta(minutes=1)
        )["new_examples"]
        == 0
    )


def test_later_news_and_active_model_do_not_replace_frozen_trade_features(db, tmp_path):
    from dataclasses import replace
    from sqlalchemy import select
    from app.models import InformationFeedbackOutbox
    from app.services.information.feedback import InformationFeedback
    from app.services.information.model import InformationModelTrainer
    from app.services.information.context import OpportunityContextBuilder
    from app.services.trading_ml.registry import TradingMLModelRegistry
    from test_information_model import labeled_rows
    from test_opportunity_context import event

    position, context = native_forex(db)
    service = InformationFeedback(artifact_root=tmp_path)
    at = datetime.utcnow() + timedelta(minutes=1)
    service.project(db, as_of=at)
    db.commit()
    record = db.scalar(select(InformationFeedbackOutbox))
    original = record.content_hash
    event(
        db,
        key="EUR",
        kind="currency",
        title="ECB issues a new policy statement",
        published=NOW + timedelta(minutes=5),
        observed=NOW + timedelta(minutes=5),
        available=NOW + timedelta(minutes=5),
    )
    newer = OpportunityContextBuilder().build(
        db,
        market_family="forex",
        asset_key="EURUSD=X",
        decision_at=NOW + timedelta(minutes=10),
        price_refs=context.price_refs,
    )
    assert newer.features["event_novelty"] > context.features["event_novelty"]
    rows = tuple(
        replace(
            row,
            market_family="forex",
            features={**row.features, "market_family": "forex"},
        )
        for row in labeled_rows()
    )
    result = InformationModelTrainer(
        parameters={"max_iter": 20, "min_samples_leaf": 5}
    ).fit(rows, maximum_holding_horizon=timedelta(days=2))
    model = TradingMLModelRegistry(tmp_path / "other-model").store_candidate(
        db, market_family="forex", result=result
    )
    model.status, model.activated_at = "ACTIVE", datetime.utcnow()
    position.current_price += 0.000001
    db.commit()
    service.project(db, as_of=at)
    assert record.content_hash == original and record.status == "PENDING"
    assert record.payload_json["checkpoint_hash"] == "a" * 64
    assert record.payload_json["frozen_context"]["hash"] == context.hash
