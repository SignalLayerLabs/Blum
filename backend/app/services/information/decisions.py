"""Register immutable intent before delegating to the single native order ledger."""

from datetime import datetime

from sqlalchemy import select

from app.models import (
    AlphaDecisionRecord,
    ForexDecision,
    ForexPosition,
    LiveForwardPaperGame,
    LiveForwardPaperTrade,
)
from app.services.market_clock import utc_naive
from .contracts import FrozenAlphaDecision, digest, thaw
from .feedback import context_from_payload
from .repository import insert_once


def decision_from_payload(payload):
    value = dict(payload)
    value["context"] = context_from_payload(value["context"])
    for name in ("decision_at", "expires_at"):
        value[name] = datetime.fromisoformat(value[name])
    return FrozenAlphaDecision(**value)


class InformationDecisionService:
    def __init__(
        self,
        *,
        now_provider=datetime.utcnow,
        forex_lifecycle=None,
        paper_lifecycle=None
    ):
        self.now_provider = now_provider
        self.forex_lifecycle = forex_lifecycle
        self.paper_lifecycle = paper_lifecycle

    def freeze(self, db, decision: FrozenAlphaDecision):
        from app.services.alpha_desk import AlphaCallRegistry

        at = utc_naive(self.now_provider())
        payload = decision.to_payload()
        sha = digest(payload)
        existing = db.scalar(
            select(AlphaDecisionRecord).where(
                AlphaDecisionRecord.decision_uid == decision.decision_uid
            )
        )
        if existing:
            if existing.manifest_sha256 != sha or digest(existing.manifest_json) != sha:
                raise ValueError("FROZEN_DECISION_CHANGED")
            return existing
        if not decision.decision_at <= at < decision.expires_at:
            raise ValueError("INVALID_REGISTRATION_TIME")
        game = db.scalar(
            select(LiveForwardPaperGame).where(
                LiveForwardPaperGame.game_id == decision.account_id,
                LiveForwardPaperGame.status == "active",
            )
        )
        if game is None:
            raise ValueError("BOUND_PAPER_ACCOUNT_REQUIRED")
        if decision.action in {"LONG", "SHORT"}:
            self._native_source(db, decision)
        insert_once(
            db,
            AlphaDecisionRecord,
            {
                "decision_uid": decision.decision_uid,
                "market_family": decision.market_family,
                "asset_key": decision.asset_key,
                "action": decision.action,
                "decision_at": decision.decision_at,
                "expires_at": decision.expires_at,
                "registered_at": at,
                "account_id": decision.account_id,
                "trial_uid": decision.trial_uid,
                "manifest_json": payload,
                "manifest_sha256": sha,
                "status": "REGISTERED",
            },
            ["decision_uid"],
        )
        record = db.scalar(
            select(AlphaDecisionRecord)
            .where(AlphaDecisionRecord.decision_uid == decision.decision_uid)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if record.manifest_sha256 != sha:
            raise ValueError("FROZEN_DECISION_CHANGED")
        AlphaCallRegistry().register_decision(
            db, decision, source_id=record.id, registered_at=record.registered_at
        )
        return record

    def submit(self, db, *, decision_uid, as_of):
        at = utc_naive(as_of)
        record = db.scalar(
            select(AlphaDecisionRecord)
            .where(AlphaDecisionRecord.decision_uid == decision_uid)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if record is None:
            raise ValueError("REGISTER_BEFORE_SUBMISSION")
        if digest(record.manifest_json) != record.manifest_sha256:
            raise ValueError("FROZEN_DECISION_CHANGED")
        decision = decision_from_payload(record.manifest_json)
        if at < record.registered_at:
            raise ValueError("SUBMISSION_PRECEDES_REGISTRATION")
        if record.native_order_uid:
            return {"status": "SUBMITTED", "order_uid": record.native_order_uid}
        if decision.action not in {"LONG", "SHORT"}:
            record.status = decision.action
            return {"status": decision.action, "order_uid": None}
        if at >= decision.expires_at:
            record.status = "EXPIRED"
            return {"status": "EXPIRED", "order_uid": None}
        account = db.scalar(
            select(LiveForwardPaperGame)
            .where(
                LiveForwardPaperGame.game_id == decision.account_id,
                LiveForwardPaperGame.status == "active",
            )
            .with_for_update()
        )
        if account is None:
            raise ValueError("BOUND_PAPER_ACCOUNT_REQUIRED")
        source = self._native_source(db, decision)
        if decision.market_family == "forex":
            from app.services.forex_contracts import ForexDirection, ForexOrderRequest
            from app.services.forex_order_lifecycle import ForexOrderLifecycle

            order = ForexOrderRequest(
                pair=decision.asset_key,
                side=ForexDirection(decision.action),
                order_type="MARKET",
                quantity_lots=decision.sizing["quantity_lots"],
                theoretical_price=decision.geometry["entry"],
                stop_price=decision.geometry["stop"],
                target_price=decision.geometry["target"],
                **thaw(decision.native_binding.get("execution_context") or {}),
            )
            native = (self.forex_lifecycle or ForexOrderLifecycle()).submit(
                db,
                decision_id=source.id,
                order=order,
                expires_at=decision.expires_at,
                account_id=decision.account_id,
                submitted_at=at,
            )
        else:
            from app.services.paper_execution_lifecycle import (
                PaperOrderLifecycleService,
            )
            from app.services.realistic_execution import ExecutionOrderRequest

            request = ExecutionOrderRequest(
                order_key="alpha-execution:" + decision.decision_uid,
                ticker=decision.asset_key,
                side="BUY" if decision.action == "LONG" else "SELL_SHORT",
                order_type="LIMIT",
                decision_timestamp=decision.decision_at,
                theoretical_price=decision.geometry["entry"],
                quantity=decision.sizing["quantity"],
                limit_price=decision.geometry["entry"],
                stop_price=decision.geometry["stop"],
                target_price=decision.geometry["target"],
                **thaw(decision.native_binding.get("execution_context") or {}),
            )
            native = (self.paper_lifecycle or PaperOrderLifecycleService()).submit(
                db,
                request,
                paper_trade_id=source.id,
                validation_id=source.promoted_validation_id,
                expires_at=decision.expires_at,
                submitted_at=at,
            )
        record.native_order_type, record.native_order_id, record.native_order_uid = (
            decision.market_family,
            native.id,
            native.order_uid,
        )
        record.status = "SUBMITTED"
        db.flush()
        return {"status": record.status, "order_uid": native.order_uid}

    @staticmethod
    def _native_source(db, decision):
        if (
            decision.market_family == "equity"
            and decision.native_binding.get("source_type") == "paper"
        ):
            source = db.get(
                LiveForwardPaperTrade, decision.native_binding.get("source_id")
            )
            game = db.scalar(
                select(LiveForwardPaperGame).where(
                    LiveForwardPaperGame.game_id == decision.account_id
                )
            )
            if (
                source is None
                or game is None
                or source.game_id != game.id
                or source.ticker != decision.asset_key
                or source.decision_timestamp != decision.decision_at
            ):
                raise ValueError("NATIVE_SOURCE_MISMATCH")
            if (
                source.closed_at is not None
                or source.opened_at is not None
                or source.position_size > 0
            ):
                raise ValueError("RETROSPECTIVE_REGISTRATION_FORBIDDEN")
            if (
                source.status != "ORDER_SUBMITTED"
                or source.side != decision.action
                or source.stop_loss != decision.geometry.get("stop")
                or source.target_1 != decision.geometry.get("target")
            ):
                raise ValueError("NATIVE_SOURCE_MISMATCH")
            accounting = (source.frozen_decision_payload or {}).get("accounting") or {}
            if accounting.get("quantity_units") != decision.sizing.get("quantity"):
                raise ValueError("NATIVE_RISK_APPROVAL_REQUIRED")
            if (source.frozen_decision_payload or {}).get(
                "observed_entry_price"
            ) != decision.geometry.get("entry"):
                raise ValueError("NATIVE_SOURCE_MISMATCH")
            return source
        if (
            decision.market_family != "forex"
            or decision.native_binding.get("source_type") != "forex"
        ):
            raise ValueError("NATIVE_SOURCE_BINDING_REQUIRED")
        source = db.get(ForexDecision, decision.native_binding.get("source_id"))
        if (
            source is None
            or source.decision_timestamp != decision.decision_at
            or source.pair != decision.asset_key
        ):
            raise ValueError("NATIVE_SOURCE_MISMATCH")
        if db.scalar(
            select(ForexPosition.id)
            .where(ForexPosition.decision_id == source.id)
            .limit(1)
        ):
            raise ValueError("RETROSPECTIVE_REGISTRATION_FORBIDDEN")
        risk = source.risk_json or {}
        if (
            source.status != "APPROVED"
            or not str(risk.get("decision", "")).startswith("APPROVE")
            or risk.get("quantity_lots") != decision.sizing.get("quantity_lots")
            or risk.get("account_id") != decision.account_id
        ):
            raise ValueError("NATIVE_RISK_APPROVAL_REQUIRED")
        if source.direction != decision.action or any(
            source.proposal_json.get(k) != decision.geometry.get(k)
            for k in ("entry", "stop", "target")
        ):
            raise ValueError("NATIVE_SOURCE_MISMATCH")
        return source
