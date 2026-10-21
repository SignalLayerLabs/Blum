"""Read-only bounded inference with optional write-workflow audit persistence."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import TradingMLPrediction

from .contracts import FeatureSchema, TradingMLAdvice, TradingMLExample
from .registry import TradingMLModelRegistry


class TradingMLInferenceService:
    def __init__(self, registry: TradingMLModelRegistry | None = None) -> None:
        self.registry = registry or TradingMLModelRegistry()
        self.settings = get_settings()

    def advise(
        self,
        db: Session,
        *,
        market_family: str,
        features: Mapping[str, object],
        baseline_output: Mapping[str, object] | None = None,
        deterministic_blockers: tuple[str, ...] | list[str] = (),
        source_object_type: str = "decision",
        source_object_id: str = "unpersisted",
        persist: bool = False,
        decision_timestamp: datetime | None = None,
        asset_key: str = "unknown",
        setup_type: str = "unknown",
        regime: str = "unknown",
    ) -> TradingMLAdvice:
        loaded = (self.registry.load_as_of(db, market_family, as_of=decision_timestamp,
                                          schema_hash=FeatureSchema.current().hash)
                  if decision_timestamp is not None else self.registry.load_active(db, market_family))
        if loaded.status not in {"ACTIVE", "ACTIVE_AS_OF"} or loaded.row is None or loaded.model is None:
            return TradingMLAdvice(
                status=loaded.status,
                model_uid=loaded.row.model_uid if loaded.row else None,
                probability_positive_r=None,
                predicted_net_r=None,
                uncertainty=None,
                confidence_adjustment=0.0,
                veto_recommended=False,
                explanation=("Deterministic BLUM retains full authority.",),
                guardrails=tuple(loaded.warnings),
            )
        if loaded.row.sample_count < self.settings.trading_ml_min_replay_samples:
            return TradingMLAdvice(
                status="INSUFFICIENT_EVIDENCE",
                model_uid=loaded.row.model_uid,
                probability_positive_r=None,
                predicted_net_r=None,
                uncertainty=None,
                confidence_adjustment=0.0,
                veto_recommended=False,
                explanation=("Active metadata does not meet the current minimum sample gate.",),
                guardrails=("MINIMUM_SAMPLE_GATE",),
            )

        now = decision_timestamp or datetime.utcnow()
        canonical = {name: features.get(name) for name in FeatureSchema.current().feature_names}
        canonical["market_family"] = market_family
        example = TradingMLExample(
            source_object_type=source_object_type,
            source_object_id=str(source_object_id),
            market_family=market_family,  # type: ignore[arg-type]
            evidence_lane="inference",
            decision_timestamp=now,
            outcome_timestamp=now,
            asset_key=asset_key,
            setup_type=setup_type,
            regime=regime,
            features=canonical,  # type: ignore[arg-type]
            realized_net_r=0.0,
            label_positive_r=0,
            benchmark_excess=None,
            sample_weight=1.0,
        )
        try:
            probabilities, predicted_rs = loaded.model.predict((example,))
            probability = float(probabilities[0])
            predicted_r = float(predicted_rs[0]) if predicted_rs is not None else None
        except Exception as exc:
            return TradingMLAdvice(
                status="SCHEMA_MISMATCH",
                model_uid=loaded.row.model_uid,
                probability_positive_r=None,
                predicted_net_r=None,
                uncertainty=None,
                confidence_adjustment=0.0,
                veto_recommended=False,
                explanation=(f"Inference rejected: {type(exc).__name__}.",),
                guardrails=("SCHEMA_MISMATCH",),
            )

        uncertainty = round(1.0 - abs(probability - 0.5) * 2.0, 6)
        signed_strength = (probability - 0.5) * 2.0
        if predicted_r is not None:
            signed_strength *= min(1.0, abs(predicted_r))
            if predicted_r < 0:
                signed_strength = -abs(signed_strength)
        proposed = signed_strength * self.settings.trading_ml_max_confidence_adjustment
        guardrails = ["MAX_CONFIDENCE_ADJUSTMENT", "DETERMINISTIC_AUTHORITY"]
        applied = max(
            -self.settings.trading_ml_max_confidence_adjustment,
            min(self.settings.trading_ml_max_confidence_adjustment, proposed),
        )
        if deterministic_blockers:
            applied = 0.0
            guardrails.append("EXISTING_BLOCKER_PRESERVED")
        veto = probability < 0.35 and predicted_r is not None and predicted_r < 0
        advice = TradingMLAdvice(
            status="ACTIVE",
            model_uid=loaded.row.model_uid,
            probability_positive_r=round(probability, 6),
            predicted_net_r=round(predicted_r, 6) if predicted_r is not None else None,
            uncertainty=uncertainty,
            confidence_adjustment=round(applied, 4),
            veto_recommended=veto,
            explanation=(
                f"Champion probability of positive net R: {probability:.3f}.",
                f"Predicted net R: {predicted_r:.3f}." if predicted_r is not None else "Predicted net R unavailable.",
                "Advice is bounded and cannot remove deterministic or risk blockers.",
            ),
            guardrails=tuple(guardrails),
        )
        if persist:
            self._persist(
                db,
                row=loaded.row,
                advice=advice,
                features=canonical,
                baseline_output=baseline_output or {},
                source_object_type=source_object_type,
                source_object_id=str(source_object_id),
                market_family=market_family,
                proposed=proposed,
            )
        return advice

    @staticmethod
    def _persist(
        db: Session,
        *,
        row,
        advice: TradingMLAdvice,
        features: Mapping[str, object],
        baseline_output: Mapping[str, object],
        source_object_type: str,
        source_object_id: str,
        market_family: str,
        proposed: float,
    ) -> None:
        existing = db.scalar(
            select(TradingMLPrediction).where(
                TradingMLPrediction.source_object_type == source_object_type,
                TradingMLPrediction.source_object_id == source_object_id,
                TradingMLPrediction.model_version_id == row.id,
            )
        )
        if existing is not None:
            return
        feature_hash = hashlib.sha256(
            json.dumps(features, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        db.add(
            TradingMLPrediction(
                source_object_type=source_object_type,
                source_object_id=source_object_id,
                model_version_id=row.id,
                market_family=market_family,
                feature_hash=feature_hash,
                probability_positive_r=advice.probability_positive_r,
                predicted_net_r=advice.predicted_net_r,
                uncertainty=advice.uncertainty,
                baseline_output_json=dict(baseline_output),
                proposed_confidence_adjustment=round(proposed, 4),
                applied_confidence_adjustment=advice.confidence_adjustment,
                guardrails_json=list(advice.guardrails),
                explanation_json=list(advice.explanation),
            )
        )
        db.flush()


def advice_payload(advice: TradingMLAdvice) -> dict[str, object]:
    return {
        "status": advice.status,
        "model_uid": advice.model_uid,
        "probability_positive_r": advice.probability_positive_r,
        "predicted_net_r": advice.predicted_net_r,
        "uncertainty": advice.uncertainty,
        "proposed_confidence_adjustment": advice.confidence_adjustment,
        "applied_confidence_adjustment": advice.confidence_adjustment,
        "veto_recommended": advice.veto_recommended,
        "explanation": list(advice.explanation),
        "guardrails": list(advice.guardrails),
    }
