"""Trusted artifact registry and evidence-bound champion governance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import os
from pathlib import Path
import pickle
from typing import Mapping
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import TradingMLModelVersion

from .contracts import FeatureSchema
from .training import TradingModelBundle, TrainingResult


@dataclass(frozen=True)
class LoadedModel:
    status: str
    row: TradingMLModelVersion | None
    model: TradingModelBundle | None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class PromotionDecision:
    status: str
    passed: bool
    failed_gates: tuple[str, ...]
    gates: Mapping[str, bool]
    explanation: str


class TradingMLModelRegistry:
    def __init__(self, artifact_root: str | Path | None = None) -> None:
        self.root = Path(artifact_root or get_settings().trading_ml_artifact_root).resolve()

    def store_candidate(
        self,
        db: Session,
        *,
        market_family: str,
        result: TrainingResult,
        evidence_lane_counts: Mapping[str, int] | None = None,
        asset_count: int = 0,
        regime_count: int = 0,
        setup_count: int = 0,
        explanation: str = "",
    ) -> TradingMLModelVersion:
        self.root.mkdir(parents=True, exist_ok=True)
        model_uid = (
            f"{market_family}-{datetime.utcnow():%Y%m%d%H%M%S}-{uuid4().hex[:10]}"
        )
        target = (self.root / market_family / f"{model_uid}.pkl").resolve()
        self._assert_beneath_root(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        with temporary.open("wb") as stream:
            stream.write(result.artifact_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        if digest != result.artifact_sha256:
            temporary.unlink(missing_ok=True)
            raise ValueError("Artifact hash changed before publication")
        os.replace(temporary, target)
        row = TradingMLModelVersion(
            model_uid=model_uid,
            market_family=market_family,
            algorithm=result.model_bundle.algorithm,
            status="CHALLENGER",
            feature_schema_version=(
                FeatureSchema.information().version
                if result.model_bundle.schema_hash == FeatureSchema.information().hash
                else FeatureSchema.current().version
            ),
            feature_schema_hash=result.model_bundle.schema_hash,
            training_window_json={
                key: value
                for key, value in getattr(result.model_bundle, "metadata", {}).items()
                if key
                in {
                    "available_at",
                    "outcome_cutoff",
                    "training_outcome_cutoff",
                    "calibration_start",
                    "calibration_outcome_cutoff",
                    "evaluation_start",
                    "embargo_seconds",
                    "information_feature_schema_hash",
                    "market_family",
                    "label_units",
                }
            },
            dataset_hash=result.dataset_hash,
            evidence_lane_counts_json=dict(evidence_lane_counts or {}),
            sample_count=result.sample_count,
            asset_count=asset_count,
            regime_count=regime_count,
            setup_count=setup_count,
            validation_metrics_json=dict(result.validation_metrics),
            baseline_metrics_json=dict(result.baseline_metrics),
            artifact_path=str(target),
            artifact_sha256=digest,
            artifact_size_bytes=target.stat().st_size,
            explanation=explanation
            or "Stored challenger; no decision authority until every promotion gate passes.",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def load_active(self, db: Session, market_family: str) -> LoadedModel:
        row = db.scalar(
            select(TradingMLModelVersion)
            .where(
                TradingMLModelVersion.market_family == market_family,
                TradingMLModelVersion.status == "ACTIVE",
            )
            .order_by(desc(TradingMLModelVersion.activated_at), desc(TradingMLModelVersion.id))
            .limit(1)
        )
        if row is None:
            return LoadedModel("NO_ACTIVE_MODEL", None, None)
        try:
            path = Path(row.artifact_path).resolve()
            self._assert_beneath_root(path)
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != row.artifact_sha256:
                raise ValueError("ARTIFACT_HASH_MISMATCH")
            if row.feature_schema_hash != FeatureSchema.current().hash:
                raise ValueError("SCHEMA_MISMATCH")
            model = pickle.loads(content)
            if not isinstance(model, TradingModelBundle) or model.schema_hash != FeatureSchema.current().hash:
                raise ValueError("SCHEMA_MISMATCH")
            return LoadedModel("ACTIVE", row, model)
        except Exception as exc:
            return LoadedModel("DEGRADED", row, None, (str(exc),))

    def load_as_of(
        self,
        db: Session,
        market_family: str,
        *,
        as_of: datetime,
        schema_hash: str,
        model_uid: str | None = None,
    ) -> LoadedModel:
        """A current champion is not automatically a historical checkpoint.

        Explicit candidate UIDs may be scored for research. Implicit selection
        requires actual activation at that clock and never adopts a challenger.
        Rollback/degradation clocks govern historical authority, not current status.
        """
        from app.services.market_clock import utc_naive
        import math

        stamp = utc_naive(as_of)
        query = select(TradingMLModelVersion).where(
            TradingMLModelVersion.market_family == market_family,
            TradingMLModelVersion.created_at <= stamp,
        )
        if model_uid is not None:
            query = query.where(TradingMLModelVersion.model_uid == model_uid)
        else:
            query = query.where(TradingMLModelVersion.activated_at <= stamp)
        rows = db.scalars(
            query.order_by(
                desc(TradingMLModelVersion.activated_at), desc(TradingMLModelVersion.id)
            ).limit(20)
        ).all()
        for row in rows:
            ended = any(
                value is not None and utc_naive(value) <= stamp
                for value in (row.degraded_at, row.rolled_back_at)
            )
            active = (
                row.activated_at is not None
                and utc_naive(row.activated_at) <= stamp
                and not ended
            )
            if ended or (not active and model_uid is None):
                continue
            if row.feature_schema_hash != schema_hash:
                return LoadedModel("SCHEMA_MISMATCH", row, None, ("SCHEMA_MISMATCH",))
            try:
                path = Path(row.artifact_path).resolve()
                self._assert_beneath_root(path)
                content = path.read_bytes()
                if hashlib.sha256(content).hexdigest() != row.artifact_sha256:
                    raise ValueError("ARTIFACT_HASH_MISMATCH")
                model = pickle.loads(content)
                if (
                    not isinstance(model, TradingModelBundle)
                    or model.schema_hash != schema_hash
                ):
                    raise ValueError("SCHEMA_MISMATCH")
                metadata = getattr(model, "metadata", {})
                names = (
                    "available_at",
                    "outcome_cutoff",
                    "training_outcome_cutoff",
                    "calibration_start",
                    "calibration_outcome_cutoff",
                    "evaluation_start",
                )
                clocks = {
                    name: utc_naive(datetime.fromisoformat(metadata[name]))
                    for name in names
                }
                if metadata.get("market_family") != market_family or any(
                    row.training_window_json.get(name) != metadata.get(name)
                    for name in names
                ):
                    raise ValueError("CHECKPOINT_METADATA_MISMATCH")
                embargo = float(metadata["embargo_seconds"])
                if not math.isfinite(embargo) or embargo <= 0:
                    raise ValueError("INVALID_CALIBRATION_EMBARGO")
                if clocks["available_at"] > stamp or clocks["outcome_cutoff"] > stamp:
                    return LoadedModel(
                        "NO_MODEL_AS_OF", row, None, ("FUTURE_MODEL_OR_OUTCOME",)
                    )
                if (
                    clocks["available_at"] < clocks["outcome_cutoff"]
                    or (
                        clocks["calibration_start"] - clocks["training_outcome_cutoff"]
                    ).total_seconds()
                    <= embargo
                    or (
                        clocks["evaluation_start"]
                        - clocks["calibration_outcome_cutoff"]
                    ).total_seconds()
                    <= embargo
                ):
                    raise ValueError("INVALID_CHECKPOINT_CHRONOLOGY")
                return LoadedModel(
                    "ACTIVE_AS_OF" if active else "CHALLENGER_AS_OF", row, model
                )
            except (
                KeyError,
                TypeError,
                ValueError,
                OSError,
                pickle.UnpicklingError,
                EOFError,
            ):
                return LoadedModel("DEGRADED", row, None, ("UNVERIFIABLE_CHECKPOINT",))
        return LoadedModel("NO_MODEL_AS_OF", None, None)

    def verify(self, row: TradingMLModelVersion) -> bool:
        try:
            path = Path(row.artifact_path).resolve()
            self._assert_beneath_root(path)
            return (
                path.is_file()
                and hashlib.sha256(path.read_bytes()).hexdigest() == row.artifact_sha256
                and row.feature_schema_hash
                in {FeatureSchema.current().hash, FeatureSchema.information().hash}
            )
        except OSError:
            return False

    def _assert_beneath_root(self, path: Path) -> None:
        if path != self.root and self.root not in path.parents:
            raise ValueError("Artifact path is outside configured trusted root")


class TradingMLPromotionService:
    def __init__(self, artifact_root: str | Path | None = None) -> None:
        self.registry = TradingMLModelRegistry(artifact_root)
        self.settings = get_settings()

    def evaluate(self, db: Session, candidate: TradingMLModelVersion) -> PromotionDecision:
        validation = candidate.validation_metrics_json or {}
        baseline = candidate.baseline_metrics_json or {}
        brier = _number(validation.get("brier_score"))
        baseline_brier = _number(baseline.get("brier_score"))
        brier_improvement = (
            (baseline_brier - brier) / baseline_brier
            if brier is not None and baseline_brier not in (None, 0)
            else None
        )
        gates = {
            "artifact_integrity": self.registry.verify(candidate),
            "minimum_samples": candidate.sample_count >= self.settings.trading_ml_min_replay_samples,
            "minimum_folds": len(validation.get("folds") or []) >= self.settings.trading_ml_min_folds,
            "minimum_assets": candidate.asset_count >= self.settings.trading_ml_min_assets,
            "positive_net_expectancy": (_number(validation.get("net_expectancy")) or 0.0) > 0.0,
            "brier_improvement": brier_improvement is not None and brier_improvement >= self.settings.trading_ml_brier_improvement,
            "asset_concentration": (_number(validation.get("asset_concentration")) or 1.0) <= 0.50,
        }
        failed = tuple(name for name, passed in gates.items() if not passed)
        status = "PROMOTABLE" if not failed else (
            "INSUFFICIENT_EVIDENCE"
            if any(name in failed for name in ("minimum_samples", "minimum_folds", "minimum_assets"))
            else "REJECTED"
        )
        candidate.promotion_gates_json = gates
        candidate.promotion_decision = status
        db.commit()
        return PromotionDecision(
            status=status,
            passed=not failed,
            failed_gates=failed,
            gates=gates,
            explanation="All out-of-sample gates passed." if not failed else f"Failed gates: {', '.join(failed)}.",
        )

    def promote(self, db: Session, candidate: TradingMLModelVersion) -> PromotionDecision:
        decision = self.evaluate(db, candidate)
        if not decision.passed:
            return decision
        if not self.registry.verify(candidate):
            return PromotionDecision("REJECTED", False, ("artifact_integrity",), {"artifact_integrity": False}, "Artifact verification failed.")
        prior = db.scalar(
            select(TradingMLModelVersion)
            .where(
                TradingMLModelVersion.market_family == candidate.market_family,
                TradingMLModelVersion.status == "ACTIVE",
                TradingMLModelVersion.id != candidate.id,
            )
            .order_by(desc(TradingMLModelVersion.activated_at), desc(TradingMLModelVersion.id))
            .limit(1)
        )
        now = datetime.utcnow()
        if prior is not None:
            prior.status = "ROLLED_BACK"
            prior.rolled_back_at = now
            candidate.champion_model_version_id = prior.id
        candidate.status = "ACTIVE"
        candidate.activated_at = now
        candidate.promotion_decision = "PROMOTED"
        db.commit()
        return PromotionDecision("ACTIVE", True, (), decision.gates, "Verified challenger atomically replaced the prior champion.")

    def evaluate_drift(self, db: Session, active: TradingMLModelVersion, *, rolling_metrics: Mapping[str, object], outcomes: int) -> PromotionDecision:
        baseline_brier = _number((active.validation_metrics_json or {}).get("brier_score"))
        rolling_brier = _number(rolling_metrics.get("brier_score"))
        expectancy = _number(rolling_metrics.get("net_expectancy"))
        failures: list[str] = []
        if not self.registry.verify(active):
            failures.append("artifact_integrity")
        if baseline_brier and rolling_brier and rolling_brier > baseline_brier * 1.10:
            failures.append("rolling_brier_deterioration")
        if outcomes >= 30 and expectancy is not None and expectancy < 0:
            failures.append("negative_forward_expectancy")
        return PromotionDecision(
            "DEGRADED" if failures else "ACTIVE",
            not failures,
            tuple(failures),
            {name: False for name in failures},
            "Active model remains within drift limits." if not failures else f"Degradation detected: {', '.join(failures)}.",
        )

    def rollback(self, db: Session, active: TradingMLModelVersion, *, reason: str) -> LoadedModel:
        active.status = "DEGRADED"
        active.degraded_at = datetime.utcnow()
        active.warnings_json = list(dict.fromkeys([*(active.warnings_json or []), reason]))
        previous = db.scalar(
            select(TradingMLModelVersion)
            .where(
                TradingMLModelVersion.market_family == active.market_family,
                TradingMLModelVersion.status == "ROLLED_BACK",
                TradingMLModelVersion.id != active.id,
            )
            .order_by(desc(TradingMLModelVersion.rolled_back_at), desc(TradingMLModelVersion.id))
            .limit(1)
        )
        if previous is not None and self.registry.verify(previous):
            previous.status = "ACTIVE"
            previous.activated_at = datetime.utcnow()
            previous.rolled_back_at = None
        db.commit()
        return self.registry.load_active(db, active.market_family)


def _number(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
