"""Immutable contracts shared by trading ML training and inference."""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from types import MappingProxyType
from typing import Literal, Mapping


class InsufficientTrainingEvidenceError(ValueError):
    """Raised when valid labels cannot form leakage-safe validation folds."""


@dataclass(frozen=True)
class TradingMLExample:
    source_object_type: str
    source_object_id: str
    market_family: Literal["equity", "forex"]
    evidence_lane: str
    decision_timestamp: datetime
    outcome_timestamp: datetime
    asset_key: str
    setup_type: str
    regime: str
    features: Mapping[str, float | str | None]
    realized_net_r: float
    label_positive_r: int
    benchmark_excess: float | None
    sample_weight: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "features", MappingProxyType(dict(self.features)))


@dataclass(frozen=True)
class TradingMLAdvice:
    status: str
    model_uid: str | None
    probability_positive_r: float | None
    predicted_net_r: float | None
    uncertainty: float | None
    confidence_adjustment: float
    veto_recommended: bool
    explanation: tuple[str, ...]
    guardrails: tuple[str, ...]


@dataclass(frozen=True)
class FeatureSchema:
    version: str
    feature_names: tuple[str, ...]
    source_schema_hash: str | None = None

    @property
    def hash(self) -> str:
        identity = {"feature_names": self.feature_names, "version": self.version}
        if self.source_schema_hash is not None:
            identity["source_schema_hash"] = self.source_schema_hash
        payload = json.dumps(
            identity,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def current(cls) -> "FeatureSchema":
        return cls(version="trading-ml-features-v1", feature_names=FEATURE_NAMES)

    @classmethod
    def information(cls) -> "FeatureSchema":
        from app.services.information.context import FEATURE_SCHEMA_HASH, FEATURE_UNITS

        return cls(
            "trading-ml-information-v2",
            FEATURE_NAMES + ("strategy_fingerprint",) + tuple(FEATURE_UNITS),
            FEATURE_SCHEMA_HASH,
        )


NUMERIC_FEATURES = (
    "aggregate_score",
    "confidence",
    "trend_score",
    "momentum_score",
    "volume_score",
    "volatility_score",
    "support_resistance_score",
    "sentiment_score",
    "narrative_score",
    "fundamental_score",
    "regime_score",
    "expected_gross_r",
    "expected_net_r",
    "expected_cost",
    "stop_distance",
    "target_distance",
    "data_quality_score",
    "liquidity_score",
    "spread",
    "slippage",
    "volatility",
    "recent_return",
    "multi_timeframe_trend",
    "contextual_bandit_adjustment",
    "contextual_bandit_sample_size",
)

CATEGORICAL_FEATURES = (
    "market_family",
    "setup_type",
    "regime",
    "session",
    "direction",
    "timeframe",
    "sector_or_currency_family",
)

FEATURE_NAMES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
