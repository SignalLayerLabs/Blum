"""Bounded scikit-learn trainers for BLUM trading challengers."""

from __future__ import annotations

from dataclasses import dataclass, fields
import hashlib
import pickle
from pathlib import Path
import time
from typing import Iterable, Mapping

import numpy as np
import optuna
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .contracts import (
    CATEGORICAL_FEATURES,
    FeatureSchema,
    NUMERIC_FEATURES,
    TradingMLExample,
)
from .validation import (
    FoldPrediction,
    PurgedWalkForwardEvaluator,
    PurgedWalkForwardResult,
    example_source_uid,
)


@dataclass(frozen=True)
class TradingModelBundle:
    schema_hash: str
    feature_names: tuple[str, ...]
    preprocessor: object
    classifier: object
    regressor: object | None
    algorithm: str

    def predict(
        self, examples: Iterable[TradingMLExample]
    ) -> tuple[np.ndarray, np.ndarray | None]:
        rows = tuple(examples)
        matrix = self.preprocessor.transform(_feature_frame(rows))
        probability = self.classifier.predict_proba(matrix)[:, 1]
        predicted_r = (
            self.regressor.predict(matrix) if self.regressor is not None else None
        )
        return probability, predicted_r


@dataclass(frozen=True)
class TrainingResult:
    status: str
    decision_authority: bool
    model_bundle: TradingModelBundle
    validation_result: PurgedWalkForwardResult | None
    validation_metrics: Mapping[str, object]
    baseline_metrics: Mapping[str, object]
    artifact_bytes: bytes
    artifact_sha256: str
    dataset_hash: str
    parameters: Mapping[str, object]
    sample_count: int


@dataclass(frozen=True)
class SearchResult:
    parameters: Mapping[str, object]
    value: float | None
    trials_completed: int
    duration_seconds: float


class OnlineShadowTrainer:
    """Fast incremental learner that never receives decision authority."""

    def __init__(self, artifact_root: str | Path, *, seed: int = 17) -> None:
        self.artifact_root = Path(artifact_root)
        self.seed = seed

    def partial_fit(
        self, examples: Iterable[TradingMLExample], *, as_of=None
    ) -> TrainingResult:
        rows = tuple(examples)
        if not rows:
            raise ValueError("Online training requires at least one example")
        from .online import update_shadow

        return update_shadow(self.artifact_root, rows, seed=self.seed, as_of=as_of)

    def current(self, market_family: str) -> TrainingResult | None:
        """Load a verified checkpoint without consuming any training examples."""
        from .online import update_shadow

        return update_shadow(
            self.artifact_root, (), seed=self.seed, market_family=market_family
        )


class _FoldModel:
    def __init__(self, parameters: Mapping[str, object], seed: int) -> None:
        self.parameters = dict(parameters)
        self.seed = seed

    def predict(
        self,
        train: tuple[TradingMLExample, ...],
        validation: tuple[TradingMLExample, ...],
    ) -> tuple[FoldPrediction, ...]:
        bundle = _fit_bundle(train, self.parameters, self.seed)
        probabilities, predicted_r = bundle.predict(validation)
        return tuple(
            FoldPrediction(
                source_uid=example_source_uid(row),
                probability_positive_r=float(probability),
                predicted_net_r=(
                    float(predicted_r[index]) if predicted_r is not None else None
                ),
                actionable=bool(
                    probability >= 0.5
                    and (predicted_r is None or predicted_r[index] > 0)
                ),
            )
            for index, (row, probability) in enumerate(zip(validation, probabilities))
        )


class _BaselineModel:
    def predict(
        self,
        train: tuple[TradingMLExample, ...],
        validation: tuple[TradingMLExample, ...],
    ) -> tuple[FoldPrediction, ...]:
        positive = sum(row.label_positive_r * row.sample_weight for row in train)
        weight = sum(row.sample_weight for row in train)
        probability = min(0.99, max(0.01, positive / weight if weight else 0.5))
        expected_r = (
            sum(row.realized_net_r * row.sample_weight for row in train) / weight
            if weight
            else 0.0
        )
        return tuple(
            FoldPrediction(
                source_uid=example_source_uid(row),
                probability_positive_r=probability,
                predicted_net_r=expected_r,
                actionable=probability >= 0.5 and expected_r > 0,
            )
            for row in validation
        )


class SklearnTradingModelTrainer:
    """Deterministic classifier/regressor with purged walk-forward evidence."""

    DEFAULT_PARAMETERS = {
        "learning_rate": 0.06,
        "max_leaf_nodes": 15,
        "max_iter": 100,
        "l2_regularization": 0.05,
    }

    def __init__(
        self,
        *,
        seed: int = 17,
        min_folds: int = 3,
        embargo_days: int = 1,
        parameters: Mapping[str, object] | None = None,
    ) -> None:
        self.seed = seed
        self.parameters = {**self.DEFAULT_PARAMETERS, **dict(parameters or {})}
        self.evaluator = PurgedWalkForwardEvaluator(
            min_folds=min_folds, embargo_days=embargo_days
        )

    def fit(self, examples: Iterable[TradingMLExample]) -> TrainingResult:
        rows = tuple(examples)
        validation = self.evaluator.evaluate(
            _FoldModel(self.parameters, self.seed), _BaselineModel(), rows
        )
        bundle = _fit_bundle(rows, self.parameters, self.seed)
        artifact = pickle.dumps(bundle, protocol=5)
        return TrainingResult(
            status="CHALLENGER",
            decision_authority=False,
            model_bundle=bundle,
            validation_result=validation,
            validation_metrics=_result_metrics(validation, candidate=True),
            baseline_metrics=_result_metrics(validation, candidate=False),
            artifact_bytes=artifact,
            artifact_sha256=hashlib.sha256(artifact).hexdigest(),
            dataset_hash=dataset_fingerprint(rows),
            parameters=dict(self.parameters),
            sample_count=len(rows),
        )


class BoundedOptunaChallengerSearch:
    """Small deterministic search; it can improve a challenger, never promote it."""

    def __init__(
        self,
        *,
        seed: int = 17,
        max_trials: int = 12,
        timeout_seconds: int = 90,
        min_folds: int = 3,
    ) -> None:
        self.seed = seed
        self.max_trials = min(12, max(1, int(max_trials)))
        self.timeout_seconds = min(90, max(1, int(timeout_seconds)))
        self.min_folds = min_folds

    def search(self, examples: Iterable[TradingMLExample]) -> SearchResult:
        rows = tuple(examples)
        started = time.perf_counter()
        sampler = optuna.samplers.TPESampler(seed=self.seed)
        pruner = optuna.pruners.MedianPruner(n_startup_trials=3)
        study = optuna.create_study(
            direction="minimize", sampler=sampler, pruner=pruner
        )

        def objective(trial: optuna.Trial) -> float:
            parameters = {
                "learning_rate": trial.suggest_float(
                    "learning_rate", 0.02, 0.15, log=True
                ),
                "max_leaf_nodes": trial.suggest_int("max_leaf_nodes", 7, 31),
                "max_iter": trial.suggest_int("max_iter", 60, 180),
                "l2_regularization": trial.suggest_float(
                    "l2_regularization", 1e-4, 1.0, log=True
                ),
            }
            result = SklearnTradingModelTrainer(
                seed=self.seed,
                min_folds=self.min_folds,
                parameters=parameters,
            ).fit(rows)
            metrics = (
                result.validation_result.candidate if result.validation_result else None
            )
            if metrics is None or metrics.brier_score is None:
                return 10.0
            penalty = max(0.0, -(metrics.net_expectancy or 0.0)) * 2.0
            return float(metrics.brier_score + penalty)

        study.optimize(
            objective,
            n_trials=self.max_trials,
            timeout=self.timeout_seconds,
            show_progress_bar=False,
            gc_after_trial=True,
        )
        completed = [
            trial
            for trial in study.trials
            if trial.state == optuna.trial.TrialState.COMPLETE
        ]
        return SearchResult(
            parameters=(
                dict(study.best_params)
                if completed
                else dict(SklearnTradingModelTrainer.DEFAULT_PARAMETERS)
            ),
            value=float(study.best_value) if completed else None,
            trials_completed=len(completed),
            duration_seconds=round(time.perf_counter() - started, 4),
        )


def _preprocessor() -> ColumnTransformer:
    numeric = Pipeline(
        [("imputer", SimpleImputer(strategy="median")), ("scale", StandardScaler())]
    )
    categorical = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]
    )
    return ColumnTransformer(
        [
            ("numeric", numeric, list(NUMERIC_FEATURES)),
            ("categorical", categorical, list(CATEGORICAL_FEATURES)),
        ],
        sparse_threshold=0.0,
    )


def _fit_bundle(
    rows: tuple[TradingMLExample, ...], parameters: Mapping[str, object], seed: int
) -> TradingModelBundle:
    if not rows:
        raise ValueError("Stable training requires labeled examples")
    preprocessor = _preprocessor()
    matrix = preprocessor.fit_transform(_feature_frame(rows))
    labels = np.asarray([row.label_positive_r for row in rows])
    if len(np.unique(labels)) < 2:
        raise ValueError(
            "Stable training requires both positive and non-positive outcomes"
        )
    weights = np.asarray([row.sample_weight for row in rows], dtype=float)
    params = dict(parameters)
    classifier = HistGradientBoostingClassifier(random_state=seed, **params)
    regressor = HistGradientBoostingRegressor(random_state=seed, **params)
    classifier.fit(matrix, labels, sample_weight=weights)
    regressor.fit(
        matrix,
        np.clip([row.realized_net_r for row in rows], -3.0, 5.0),
        sample_weight=weights,
    )
    return TradingModelBundle(
        schema_hash=FeatureSchema.current().hash,
        feature_names=FeatureSchema.current().feature_names,
        preprocessor=preprocessor,
        classifier=classifier,
        regressor=regressor,
        algorithm="hist_gradient_boosting_classifier_regressor",
    )


def _feature_frame(rows: Iterable[TradingMLExample]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                name: row.features.get(name)
                for name in FeatureSchema.current().feature_names
            }
            for row in rows
        ],
        columns=list(FeatureSchema.current().feature_names),
    )


def dataset_fingerprint(rows: Iterable[TradingMLExample]) -> str:
    payload = [
        {
            "source": example_source_uid(row),
            "decision": row.decision_timestamp.isoformat(),
            "outcome": row.outcome_timestamp.isoformat(),
            "features": dict(row.features),
            "r": row.realized_net_r,
            "label": row.label_positive_r,
            "weight": row.sample_weight,
            "lane": row.evidence_lane,
            "asset": row.asset_key,
            "benchmark": row.benchmark_excess,
        }
        for row in rows
    ]
    return hashlib.sha256(
        __import__("json")
        .dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        .encode()
    ).hexdigest()


def _result_metrics(
    result: PurgedWalkForwardResult, *, candidate: bool
) -> dict[str, object]:
    metrics = result.candidate if candidate else result.baseline
    payload = _metrics_dict(metrics)
    payload["folds"] = [
        {
            "fold_index": fold.fold.fold_index,
            "validation_start": fold.fold.validation_start.isoformat(),
            "train_size": len(fold.fold.train),
            "validation_size": len(fold.fold.validation),
            "metrics": _metrics_dict(
                fold.candidate.metrics if candidate else fold.baseline.metrics
            ),
        }
        for fold in result.folds
    ]
    if candidate:
        payload["brier_improvement"] = result.brier_improvement
    return payload


def _metrics_dict(metrics) -> dict[str, object]:
    payload: dict[str, object] = {}
    for field in fields(metrics):
        value = getattr(metrics, field.name)
        payload[field.name] = dict(value) if isinstance(value, Mapping) else value
    return payload
