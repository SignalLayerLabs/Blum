"""A decision must exist, be immutable and bind its account before any order."""

from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from test_forex_trader_core import db, NOW, market_input, strategy


def frozen_forex(db, *, action="LONG", uid="alpha:fixture", account="original"):
    from app.models import ForexDecision, ForexTraderCycle, LiveForwardPaperGame
    from app.services.forex_trader import BlumForexTraderCore
    from app.services.information.context import OpportunityContextBuilder
    from app.services.information.contracts import FrozenAlphaDecision

    market = market_input()
    spec = strategy().executable_strategy
    context = OpportunityContextBuilder().build(
        db,
        market_family="forex",
        asset_key=market.pair,
        decision_at=NOW,
        price_refs=(
            {
                "source_uid": "fixture:EURUSD",
                "provider": "fixture",
                "timestamp": (NOW - timedelta(minutes=1)).isoformat(),
                "available_at": NOW.isoformat(),
                "acquired_at": NOW.isoformat(),
                "close": 1.1,
                "timeframe": "1m",
            },
        ),
    )
    db.add(
        LiveForwardPaperGame(
            game_id=account,
            cash=1000,
            current_capital=1000,
            starting_capital=1000,
            configuration={"account_currency": "EUR"},
        )
    )
    native = None
    if action == "LONG":
        cycle = ForexTraderCycle(
            cycle_uid=uid,
            cycle_key=uid,
            status="RUNNING",
            started_at=NOW,
            configuration_hash="fixture",
            data_coverage_hash="fixture",
            code_commit="fixture",
        )
        db.add(cycle)
        db.flush()
        proposal = (
            BlumForexTraderCore().evaluate_input(market, strategy=strategy()).proposal
        )
        native = ForexDecision(
            decision_uid="native:" + uid,
            cycle_id=cycle.id,
            pair=market.pair,
            strategy_id=strategy().strategy_id,
            direction="LONG",
            status="APPROVED",
            decision_timestamp=NOW,
            proposal_json={
                "entry": proposal.entry,
                "stop": proposal.stop,
                "target": proposal.target,
            },
            input_snapshot={},
            risk_json={
                "decision": "APPROVE",
                "quantity_lots": 0.01,
                "account_id": account,
            },
        )
        db.add(native)
        db.flush()
        geometry = {
            "entry": proposal.entry,
            "stop": proposal.stop,
            "target": proposal.target,
        }
    else:
        geometry = {}
    return FrozenAlphaDecision(
        decision_uid=uid,
        trial_uid=None,
        market_family="forex",
        asset_key=market.pair,
        decision_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        context=context,
        executable_strategy=spec,
        strategy_fingerprint=spec["strategy_fingerprint"],
        model_uid=None,
        checkpoint_hash=None,
        action=action,
        reason="fixture research decision",
        geometry=geometry,
        sizing={"quantity_lots": 0.01, "risk_percent": 0.1},
        expected_outcome={"status": "NO_MODEL_AS_OF", "predicted_net_r": None},
        evidence_lane="EXPERIMENTAL_PAPER",
        policy_version="information-policy-v1",
        account_id=account,
        decision_effect={"information_applied": False},
        native_binding=(
            {"source_type": "forex", "source_id": native.id} if native else {}
        ),
    )


def test_freeze_registers_before_native_submission_and_retry_reuses_order(db):
    from app.models import (
        AlphaCallRegistration,
        ForexPendingOrder,
        LiveForwardPaperGame,
    )
    from app.services.information.decisions import InformationDecisionService

    decision = frozen_forex(db)
    service = InformationDecisionService(now_provider=lambda: NOW)
    record = service.freeze(db, decision)
    registration = db.scalar(select(AlphaCallRegistration))
    assert registration is not None
    assert db.scalar(select(func.count(ForexPendingOrder.id))) == 0
    # A subsequently created active account must not steal this decision's order.
    db.add(LiveForwardPaperGame(game_id="other", started_at=NOW + timedelta(seconds=1)))
    db.flush()
    first = service.submit(db, decision_uid=decision.decision_uid, as_of=NOW)
    second = service.submit(
        db, decision_uid=decision.decision_uid, as_of=NOW + timedelta(seconds=1)
    )
    order = db.scalar(select(ForexPendingOrder))
    assert first["order_uid"] == second["order_uid"] == record.native_order_uid
    assert order.account_id == "original"
    assert registration.registered_at <= order.submitted_at
    assert db.scalar(select(func.count(ForexPendingOrder.id))) == 1
    assert registration.manifest_json["context"]["hash"] == decision.context.hash
    assert (
        registration.manifest_json["strategy_fingerprint"]
        == decision.strategy_fingerprint
    )


def test_abstention_registers_without_creating_a_native_trade(db):
    from app.models import (
        AlphaCallRegistration,
        ForexDecision,
        ForexPendingOrder,
        ForexPosition,
    )
    from app.services.information.decisions import InformationDecisionService

    decision = frozen_forex(db, action="ABSTAIN")
    service = InformationDecisionService(now_provider=lambda: NOW)
    record = service.freeze(db, decision)
    result = service.submit(db, decision_uid=decision.decision_uid, as_of=NOW)
    assert record.native_order_uid is None and result["status"] == "ABSTAIN"
    assert db.scalar(select(func.count(AlphaCallRegistration.id))) == 1
    for model in (ForexDecision, ForexPendingOrder, ForexPosition):
        assert db.scalar(select(func.count(model.id))) == 0


def test_changed_same_decision_uid_and_mutated_stored_manifest_are_rejected(db):
    from app.services.information.decisions import InformationDecisionService

    decision = frozen_forex(db)
    service = InformationDecisionService(now_provider=lambda: NOW)
    record = service.freeze(db, decision)
    with pytest.raises(ValueError, match="FROZEN_DECISION_CHANGED"):
        service.freeze(db, replace(decision, reason="different after seeing prices"))
    record.manifest_json = {**record.manifest_json, "action": "SHORT"}
    db.flush()
    with pytest.raises(ValueError, match="FROZEN_DECISION_CHANGED"):
        service.submit(db, decision_uid=decision.decision_uid, as_of=NOW)


def frozen_equity(db):
    from app.models import LiveForwardPaperGame, LiveForwardPaperTrade
    from app.services.executable_strategy import canonical_strategy_spec
    from app.services.information.context import OpportunityContextBuilder

    original = frozen_forex(db, action="ABSTAIN")
    from test_opportunity_context import asset

    asset(db, "NVDA")
    game = db.scalar(select(LiveForwardPaperGame))
    source = LiveForwardPaperTrade(
        game_id=game.id,
        trade_uid="usa-native",
        duplicate_key="usa-native",
        ticker="NVDA",
        market="USA",
        side="LONG",
        setup_type="intraday_breakout",
        status="ORDER_SUBMITTED",
        decision_timestamp=NOW,
        stop_loss=95,
        target_1=110,
        confidence=60,
        position_size=0,
        model_version_used="baseline",
        frozen_decision_payload={
            "observed_entry_price": 100.0,
            "accounting": {"quantity_units": 1.0, "account_currency": "EUR"},
        },
    )
    db.add(source)
    db.flush()
    context = OpportunityContextBuilder().build(
        db,
        market_family="equity",
        asset_key="NVDA",
        decision_at=NOW,
        price_refs=(
            {
                "source_uid": "fixture:NVDA",
                "provider": "fixture",
                "timestamp": NOW.isoformat(),
                "available_at": NOW.isoformat(),
                "acquired_at": NOW.isoformat(),
                "close": 100,
                "timeframe": "1m",
            },
        ),
    )
    spec = canonical_strategy_spec("intraday_breakout")
    return replace(
        original,
        market_family="equity",
        asset_key="NVDA",
        context=context,
        executable_strategy=spec.to_payload(),
        strategy_fingerprint=spec.fingerprint,
        action="LONG",
        geometry={"entry": 100.0, "stop": 95.0, "target": 110.0},
        sizing={"quantity": 1.0, "risk_percent": 0.1},
        native_binding={
            "source_type": "paper",
            "source_id": source.id,
            "execution_context": {
                "currency": "USD",
                "account_currency": "EUR",
                "fx_rate": 0.9,
            },
        },
    )


def test_equity_uses_its_registered_intent_and_the_existing_native_order_ledger(db):
    from app.models import AlphaCallRegistration, PaperExecutionOrder
    from app.services.information.decisions import InformationDecisionService

    decision = frozen_equity(db)
    service = InformationDecisionService(now_provider=lambda: NOW)
    service.freeze(db, decision)
    first = service.submit(db, decision_uid=decision.decision_uid, as_of=NOW)
    assert (
        first["order_uid"]
        == service.submit(db, decision_uid=decision.decision_uid, as_of=NOW)[
            "order_uid"
        ]
    )
    order = db.scalar(select(PaperExecutionOrder))
    assert order.side == "BUY" and order.requested_quantity == 1
    assert order.stop_price == 95 and order.target_price == 110
    assert order.submitted_at >= db.scalar(select(AlphaCallRegistration)).registered_at
    assert db.scalar(select(func.count(PaperExecutionOrder.id))) == 1


def test_expired_registered_intent_cannot_submit_a_new_order(db):
    from app.models import ForexPendingOrder
    from app.services.information.decisions import InformationDecisionService

    decision = frozen_forex(db)
    service = InformationDecisionService(now_provider=lambda: NOW)
    service.freeze(db, decision)
    assert (
        service.submit(
            db, decision_uid=decision.decision_uid, as_of=decision.expires_at
        )["status"]
        == "EXPIRED"
    )
    assert db.scalar(select(func.count(ForexPendingOrder.id))) == 0


def test_closed_legacy_position_cannot_be_backfilled_as_a_new_decision(db):
    from test_information_feedback import native_forex
    from app.services.information.decisions import InformationDecisionService

    position, _ = native_forex(db)
    decision = frozen_forex(db)
    decision = replace(
        decision,
        native_binding={"source_type": "forex", "source_id": position.decision_id},
    )
    with pytest.raises(ValueError, match="RETROSPECTIVE_REGISTRATION_FORBIDDEN"):
        InformationDecisionService(now_provider=lambda: NOW).freeze(db, decision)


@pytest.mark.parametrize("family", ["equity", "forex"])
def test_account_closed_after_registration_cannot_receive_a_new_order(db, family):
    from app.models import LiveForwardPaperGame, PaperExecutionOrder, ForexPendingOrder
    from app.services.information.decisions import InformationDecisionService

    decision = frozen_equity(db) if family == "equity" else frozen_forex(db)
    service = InformationDecisionService(now_provider=lambda: NOW)
    service.freeze(db, decision)
    db.scalar(select(LiveForwardPaperGame)).status = "closed"
    db.flush()
    with pytest.raises(ValueError, match="BOUND_PAPER_ACCOUNT_REQUIRED"):
        service.submit(db, decision_uid=decision.decision_uid, as_of=NOW)
    assert db.scalar(select(func.count(PaperExecutionOrder.id))) == 0
    assert db.scalar(select(func.count(ForexPendingOrder.id))) == 0


def test_concurrent_submitters_share_one_native_order(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.core.database import Base
    from app.models import ForexPendingOrder
    from app.services.information.decisions import InformationDecisionService

    engine = create_engine(
        "sqlite:///" + str(tmp_path / "concurrent.db"), connect_args={"timeout": 10}
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        decision = frozen_forex(db)
        InformationDecisionService(now_provider=lambda: NOW).freeze(db, decision)
        db.commit()
    barrier = Barrier(3)

    def submit():
        with Session(engine) as db:
            barrier.wait(timeout=10)
            result = InformationDecisionService().submit(
                db, decision_uid=decision.decision_uid, as_of=NOW
            )
            db.commit()
            return result["order_uid"]

    with ThreadPoolExecutor(max_workers=3) as pool:
        orders = list(pool.map(lambda _: submit(), range(3)))
    assert len(set(orders)) == 1
    with Session(engine) as db:
        assert db.scalar(select(func.count(ForexPendingOrder.id))) == 1
    engine.dispose()


@pytest.mark.parametrize("family", ["equity", "forex"])
def test_frozen_intent_cannot_increase_native_approved_quantity(db, family):
    from app.services.information.decisions import InformationDecisionService

    decision = frozen_equity(db) if family == "equity" else frozen_forex(db)
    key = "quantity" if family == "equity" else "quantity_lots"
    larger = replace(decision, sizing={**dict(decision.sizing), key: 1000.0})
    with pytest.raises(ValueError, match="NATIVE_RISK_APPROVAL_REQUIRED"):
        InformationDecisionService(now_provider=lambda: NOW).freeze(db, larger)


def test_registered_abstention_is_readable_and_does_not_count_as_a_trade(db):
    from app.services.alpha_desk import AlphaDeskService
    from app.services.information.decisions import InformationDecisionService

    decision = frozen_forex(db, action="ABSTAIN")
    InformationDecisionService(now_provider=lambda: NOW).freeze(db, decision)
    snapshot = AlphaDeskService().snapshot(db, now=NOW + timedelta(seconds=1))
    assert snapshot["markets"]["forex"]["qualified_closed"] == 0
    row = snapshot["journal"][0]
    assert row["status"] == "ABSTAIN" and row["outcome_status"] == "NO_ACTION"
    assert "SOURCE_MISSING" not in row["blockers"]


def test_native_forex_cycle_registers_before_fill_and_matures_into_feedback(
    db, tmp_path
):
    from datetime import datetime
    from app.models import (
        AlphaDecisionRecord,
        ForexPendingOrder,
        InformationFeedbackOutbox,
    )
    from app.services.information.feedback import InformationFeedback
    from test_information_feedback import native_forex

    position, context = native_forex(db)
    record = db.scalar(select(AlphaDecisionRecord))
    assert record is not None
    order = db.scalar(select(ForexPendingOrder))
    assert record.native_order_uid == order.order_uid
    assert record.registered_at <= order.submitted_at < position.opened_at
    assert record.manifest_json["context"]["hash"] == context.hash
    service = InformationFeedback(artifact_root=tmp_path)
    at = datetime.utcnow() + timedelta(minutes=1)
    assert service.project(db, as_of=at)["new_examples"] == 1
    db.commit()
    publication = db.scalar(select(InformationFeedbackOutbox))
    assert publication.decision_uid == record.decision_uid
    db.commit()
    assert service.publish_pending(db, as_of=at)["published"] == 1
    assert service.trainer.current("forex").sample_count == 1
