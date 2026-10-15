# Trading ML Champion/Challenger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a rapid but evidence-bound scikit-learn learning system that trains Forex and equity challengers, promotes only superior models, and applies bounded, reversible advice to future paper decisions.

**Architecture:** SQL remains the source of truth and an incremental projector writes immutable Polars/Parquet feature partitions. Separate online shadow and stable batch learners are evaluated with purged walk-forward folds against deterministic BLUM; a registry promotes validated challengers and read-only inference services advise, but never override, existing decision and risk engines.

**Tech Stack:** Python 3.11, SQLAlchemy 2, Alembic, scikit-learn 1.6, Polars 1.43, Optuna 4.9, joblib, FastAPI, APScheduler, pytest.

## Global Constraints

- Keep the existing project version unchanged.
- Database records remain the source of truth.
- No training, projection, promotion, or model update from GET endpoints or frontend render.
- No model may use observations after its decision timestamp.
- Forex and equity evidence and champions remain separate.
- Online learning is shadow-only.
- Active supervised influence is capped at plus or minus five confidence points.
- Combined contextual-bandit and supervised influence is capped at plus or minus ten confidence points.
- Existing data, session, liquidity, cost, portfolio, and risk vetoes remain authoritative.
- A challenger requires 300 replay samples, three purged folds, six assets/pairs, positive net expectancy, and at least 5% Brier improvement to become active.
- Copy readiness continues to require at least 100 closed forward outcomes.
- Model artifacts are trusted only after feature-schema and SHA-256 verification.
- All training jobs must be bounded to 120 seconds and resumable.
- Existing APIs and financial behavior remain backward compatible.

---

## File Structure

Create a focused `backend/app/services/trading_ml/` package:

- `contracts.py`: immutable examples, predictions, folds, and model-health DTOs.
- `features.py`: point-in-time feature extraction for equities, replay, and Forex.
- `dataset.py`: bounded SQL retrieval and evidence-lane filtering.
- `feature_store.py`: incremental Polars/Parquet projection and manifests.
- `validation.py`: purged walk-forward folds and metrics.
- `training.py`: online and batch scikit-learn training plus bounded Optuna search.
- `registry.py`: artifact storage, integrity, promotion, degradation, and rollback.
- `inference.py`: read-only active-model scoring and bounded advice.
- `worker.py`: background orchestration and snapshot refresh.

Use existing composition roots:

- `PredictionEngine` integrates equity advice.
- `BlumForexTraderCore.run_cycle` integrates Forex advice after deterministic analysis and before risk-authorized execution.
- `realtime.py` schedules bounded learning.
- `DashboardSnapshot` stores lightweight status.

---

### Task 1: Persistence, Configuration, and Dependencies

**Files:**
- Modify: `requirements.txt`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/0040_trading_ml_champion_challenger.py`
- Modify: `backend/tests/test_migration_chain.py`
- Create: `backend/tests/test_trading_ml_persistence.py`

**Interfaces:**
- Produces: `TradingMLModelVersion`, `TradingMLTrainingRun`, and `TradingMLPrediction` ORM models.
- Produces settings with the `trading_ml_` prefix used by all later tasks.

- [ ] **Step 1: Write failing persistence and migration tests**

```python
def test_trading_ml_model_version_enforces_one_model_identity(db):
    row = TradingMLModelVersion(
        model_uid="ml-equity-test",
        market_family="equity",
        algorithm="hist_gradient_boosting",
        status="SHADOW",
        feature_schema_version="trading-ml-features-v1",
        feature_schema_hash="schema-hash",
        dataset_hash="dataset-hash",
        artifact_path="/data/models/test.joblib",
        artifact_sha256="artifact-hash",
    )
    db.add(row)
    db.commit()
    assert db.scalar(select(TradingMLModelVersion)).model_uid == "ml-equity-test"


def test_migration_head_is_trading_ml():
    assert migration_head() == "0040_trading_ml_champion"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_trading_ml_persistence.py \
  backend/tests/test_migration_chain.py -q
```

Expected: import or head assertion failure because the models and migration do not exist.

- [ ] **Step 3: Add exact dependencies and settings**

Add:

```text
polars==1.43.0
optuna==4.9.0
```

Add settings:

```python
trading_ml_enabled: bool = True
trading_ml_worker_minutes: int = 15
trading_ml_new_label_threshold: int = 25
trading_ml_max_runtime_seconds: int = 120
trading_ml_max_rows_per_slice: int = 5000
trading_ml_min_replay_samples: int = 300
trading_ml_min_folds: int = 3
trading_ml_min_assets: int = 6
trading_ml_brier_improvement: float = 0.05
trading_ml_max_confidence_adjustment: float = 5.0
trading_ml_max_combined_adjustment: float = 10.0
trading_ml_optuna_trials: int = 12
trading_ml_optuna_timeout_seconds: int = 90
trading_ml_artifact_root: str = "/data/trading_ml"
```

- [ ] **Step 4: Add ORM models and migration**

`TradingMLModelVersion` must persist identity, market family, algorithm,
status, schema/dataset hashes, evidence counts, split metadata, model and
baseline metrics, promotion gates, artifact metadata, parent/champion IDs,
timestamps, warnings, and explanations.

`TradingMLTrainingRun` must persist run identity, trigger, cursor, resource
limits, row counts, split metadata, status, duration, candidate model ID, and
error.

`TradingMLPrediction` must persist source decision identity, model identity,
feature hash, probability, predicted R, uncertainty, baseline, proposed and
applied adjustments, guardrails, explanation, and eventual outcome.

Create unique/index constraints for:

```python
UniqueConstraint("model_uid", name="uq_trading_ml_model_uid")
UniqueConstraint(
    "source_object_type",
    "source_object_id",
    "model_version_id",
    name="uq_trading_ml_prediction_source_model",
)
Index("ix_trading_ml_models_market_status", "market_family", "status")
Index("ix_trading_ml_runs_market_started", "market_family", "started_at")
Index("ix_trading_ml_predictions_market_created", "market_family", "created_at")
```

Use cross-database `JsonType` fields and include a complete downgrade.

- [ ] **Step 5: Run persistence and full migration-chain tests**

Run:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_trading_ml_persistence.py \
  backend/tests/test_migration_chain.py -q
```

Expected: PASS, including SQLite upgrade and downgrade.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt backend/app/core/config.py backend/app/models.py \
  backend/alembic/versions/0040_trading_ml_champion_challenger.py \
  backend/tests/test_migration_chain.py backend/tests/test_trading_ml_persistence.py
git commit -m "feat: add trading ML persistence"
```

---

### Task 2: Immutable Feature Contract and Point-in-Time Builders

**Files:**
- Create: `backend/app/services/trading_ml/__init__.py`
- Create: `backend/app/services/trading_ml/contracts.py`
- Create: `backend/app/services/trading_ml/features.py`
- Create: `backend/tests/test_trading_ml_features.py`

**Interfaces:**
- Produces: `TradingMLExample`, `TradingMLAdvice`, `FeatureSchema`, and `TradingMLFeatureBuilder`.
- Consumes stored `HistoricalPrediction`, `PredictionOutcome`, `HyperbolicReplayTrade`, `ForexDecision`, and `ForexLearningEvidence`.

- [ ] **Step 1: Write failing feature-contract tests**

```python
def test_equity_feature_builder_uses_only_frozen_prediction_context():
    example = TradingMLFeatureBuilder().from_equity(
        prediction=equity_prediction(),
        outcome=equity_outcome(realized_return=4.0),
    )
    assert example.market_family == "equity"
    assert example.label_positive_r == 1
    assert example.decision_timestamp <= example.outcome_timestamp
    assert "future_prices" not in example.features


def test_forex_feature_builder_rejects_future_snapshot_data():
    decision = forex_decision_with_frame_timestamp(
        market_timestamp=datetime(2026, 1, 2, 10, 1),
        decision_timestamp=datetime(2026, 1, 2, 10, 0),
    )
    with pytest.raises(FutureFeatureDataError):
        TradingMLFeatureBuilder().from_forex(decision, forex_evidence())
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_trading_ml_features.py -q
```

Expected: module import failure.

- [ ] **Step 3: Implement immutable contracts**

Use frozen dataclasses:

```python
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
    features: dict[str, float | str | None]
    realized_net_r: float
    label_positive_r: int
    benchmark_excess: float | None
    sample_weight: float


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
```

- [ ] **Step 4: Implement point-in-time extraction**

Normalize a fixed schema with numeric defaults represented as `None`, preserve
categorical context, and hash canonical JSON. Validate every nested market
timestamp before emitting a Forex example. Map sample weights:

```python
EVIDENCE_WEIGHTS = {
    "REPLAY_EVIDENCE": 0.25,
    "WALK_FORWARD_EVIDENCE": 0.75,
    "PAPER_FORWARD": 1.0,
    "PAPER_FORWARD_FOREX": 1.0,
    "LIVE_FORWARD": 1.0,
}
```

- [ ] **Step 5: Run tests**

Run:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_trading_ml_features.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/trading_ml backend/tests/test_trading_ml_features.py
git commit -m "feat: add point-in-time trading ML features"
```

---

### Task 3: Bounded Dataset Repository and Polars Feature Store

**Files:**
- Create: `backend/app/services/trading_ml/dataset.py`
- Create: `backend/app/services/trading_ml/feature_store.py`
- Create: `backend/tests/test_trading_ml_feature_store.py`

**Interfaces:**
- Produces: `TradingMLDatasetRepository.read_slice(...)`.
- Produces: `TradingMLFeatureStoreProjector.project(...)` and `scan(...)`.
- Consumes `TradingMLExample` and persistent storage root.

- [ ] **Step 1: Write failing dataset and projection tests**

```python
def test_repository_excludes_open_and_unlabeled_rows(db):
    seed_closed_and_open_evidence(db)
    rows = TradingMLDatasetRepository().read_slice(
        db, market_family="forex", after_cursor=None, limit=100
    )
    assert [row.source_object_id for row in rows.examples] == ["closed-1"]


def test_projector_is_incremental_and_idempotent(db, tmp_path):
    projector = TradingMLFeatureStoreProjector(root=tmp_path)
    first = projector.project(db, market_family="equity", limit=100)
    second = projector.project(db, market_family="equity", limit=100)
    assert first.rows_written > 0
    assert second.rows_written == 0
    assert second.dataset_hash == first.dataset_hash
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_trading_ml_feature_store.py -q
```

Expected: module import failure.

- [ ] **Step 3: Implement bounded SQL retrieval**

Query only eligible terminal rows with explicit ordering and `LIMIT`. Return a
cursor containing source table and last ID. Never query all ORM rows before
applying the limit.

- [ ] **Step 4: Implement immutable Parquet projection**

Write partitions under:

```text
{root}/features/market_family={market_family}/year={YYYY}/month={MM}/part-{hash}.parquet
```

Persist an atomic JSON manifest with:

```json
{
  "schema_version": "trading-ml-features-v1",
  "schema_hash": "...",
  "dataset_hash": "...",
  "partitions": [],
  "source_cursors": {},
  "evidence_lane_counts": {}
}
```

Use `pl.scan_parquet` for reads and select only requested feature/label columns.
Write to a temporary path and rename only after hash verification.

- [ ] **Step 5: Test streaming and memory bounds**

Generate 20,000 synthetic rows in the test and assert that `scan()` returns a
lazy frame, predicate filtering works, and projection writes multiple bounded
partitions without duplicate source IDs.

- [ ] **Step 6: Run tests**

Run:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_trading_ml_feature_store.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/trading_ml/dataset.py \
  backend/app/services/trading_ml/feature_store.py \
  backend/tests/test_trading_ml_feature_store.py
git commit -m "feat: add incremental trading feature store"
```

---

### Task 4: Purged Walk-Forward Evaluation

**Files:**
- Create: `backend/app/services/trading_ml/validation.py`
- Create: `backend/tests/test_trading_ml_validation.py`

**Interfaces:**
- Produces: `PurgedWalkForwardEvaluator.split(...)` and `evaluate(...)`.
- Consumes canonical feature rows and deterministic baseline outputs.

- [ ] **Step 1: Write failing leakage and metric tests**

```python
def test_purged_folds_never_overlap_outcome_horizons():
    folds = PurgedWalkForwardEvaluator(min_folds=3, embargo_days=2).split(rows())
    for fold in folds:
        latest_train_outcome = max(row.outcome_timestamp for row in fold.train)
        earliest_validation_decision = min(
            row.decision_timestamp for row in fold.validation
        )
        assert latest_train_outcome < earliest_validation_decision


def test_evaluator_compares_candidate_and_baseline_on_identical_rows():
    result = evaluator().evaluate(candidate(), baseline(), rows())
    assert result.candidate.sample_size == result.baseline.sample_size
    assert result.brier_improvement == pytest.approx(0.1)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_trading_ml_validation.py -q
```

Expected: module import failure.

- [ ] **Step 3: Implement expanding folds with purge and embargo**

Sort by decision timestamp, split into at least three expanding folds, purge
training rows whose outcome timestamp reaches the validation boundary, and
apply the configured embargo. Reject random or shuffled splits.

- [ ] **Step 4: Implement candidate and baseline metrics**

Calculate Brier score, log loss, balanced accuracy, precision, recall,
calibration error, net expectancy, drawdown, benchmark excess, and
concentration by asset/regime. Preserve per-fold and aggregate values.

- [ ] **Step 5: Run tests**

Run:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_trading_ml_validation.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/trading_ml/validation.py \
  backend/tests/test_trading_ml_validation.py
git commit -m "feat: add purged trading ML validation"
```

---

### Task 5: Online Shadow and Stable Batch Trainers

**Files:**
- Create: `backend/app/services/trading_ml/training.py`
- Create: `backend/tests/test_trading_ml_training.py`

**Interfaces:**
- Produces: `OnlineShadowTrainer.partial_fit(...)`.
- Produces: `SklearnTradingModelTrainer.fit(...)`.
- Produces: `BoundedOptunaChallengerSearch.search(...)`.
- Consumes Polars feature scans and purged folds.

- [ ] **Step 1: Write failing trainer tests**

```python
def test_online_update_remains_shadow_only(tmp_path):
    result = OnlineShadowTrainer(tmp_path).partial_fit(examples())
    assert result.status == "SHADOW"
    assert result.decision_authority is False


def test_batch_training_is_deterministic_for_fixed_seed(tmp_path):
    first = trainer(tmp_path, seed=17).fit(dataset())
    second = trainer(tmp_path, seed=17).fit(dataset())
    assert first.validation_metrics == second.validation_metrics
    assert first.artifact_sha256 == second.artifact_sha256
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_trading_ml_training.py -q
```

Expected: module import failure.

- [ ] **Step 3: Implement preprocessing and online learner**

Use a `ColumnTransformer` with median imputation and scaling for numeric
features and `OneHotEncoder(handle_unknown="ignore")` for categorical features.
The online pipeline uses `SGDClassifier(loss="log_loss", random_state=seed)` and
persists only shadow metrics and artifact metadata.

- [ ] **Step 4: Implement stable classifier and regressor**

Train `HistGradientBoostingClassifier` and
`HistGradientBoostingRegressor` from a deterministic parameter set. Fit each
fold independently. Clip training R to `[-3, 5]` but evaluate against raw R.

- [ ] **Step 5: Implement bounded Optuna search**

Search only:

```python
{
    "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.15, log=True),
    "max_leaf_nodes": trial.suggest_int("max_leaf_nodes", 7, 31),
    "max_iter": trial.suggest_int("max_iter", 60, 180),
    "l2_regularization": trial.suggest_float(
        "l2_regularization", 1e-4, 1.0, log=True
    ),
}
```

Optimize purged-fold Brier score with penalties when net expectancy is not
positive. Enforce 12 trials, 90 seconds, fixed seed, and pruning.

- [ ] **Step 6: Run tests**

Run:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_trading_ml_training.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/trading_ml/training.py \
  backend/tests/test_trading_ml_training.py
git commit -m "feat: train bounded trading ML challengers"
```

---

### Task 6: Artifact Registry, Promotion, Degradation, and Rollback

**Files:**
- Create: `backend/app/services/trading_ml/registry.py`
- Create: `backend/tests/test_trading_ml_registry.py`

**Interfaces:**
- Produces: `TradingMLModelRegistry.store_candidate(...)`, `load_active(...)`.
- Produces: `TradingMLPromotionService.evaluate(...)`, `promote(...)`, and `rollback(...)`.

- [ ] **Step 1: Write failing integrity and promotion tests**

```python
def test_low_sample_forex_challenger_is_not_promoted(db, tmp_path):
    candidate = model_candidate(market_family="forex", sample_size=299)
    decision = TradingMLPromotionService(tmp_path).evaluate(db, candidate)
    assert decision.status == "INSUFFICIENT_EVIDENCE"


def test_artifact_hash_mismatch_disables_model(db, tmp_path):
    active = store_active_model(db, tmp_path)
    Path(active.artifact_path).write_bytes(b"tampered")
    loaded = TradingMLModelRegistry(tmp_path).load_active(db, "equity")
    assert loaded.status == "DEGRADED"
    assert loaded.model is None
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_trading_ml_registry.py -q
```

Expected: module import failure.

- [ ] **Step 3: Implement trusted artifact storage**

Write artifacts to a temporary file, compute SHA-256, fsync, rename, and persist
metadata. Load only database-referenced files beneath the configured root and
only after hash and schema verification.

- [ ] **Step 4: Implement promotion gates**

Return a named failed gate for every requirement. Promotion must atomically:

1. mark the prior active model as `ROLLED_BACK` only after the new artifact is
   verified;
2. mark the challenger `ACTIVE`;
3. store activation time and previous champion ID;
4. commit one auditable transaction.

- [ ] **Step 5: Implement degradation and rollback**

Degrade after artifact failure, rolling Brier deterioration greater than 10%,
or negative expectancy over at least 30 outcomes. Reactivate the latest valid
previous champion; otherwise return deterministic BLUM to full authority.

- [ ] **Step 6: Run tests**

Run:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_trading_ml_registry.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/trading_ml/registry.py \
  backend/tests/test_trading_ml_registry.py
git commit -m "feat: govern trading ML model promotion"
```

---

### Task 7: Read-Only Inference and Equity Integration

**Files:**
- Create: `backend/app/services/trading_ml/inference.py`
- Modify: `backend/app/services/learning_loop.py`
- Create: `backend/tests/test_trading_ml_inference.py`
- Modify: `backend/tests/test_learning_feedback_loop.py`

**Interfaces:**
- Produces: `TradingMLInferenceService.advise(...) -> TradingMLAdvice`.
- Consumes active model registry, canonical features, and deterministic output.
- Extends `PredictionEngine.feedback_context` with `supervised_model_memory`.

- [ ] **Step 1: Write failing inference-bound tests**

```python
def test_active_equity_model_adjusts_confidence_within_five_points(db):
    seed_active_equity_model(db, probability=0.8, predicted_r=0.4)
    prediction = PredictionEngine().predict(equity_context(), db=db)
    advice = prediction["feedback_loop"]["supervised_model_memory"]
    assert 0 < advice["applied_confidence_adjustment"] <= 5.0


def test_ml_cannot_bypass_deterministic_avoid(db):
    seed_active_equity_model(db, probability=0.99, predicted_r=2.0)
    prediction = PredictionEngine().predict(avoid_context(), db=db)
    assert prediction["prediction"]["dominant_direction"] == "neutral"
    assert prediction["feedback_loop"]["supervised_model_memory"][
        "applied_confidence_adjustment"
    ] == 0.0
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_trading_ml_inference.py \
  backend/tests/test_learning_feedback_loop.py -q
```

Expected: missing service or feedback key failure.

- [ ] **Step 3: Implement inference**

Load only the active market-family model through the registry. Return
`NO_ACTIVE_MODEL`, `INSUFFICIENT_EVIDENCE`, `SCHEMA_MISMATCH`, or `DEGRADED`
without raising into the decision path. Calculate a signed adjustment capped at
five points and persist `TradingMLPrediction` only during write-oriented
decision workflows.

- [ ] **Step 4: Integrate equity prediction**

Call the advisor after deterministic score and memory calculation. Preserve
the deterministic baseline, cap combined learning adjustment at ten points,
and persist model version, probability, predicted R, explanation, and applied
guardrails in `HistoricalPrediction.prediction_payload`.

- [ ] **Step 5: Run tests**

Run:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_trading_ml_inference.py \
  backend/tests/test_learning_feedback_loop.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/trading_ml/inference.py \
  backend/app/services/learning_loop.py \
  backend/tests/test_trading_ml_inference.py \
  backend/tests/test_learning_feedback_loop.py
git commit -m "feat: advise equity predictions with active ML"
```

---

### Task 8: Forex Advisor Integration and Risk Authority

**Files:**
- Modify: `backend/app/services/forex_trader.py`
- Modify: `backend/app/services/forex_agents.py`
- Modify: `backend/app/services/forex_contracts.py`
- Modify: `backend/tests/test_forex_trader_core.py`
- Create: `backend/tests/test_forex_ml_integration.py`

**Interfaces:**
- Consumes `TradingMLInferenceService.advise(...)`.
- Extends `ForexTradeProposal.knowledge_context` with `supervised_model`.
- Persists one `TradingMLPrediction` per Forex decision/model version.

- [ ] **Step 1: Write failing Forex authority tests**

```python
def test_forex_model_cannot_remove_stale_data_veto(db):
    seed_active_forex_model(db, probability=0.95, predicted_r=1.2)
    result = run_forex_cycle(db, market=stale_market_input())
    assert result["trades_opened"] == 0
    assert "STALE_DATA" in result["blockers"]


def test_validated_negative_forex_model_adds_veto(db):
    seed_active_forex_model(db, probability=0.2, predicted_r=-0.5)
    result = run_forex_cycle(db, market=otherwise_actionable_market())
    assert result["trades_opened"] == 0
    assert "SUPERVISED_MODEL_NEGATIVE_EDGE" in result["blockers"]
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_forex_ml_integration.py \
  backend/tests/test_forex_trader_core.py -q
```

Expected: missing supervised advice and veto.

- [ ] **Step 3: Integrate advisor in write-oriented Forex cycle**

Run deterministic agents first. Build features from the frozen input and
proposal, request advice, then rerun only the confidence/risk resolution step.
Do not rerun market analysis or mutate entry, stop, targets, or costs.

- [ ] **Step 4: Enforce combined limits and disagreement**

Cap combined contextual-bandit plus supervised confidence influence at ten
points. Model/deterministic disagreement lowers confidence. Positive advice
cannot remove existing blockers; validated negative advice can add
`SUPERVISED_MODEL_NEGATIVE_EDGE`.

- [ ] **Step 5: Persist audit payload**

Store model version, feature hash, probability, predicted R, proposed/applied
adjustment, baseline proposal, final blockers, and explanation in both
`TradingMLPrediction` and `ForexDecision.proposal_json["supervised_model"]`.

- [ ] **Step 6: Run tests**

Run:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_forex_ml_integration.py \
  backend/tests/test_forex_trader_core.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/forex_trader.py \
  backend/app/services/forex_agents.py backend/app/services/forex_contracts.py \
  backend/tests/test_forex_trader_core.py \
  backend/tests/test_forex_ml_integration.py
git commit -m "feat: advise forex decisions with active ML"
```

---

### Task 9: Background Worker, Status Snapshot, and Read-Only API

**Files:**
- Create: `backend/app/services/trading_ml/worker.py`
- Modify: `backend/app/services/realtime.py`
- Modify: `backend/app/api/routes.py`
- Create: `backend/tests/test_trading_ml_worker.py`
- Create: `backend/tests/test_trading_ml_api.py`

**Interfaces:**
- Produces: `TradingMLLearningWorker.run_once(db, trigger)`.
- Produces snapshot type `trading_ml_status`.
- Produces GET `/api/trading-ml/status`, which reads the snapshot only.
- Produces explicit POST `/api/trading-ml/run`, which invokes one bounded slice.

- [ ] **Step 1: Write failing worker and GET hygiene tests**

```python
def test_status_get_never_runs_training(monkeypatch, client):
    monkeypatch.setattr(
        TradingMLLearningWorker,
        "run_once",
        lambda *args, **kwargs: pytest.fail("GET triggered training"),
    )
    assert client.get("/api/trading-ml/status").status_code == 200


def test_worker_resumes_cursor_after_budget(db, fake_clock):
    first = TradingMLLearningWorker(max_runtime_seconds=1).run_once(db, "test")
    second = TradingMLLearningWorker(max_runtime_seconds=1).run_once(db, "test")
    assert second["cursor"]["last_source_id"] >= first["cursor"]["last_source_id"]
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_trading_ml_worker.py \
  backend/tests/test_trading_ml_api.py -q
```

Expected: missing worker and route.

- [ ] **Step 3: Implement bounded orchestration**

The worker must:

1. project new labels;
2. update online shadow artifacts;
3. retrain stable challengers when due;
4. evaluate and promote/reject;
5. evaluate active-model drift;
6. write `trading_ml_status`;
7. checkpoint `BackgroundJobState`;
8. publish a `BrainRuntimeEvent`.

Failure in one market family must not prevent the other family from completing.

- [ ] **Step 4: Register scheduler**

Add `run_trading_ml_learning_job` through `_run_job` with a 15-minute interval,
delayed startup, bounded runtime, and no startup full training.

- [ ] **Step 5: Add snapshot-only GET and explicit POST**

GET returns current champions, challengers, sample counts, evidence lanes,
latest metrics, failed gates, staleness, and last run. Missing snapshots return
`INITIALIZING` without training.

- [ ] **Step 6: Run tests**

Run:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_trading_ml_worker.py \
  backend/tests/test_trading_ml_api.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/trading_ml/worker.py \
  backend/app/services/realtime.py backend/app/api/routes.py \
  backend/tests/test_trading_ml_worker.py backend/tests/test_trading_ml_api.py
git commit -m "feat: run trading ML learning in background"
```

---

### Task 10: Certification, Documentation, and Deployment

**Files:**
- Modify: `README.md`
- Create: `TRADING_ML_CHAMPION_CHALLENGER_REPORT.md`

**Interfaces:**
- Documents data lineage, training cadence, promotion gates, active influence,
  rollback, and known evidence limitations.

- [ ] **Step 1: Add end-to-end audit test**

Add to `backend/tests/test_trading_ml_worker.py`:

```python
def test_end_to_end_challenger_audit_chain(db, tmp_path):
    seed_sufficient_equity_evidence(db)
    result = worker(tmp_path).run_once(db, "certification")
    model = db.scalar(select(TradingMLModelVersion).where(
        TradingMLModelVersion.market_family == "equity"
    ))
    assert result["markets"]["equity"]["status"] in {
        "CHALLENGER",
        "ACTIVE",
        "REJECTED",
    }
    assert model.dataset_hash
    assert model.artifact_sha256
    assert model.validation_metrics_json["folds"]
```

- [ ] **Step 2: Run focused ML and financial regression suites**

Run:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_trading_ml_*.py \
  backend/tests/test_learning_feedback_loop.py \
  backend/tests/test_forex_reinforcement_policy.py \
  backend/tests/test_forex_trader_core.py \
  backend/tests/test_live_forward_paper_trading.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full backend suite**

Run:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q
```

Expected: all tests pass.

- [ ] **Step 4: Run static and migration checks**

Run:

```bash
git diff --check
PYTHONPATH=backend .venv/bin/python -m compileall -q backend/app
cd backend
PYTHONPATH=. ../.venv/bin/alembic -c alembic.ini heads
```

Expected: clean diff, compile success, and
`0040_trading_ml_champion (head)`.

- [ ] **Step 5: Build frontend regression**

Run:

```bash
cd frontend
/Users/renatovinai/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node \
  node_modules/next/dist/bin/next build
```

Expected: production build succeeds without frontend changes.

- [ ] **Step 6: Update documentation**

README and report must state:

- scikit-learn was selected because current evidence does not justify deep RL;
- Polars/Parquet accelerates bounded feature reads;
- online learning is shadow-only;
- promotion is out-of-sample and benchmark-aware;
- active model influence is bounded and reversible;
- Forex currently has only 38 forward outcomes;
- no model claims guaranteed profitability or copy readiness.

- [ ] **Step 7: Commit implementation documentation**

```bash
git add README.md TRADING_ML_CHAMPION_CHALLENGER_REPORT.md
git commit -m "docs: certify trading ML champion challenger"
```

- [ ] **Step 8: Push and verify Hugging Face deployment**

Run:

```bash
git push hf main
```

Wait until the Space runtime SHA equals local `HEAD` and stage is `RUNNING`.
Then verify:

```bash
curl -fsS https://italianhype-blum.hf.space/startup/status
curl -fsS https://italianhype-blum.hf.space/learning/health
curl -fsS https://italianhype-blum.hf.space/api/trading-ml/status
curl -fsS https://italianhype-blum.hf.space/api/forex-trader/snapshot
curl -fsS https://italianhype-blum.hf.space/api/paper-trading/snapshot
```

Expected:

- runtime and API ready;
- no migration error;
- training ML status is `INITIALIZING`, `SHADOW`, `CHALLENGER`, `ACTIVE`, or
  evidence-bound `INSUFFICIENT_EVIDENCE`;
- Forex and paper snapshots remain available;
- no GET request starts training.
