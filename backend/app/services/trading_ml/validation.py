"""Leakage-safe expanding walk-forward validation for trading ML models.

The evaluator deliberately owns only chronological splitting and evaluation.
Model fitting stays with the trainer so every candidate and deterministic
baseline is scored on the same out-of-sample examples.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import math
from types import MappingProxyType
from typing import Callable, Iterable, Mapping, Protocol, Sequence

from .contracts import InsufficientTrainingEvidenceError, TradingMLExample


_EPSILON = 1e-15


def example_source_uid(example: TradingMLExample) -> str:
    """Return the stable source identity used to align model outputs."""

    return f"{example.source_object_type}:{example.source_object_id}"


@dataclass(frozen=True)
class FoldPrediction:
    """One model prediction aligned to a canonical trading ML example."""

    source_uid: str
    probability_positive_r: float
    predicted_net_r: float | None
    actionable: bool = True

    def __post_init__(self) -> None:
        if not self.source_uid:
            raise ValueError("source_uid is required")
        if not math.isfinite(self.probability_positive_r) or not 0.0 <= self.probability_positive_r <= 1.0:
            raise ValueError("probability_positive_r must be a finite value between zero and one")
        if self.predicted_net_r is not None and not math.isfinite(self.predicted_net_r):
            raise ValueError("predicted_net_r must be finite when provided")


class FoldScorer(Protocol):
    """A deterministic fold scorer fitted only on its supplied training data."""

    def predict(
        self,
        train: tuple[TradingMLExample, ...],
        validation: tuple[TradingMLExample, ...],
    ) -> Sequence[FoldPrediction]: ...


@dataclass(frozen=True)
class WalkForwardFold:
    """An expanding, purged training window and its later validation window."""

    fold_index: int
    train: tuple[TradingMLExample, ...]
    validation: tuple[TradingMLExample, ...]
    validation_start: datetime
    embargo_cutoff: datetime


@dataclass(frozen=True)
class EvaluationMetrics:
    """Out-of-sample classification, return, and concentration metrics."""

    sample_size: int
    selected_count: int
    brier_score: float | None
    log_loss: float | None
    balanced_accuracy: float | None
    precision: float | None
    recall: float | None
    calibration_error: float | None
    net_expectancy: float | None
    expected_net_r: float | None
    max_drawdown: float | None
    benchmark_excess: float | None
    asset_concentration: float | None
    regime_concentration: float | None
    asset_selection_concentration: float | None
    regime_selection_concentration: float | None
    per_asset: Mapping[str, float] = field(default_factory=dict)
    per_regime: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "per_asset", MappingProxyType(dict(self.per_asset)))
        object.__setattr__(self, "per_regime", MappingProxyType(dict(self.per_regime)))


@dataclass(frozen=True)
class FoldScoredResult:
    source_uids: tuple[str, ...]
    metrics: EvaluationMetrics


@dataclass(frozen=True)
class FoldEvaluation:
    fold: WalkForwardFold
    candidate: FoldScoredResult
    baseline: FoldScoredResult


@dataclass(frozen=True)
class PurgedWalkForwardResult:
    folds: tuple[FoldEvaluation, ...]
    candidate: EvaluationMetrics
    baseline: EvaluationMetrics
    brier_improvement: float | None


PredictionProvider = (
    FoldScorer
    | Callable[[tuple[TradingMLExample, ...], tuple[TradingMLExample, ...]], Sequence[FoldPrediction]]
    | Mapping[str, FoldPrediction | float]
)


class PurgedWalkForwardEvaluator:
    """Evaluate models with chronological expanding folds, purge, and embargo.

    Rows are never shuffled. A train row is eligible only when its terminal
    outcome is strictly before ``validation_start - embargo``. This is more
    conservative than merely preventing equal timestamps and blocks labels
    whose horizon could overlap the next validation period.
    """

    def __init__(self, *, min_folds: int = 3, embargo_days: int = 0) -> None:
        if min_folds < 1:
            raise ValueError("min_folds must be at least one")
        if embargo_days < 0:
            raise ValueError("embargo_days must be non-negative")
        self.min_folds = min_folds
        self.embargo_days = embargo_days

    def split(self, rows: Iterable[TradingMLExample]) -> tuple[WalkForwardFold, ...]:
        """Create exactly ``min_folds`` expanding, purged chronological folds."""

        ordered = _ordered_rows(rows)
        _validate_examples(ordered)
        decision_timestamps = tuple(sorted({row.decision_timestamp for row in ordered}))
        required_groups = self.min_folds + 1
        if len(decision_timestamps) < required_groups:
            raise InsufficientTrainingEvidenceError(
                f"At least {required_groups} distinct decision timestamps are required for {self.min_folds} folds"
            )

        timestamp_groups = _split_timestamp_groups(decision_timestamps, required_groups)
        folds: list[WalkForwardFold] = []
        for fold_index in range(self.min_folds):
            validation_timestamps = set(timestamp_groups[fold_index + 1])
            validation = tuple(row for row in ordered if row.decision_timestamp in validation_timestamps)
            validation_start = validation[0].decision_timestamp
            embargo_cutoff = validation_start - timedelta(days=self.embargo_days)
            train = tuple(
                row
                for row in ordered
                if row.decision_timestamp < validation_start and row.outcome_timestamp < embargo_cutoff
            )
            if not train:
                raise InsufficientTrainingEvidenceError(
                    "Insufficient chronological history after applying purge and embargo for "
                    f"fold {fold_index + 1}"
                )
            folds.append(
                WalkForwardFold(
                    fold_index=fold_index + 1,
                    train=train,
                    validation=validation,
                    validation_start=validation_start,
                    embargo_cutoff=embargo_cutoff,
                )
            )
        return tuple(folds)

    def evaluate(
        self,
        candidate: PredictionProvider,
        baseline: PredictionProvider,
        rows: Iterable[TradingMLExample],
    ) -> PurgedWalkForwardResult:
        """Score a candidate and baseline on identical purged validation rows."""

        folds = self.split(rows)
        fold_results: list[FoldEvaluation] = []
        candidate_records: list[tuple[TradingMLExample, FoldPrediction]] = []
        baseline_records: list[tuple[TradingMLExample, FoldPrediction]] = []

        for fold in folds:
            candidate_predictions = _aligned_predictions(candidate, fold.train, fold.validation)
            baseline_predictions = _aligned_predictions(baseline, fold.train, fold.validation)
            validation_uids = tuple(example_source_uid(row) for row in fold.validation)
            candidate_metrics = _metrics(zip(fold.validation, candidate_predictions))
            baseline_metrics = _metrics(zip(fold.validation, baseline_predictions))
            fold_results.append(
                FoldEvaluation(
                    fold=fold,
                    candidate=FoldScoredResult(source_uids=validation_uids, metrics=candidate_metrics),
                    baseline=FoldScoredResult(source_uids=validation_uids, metrics=baseline_metrics),
                )
            )
            candidate_records.extend(zip(fold.validation, candidate_predictions))
            baseline_records.extend(zip(fold.validation, baseline_predictions))

        candidate_metrics = _metrics(candidate_records)
        baseline_metrics = _metrics(baseline_records)
        brier_improvement = (
            None
            if candidate_metrics.brier_score is None or baseline_metrics.brier_score is None
            else baseline_metrics.brier_score - candidate_metrics.brier_score
        )
        return PurgedWalkForwardResult(
            folds=tuple(fold_results),
            candidate=candidate_metrics,
            baseline=baseline_metrics,
            brier_improvement=brier_improvement,
        )


def score_frozen_predictions(
    rows: Iterable[TradingMLExample], predictions: Mapping[str, FoldPrediction | float],
) -> EvaluationMetrics:
    """Score a pre-frozen holdout using the canonical alignment and metrics.

    This entry point does not fit, select, or change any prediction. The caller
    owns freezing and withholding the holdout from candidate optimization.
    """
    ordered = _ordered_rows(rows)
    _validate_examples(ordered)
    aligned = _aligned_predictions(predictions, (), ordered)
    return _metrics(zip(ordered, aligned))


def _ordered_rows(rows: Iterable[TradingMLExample]) -> tuple[TradingMLExample, ...]:
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                row.decision_timestamp,
                row.outcome_timestamp,
                row.source_object_type,
                row.source_object_id,
            ),
        )
    )


@dataclass(frozen=True)
class ChronologicalCalibrationSplit:
    train: tuple[TradingMLExample, ...]
    calibration: tuple[TradingMLExample, ...]
    evaluation: tuple[TradingMLExample, ...]
    embargo: timedelta


def chronological_calibration_split(
    rows: Iterable[TradingMLExample],
    *,
    maximum_holding_horizon: timedelta,
) -> ChronologicalCalibrationSplit:
    """Separate fitting, sigmoid calibration and untouched numerical evaluation.

    Both boundaries purge complete outcomes and an embargo covering the larger
    of the configured holding horizon and the longest observed label horizon.
    Simultaneous decisions always stay in one partition.
    """
    from dataclasses import replace
    from app.services.market_clock import utc_naive

    ordered = _ordered_rows(
        tuple(
            replace(
                row,
                decision_timestamp=utc_naive(row.decision_timestamp),
                outcome_timestamp=utc_naive(row.outcome_timestamp),
            )
            for row in rows
        )
    )
    _validate_examples(ordered)
    if maximum_holding_horizon <= timedelta(0):
        raise ValueError("A positive maximum holding horizon is required")
    timestamps = sorted({row.decision_timestamp for row in ordered})
    if len(timestamps) < 10:
        raise InsufficientTrainingEvidenceError(
            "Insufficient chronological calibration history"
        )
    calibration_start = timestamps[int(len(timestamps) * 0.6)]
    evaluation_start = timestamps[int(len(timestamps) * 0.8)]
    embargo = max(
        maximum_holding_horizon,
        max(row.outcome_timestamp - row.decision_timestamp for row in ordered),
    )
    train = tuple(
        row
        for row in ordered
        if row.decision_timestamp < calibration_start
        and row.outcome_timestamp < calibration_start - embargo
    )
    calibration = tuple(
        row
        for row in ordered
        if calibration_start <= row.decision_timestamp < evaluation_start
        and row.outcome_timestamp < evaluation_start - embargo
    )
    evaluation = tuple(
        row for row in ordered if row.decision_timestamp >= evaluation_start
    )
    if len(train) < 40 or len(calibration) < 20 or len(evaluation) < 20:
        raise InsufficientTrainingEvidenceError(
            "Insufficient samples after horizon purge and embargo"
        )
    if any(
        len({row.label_positive_r for row in group}) < 2
        for group in (train, calibration)
    ):
        raise InsufficientTrainingEvidenceError(
            "Fit and calibration each require both outcome classes"
        )
    return ChronologicalCalibrationSplit(train, calibration, evaluation, embargo)


def _validate_examples(rows: tuple[TradingMLExample, ...]) -> None:
    if not rows:
        raise ValueError("At least one labeled trading ML example is required")
    source_uids = [example_source_uid(row) for row in rows]
    if len(source_uids) != len(set(source_uids)):
        raise ValueError("Trading ML examples must have unique source identities")
    for row in rows:
        if row.outcome_timestamp < row.decision_timestamp:
            raise ValueError(f"Outcome precedes decision for {example_source_uid(row)}")
        if row.label_positive_r not in (0, 1):
            raise ValueError(f"label_positive_r must be zero or one for {example_source_uid(row)}")
        if not math.isfinite(row.realized_net_r):
            raise ValueError(f"realized_net_r must be finite for {example_source_uid(row)}")
        if not math.isfinite(row.sample_weight) or row.sample_weight < 0:
            raise ValueError(f"sample_weight must be finite and non-negative for {example_source_uid(row)}")


def _split_timestamp_groups(
    timestamps: tuple[datetime, ...], groups: int
) -> tuple[tuple[datetime, ...], ...]:
    """Partition ordered timestamps without ever splitting simultaneous decisions."""

    base, remainder = divmod(len(timestamps), groups)
    result: list[tuple[datetime, ...]] = []
    offset = 0
    for index in range(groups):
        size = base + (1 if index < remainder else 0)
        result.append(timestamps[offset : offset + size])
        offset += size
    return tuple(result)


def _aligned_predictions(
    provider: PredictionProvider,
    train: tuple[TradingMLExample, ...],
    validation: tuple[TradingMLExample, ...],
) -> tuple[FoldPrediction, ...]:
    expected_uids = tuple(example_source_uid(row) for row in validation)
    expected_set = set(expected_uids)
    raw_predictions: Sequence[FoldPrediction] | Mapping[str, FoldPrediction | float]
    if isinstance(provider, Mapping):
        raw_predictions = provider
    elif hasattr(provider, "predict"):
        raw_predictions = provider.predict(train, validation)  # type: ignore[union-attr]
    elif callable(provider):
        raw_predictions = provider(train, validation)
    else:
        raise TypeError("Prediction provider must be a scorer, callable, or source-keyed mapping")

    if isinstance(raw_predictions, Mapping):
        missing = expected_set - set(raw_predictions)
        if missing:
            raise ValueError("Prediction provider must return exactly one prediction for every validation row")
        predictions = tuple(
            _mapping_prediction(uid, raw_predictions[uid])
            for uid in expected_uids
        )
    else:
        predictions = tuple(raw_predictions)

    prediction_uids = tuple(prediction.source_uid for prediction in predictions)
    if len(prediction_uids) != len(expected_uids) or set(prediction_uids) != expected_set or len(set(prediction_uids)) != len(prediction_uids):
        raise ValueError("Prediction provider must return exactly one prediction for every validation row")
    by_uid = {prediction.source_uid: prediction for prediction in predictions}
    return tuple(by_uid[uid] for uid in expected_uids)


def _mapping_prediction(source_uid: str, value: FoldPrediction | float) -> FoldPrediction:
    if isinstance(value, FoldPrediction):
        if value.source_uid != source_uid:
            raise ValueError("Prediction mapping key must match FoldPrediction.source_uid")
        return value
    if isinstance(value, (float, int)):
        return FoldPrediction(source_uid=source_uid, probability_positive_r=float(value), predicted_net_r=None)
    raise TypeError("Prediction mapping values must be FoldPrediction or probability floats")


def _metrics(records: Iterable[tuple[TradingMLExample, FoldPrediction]]) -> EvaluationMetrics:
    items = tuple(records)
    if not items:
        return EvaluationMetrics(
            sample_size=0,
            selected_count=0,
            brier_score=None,
            log_loss=None,
            balanced_accuracy=None,
            precision=None,
            recall=None,
            calibration_error=None,
            net_expectancy=None,
            expected_net_r=None,
            max_drawdown=None,
            benchmark_excess=None,
            asset_concentration=None,
            regime_concentration=None,
            asset_selection_concentration=None,
            regime_selection_concentration=None,
        )

    weights = tuple(max(0.0, float(row.sample_weight)) for row, _ in items)
    weight_total = sum(weights)
    if weight_total <= 0:
        raise ValueError("At least one validation sample must have a positive sample weight")
    labels = tuple(int(row.label_positive_r) for row, _ in items)
    probabilities = tuple(prediction.probability_positive_r for _, prediction in items)
    brier = _weighted_mean(tuple((probability - label) ** 2 for probability, label in zip(probabilities, labels)), weights)
    log_loss = _weighted_mean(
        tuple(
            -(
                label * math.log(_clip_probability(probability))
                + (1 - label) * math.log(1.0 - _clip_probability(probability))
            )
            for probability, label in zip(probabilities, labels)
        ),
        weights,
    )
    predicted_labels = tuple(1 if probability >= 0.5 else 0 for probability in probabilities)
    balanced_accuracy, precision, recall = _classification_metrics(labels, predicted_labels, weights)
    selected = tuple((row, prediction) for row, prediction in items if prediction.actionable)
    selected_weights = tuple(max(0.0, float(row.sample_weight)) for row, _ in selected)
    selected_weight_total = sum(selected_weights)
    selected_returns = tuple(row.realized_net_r for row, _ in selected)
    expected_returns = tuple(
        (float(prediction.predicted_net_r), weight)
        for (row, prediction), weight in zip(selected, selected_weights)
        if prediction.predicted_net_r is not None and weight > 0
    )
    selected_excess = tuple(row.benchmark_excess for row, _ in selected)
    per_asset = _positive_pnl_concentration(selected, key=lambda row: row.asset_key)
    per_regime = _positive_pnl_concentration(selected, key=lambda row: row.regime)
    selection_per_asset = _selection_concentration(selected, key=lambda row: row.asset_key)
    selection_per_regime = _selection_concentration(selected, key=lambda row: row.regime)
    comparable_excess = tuple(
        (float(excess), weight)
        for excess, weight in zip(selected_excess, selected_weights)
        if excess is not None and weight > 0
    )
    outcome_ordered_returns = tuple(
        row.realized_net_r
        for row, _ in sorted(
            selected,
            key=lambda item: (
                item[0].outcome_timestamp,
                example_source_uid(item[0]),
            ),
        )
    )
    return EvaluationMetrics(
        sample_size=len(items),
        selected_count=len(selected),
        brier_score=brier,
        log_loss=log_loss,
        balanced_accuracy=balanced_accuracy,
        precision=precision,
        recall=recall,
        calibration_error=_expected_calibration_error(labels, probabilities, weights),
        net_expectancy=(
            _weighted_mean(selected_returns, selected_weights) if selected_weight_total > 0 else None
        ),
        expected_net_r=(
            _weighted_mean(
                tuple(value for value, _ in expected_returns),
                tuple(weight for _, weight in expected_returns),
            )
            if expected_returns
            else None
        ),
        max_drawdown=_max_drawdown(outcome_ordered_returns) if outcome_ordered_returns else None,
        benchmark_excess=(
            _weighted_mean(
                tuple(value for value, _ in comparable_excess),
                tuple(weight for _, weight in comparable_excess),
            )
            if comparable_excess
            else None
        ),
        asset_concentration=max(per_asset.values()) if per_asset else None,
        regime_concentration=max(per_regime.values()) if per_regime else None,
        asset_selection_concentration=max(selection_per_asset.values()) if selection_per_asset else None,
        regime_selection_concentration=max(selection_per_regime.values()) if selection_per_regime else None,
        per_asset=per_asset,
        per_regime=per_regime,
    )


def _classification_metrics(
    labels: tuple[int, ...],
    predictions: tuple[int, ...],
    weights: tuple[float, ...],
) -> tuple[float | None, float | None, float | None]:
    true_positive = sum(weight for label, prediction, weight in zip(labels, predictions, weights) if label == 1 and prediction == 1)
    true_negative = sum(weight for label, prediction, weight in zip(labels, predictions, weights) if label == 0 and prediction == 0)
    false_positive = sum(weight for label, prediction, weight in zip(labels, predictions, weights) if label == 0 and prediction == 1)
    false_negative = sum(weight for label, prediction, weight in zip(labels, predictions, weights) if label == 1 and prediction == 0)
    positive_total = true_positive + false_negative
    negative_total = true_negative + false_positive
    recall = true_positive / positive_total if positive_total > 0 else None
    specificity = true_negative / negative_total if negative_total > 0 else None
    balanced_accuracy = (
        (recall + specificity) / 2.0
        if recall is not None and specificity is not None
        else None
    )
    precision_denominator = true_positive + false_positive
    precision = true_positive / precision_denominator if precision_denominator > 0 else None
    return balanced_accuracy, precision, recall


def _expected_calibration_error(
    labels: tuple[int, ...], probabilities: tuple[float, ...], weights: tuple[float, ...]
) -> float:
    bins: dict[int, list[tuple[int, float, float]]] = defaultdict(list)
    for label, probability, weight in zip(labels, probabilities, weights):
        bins[min(9, int(probability * 10))].append((label, probability, weight))
    total_weight = sum(weights)
    return sum(
        (bin_weight / total_weight)
        * abs(
            _weighted_mean(tuple(probability for _, probability, _ in values), tuple(weight for _, _, weight in values))
            - _weighted_mean(tuple(float(label) for label, _, _ in values), tuple(weight for _, _, weight in values))
        )
        for values in bins.values()
        if (bin_weight := sum(weight for _, _, weight in values)) > 0
    )


def _positive_pnl_concentration(
    selected: tuple[tuple[TradingMLExample, FoldPrediction], ...],
    *,
    key: Callable[[TradingMLExample], str],
) -> dict[str, float]:
    contributions: dict[str, float] = defaultdict(float)
    for row, _ in selected:
        contributions[key(row)] += max(0.0, row.realized_net_r * row.sample_weight)
    total = sum(contributions.values())
    if total <= 0:
        return {}
    return {name: contribution / total for name, contribution in sorted(contributions.items())}


def _selection_concentration(
    selected: tuple[tuple[TradingMLExample, FoldPrediction], ...],
    *,
    key: Callable[[TradingMLExample], str],
) -> dict[str, float]:
    if not selected:
        return {}
    counts = Counter(key(row) for row, _ in selected)
    total = len(selected)
    return {name: count / total for name, count in sorted(counts.items())}


def _max_drawdown(returns: tuple[float, ...]) -> float:
    equity = 0.0
    high_water_mark = 0.0
    max_drawdown = 0.0
    for realized_net_r in returns:
        equity += realized_net_r
        high_water_mark = max(high_water_mark, equity)
        max_drawdown = min(max_drawdown, equity - high_water_mark)
    return max_drawdown


def _weighted_mean(values: tuple[float, ...], weights: tuple[float, ...]) -> float:
    total_weight = sum(weights)
    if total_weight <= 0:
        raise ValueError("Weighted metrics require positive total sample weight")
    return sum(value * weight for value, weight in zip(values, weights)) / total_weight


def _clip_probability(probability: float) -> float:
    return min(1.0 - _EPSILON, max(_EPSILON, probability))
