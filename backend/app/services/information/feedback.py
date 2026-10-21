"""Native financial truth → durable outbox → idempotent learning publication."""

from dataclasses import fields, replace
from datetime import datetime
from pathlib import Path

from sqlalchemy import and_, or_, select, update

from app.core.config import get_settings
from app.models import (
    ForexDecision,
    ForexPosition,
    InformationFeedbackCursor,
    InformationFeedbackOutbox,
    LiveForwardPaperTrade,
    PaperExecutionOrder,
    TradingMLModelVersion,
)
from app.services.market_clock import utc_naive
from app.services.trading_ml.contracts import FeatureSchema, TradingMLExample
from app.services.trading_ml.feature_store import TradingMLFeatureStoreProjector
from app.services.trading_ml.training import OnlineShadowTrainer
from .contracts import (
    EvidenceLink,
    MaturedAlphaOutcome,
    OpportunityContext,
    digest,
    thaw,
)
from .model import information_example
from .repository import insert_once

CONSUMER_VERSION = "native-information-v2"


def context_from_payload(payload):
    value = dict(payload)
    for name in ("decision_at", "max_available_at"):
        value[name] = datetime.fromisoformat(value[name])
    value["links"] = tuple(EvidenceLink(**row) for row in value["links"])
    return OpportunityContext(**value)


def example_payload(example):
    payload = {
        field.name: getattr(example, field.name) for field in fields(TradingMLExample)
    }
    payload["features"] = dict(example.features)
    for name in ("decision_timestamp", "outcome_timestamp"):
        payload[name] = payload[name].isoformat()
    return payload


def example_from_payload(payload):
    value = dict(payload)
    for name in ("decision_timestamp", "outcome_timestamp"):
        value[name] = datetime.fromisoformat(value[name])
    return TradingMLExample(**value)


class InformationFeedback:
    def __init__(self, *, artifact_root=None):
        root = (
            Path(artifact_root or get_settings().trading_ml_artifact_root)
            / "information-v2"
        )
        self.feature_store = TradingMLFeatureStoreProjector(
            root=root / "features", schema=FeatureSchema.information()
        )
        self.trainer = OnlineShadowTrainer(
            root / "online", schema=FeatureSchema.information()
        )

    def project(self, db, *, as_of, max_items=100):
        """Stage outcomes transactionally. The caller commits before publication."""
        if not 1 <= max_items <= 1000:
            raise ValueError("Native outcome projection budget must be 1..1000")
        at = utc_naive(as_of)
        db.flush()
        inserted = skipped = conflicts = considered = 0
        rotation_key = CONSUMER_VERSION + ":rotation"
        insert_once(
            db,
            InformationFeedbackCursor,
            {"source": rotation_key, "source_updated_at": datetime.min, "source_id": 0},
            ["source"],
        )
        rotation = db.scalar(
            select(InformationFeedbackCursor)
            .where(InformationFeedbackCursor.source == rotation_key)
            .with_for_update()
        )
        sources = (
            ("forex", ForexPosition),
            ("equity", LiveForwardPaperTrade),
        )
        phase = rotation.source_id % len(sources)
        rotation.source_id = (phase + 1) % len(sources)
        for source, model in (*sources[phase:], *sources[:phase]):
            if considered >= max_items:
                break
            key = CONSUMER_VERSION + ":" + source
            insert_once(
                db,
                InformationFeedbackCursor,
                {"source": key, "source_updated_at": datetime.min, "source_id": 0},
                ["source"],
            )
            cursor = db.scalar(
                select(InformationFeedbackCursor)
                .where(InformationFeedbackCursor.source == key)
                .with_for_update()
            )
            terminal = (
                model.status == "CLOSED"
                if source == "forex"
                else model.position_size > 0
            )
            rows = db.scalars(
                select(model)
                .where(
                    terminal,
                    model.closed_at.is_not(None),
                    model.closed_at <= at,
                    model.updated_at <= at,
                    or_(
                        model.updated_at > cursor.source_updated_at,
                        and_(
                            model.updated_at == cursor.source_updated_at,
                            model.id > cursor.source_id,
                        ),
                    ),
                )
                .order_by(model.updated_at, model.id)
                .limit(min(max_items - considered, max(1, max_items // 2)))
            ).all()
            for row in rows:
                considered += 1
                cursor.source_updated_at, cursor.source_id = row.updated_at, row.id
                try:
                    outcome, baseline = (
                        self._forex(db, row)
                        if source == "forex"
                        else self._equity(db, row)
                    )
                    example = information_example(
                        outcome.context,
                        baseline,
                        strategy_fingerprint=outcome.strategy_fingerprint,
                    )
                    kind, native_id = outcome.source_uid.split(":", 1)
                    example = replace(
                        example,
                        source_object_type=kind,
                        source_object_id=native_id,
                        evidence_lane=outcome.evidence_lane,
                        outcome_timestamp=outcome.outcome_at,
                        realized_net_r=outcome.realized_net_r,
                        label_positive_r=int(outcome.realized_net_r > 0),
                        sample_weight=0.5,
                    )
                    payload = {
                        "example": example_payload(example),
                        "frozen_context": outcome.context.to_payload(),
                        "executable_strategy": thaw(outcome.executable_strategy),
                        "strategy_fingerprint": outcome.strategy_fingerprint,
                        "checkpoint_hash": outcome.checkpoint_hash,
                        "decision_uid": outcome.decision_uid,
                        "cost_breakdown": thaw(outcome.cost_breakdown),
                        "benchmark_reference": thaw(outcome.benchmark_reference),
                        "account_return": outcome.account_return,
                    }
                    content_hash = digest(payload)
                except (ValueError, TypeError, KeyError, AttributeError):
                    skipped += 1
                    continue
                fresh = insert_once(
                    db,
                    InformationFeedbackOutbox,
                    {
                        "consumer_version": CONSUMER_VERSION,
                        "source_uid": outcome.source_uid,
                        "decision_uid": outcome.decision_uid,
                        "market_family": outcome.market_family,
                        "content_hash": content_hash,
                        "payload_json": payload,
                        "status": "PENDING",
                        "source_updated_at": row.updated_at,
                        "created_at": at,
                    },
                    ["consumer_version", "source_uid"],
                )
                record = db.scalar(
                    select(InformationFeedbackOutbox)
                    .where(
                        InformationFeedbackOutbox.consumer_version == CONSUMER_VERSION,
                        InformationFeedbackOutbox.source_uid == outcome.source_uid,
                    )
                    .with_for_update()
                )
                if record.content_hash != content_hash and (
                    record.status != "QUARANTINED"
                    or record.conflict_hash != content_hash
                ):
                    record.status, record.conflict_hash = "QUARANTINED", content_hash
                    record.quarantine_published_at = None
                    db.execute(
                        update(TradingMLModelVersion)
                        .where(
                            TradingMLModelVersion.market_family
                            == outcome.market_family,
                            TradingMLModelVersion.feature_schema_hash
                            == FeatureSchema.information().hash,
                            TradingMLModelVersion.status.in_(["ACTIVE", "CHALLENGER"]),
                            TradingMLModelVersion.created_at <= at,
                        )
                        .values(status="DEGRADED", degraded_at=at)
                    )
                    conflicts += 1
                elif fresh:
                    inserted += 1
            db.flush()
        return {
            "new_examples": inserted,
            "rows_considered": considered,
            "rows_rejected": skipped,
            "conflicts": conflicts,
        }

    def publish_pending(self, db, *, as_of, max_items=100):
        """Only a committed/pristine session may cause external publication.

        Files/model are idempotent by native UID. A crash before the final DB
        commit safely retries both, including a committed SQLite model update.
        """
        if db.in_transaction():
            raise RuntimeError("COMMIT_BEFORE_FEEDBACK_PUBLICATION")
        if not 1 <= max_items <= 1000:
            raise ValueError("Native publication budget must be 1..1000")
        at = utc_naive(as_of)
        quarantines = db.scalars(
            select(InformationFeedbackOutbox)
            .where(
                InformationFeedbackOutbox.consumer_version == CONSUMER_VERSION,
                InformationFeedbackOutbox.status == "QUARANTINED",
                InformationFeedbackOutbox.quarantine_published_at.is_(None),
                InformationFeedbackOutbox.created_at <= at,
            )
            .order_by(InformationFeedbackOutbox.id)
            .limit(max_items)
            .with_for_update(skip_locked=True)
        ).all()
        for row in quarantines:
            self.feature_store.quarantine_source(
                row.source_uid,
                conflict_hash=row.conflict_hash,
                market_family=row.market_family,
            )
            row.quarantine_published_at = at
        blocked = sorted(
            set(
                db.scalars(
                    select(InformationFeedbackOutbox.market_family)
                    .where(
                        InformationFeedbackOutbox.consumer_version == CONSUMER_VERSION,
                        InformationFeedbackOutbox.status == "QUARANTINED",
                        InformationFeedbackOutbox.created_at <= at,
                    )
                    .distinct()
                ).all()
            )
        )
        rows = db.scalars(
            select(InformationFeedbackOutbox)
            .where(
                InformationFeedbackOutbox.consumer_version == CONSUMER_VERSION,
                or_(
                    InformationFeedbackOutbox.status == "PENDING",
                    and_(
                        InformationFeedbackOutbox.status == "FEATURE_PUBLISHED",
                        InformationFeedbackOutbox.market_family.not_in(blocked),
                    ),
                ),
                InformationFeedbackOutbox.created_at <= at,
            )
            .order_by(InformationFeedbackOutbox.id)
            .limit(max_items)
            .with_for_update(skip_locked=True)
        ).all()
        published = features_published = 0
        for row in rows:
            if digest(row.payload_json) != row.content_hash:
                raise ValueError("FROZEN_OUTCOME_CONTENT_CHANGED")
            example = example_from_payload(row.payload_json["example"])
            features_published += self.feature_store.append_examples(
                (example,),
                publication_uid=row.source_uid,
                content_hash=row.content_hash,
            )["rows_written"]
            row.feature_published_at = at
            if row.market_family in blocked:
                row.status = "FEATURE_PUBLISHED"
                continue
            self.trainer.partial_fit((example,), as_of=at)
            row.status, row.feature_published_at, row.model_published_at = (
                "PUBLISHED",
                at,
                at,
            )
            published += 1
        db.commit()
        return {
            "published": published,
            "features_published": features_published,
            "model_blocked_markets": blocked,
        }

    @staticmethod
    def _forex(db, position):
        decision = db.get(ForexDecision, position.decision_id)
        contract, proposal = position.contract_json, decision.proposal_json
        if (
            contract.get("accounting_version") != "forex-cashflow-v2"
            or position.realized_r is None
        ):
            raise ValueError("Verified terminal native cash accounting required")
        context = context_from_payload(decision.input_snapshot["information_context"])
        spec = proposal["executable_strategy"]
        advice = proposal.get("information_advice") or {}
        outcome = MaturedAlphaOutcome(
            f"forex_position:{position.position_uid}",
            decision.decision_uid,
            "forex",
            position.pair,
            decision.decision_timestamp,
            position.closed_at,
            position.realized_r,
            str(contract.get("evidence_lane") or "UNQUALIFIED_NATIVE_PAPER"),
            context,
            spec,
            proposal["strategy_fingerprint"],
            advice.get("model_hash"),
            {
                "currency": contract.get("account_currency"),
                "commission": position.commission,
                "swap": position.swap_accrued,
                "net_pnl": position.net_pnl,
                "accounting_version": contract["accounting_version"],
            },
            {},
        )
        return outcome, {
            "setup_type": spec["setup_type"],
            "regime": proposal.get("regime", "unknown"),
            "features": {
                **proposal,
                "session": decision.input_snapshot.get("session"),
                "direction": decision.direction,
                "timeframe": spec["execution_timeframe"],
                "sector_or_currency_family": position.pair,
            },
        }

    @staticmethod
    def _equity(db, trade):
        from app.services.executable_strategy import normalize_market

        frozen = trade.frozen_decision_payload or {}
        if normalize_market(frozen.get("market") or "UNKNOWN") != "USA":
            raise ValueError("The equity information model is scoped to USA")
        if (
            trade.accounting_status != "VALID"
            or trade.r_multiple is None
            or trade.net_pnl_eur is None
        ):
            raise ValueError("Verified terminal native accounting required")
        executed = db.scalar(
            select(PaperExecutionOrder)
            .where(
                PaperExecutionOrder.paper_trade_id == trade.id,
                PaperExecutionOrder.filled_quantity > 0,
            )
            .limit(1)
        )
        if executed is None:
            raise ValueError("Actual native execution required")
        context = context_from_payload(frozen["information_context"])
        spec = frozen["executable_strategy"]
        outcome = MaturedAlphaOutcome(
            f"paper_trade:{trade.id}",
            str(frozen.get("decision_uid") or f"native-paper:{trade.id}"),
            "equity",
            trade.ticker,
            context.decision_at,
            trade.closed_at,
            trade.r_multiple,
            str(frozen.get("evidence_lane") or "UNQUALIFIED_NATIVE_PAPER"),
            context,
            spec,
            frozen["strategy_fingerprint"],
            (frozen.get("information_advice") or {}).get("model_hash"),
            {
                "currency": executed.account_currency,
                "net_pnl": trade.net_pnl_eur,
                "costs_paid": trade.costs_paid,
                "execution_costs": trade.execution_costs,
            },
            {
                "ticker": trade.benchmark_ticker,
                "return": trade.benchmark_return_same_period,
                "excess": trade.excess_return_vs_benchmark,
            },
        )
        return outcome, {
            "setup_type": spec["setup_type"],
            "regime": frozen.get("regime", "unknown"),
            "features": frozen.get("features") or {},
        }
