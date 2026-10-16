#!/usr/bin/env python3
"""Reproduce local-only daily research and persistent-learning measurements.

Download the three pinned bars_1day files separately, respecting vendor terms.
This command opens train and validation only. It never downloads, deploys,
publishes market data, writes the production feature store or promotes models.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from hashlib import sha256
import json
import importlib.metadata
from pathlib import Path
import platform
import time

import numpy as np

from app.services.trading_ml.daily_research import (
    TRANSFORM_VERSION,
    examples_from_daily_bars,
    load_pinned_daily_bars,
)
from app.services.trading_ml.training import OnlineShadowTrainer, _fit_bundle

REPO = "twelvedata/financial-world-model"
REVISION = "a13200d8cc7537a9096e0d8c54eccd17dde8721e"
HASHES = {
    "train": "46fe4f338aa5a4d42d426851e8a830654358f9efa3f3bf588168a285e406c851",
    "val": "51aeca7ef0989d98b068bbfec689bde6436e15220b3ed452b517e379b699bbc1",
}


def score(labels, net_r, probabilities, estimates):
    return {
        "samples": len(labels),
        "brier_score": float(np.mean((probabilities - labels) ** 2)),
        "mean_absolute_net_r_error": float(np.mean(np.abs(estimates - net_r))),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--max-train-rows", type=int, default=100000)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--cost-bps", type=float, default=10)
    args = parser.parse_args()
    if args.max_train_rows < 100 or args.batch_size < 1:
        parser.error("Positive batch size and at least 100 training rows required")
    # Refuse accidental reuse of an already learned validation/final-test model.
    if args.output_root.exists():
        parser.error("Use a new output root for a clean, reproducible experiment")
    args.output_root.mkdir(parents=True)
    started = time.perf_counter()
    source_id = f"{REPO}@{REVISION}"
    train_bars = load_pinned_daily_bars(
        args.data_root / "train.parquet", expected_sha256=HASHES["train"]
    )
    validation_bars = load_pinned_daily_bars(
        args.data_root / "val.parquet", expected_sha256=HASHES["val"]
    )
    # Past training bars provide the first validation windows; validation bars
    # never supply features or labels for a training decision.
    train = examples_from_daily_bars(
        train_bars, source_id=source_id, split="train", cost_bps=args.cost_bps
    )
    validation = examples_from_daily_bars(
        train_bars + validation_bars,
        source_id=source_id,
        split="validation",
        cost_bps=args.cost_bps,
    )
    if not train or not validation:
        raise ValueError(
            "Both chronological training and validation examples are required"
        )
    cutoff = min(row.decision_timestamp for row in validation) - timedelta(days=1)
    eligible_train = tuple(row for row in train if row.outcome_timestamp < cutoff)
    train = eligible_train[-args.max_train_rows :]
    del train_bars, validation_bars
    trainer = OnlineShadowTrainer(args.output_root / "shadow")
    batches = []
    for offset in range(0, len(train), args.batch_size):
        tick = time.perf_counter()
        result = trainer.partial_fit(train[offset : offset + args.batch_size])
        batches.append(
            {
                "rows": result.parameters["new_samples"],
                "seconds": time.perf_counter() - tick,
            }
        )
    before = result.artifact_sha256
    tick = time.perf_counter()
    duplicate = trainer.partial_fit(train[-args.batch_size :])
    repeated_seconds = time.perf_counter() - tick
    assert (
        duplicate.parameters["new_samples"] == 0 and duplicate.artifact_sha256 == before
    )

    # Fixed parameters, declared before observing validation. No Optuna search
    # on these holdouts, and no production promotion is available here.
    tick = time.perf_counter()
    nonlinear = _fit_bundle(
        train,
        dict(
            learning_rate=0.06, max_leaf_nodes=15, max_iter=100, l2_regularization=0.05
        ),
        17,
    )
    nonlinear_seconds = time.perf_counter() - tick
    labels = np.asarray([row.label_positive_r for row in validation])
    net_r = np.asarray([row.realized_net_r for row in validation])
    baseline_p = np.average(
        [row.label_positive_r for row in train],
        weights=[row.sample_weight for row in train],
    )
    baseline_r = np.average(
        [row.realized_net_r for row in train],
        weights=[row.sample_weight for row in train],
    )
    baseline = score(
        labels,
        net_r,
        np.full(len(validation), baseline_p),
        np.full(len(validation), baseline_r),
    )
    candidates = {}
    for name, bundle in (
        ("persistent_online", result.model_bundle),
        ("fixed_hist_gradient_boosting", nonlinear),
    ):
        p, r = bundle.predict(validation)
        metrics = score(labels, net_r, p, r)
        metrics["brier_improvement_fraction"] = (
            baseline["brier_score"] - metrics["brier_score"]
        ) / baseline["brier_score"]
        candidates[name] = metrics
    receipt = {
        "runtime": {
            "python": platform.python_version(),
            "system": platform.system(),
            "machine": platform.machine(),
            "packages": {
                name: importlib.metadata.version(name)
                for name in ("scikit-learn", "numpy", "pandas", "polars", "pyarrow")
            },
        },
        "scope": "Local historical research, one long next-open/close hypothesis; not executable trading or forward alpha.",
        "source": {
            "repo": REPO,
            "revision": REVISION,
            "sha256": HASHES,
            "transform": TRANSFORM_VERSION,
        },
        "rights": "Publisher MIT tag does not establish underlying vendor redistribution rights; raw files and checkpoints remain local.",
        "market_family": "equity",
        "forex": "Not evaluated: no accepted new executable Forex dataset.",
        "training_samples": len(train),
        "eligible_training_samples": len(eligible_train),
        "validation_samples": len(validation),
        "asset_count": len({row.asset_key for row in train}),
        "training_first_decision": train[0].decision_timestamp.isoformat(),
        "training_last_outcome": max(
            row.outcome_timestamp for row in train
        ).isoformat(),
        "validation_first_decision": min(
            row.decision_timestamp for row in validation
        ).isoformat(),
        "validation_last_outcome": max(
            row.outcome_timestamp for row in validation
        ).isoformat(),
        "purge_and_embargo_days": 1,
        "round_trip_cost_bps": args.cost_bps,
        "sample_weight": 0.15,
        "final_test_opened_by_experiment": False,
        "decision_authority": False,
        "runtime_ingestion_enabled": False,
        "baseline": baseline,
        "candidates": candidates,
        "throughput": {
            "batch_size": args.batch_size,
            "batches": len(batches),
            "new_samples": sum(b["rows"] for b in batches),
            "online_training_seconds": sum(b["seconds"] for b in batches),
            "median_batch_seconds": float(np.median([b["seconds"] for b in batches])),
            "repeated_batch_seconds": repeated_seconds,
            "repeated_batch_optimizer_updates": duplicate.parameters["new_samples"],
            "nonlinear_training_seconds": nonlinear_seconds,
        },
        "historical_prequential_subset": dict(result.validation_metrics),
        "limitations": [
            "Current large-cap universe/survivorship bias",
            "Restated prices and conservative availability assumption",
            "Observed past action windows excluded; future returns do not filter decisions; not a corporate-action audit",
            "Missing historical spreads/borrow/fills",
            "Page boundaries may conservatively reduce prequential coverage; frozen validation is separate",
        ],
        "duration_seconds": time.perf_counter() - started,
    }
    (args.output_root / "evaluation.json").write_text(
        json.dumps(receipt, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                k: receipt[k]
                for k in (
                    "training_samples",
                    "validation_samples",
                    "baseline",
                    "candidates",
                    "throughput",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
