"""Calibrated outcome advice; a target distance is never a win probability."""

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime
import hashlib
import json
import math
import pickle

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss

from app.services.market_clock import utc_naive
from app.services.trading_ml.contracts import (
    FeatureSchema,
    TradingMLExample,
    InsufficientTrainingEvidenceError,
)
from app.services.trading_ml.registry import TradingMLModelRegistry
from app.services.trading_ml.training import (
    SklearnTradingModelTrainer,
    TrainingResult,
    _fit_bundle,
    dataset_fingerprint,
)
from app.services.trading_ml.validation import (
    chronological_calibration_split,
    example_source_uid,
)
from .context import FEATURE_SCHEMA_HASH


def scope_key(market, setup, regime, fingerprint):
    return json.dumps([market, setup, regime, fingerprint], separators=(",", ":"))


def _logits(probabilities):
    p = np.clip(np.asarray(probabilities, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p)).reshape(-1, 1)


@dataclass(frozen=True)
class _CalibratedClassifier:
    classifier: object
    calibrator: object

    def predict_proba(self, matrix):
        raw = self.classifier.predict_proba(matrix)[:, 1]
        return self.calibrator.predict_proba(_logits(raw))


def _scores(rows, probabilities):
    labels = np.asarray([row.label_positive_r for row in rows])
    weights = np.asarray([row.sample_weight for row in rows])
    error = 0.0
    for low in np.linspace(0, 0.9, 10):
        mask = (probabilities >= low) & (
            probabilities < low + 0.1 if low < 0.9 else probabilities <= 1
        )
        if mask.any():
            weight = weights[mask].sum()
            error += weight * abs(
                np.average(probabilities[mask], weights=weights[mask])
                - np.average(labels[mask], weights=weights[mask])
            )
    return {
        "sample_size": len(rows),
        "brier_score": float(
            brier_score_loss(labels, probabilities, sample_weight=weights)
        ),
        "log_loss": float(
            log_loss(
                labels,
                np.column_stack((1 - probabilities, probabilities)),
                labels=[0, 1],
                sample_weight=weights,
            )
        ),
        "calibration_error": float(error / weights.sum()),
    }


class InformationModelTrainer:
    def __init__(self, *, seed=17, parameters=None):
        self.seed = seed
        self.parameters = {
            **SklearnTradingModelTrainer.DEFAULT_PARAMETERS,
            "early_stopping": False,
            **(parameters or {}),
        }

    def fit(self, examples, *, maximum_holding_horizon):
        rows = tuple(examples)
        if not rows or len({row.market_family for row in rows}) != 1:
            raise InsufficientTrainingEvidenceError(
                "Train USA/equity and Forex separately"
            )
        if any(
            row.features.get("information_feature_schema_hash") != FEATURE_SCHEMA_HASH
            or not row.features.get("strategy_fingerprint")
            for row in rows
        ):
            raise InsufficientTrainingEvidenceError(
                "Frozen information schema and strategy identity required"
            )
        if any(
            row.sample_weight <= 0
            or row.label_positive_r != int(row.realized_net_r > 0)
            for row in rows
        ):
            raise InsufficientTrainingEvidenceError(
                "Only weighted, consistent matured net outcome labels are supported"
            )
        split = chronological_calibration_split(
            rows, maximum_holding_horizon=maximum_holding_horizon
        )
        schema = FeatureSchema.information()
        bundle = _fit_bundle(
            split.train,
            self.parameters,
            self.seed,
            schema=schema,
            clip_net_labels=False,
        )
        raw, _ = bundle.predict(split.calibration)
        calibrator = LogisticRegression(random_state=self.seed, C=1.0, max_iter=200)
        calibrator.fit(
            _logits(raw),
            [row.label_positive_r for row in split.calibration],
            sample_weight=[row.sample_weight for row in split.calibration],
        )
        bundle = replace(
            bundle,
            classifier=_CalibratedClassifier(bundle.classifier, calibrator),
            algorithm="information_hgb_sigmoid_v2",
        )
        probabilities, net_rs = bundle.predict(split.evaluation)
        validation = _scores(split.evaluation, probabilities)
        prior = np.average(
            [row.label_positive_r for row in split.train],
            weights=[row.sample_weight for row in split.train],
        )
        baseline = _scores(split.evaluation, np.full(len(split.evaluation), prior))
        groups = defaultdict(lambda: {"calibration": [], "evaluation": []})
        for partition in ("calibration", "evaluation"):
            for sample in getattr(split, partition):
                key = scope_key(
                    sample.market_family,
                    sample.setup_type,
                    sample.regime,
                    sample.features["strategy_fingerprint"],
                )
                groups[key][partition].append(sample)
        support = {}
        for key, group in groups.items():
            calibration, evaluation = group["calibration"], group["evaluation"]
            supported = (
                len(calibration) >= 20
                and len(evaluation) >= 20
                and len({row.label_positive_r for row in calibration}) == 2
            )
            metrics = (
                _scores(evaluation, bundle.predict(evaluation)[0]) if evaluation else {}
            )
            support[key] = {
                "supported": supported,
                "calibration_count": len(calibration),
                "evaluation_count": len(evaluation),
                **metrics,
            }
        selected = [
            row.realized_net_r
            for row, p, r in zip(split.evaluation, probabilities, net_rs)
            if p >= 0.5 and r > 0
        ]
        validation.update(
            net_expectancy=float(np.mean(selected)) if selected else None,
            predicted_net_r_mae=float(
                np.mean(
                    np.abs(
                        net_rs
                        - np.asarray([row.realized_net_r for row in split.evaluation])
                    )
                )
            ),
            folds=[
                {
                    "validation_start": split.evaluation[
                        0
                    ].decision_timestamp.isoformat(),
                    "protocol": "fit_calibration_evaluation_v2",
                }
            ],
            calibration_support=support,
        )
        metadata = {
            "schema_version": schema.version,
            "information_feature_schema_hash": FEATURE_SCHEMA_HASH,
            "market_family": rows[0].market_family,
            "label_units": "realized_net_r_including_costs",
            "training_outcome_cutoff": max(
                row.outcome_timestamp for row in split.train
            ).isoformat(),
            "calibration_start": split.calibration[0].decision_timestamp.isoformat(),
            "calibration_outcome_cutoff": max(
                row.outcome_timestamp for row in split.calibration
            ).isoformat(),
            "evaluation_start": split.evaluation[0].decision_timestamp.isoformat(),
            "outcome_cutoff": max(
                utc_naive(row.outcome_timestamp) for row in rows
            ).isoformat(),
            "embargo_seconds": split.embargo.total_seconds(),
            "available_at": datetime.utcnow().isoformat(),
            "calibration_support": support,
            **{
                name
                + "_source_uids": [
                    example_source_uid(row) for row in getattr(split, name)
                ]
                for name in ("train", "calibration", "evaluation")
            },
        }
        metadata["training_source_uids"] = metadata.pop("train_source_uids")
        bundle = replace(bundle, metadata=metadata)
        artifact = pickle.dumps(bundle, protocol=5)
        return TrainingResult(
            "CHALLENGER",
            False,
            bundle,
            None,
            validation,
            baseline,
            artifact,
            hashlib.sha256(artifact).hexdigest(),
            dataset_fingerprint(rows),
            {**self.parameters, "embargo_seconds": split.embargo.total_seconds()},
            len(rows),
        )


@dataclass(frozen=True)
class InformationAdvice:
    status: str
    model_uid: str | None = None
    probability_positive_r: float | None = None
    predicted_net_r: float | None = None
    uncertainty: float | None = None
    training_cutoff: datetime | None = None
    outcome_cutoff: datetime | None = None
    calibration_support: dict | None = None
    decision_authority: bool = False
    model_hash: str | None = None
    guardrails: tuple[str, ...] = ()
    feature_schema_hash: str | None = None
    net_costs_included: bool = False
    confidence_adjustment: float = 0.0
    veto_recommended: bool = False
    explanation: tuple[str, ...] = ()


def information_example(context, baseline, *, strategy_fingerprint):
    setup, regime = str(baseline.get("setup_type") or "unknown"), str(
        baseline.get("regime") or "unknown"
    )
    features = {
        **dict(baseline.get("features") or {}),
        **dict(context.features),
        "market_family": context.market_family,
        "setup_type": setup,
        "regime": regime,
        "strategy_fingerprint": strategy_fingerprint,
        "information_feature_schema_hash": FEATURE_SCHEMA_HASH,
    }
    return TradingMLExample(
        "information_context",
        context.context_uid,
        context.market_family,
        "INFERENCE",
        context.decision_at,
        context.decision_at,
        context.asset_key,
        setup,
        regime,
        features,
        0.0,
        0,
        None,
        1.0,
    )


class InformationOutcomeAdvisor:
    def __init__(self, registry=None):
        self.registry = registry or TradingMLModelRegistry()

    def advise(
        self, db, *, context, strategy_fingerprint, baseline, as_of, model_uid=None
    ):
        if utc_naive(as_of) != context.decision_at:
            return InformationAdvice("CONTEXT_CLOCK_MISMATCH")
        if context.coverage.get("feature_schema_hash") != FEATURE_SCHEMA_HASH:
            return InformationAdvice("SCHEMA_MISMATCH")
        loaded = self.registry.load_as_of(
            db,
            context.market_family,
            as_of=context.decision_at,
            schema_hash=FeatureSchema.information().hash,
            model_uid=model_uid,
        )
        if loaded.model is None:
            return InformationAdvice(loaded.status, guardrails=loaded.warnings)
        sample = information_example(
            context, baseline, strategy_fingerprint=strategy_fingerprint
        )
        metadata = loaded.model.metadata
        key = scope_key(
            context.market_family,
            sample.setup_type,
            sample.regime,
            strategy_fingerprint,
        )
        support = metadata.get("calibration_support", {}).get(key, {})
        if not support.get("supported"):
            return InformationAdvice(
                "UNSUPPORTED_SCOPE", loaded.row.model_uid, calibration_support=support
            )
        probabilities, predicted_rs = loaded.model.predict((sample,))
        p, r = float(probabilities[0]), float(predicted_rs[0])
        if not math.isfinite(p) or not 0 <= p <= 1 or not math.isfinite(r):
            return InformationAdvice("INVALID_MODEL_OUTPUT", loaded.row.model_uid)
        return InformationAdvice(
            "CALIBRATED",
            loaded.row.model_uid,
            p,
            r,
            # Finite calibration support is an explicit sampling error estimate,
            # not an interval guaranteeing future trading profitability.
            math.sqrt(p * (1 - p) / support["calibration_count"]),
            datetime.fromisoformat(metadata["training_outcome_cutoff"]),
            datetime.fromisoformat(metadata["outcome_cutoff"]),
            support,
            loaded.status == "ACTIVE_AS_OF",
            loaded.row.artifact_sha256,
            (
                "NET_LABEL_COSTS_ALREADY_INCLUDED",
                "EXISTING_RISK_GATES",
                "SCOPE_CALIBRATION_REQUIRED",
            ),
            feature_schema_hash=loaded.model.schema_hash,
            net_costs_included=True,
            veto_recommended=r <= 0,
            explanation=(
                "Conditional net outcome calibrated on a later disjoint period; numerical support is not proof of alpha.",
            ),
        )
