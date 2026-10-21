"""Exactly-once, per-market shadow updates with causal pre-update measurements."""

from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
from itertools import groupby
import json
import math
import pickle
import sqlite3

import numpy as np
import sklearn
from sklearn.feature_extraction import FeatureHasher
from sklearn.linear_model import SGDClassifier, SGDRegressor
from sklearn.preprocessing import normalize

from .contracts import CATEGORICAL_FEATURES, FeatureSchema, NUMERIC_FEATURES
from .training import TradingModelBundle, TrainingResult, _feature_frame
from .validation import example_source_uid

ALGORITHM = "sgd_persistent_shadow_v2"
STATE_VERSION = "online-shadow-v2"


def _utc(value):
    return (
        value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    )


class OnlineFeatureEncoder:
    """Fixed coordinates; new categories and missing values need no refitting."""

    def __init__(self, schema=None):
        self.feature_names = (schema or FeatureSchema.current()).feature_names

    def transform(self, frame):
        # Old persisted encoders have no feature_names attribute. Their fixed
        # v1 coordinates stay identical when a new schema is introduced.
        names = getattr(self, "feature_names", FeatureSchema.current().feature_names)
        categorical = (*CATEGORICAL_FEATURES, "strategy_fingerprint")
        records = []
        for row in (
            frame.to_dicts()
            if hasattr(frame, "to_dicts")
            else frame.to_dict(orient="records")
        ):
            record = {}
            for name in (item for item in names if item not in categorical):
                value = row.get(name)
                if value is None or isinstance(value, float) and math.isnan(value):
                    record["missing:" + name] = 1.0
                else:
                    value = float(value)
                    record["numeric:" + name] = math.copysign(
                        math.log1p(abs(value)), value
                    )
            for name in (item for item in names if item in categorical):
                record[
                    "category:"
                    + name
                    + "="
                    + str(row.get(name) if row.get(name) is not None else "<MISSING>")
                ] = 1.0
            records.append(record)
        return normalize(
            FeatureHasher(
                n_features=4096, input_type="dict", alternate_sign=False
            ).transform(records)
        )


def _fingerprint(row):
    content = {
        "uid": example_source_uid(row),
        "decision": _utc(row.decision_timestamp).isoformat(),
        "outcome": _utc(row.outcome_timestamp).isoformat(),
        "features": dict(row.features),
        "label": row.label_positive_r,
        "net_r": row.realized_net_r,
        "weight": row.sample_weight,
        "lane": row.evidence_lane,
        "asset": row.asset_key,
        "benchmark": row.benchmark_excess,
    }
    return sha256(
        json.dumps(
            content, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _fresh_state(seed, schema):
    return TradingModelBundle(
        schema_hash=schema.hash,
        feature_names=schema.feature_names,
        preprocessor=OnlineFeatureEncoder(schema),
        classifier=SGDClassifier(
            loss="log_loss",
            random_state=seed,
            shuffle=False,
            learning_rate="constant",
            eta0=0.03,
            average=True,
        ),
        regressor=SGDRegressor(
            loss="huber",
            random_state=seed,
            shuffle=False,
            learning_rate="constant",
            eta0=0.01,
            average=True,
        ),
        algorithm=ALGORITHM,
    ), {
        "count": 0,
        "weight": 0.0,
        "positive_weight": 0.0,
        "net_r_weight": 0.0,
        "prequential_count": 0,
        "brier_sum": 0.0,
        "baseline_brier_sum": 0.0,
        "absolute_r_error_sum": 0.0,
        "baseline_absolute_r_error_sum": 0.0,
        "overlap_excluded": 0,
        "last_outcome": None,
        "dataset_hash": sha256(b"").hexdigest(),
        "assets": [],
        "regimes": [],
        "setups": [],
        "lane_counts": {},
    }


def update_shadow(root, rows, *, seed, as_of=None, market_family=None, schema=None):
    schema = schema or FeatureSchema.current()
    numeric = tuple(
        name
        for name in schema.feature_names
        if name not in (*CATEGORICAL_FEATURES, "strategy_fingerprint")
    )
    now = _utc(as_of or datetime.now(timezone.utc))
    families = {row.market_family for row in rows} or {market_family}
    if len(families) != 1 or not families.issubset({"equity", "forex"}):
        raise ValueError("Online update requires one valid market family")
    family = next(iter(families))
    for row in rows:
        if schema.hash == FeatureSchema.information().hash and (
            row.features.get("information_feature_schema_hash")
            != schema.source_schema_hash
            or not row.features.get("strategy_fingerprint")
        ):
            raise ValueError("INFORMATION_SCHEMA_REQUIRED")
        if _utc(row.outcome_timestamp) > now or _utc(row.outcome_timestamp) <= _utc(
            row.decision_timestamp
        ):
            raise ValueError("Online examples require mature causal outcomes")
        if (
            row.label_positive_r not in (0, 1)
            or not math.isfinite(row.realized_net_r)
            or row.label_positive_r != int(row.realized_net_r > 0)
        ):
            raise ValueError("Invalid cost-adjusted online label")
        if not math.isfinite(row.sample_weight) or row.sample_weight <= 0:
            raise ValueError("Online sample weight must be positive and finite")
        for name in numeric:
            value = row.features.get(name)
            if value is not None and (
                isinstance(value, bool) or not math.isfinite(float(value))
            ):
                raise ValueError("Non-finite numeric online feature")
    root.mkdir(parents=True, exist_ok=True)
    contract = {
        "version": STATE_VERSION,
        "schema_hash": schema.hash,
        "sklearn": sklearn.__version__,
        "seed": seed,
        "market_family": family,
    }
    with closing(sqlite3.connect(root / (family + ".sqlite"), timeout=10)) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS checkpoint (id INTEGER PRIMARY KEY, contract TEXT NOT NULL, artifact BLOB NOT NULL, sha TEXT NOT NULL, stats TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS processed (uid TEXT PRIMARY KEY, fingerprint TEXT NOT NULL)"
        )
        db.execute("BEGIN IMMEDIATE")
        try:
            stored = db.execute(
                "SELECT contract, artifact, sha, stats FROM checkpoint WHERE id=1"
            ).fetchone()
            if stored:
                if json.loads(stored[0]) != contract:
                    raise ValueError("ONLINE_STATE_CONTRACT_CHANGED")
                artifact = bytes(stored[1])
                if (
                    sha256(
                        artifact + stored[0].encode() + stored[3].encode()
                    ).hexdigest()
                    != stored[2]
                ):
                    raise ValueError("ONLINE_STATE_CHECKSUM_FAILED")
                bundle = pickle.loads(artifact)
                stats = json.loads(stored[3])
            else:
                if not rows:
                    db.commit()
                    return None
                bundle, stats = _fresh_state(seed, schema)
                artifact = None
            pending = {}
            for row in rows:
                uid = example_source_uid(row)
                fingerprint = _fingerprint(row)
                previous = db.execute(
                    "SELECT fingerprint FROM processed WHERE uid=?", (uid,)
                ).fetchone()
                if (
                    previous is not None
                    and previous[0] != fingerprint
                    or uid in pending
                    and pending[uid][1] != fingerprint
                ):
                    raise ValueError("ONLINE_SOURCE_CHANGED")
                if previous is None:
                    pending[uid] = (row, fingerprint)
            ordered = sorted(
                pending.items(),
                key=lambda item: (
                    _utc(item[1][0].decision_timestamp),
                    _utc(item[1][0].outcome_timestamp),
                    item[0],
                ),
            )
            for decision, group_iter in groupby(
                ordered, key=lambda item: _utc(item[1][0].decision_timestamp)
            ):
                group = list(group_iter)
                examples = tuple(item[1][0] for item in group)
                matrix = bundle.preprocessor.transform(
                    _feature_frame(examples, feature_names=schema.feature_names)
                )
                eligible = (
                    stats["last_outcome"] is None
                    or datetime.fromisoformat(stats["last_outcome"]) <= decision
                )
                if eligible:
                    probability = (
                        bundle.classifier.predict_proba(matrix)[:, 1]
                        if stats["count"]
                        else np.full(len(group), 0.5)
                    )
                    predicted_r = (
                        bundle.regressor.predict(matrix)
                        if stats["count"]
                        else np.zeros(len(group))
                    )
                    baseline = (
                        stats["positive_weight"] / stats["weight"]
                        if stats["weight"]
                        else 0.5
                    )
                    baseline_r = (
                        stats["net_r_weight"] / stats["weight"]
                        if stats["weight"]
                        else 0.0
                    )
                    for row, pred, estimate in zip(examples, probability, predicted_r):
                        stats["brier_sum"] += (float(pred) - row.label_positive_r) ** 2
                        stats["baseline_brier_sum"] += (
                            baseline - row.label_positive_r
                        ) ** 2
                        stats["absolute_r_error_sum"] += abs(
                            float(estimate) - row.realized_net_r
                        )
                        stats["baseline_absolute_r_error_sum"] += abs(
                            baseline_r - row.realized_net_r
                        )
                    stats["prequential_count"] += len(group)
                else:
                    stats["overlap_excluded"] += len(group)
                weights = np.asarray([row.sample_weight for row in examples])
                bundle.classifier.partial_fit(
                    matrix,
                    np.asarray([row.label_positive_r for row in examples]),
                    classes=np.asarray([0, 1]),
                    sample_weight=weights,
                )
                bundle.regressor.partial_fit(
                    matrix,
                    (
                        np.clip([row.realized_net_r for row in examples], -3, 5)
                        if schema.hash == FeatureSchema.current().hash
                        else [row.realized_net_r for row in examples]
                    ),
                    sample_weight=weights,
                )
                for uid, (row, fingerprint) in group:
                    db.execute("INSERT INTO processed VALUES (?,?)", (uid, fingerprint))
                    stats["dataset_hash"] = sha256(
                        (stats["dataset_hash"] + fingerprint).encode()
                    ).hexdigest()
                    stats["count"] += 1
                    stats["weight"] += row.sample_weight
                    stats["positive_weight"] += row.sample_weight * row.label_positive_r
                    stats["net_r_weight"] += row.sample_weight * row.realized_net_r
                    stats["assets"] = sorted(set(stats["assets"]) | {row.asset_key})
                    stats["regimes"] = sorted(set(stats["regimes"]) | {row.regime})
                    stats["setups"] = sorted(set(stats["setups"]) | {row.setup_type})
                    stats["lane_counts"][row.evidence_lane] = (
                        stats["lane_counts"].get(row.evidence_lane, 0) + 1
                    )
                    stats["last_outcome"] = max(
                        stats["last_outcome"] or "",
                        _utc(row.outcome_timestamp).isoformat(),
                    )
            if pending:
                artifact = pickle.dumps(bundle, protocol=5)
                contract_text = json.dumps(contract, sort_keys=True)
                stats_text = json.dumps(stats, sort_keys=True)
                db.execute(
                    "INSERT OR REPLACE INTO checkpoint VALUES (1,?,?,?,?)",
                    (
                        contract_text,
                        artifact,
                        sha256(
                            artifact + contract_text.encode() + stats_text.encode()
                        ).hexdigest(),
                        stats_text,
                    ),
                )
            db.commit()
        except Exception:
            db.rollback()
            raise
    count = stats["prequential_count"]
    metrics = {
        "sample_size": stats["count"],
        "policy": "shadow_only",
        "prequential_samples": count,
        "overlap_samples_excluded": stats["overlap_excluded"],
        "brier_score": stats["brier_sum"] / count if count else None,
        "mean_absolute_net_r_error": (
            stats["absolute_r_error_sum"] / count if count else None
        ),
        "evaluation_scope": "Causal historical test-before-update subset; not prospective trading evidence.",
    }
    baseline = {
        "brier_score": stats["baseline_brier_sum"] / count if count else None,
        "mean_absolute_net_r_error": (
            stats["baseline_absolute_r_error_sum"] / count if count else None
        ),
    }
    return TrainingResult(
        status="SHADOW",
        decision_authority=False,
        model_bundle=bundle,
        validation_result=None,
        validation_metrics=metrics,
        baseline_metrics=baseline,
        artifact_bytes=artifact,
        artifact_sha256=sha256(artifact).hexdigest(),
        dataset_hash=stats["dataset_hash"],
        parameters={
            "seed": seed,
            "new_samples": len(pending),
            "duplicate_samples": len(rows) - len(pending),
            "last_outcome_at": stats["last_outcome"],
            "encoding": "fixed_hash_log_numeric_l2_v2",
            "regression_target_clip": (
                [-3, 5] if schema.hash == FeatureSchema.current().hash else None
            ),
            "asset_count": len(stats["assets"]),
            "regime_count": len(stats["regimes"]),
            "setup_count": len(stats["setups"]),
            "evidence_lane_counts": stats["lane_counts"],
        },
        sample_count=stats["count"],
    )
