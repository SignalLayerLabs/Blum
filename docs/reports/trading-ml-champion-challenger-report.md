# Trading ML Champion/Challenger Certification

> Historical record. This document describes an earlier implementation or audit; its counts, configuration and readiness claims are not the current release status. Start with the [documentation index](../README.md) and [current data policy](../research/data-quality.md).

## Scope

This release adds an evidence-bound supervised learning lane without changing
BLUM's version or granting machine-learning models independent trading
authority.

## Data lineage

1. SQL terminal evidence remains authoritative.
2. Feature builders reject future, mutable, unlinked or non-cost-adjusted data.
3. A bounded projector writes immutable Polars/Parquet partitions and a
   resumable manifest.
4. Validation uses chronological expanding folds with purge and embargo.
5. Expected net R and realized net R are measured separately.
6. Drawdown follows outcome timestamps, while concentration follows positive
   weighted P/L contribution rather than row count.

## Training

- Rapid lane: `SGDClassifier(loss="log_loss")`, shadow-only.
- Stable lane: deterministic `HistGradientBoostingClassifier` plus
  `HistGradientBoostingRegressor`.
- Regression targets are clipped to `[-3R, 5R]` for fitting and evaluated
  against raw realized R.
- Optuna is bounded to 12 trials, 90 seconds and the approved small search
  space.

Scikit-learn was selected because current evidence is tabular, bounded and too
small to justify TensorFlow/PyTorch deep RL. Adding a neural network now would
increase variance and overfitting risk, not decision quality.

## Promotion and rollback

A challenger needs 300 terminal replay examples, three purged walk-forward
folds, six assets or currency pairs, positive net expectancy after costs, at
least 5% relative Brier improvement, non-concentrated positive P/L and a valid
artifact hash/schema.

Promotion is auditable and reversible. A model degrades on artifact failure,
greater than 10% rolling Brier deterioration, or negative expectancy over at
least 30 outcomes. A verified prior champion can be restored; otherwise the ML
advisor is disabled and deterministic BLUM retains authority.

## Decision influence

Active models are read through a bounded inference service. Advice is limited
to five confidence points and total learned influence to ten. Positive ML
advice cannot remove deterministic or risk blockers. Negative validated Forex
advice can add `SUPERVISED_MODEL_NEGATIVE_EDGE`.

Each persisted decision/model pair has one audit row containing feature hash,
probability, predicted net R, uncertainty, baseline, proposed/applied
adjustment and guardrails.

## Runtime

`TradingMLLearningWorker` performs bounded projection, shadow update,
challenger validation, promotion evaluation and snapshot publication
independently for equities and Forex. One market-family failure does not abort
the other. Each resumable slice accepts at most 500 examples per market family,
so CPU-basic deployments make frequent progress without one large training job
blocking the runtime. The scheduler delays first execution and runs every 15
minutes.

`GET /api/trading-ml/status` is snapshot-only and side-effect free.
`POST /api/trading-ml/run` explicitly starts one bounded slice.

## Evidence limitations

At design time BLUM had broad replay evidence but only 38 Forex forward
outcomes. That is insufficient for copy-readiness or a profitability claim.
Fast shadow updates improve learning latency, while promotion still waits for
out-of-sample, cost-adjusted and sufficiently diverse evidence. No component
promises profit or bypasses BLUM's no-trade and risk controls.
