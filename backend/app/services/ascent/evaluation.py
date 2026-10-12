"""Trusted forecasting experiment policy; candidates cannot alter this module."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
import math
import hashlib
import json
from statistics import mean, stdev

from scipy.stats import t

from app.services.trading_ml.contracts import TradingMLExample
from app.services.trading_ml.validation import (
    EvaluationMetrics, FoldPrediction, example_source_uid, score_frozen_predictions,
)
from .kernel import ArithmeticKernel


POLICY_VERSION = "ascent-calibration-policy-v1"
LANES = ("REPLAY_EVIDENCE", "PAPER_FORWARD_FOREX")
MIN_ROWS = 400
MIN_HOLDOUT = 100
EMBARGO_DAYS = 2


@dataclass(frozen=True)
class FrozenSplit:
    development: tuple[TradingMLExample, ...]
    holdout: tuple[TradingMLExample, ...]
    purged_count: int


def utc_naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def probability(row: TradingMLExample) -> float:
    value = row.features.get("confidence")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError("MISSING_OR_INVALID_FROZEN_CONFIDENCE")
    return float(value) / 100.0


def decision_identity(row: TradingMLExample) -> str:
    """Stable economic identity independent of regenerated ledger IDs or labels."""
    key = (row.market_family, row.evidence_lane, row.asset_key, row.setup_type,
           utc_naive(row.decision_timestamp).isoformat())
    return hashlib.sha256(json.dumps(key, separators=(",", ":")).encode()).hexdigest()


def freeze_split(rows: tuple[TradingMLExample, ...], *, as_of: datetime) -> FrozenSplit:
    if len(rows) < MIN_ROWS or len(rows) > 2000:
        raise ValueError("INSUFFICIENT_OR_EXCESSIVE_SAMPLE")
    if len({example_source_uid(row) for row in rows}) != len(rows):
        raise ValueError("DUPLICATE_SOURCE")
    if len({decision_identity(row) for row in rows}) != len(rows):
        raise ValueError("DUPLICATE_ECONOMIC_DECISION")
    if len({row.evidence_lane for row in rows}) != 1 or rows[0].evidence_lane not in LANES:
        raise ValueError("MIXED_OR_UNSUPPORTED_EVIDENCE")
    if len({row.market_family for row in rows}) != 1:
        raise ValueError("MIXED_MARKETS")
    for row in rows:
        probability(row)
        if not utc_naive(row.decision_timestamp) < utc_naive(row.outcome_timestamp) <= utc_naive(as_of):
            raise ValueError("IMMATURE_OR_INVALID_CHRONOLOGY")
        quality, cost = row.features.get("data_quality_score"), row.features.get("expected_cost")
        if (not isinstance(quality, (int, float)) or not math.isfinite(quality) or quality < 70 or
                not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0):
            raise ValueError("INSUFFICIENT_QUALITY_OR_COST_PROVENANCE")
        if (not math.isfinite(row.realized_net_r) or row.label_positive_r not in (0, 1) or
                row.label_positive_r != int(row.realized_net_r > 0) or
                not math.isfinite(row.sample_weight) or row.sample_weight <= 0):
            raise ValueError("INVALID_LABEL_OR_WEIGHT")
        if not row.asset_key or not row.regime or row.regime.lower() in ("unknown", "none"):
            raise ValueError("MISSING_ASSET_OR_REGIME")
    ordered = tuple(sorted(rows, key=lambda row: (utc_naive(row.decision_timestamp), example_source_uid(row))))
    timestamps = sorted({utc_naive(row.decision_timestamp) for row in ordered})
    boundary = timestamps[int(len(timestamps) * 0.75)]
    holdout = tuple(row for row in ordered if utc_naive(row.decision_timestamp) >= boundary)
    development = tuple(row for row in ordered if utc_naive(row.outcome_timestamp) < boundary - timedelta(days=EMBARGO_DAYS))
    if len(holdout) < MIN_HOLDOUT or len(development) < 200:
        raise ValueError("INSUFFICIENT_PURGED_SAMPLE")
    return FrozenSplit(development, holdout, len(rows) - len(development) - len(holdout))


def predictions(source: str, rows: tuple[TradingMLExample, ...]) -> dict[str, FoldPrediction]:
    kernel = ArithmeticKernel(source)
    return {example_source_uid(row): FoldPrediction(example_source_uid(row),
            kernel.predict(probability(row)), None, actionable=True) for row in rows}


def metrics_json(metrics: EvaluationMetrics) -> dict:
    return {field.name: dict(value) if field.name.startswith("per_") else value
            for field in fields(metrics) for value in [getattr(metrics, field.name)]}


def _uncertainty(rows, candidate, champion, *, trial_number: int) -> dict:
    """Paired horizon-aware blocks; purge labels crossing each boundary.

    The interval is conditional on block independence, not an alpha proof.
    Alpha spending sums to .05 across unbounded sequential generations and
    Bonferroni accounts for the four candidate hypotheses per generation.
    """
    alpha = 0.05 / ((trial_number + 1) * (trial_number + 2) * 4)
    blocks: dict[int, list[float]] = defaultdict(list)
    anchor = min(utc_naive(row.decision_timestamp) for row in rows)
    block_days = max(7, 1 + math.ceil(max((utc_naive(row.outcome_timestamp) -
        utc_naive(row.decision_timestamp)).total_seconds() / 86400 for row in rows)))
    purged = 0
    for row in rows:
        block = (utc_naive(row.decision_timestamp) - anchor).days // block_days
        end = anchor + timedelta(days=block_days * (block + 1))
        if utc_naive(row.outcome_timestamp) >= end:
            purged += 1
            continue
        uid = example_source_uid(row)
        y = row.label_positive_r
        blocks[block].append((champion[uid].probability_positive_r - y) ** 2 -
                            (candidate[uid].probability_positive_r - y) ** 2)
    values = [mean(block) for block in blocks.values()]
    estimate = mean(values) if values else None
    lower = None
    if len(values) >= 20:
        lower = estimate - float(t.ppf(1 - alpha, len(values) - 1)) * stdev(values) / math.sqrt(len(values))
    return {"method": "paired_horizon_block_t_interval", "blocks": len(values), "block_days": block_days, "alpha": alpha,
            "mean_brier_gain": estimate, "gain_lower_bound": lower,
            "boundary_rows_purged": purged, "multiple_testing": "sequential_alpha_spending_and_bonferroni_4",
            "assumption": "Independent horizon-aware blocks; residual dependence may invalidate inference."}


def validate_candidate(rows: tuple[TradingMLExample, ...], *, source: str,
                       champion_source: str, prior: float, trial_number: int) -> dict:
    candidate = predictions(source, rows)
    champion = predictions(champion_source, rows)
    # A new interpreter re-evaluates the frozen source; no candidate-reported metrics are accepted.
    independent = candidate == predictions(source, rows)
    candidate_metrics = score_frozen_predictions(rows, candidate)
    champion_metrics = score_frozen_predictions(rows, champion)
    climatology = score_frozen_predictions(rows, {example_source_uid(row): prior for row in rows})
    uncertainty = _uncertainty(rows, candidate, champion, trial_number=trial_number)
    blockers = []
    if len(rows) < MIN_HOLDOUT:
        blockers.append("INSUFFICIENT_HOLDOUT_SAMPLE")
    if len({row.asset_key for row in rows}) < 3:
        blockers.append("INSUFFICIENT_ASSET_COVERAGE")
    if len({row.regime for row in rows}) < 2:
        blockers.append("INSUFFICIENT_REGIME_COVERAGE")
    if not independent:
        blockers.append("INDEPENDENT_RECHECK_FAILED")
    lower = uncertainty["gain_lower_bound"]
    if lower is None or lower <= 0 or candidate_metrics.brier_score >= champion_metrics.brier_score:
        blockers.append("NO_CONFIRMED_CALIBRATION_GAIN")
    if candidate_metrics.log_loss > champion_metrics.log_loss + 1e-12:
        blockers.append("LOG_LOSS_REGRESSION")
    if candidate_metrics.calibration_error > champion_metrics.calibration_error + 1e-12:
        blockers.append("CALIBRATION_ERROR_REGRESSION")
    if candidate_metrics.brier_score > climatology.brier_score + 1e-12:
        blockers.append("WORSE_THAN_TRAINING_CLIMATOLOGY")
    slices = []
    for dimension in ("asset_key", "regime"):
        for key, count in Counter(getattr(row, dimension) for row in rows).items():
            group = tuple(row for row in rows if getattr(row, dimension) == key)
            gain = mean((champion[example_source_uid(row)].probability_positive_r - row.label_positive_r) ** 2 -
                        (candidate[example_source_uid(row)].probability_positive_r - row.label_positive_r) ** 2 for row in group)
            slices.append({"dimension": dimension, "key": key, "sample_size": count, "brier_gain": gain})
            if count < 20:
                blockers.append("INSUFFICIENT_SLICE_SAMPLE")
            elif gain < -0.01:
                blockers.append("ROBUSTNESS_REGRESSION")
    return {"candidate": metrics_json(candidate_metrics), "champion": metrics_json(champion_metrics),
            "climatology": metrics_json(climatology), "uncertainty": uncertainty, "slices": slices,
            "blockers": sorted(set(blockers)), "research_eligible": not blockers,
            "production_eligible": False, "independent_recheck": independent,
            "financial_effect": "UNCHANGED_DECISIONS", "policy_version": POLICY_VERSION,
            "warnings": ["Confidence is a baseline proxy for positive net R, not a verified input probability.",
                         "Stored net R and drawdown are trade statistics, not portfolio returns.",
                         "Calibration evidence does not establish trading alpha or model-weight improvement."]}
