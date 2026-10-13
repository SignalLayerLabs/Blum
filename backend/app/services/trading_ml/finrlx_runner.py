"""Subprocess runner for the pinned FinRL-X weight-centric strategy contract.

The runner deliberately owns optional upstream and ML imports. The API process
never imports FinRL-X, and artifacts are JSON rather than pickle so validation
can happen before any model state is interpreted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, Mapping
from uuid import uuid4

import numpy as np
import pandas as pd
import polars as pl
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import accuracy_score
from sklearn.preprocessing import StandardScaler

from app.services.trading_ml.contracts import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
)
from app.services.trading_ml.finrlx import (
    FINRLX_UPSTREAM_REPOSITORY,
    FINRLX_UPSTREAM_REVISION,
)
from app.services.trading_ml.forex_history import FOREX_HISTORY_TRANSFORM_VERSION
from app.services.trading_ml.feature_store import quality_adjusted_hash


class FinRLXRunnerError(RuntimeError):
    """Structured runner failure returned to the BLUM subprocess boundary."""


@dataclass(frozen=True)
class UpstreamContract:
    base_strategy: type
    strategy_config: type
    strategy_result: type
    source: str


def run_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    operation = str(payload.get("operation") or "").lower()
    if operation == "train":
        return _train(payload)
    if operation == "propose":
        return _propose(payload)
    raise FinRLXRunnerError(f"unsupported operation: {operation or 'missing'}")


def _train(payload: Mapping[str, Any]) -> dict[str, Any]:
    market_family = _market_family(payload)
    request = _mapping(payload.get("request"))
    constraints = _mapping(payload.get("constraints"))
    if request.get("paper_only") is False or constraints.get("paper_only") is not True:
        raise FinRLXRunnerError("paper_only=true is required")
    if constraints.get("upstream_revision") != FINRLX_UPSTREAM_REVISION:
        raise FinRLXRunnerError("upstream revision is not the pinned BLUM revision")
    feature_schema_hash = str(constraints.get("feature_schema_hash") or "")
    if not feature_schema_hash:
        raise FinRLXRunnerError("feature schema hash is required")

    contract = _load_upstream_contract()
    feature_store_root = Path(str(request.get("feature_store_root") or "")).expanduser().resolve()
    artifact_root = Path(str(request.get("artifact_root") or "")).expanduser().resolve()
    max_rows = max(1, min(int(request.get("max_rows") or 500), 20_000))
    minimum_samples = max(32, int(request.get("minimum_samples") or 64))
    rows = _load_feature_rows(feature_store_root, market_family, max_rows=max_rows)
    dataset_hash = _market_dataset_hash(feature_store_root, market_family)
    if len(rows) < minimum_samples:
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "sample_count": len(rows),
            "minimum_samples": minimum_samples,
            "reason": "Not enough chronological point-in-time outcomes for FinRL-X training.",
            "paper_only": True,
        }

    x = np.asarray([_feature_vector(row) for row in rows], dtype=np.float64)
    y_class = np.asarray([int(row["label_positive_r"]) for row in rows], dtype=np.int64)
    y_return = np.asarray([float(row["realized_net_r"]) for row in rows], dtype=np.float64)
    sample_weight = np.asarray(
        [max(0.01, float(row.get("sample_weight") or 1.0)) for row in rows],
        dtype=np.float64,
    )
    if len(np.unique(y_class)) < 2:
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "sample_count": len(rows),
            "minimum_samples": minimum_samples,
            "reason": "Both positive and negative outcomes are required.",
            "paper_only": True,
        }

    split = min(len(rows) - 1, max(1, int(len(rows) * 0.8)))
    validation = _fit_and_validate(
        x[:split],
        y_class[:split],
        y_return[:split],
        sample_weight[:split],
        x[split:],
        y_class[split:],
        y_return[split:],
    )
    scaler, classifier, regressor = _fit_policy(x, y_class, y_return, sample_weight)
    artifact = {
        "format": "blum_finrlx_safe_linear_policy_v1",
        "upstream_repository": FINRLX_UPSTREAM_REPOSITORY,
        "upstream_revision": FINRLX_UPSTREAM_REVISION,
        "upstream_contract": "BaseStrategy.generate_weights -> StrategyResult",
        "upstream_contract_source": contract.source,
        "market_family": market_family,
        "feature_names": [*NUMERIC_FEATURES, *CATEGORICAL_FEATURES],
        "numeric_features": list(NUMERIC_FEATURES),
        "categorical_features": list(CATEGORICAL_FEATURES),
        "scaler_mean": scaler.mean_.tolist(),
        "scaler_scale": scaler.scale_.tolist(),
        "classifier_coef": classifier.coef_[0].tolist(),
        "classifier_intercept": float(classifier.intercept_[0]),
        "regressor_coef": regressor.coef_.tolist(),
        "regressor_intercept": float(regressor.intercept_),
        "validation": validation,
        "sample_count": len(rows),
        "dataset_hash": dataset_hash,
        "trained_at": datetime.now(UTC).isoformat(),
        "paper_only": True,
    }
    market_root = artifact_root / market_family
    market_root.mkdir(parents=True, exist_ok=True)
    artifact_path = market_root / "policy.json"
    _atomic_json_write(artifact_path, artifact)
    digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    manifest = {
        "provider": "finrlx",
        "upstream_repository": FINRLX_UPSTREAM_REPOSITORY,
        "upstream_revision": FINRLX_UPSTREAM_REVISION,
        "algorithm": "DETERMINISTIC",
        "market_family": market_family,
        "feature_schema_hash": feature_schema_hash,
        "action_schema": (
            "directional_score_v1"
            if market_family == "forex"
            else "target_weights_v1"
        ),
        "artifact_path": artifact_path.name,
        "artifact_sha256": digest,
        "sample_count": len(rows),
        "dataset_hash": dataset_hash,
        "paper_only": True,
        "validation": validation,
        "upstream_contract_source": contract.source,
    }
    manifest_path = market_root / "manifest.json"
    _atomic_json_write(manifest_path, manifest)
    return {
        "status": "TRAINED",
        "manifest_path": str(manifest_path),
        "sample_count": len(rows),
        "validation": validation,
        "paper_only": True,
    }


def _propose(payload: Mapping[str, Any]) -> dict[str, Any]:
    market_family = _market_family(payload)
    manifest = _mapping(payload.get("manifest"))
    manifest_path = Path(str(payload.get("manifest_path") or "")).expanduser().resolve()
    if not manifest_path.is_file():
        raise FinRLXRunnerError("validated manifest path is unavailable")
    artifact_path = (manifest_path.parent / str(manifest.get("artifact_path") or "")).resolve()
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    if artifact.get("paper_only") is not True:
        raise FinRLXRunnerError("artifact is not paper-only")
    vector = np.asarray(_feature_vector(_mapping(payload.get("features"))), dtype=np.float64)
    mean = np.asarray(artifact["scaler_mean"], dtype=np.float64)
    scale = np.asarray(artifact["scaler_scale"], dtype=np.float64)
    normalized = (vector - mean) / np.where(scale == 0, 1.0, scale)
    logit = float(np.dot(normalized, artifact["classifier_coef"]) + artifact["classifier_intercept"])
    probability = _sigmoid(logit)
    predicted_r = float(np.dot(normalized, artifact["regressor_coef"]) + artifact["regressor_intercept"])
    directional_score = float(
        np.clip(0.65 * ((probability - 0.5) * 2.0) + 0.35 * math.tanh(predicted_r), -1.0, 1.0)
    )
    confidence = max(probability, 1.0 - probability)
    response: dict[str, Any] = {
        "directional_score": round(directional_score, 6),
        "confidence": round(confidence, 6),
        "uncertainty": round(1.0 - confidence, 6),
        "reason": (
            f"FinRL-X weight-contract challenger; chronological validation "
            f"n={artifact['validation']['holdout_count']}."
        ),
        "validation": dict(artifact.get("validation") or {}),
    }
    if market_family == "equity":
        ticker = str(
            _mapping(payload.get("context")).get("ticker")
            or _mapping(payload.get("context")).get("asset")
            or ""
        ).upper()
        response["target_weights"] = _upstream_target_weights(
            {ticker: directional_score} if ticker else {},
            target_date=str(_mapping(payload.get("context")).get("timestamp") or ""),
        )
    return response


def _load_feature_rows(root: Path, market_family: str, *, max_rows: int) -> list[dict[str, Any]]:
    paths = _select_feature_paths(root, market_family, max_rows=max_rows)
    if not paths:
        return []
    required_columns = list(
        dict.fromkeys(
            [
                "source_uid",
                "market_family",
                "decision_timestamp",
                "outcome_timestamp",
                "realized_net_r",
                "label_positive_r",
                "sample_weight",
                *NUMERIC_FEATURES,
                *CATEGORICAL_FEATURES,
            ]
        )
    )
    frame = (
        pl.scan_parquet([str(path) for path in paths], hive_partitioning=False)
        .filter(pl.col("market_family") == market_family)
        .filter((pl.col("source_object_type") != "external_forex_history")
                | pl.col("source_object_id").str.contains(FOREX_HISTORY_TRANSFORM_VERSION, literal=True))
        .select(required_columns)
        .sort(["decision_timestamp", "outcome_timestamp", "source_uid"])
        .tail(max_rows)
        .collect()
    )
    return frame.to_dicts()


def _select_feature_paths(
    root: Path,
    market_family: str,
    *,
    max_rows: int,
) -> list[Path]:
    """Select the newest immutable parts needed for one bounded sample.

    The feature-store manifest is append-only and records the row count for
    every part. Reading it avoids globbing and hydrating the complete history
    when the runner only needs the latest bounded training window.
    """

    resolved_root = root.expanduser().resolve()
    manifest_path = resolved_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        partitions = manifest.get("partitions")
        if not isinstance(partitions, list):
            raise ValueError("partitions must be a list")
    except (OSError, json.JSONDecodeError, ValueError):
        directory = resolved_root / "features" / f"market_family={market_family}"
        return sorted(directory.glob("**/*.parquet")) if directory.is_dir() else []

    selected: list[Path] = []
    selected_rows = 0
    for partition in reversed(partitions):
        if not isinstance(partition, dict):
            continue
        if str(partition.get("market_family") or "").lower() != market_family:
            continue
        candidate = (resolved_root / str(partition.get("path") or "")).resolve()
        if not candidate.is_relative_to(resolved_root) or not candidate.is_file():
            continue
        try:
            partition_rows = max(1, int(partition.get("rows") or 1))
        except (TypeError, ValueError):
            partition_rows = 1
        selected.append(candidate)
        selected_rows += partition_rows
        if selected_rows >= max_rows:
            break
    selected.reverse()
    return selected


def _market_dataset_hash(root: Path, market_family: str) -> str:
    manifest_path = root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        partitions = [
            {
                "content_hash": partition["content_hash"],
                "market_family": partition["market_family"],
                "path": partition["path"],
                "rows": partition["rows"],
            }
            for partition in manifest.get("partitions", [])
            if isinstance(partition, dict)
            and partition.get("market_family") == market_family
        ]
        if partitions:
            payload = json.dumps(
                partitions,
                sort_keys=True,
                separators=(",", ":"),
            )
            return quality_adjusted_hash(hashlib.sha256(payload.encode("utf-8")).hexdigest(), market_family, manifest)
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        pass
    digest = hashlib.sha256()
    for path in _select_feature_paths(root, market_family, max_rows=20_000):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _fit_policy(
    x: np.ndarray,
    y_class: np.ndarray,
    y_return: np.ndarray,
    sample_weight: np.ndarray,
) -> tuple[StandardScaler, LogisticRegression, Ridge]:
    scaler = StandardScaler().fit(x)
    normalized = scaler.transform(x)
    classifier = LogisticRegression(
        class_weight="balanced",
        max_iter=400,
        random_state=41,
        solver="liblinear",
    ).fit(normalized, y_class, sample_weight=sample_weight)
    regressor = Ridge(alpha=2.0).fit(normalized, y_return, sample_weight=sample_weight)
    return scaler, classifier, regressor


def _fit_and_validate(
    x_train: np.ndarray,
    y_train: np.ndarray,
    return_train: np.ndarray,
    weight_train: np.ndarray,
    x_test: np.ndarray,
    y_test: np.ndarray,
    return_test: np.ndarray,
) -> dict[str, Any]:
    scaler, classifier, regressor = _fit_policy(
        x_train,
        y_train,
        return_train,
        weight_train,
    )
    normalized = scaler.transform(x_test)
    probability = classifier.predict_proba(normalized)[:, 1]
    predicted_return = regressor.predict(normalized)
    score = 0.65 * ((probability - 0.5) * 2.0) + 0.35 * np.tanh(predicted_return)
    action = np.where(score > 0.05, 1.0, np.where(score < -0.05, -1.0, 0.0))
    policy_reward = action * return_test
    regression_mae = float(np.mean(np.abs(predicted_return - return_test)))
    baseline_mae = float(np.mean(np.abs(return_test - np.mean(return_train))))
    return {
        "holdout_count": int(len(x_test)),
        "directional_accuracy": round(float(accuracy_score(y_test, probability >= 0.5)), 6),
        "mean_policy_net_r": round(float(np.mean(policy_reward)), 6),
        "mean_observed_net_r": round(float(np.mean(return_test)), 6),
        "participation_rate": round(float(np.mean(action != 0)), 6),
        "regression_mae": round(regression_mae, 6),
        "baseline_regression_mae": round(baseline_mae, 6),
        "regression_improvement": round(baseline_mae - regression_mae, 6),
        "chronological_split": True,
    }


def _feature_vector(row: Mapping[str, Any]) -> list[float]:
    values = [_finite(row.get(name)) for name in NUMERIC_FEATURES]
    values.extend(_stable_category(row.get(name)) for name in CATEGORICAL_FEATURES)
    return values


def _stable_category(value: Any) -> float:
    digest = hashlib.sha256(str(value or "missing").encode("utf-8")).digest()
    integer = int.from_bytes(digest[:4], "big")
    return (integer / 0xFFFFFFFF) * 2.0 - 1.0


def _finite(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _load_upstream_contract() -> UpstreamContract:
    source = os.getenv("FINRLX_UPSTREAM_SOURCE", "").strip()
    if source:
        resolved = str(Path(source).expanduser().resolve())
        if resolved not in sys.path:
            sys.path.insert(0, resolved)
    try:
        from strategies.base_strategy import BaseStrategy, StrategyConfig, StrategyResult
    except ImportError as exc:
        raise FinRLXRunnerError("pinned FinRL-X BaseStrategy contract is unavailable") from exc
    if not callable(getattr(BaseStrategy, "generate_weights", None)):
        raise FinRLXRunnerError("FinRL-X BaseStrategy contract is incompatible")
    return UpstreamContract(
        base_strategy=BaseStrategy,
        strategy_config=StrategyConfig,
        strategy_result=StrategyResult,
        source=str(Path(sys.modules[BaseStrategy.__module__].__file__).resolve()),
    )


def _upstream_target_weights(scores: Mapping[str, float], *, target_date: str) -> dict[str, float]:
    contract = _load_upstream_contract()

    class BlumFinRLXWeightStrategy(contract.base_strategy):
        def generate_weights(self, data, target_date=None):
            raw_scores = {
                str(ticker): float(score)
                for ticker, score in _mapping(data.get("scores")).items()
                if str(ticker)
            }
            gross = sum(abs(score) for score in raw_scores.values())
            weights = (
                {ticker: score / gross for ticker, score in raw_scores.items()}
                if gross > 1.0
                else raw_scores
            )
            frame = pd.DataFrame([weights], index=[target_date or "latest"])
            return contract.strategy_result(
                strategy_name="BLUM FinRL-X Challenger",
                weights=frame,
                metadata={"paper_only": True},
            )

    strategy = BlumFinRLXWeightStrategy(
        contract.strategy_config(name="BLUM FinRL-X Challenger")
    )
    result = strategy.generate_weights({"scores": dict(scores)}, target_date=target_date)
    if result.weights.empty:
        return {}
    return {
        str(ticker): round(float(weight), 6)
        for ticker, weight in result.weights.iloc[-1].to_dict().items()
    }


def _market_family(payload: Mapping[str, Any]) -> str:
    market_family = str(payload.get("market_family") or "").lower()
    if market_family not in {"equity", "forex"}:
        raise FinRLXRunnerError("market_family must be equity or forex")
    return market_family


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exponent = math.exp(value)
    return exponent / (1.0 + exponent)


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise FinRLXRunnerError("request must be a JSON object")
        response = run_request(request)
    except Exception as exc:
        response = {
            "status": "FAILED",
            "reason": f"{type(exc).__name__}: {exc}",
            "paper_only": True,
        }
    json.dump(response, sys.stdout, sort_keys=True)


if __name__ == "__main__":
    main()
