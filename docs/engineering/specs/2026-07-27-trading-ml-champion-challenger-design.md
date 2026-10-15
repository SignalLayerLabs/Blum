# Trading ML Champion/Challenger Design

## Objective

Add an evidence-bound machine-learning layer that improves BLUM's Forex and
equity paper-trading decisions without replacing deterministic risk controls or
claiming unsupported alpha.

The system must learn quickly from new outcomes while promoting changes slowly
enough to protect against leakage, overfitting, regime concentration, and small
samples.

## Framework Decision

Use scikit-learn 1.6, which is already installed.

The first production implementation will not use TensorFlow or a PyTorch neural
network. The available equity evidence is sufficient for compact supervised
models, but the 38 closed Forex paper-forward trades are not sufficient for a
deep model. PyTorch remains available for a later challenger after BLUM has
thousands of independent, cost-adjusted outcomes.

The initial model family is:

- `SGDClassifier(loss="log_loss")` for rapid online shadow learning;
- `HistGradientBoostingClassifier` for batch probability estimation;
- `HistGradientBoostingRegressor` for expected net R estimation;
- deterministic BLUM rules as the incumbent champion and counterfactual
  baseline.

## Data Plane and Library Decisions

Use Polars lazy frames and partitioned Parquet as the training feature-store
boundary.

The database remains the source of truth. A bounded background projector reads
new labeled database rows, produces immutable feature partitions, and stores a
manifest containing row IDs, timestamps, feature schema hash, evidence lanes,
and file hashes. Trainers scan only the required columns and date partitions.
They do not hydrate the full SQLAlchemy object graph or load the full dataset
into RAM.

Polars is selected because lazy `scan_parquet` supports projection and predicate
pushdown and can stream batches larger than memory. Parquet is selected over
HDF5 because the training corpus is append-oriented, partitionable, portable,
and readable without one shared mutable file.

Dask is not added in this sprint. BLUM currently runs on one CPU node, where a
second distributed scheduler would add orchestration and memory overhead
without providing distributed hardware.

TA-Lib is not added in this sprint. BLUM already computes technical evidence
through tested deterministic services and the existing `ta` dependency. The ML
feature store reuses persisted point-in-time indicators instead of creating a
second indicator implementation with native build dependencies.

Add Optuna only for bounded challenger research:

- maximum 12 trials per market family;
- maximum 90 seconds per study;
- purged walk-forward score as the objective;
- pruning of trials that cannot beat the deterministic baseline;
- fixed seed and persisted study metadata;
- no optimization during inference or HTTP requests.

PyTorch remains installed but is not placed on the critical path. PyTorch
Lightning, TensorFlow, Gymnasium, and Stable-Baselines3 are not added to the
production runtime in this sprint.

A future neural or deep-RL challenger must first pass these entry gates:

- at least 5,000 independent labeled outcomes for the relevant market family;
- a versioned Gymnasium environment matching BLUM execution costs and
  lifecycle;
- deterministic replay and environment checks;
- separate train, validation, and paper-forward evaluation;
- superiority over the supervised champion after costs;
- no direct trading authority before the existing promotion gates pass.

This keeps the architecture open to LSTM, GRU, Transformer, PPO, or recurrent
policy challengers without pretending that GPU parallelism or a more complex
algorithm creates evidence.

## Scope

This sprint covers:

- immutable feature extraction for Forex and equities;
- labeled dataset assembly from stored point-in-time evidence;
- time-aware training and evaluation;
- model versioning and artifact integrity;
- champion/challenger promotion and rollback;
- bounded inference integration in paper decisions;
- scheduler integration;
- audit records and tests.

It does not cover:

- broker execution;
- real-money trading;
- frontend-triggered training;
- neural-network training;
- source-code self-modification;
- weakening existing data, execution, session, liquidity, or risk guards.

## Evidence Sources

### Equities

Eligible rows:

- `HistoricalPrediction` joined to mature `PredictionOutcome`;
- evaluated `HyperbolicReplayTrade` rows for stocks and ETFs;
- closed equity paper-forward trades.

### Forex

Eligible rows:

- evaluated Forex `HyperbolicReplayTrade` rows;
- terminal `ForexLearningEvidence` rows linked to frozen `ForexDecision`
  snapshots;
- closed Forex paper-forward positions with realized, cost-adjusted R.

Unlabeled candidates, rejected decisions without a future outcome, and open
positions are excluded from supervised targets.

Each example retains:

- evidence lane;
- decision timestamp;
- outcome timestamp;
- asset or pair;
- market and asset class;
- setup, regime, session, and direction;
- source object type and ID;
- point-in-time feature payload;
- data-quality score;
- realized net R;
- benchmark excess where available.

Replay, walk-forward, paper-forward, and live-forward evidence remain separate
in metrics and claims. Training may use multiple lanes with explicit sample
weights, but evaluation never blends them into a single evidence claim.

## Canonical Feature Contract

The common numeric feature set includes:

- deterministic BLUM aggregate score and confidence;
- trend, momentum, volume, volatility, support/resistance, sentiment,
  narrative, fundamental, and regime scores when available;
- expected gross R, expected net R, expected cost, stop distance, and target
  distance;
- data quality, liquidity, spread, slippage, and volatility;
- recent return and normalized multi-timeframe trend features;
- current contextual-bandit adjustment and sample size.

Categorical features include:

- market family (`equity` or `forex`);
- setup family;
- regime;
- session;
- direction;
- timeframe;
- sector or currency family.

Missing values remain explicit. Feature extraction must never query rows after
the decision timestamp.

The feature schema is versioned and hashed. Inference is rejected when the
active artifact and runtime feature schema do not match.

## Targets

The classifier target is:

`1` when realized net R is greater than zero after modeled costs, otherwise
`0`.

The regressor target is realized net R, clipped only for training robustness.
Raw realized R remains persisted for evaluation.

The decision advisor emits:

- calibrated probability of positive net R;
- predicted net R;
- model confidence;
- uncertainty and evidence sufficiency;
- proposed confidence adjustment;
- veto recommendation when validated negative edge is present;
- explanation using feature contributions or controlled ablation evidence.

## Dual-Speed Learning

### Fast Lane

The online `SGDClassifier` consumes each newly labeled outcome with
`partial_fit`. It remains a shadow learner and cannot directly alter decisions.
It provides rapid drift detection, preliminary probability estimates, and a
candidate starting point for research prioritization.

### Stable Lane

The batch classifier and regressor retrain when either condition is met:

- at least 25 new eligible labels exist since the latest completed run;
- 15 minutes have elapsed and new eligible labels exist.

Training runs only in background jobs, is limited to 120 seconds, persists a
cursor, and can resume. Identical dataset and feature hashes are idempotent.

## Time-Aware Validation

Validation uses expanding purged walk-forward folds:

- training data precedes validation data;
- rows whose outcome horizon overlaps a validation boundary are purged;
- an embargo separates training and validation;
- assets or pairs are grouped when measuring concentration;
- no random shuffle is allowed.

Metrics include:

- Brier score;
- log loss;
- balanced accuracy;
- precision and recall for positive-R outcomes;
- calibration error;
- expected and realized net R;
- benchmark excess where available;
- maximum drawdown;
- performance by regime, setup, asset, pair, and evidence lane.

The deterministic BLUM prediction is evaluated over the same rows as the
counterfactual baseline.

## Champion/Challenger Registry

A model version has one of these statuses:

- `SHADOW`;
- `CHALLENGER`;
- `ACTIVE`;
- `DEGRADED`;
- `ROLLED_BACK`;
- `REJECTED`;
- `INSUFFICIENT_EVIDENCE`.

Forex and equity models have independent champions.

A challenger may be promoted for paper-decision influence only when all gates
pass:

- at least 300 evaluated replay samples;
- at least three purged walk-forward windows;
- at least six distinct assets or Forex pairs;
- positive out-of-sample net expectancy after costs;
- Brier score at least 5% better than the deterministic baseline;
- no single asset contributes more than 35% of positive P/L;
- no single regime contributes more than 50% of positive P/L;
- drawdown does not exceed the configured paper risk budget;
- feature and artifact integrity checks pass.

Promotion to copy readiness remains separate and requires at least 100 closed
forward outcomes plus the existing BLUM copy-readiness gates.

## Decision Integration

Deterministic BLUM logic remains the primary decision creator. The active ML
model acts as an advisor after entry, stop, targets, expected costs, and risk
have been calculated.

Initial influence is bounded to plus or minus five percentage points of
confidence.

Positive adjustment requires:

- active model status;
- model and deterministic direction agreement;
- calibrated probability above the promoted threshold;
- predicted net R above zero;
- no hard blocker.

Negative adjustment or veto may be applied when:

- the active model has enough relevant evidence;
- calibrated probability and predicted net R both indicate negative edge;
- the model is not stale or degraded.

ML can never bypass:

- stale or missing data;
- future-data detection;
- market or session closure;
- liquidity and execution-cost blocks;
- portfolio and capital limits;
- invalid stop, target, or risk/reward;
- existing hard Risk Agent vetoes.

Every influenced decision persists model version, feature schema, prediction,
adjustment, baseline comparison, and guardrails applied.

## Reinforcement Integration

The existing hierarchical contextual bandit remains the online reward learner.
It specializes in local strategy, setup, regime, session, and direction
contexts.

The supervised model generalizes across comparable observations. The two
sources are resolved independently and then bounded:

- contextual bandit adjustment: existing maximum plus or minus 8%;
- supervised model adjustment: initial maximum plus or minus 5%;
- combined learned influence: maximum plus or minus 10%;
- all deterministic and risk gates remain authoritative.

Disagreement reduces confidence and is persisted as research evidence. It does
not trigger automatic trade creation.

## Persistence

Add:

### `trading_ml_model_versions`

- model ID, market family, algorithm, status;
- feature schema version and hash;
- dataset hash and evidence-lane counts;
- training and validation windows;
- sample, asset, regime, and setup counts;
- metrics and baseline metrics;
- promotion gates and decision;
- artifact path, SHA-256, and byte size;
- parent/champion version;
- creation, activation, degradation, and rollback timestamps.

### `trading_ml_training_runs`

- run ID, market family, trigger, status;
- cursor and resource budget;
- rows considered, accepted, and rejected;
- rejection reasons;
- split metadata;
- duration and error;
- candidate model version.

### `trading_ml_predictions`

- source decision type and ID;
- model version and market family;
- timestamp and feature hash;
- probability, predicted R, uncertainty;
- proposed and applied confidence adjustment;
- baseline output;
- guardrails and explanation;
- eventual realized outcome and evaluation timestamp.

Artifacts are written under controlled persistent storage and loaded only when
their SHA-256 and feature schema match the database record. BLUM never
deserializes user-provided artifacts.

## Components

- `TradingMLFeatureBuilder`: pure, point-in-time feature extraction.
- `TradingMLDatasetRepository`: bounded labeled-row retrieval and cursoring.
- `TradingMLFeatureStoreProjector`: incremental Polars/Parquet projection and
  manifest integrity.
- `SklearnTradingModelTrainer`: preprocessing, fitting, and artifact creation.
- `BoundedOptunaChallengerSearch`: time- and trial-limited parameter search.
- `PurgedWalkForwardEvaluator`: leakage-safe baseline comparison.
- `TradingMLModelRegistry`: version lifecycle and artifact integrity.
- `TradingMLInferenceService`: read-only bounded inference.
- `TradingMLPromotionService`: evidence gates and reversible activation.
- `TradingMLLearningWorker`: scheduled fast and stable learning slices.

Services depend on explicit protocols for feature extraction, artifact storage,
and model scoring so a later PyTorch implementation can become another
challenger without changing decision services.

## Scheduler and Runtime

Training runs in its own bounded worker. GET endpoints and frontend rendering
never fit, update, promote, or load an unbounded dataset.

The worker:

1. detects new labeled evidence;
2. updates the fast shadow learner;
3. schedules stable retraining when due;
4. evaluates the challenger;
5. promotes or rejects it;
6. refreshes a lightweight model-health snapshot;
7. publishes runtime events.

A worker failure cannot stop Forex, equities, Learning Loop, snapshots, or
paper-position management.

## Rollback and Drift

The active model is degraded and its influence becomes zero when:

- artifact or schema integrity fails;
- rolling Brier score worsens by more than 10% versus promotion evidence;
- rolling net expectancy becomes negative over at least 30 outcomes;
- calibration error exceeds the configured threshold;
- input drift exceeds the stored feature-distribution limit.

Rollback reactivates the previous valid champion. No historical model version
or prediction is overwritten.

## Testing

Tests must prove:

- point-in-time feature extraction rejects future data;
- unlabeled and open outcomes are excluded;
- purged folds do not overlap;
- online learning updates only shadow state;
- batch training is deterministic for a fixed seed;
- a weak challenger is rejected;
- a superior challenger is promoted;
- low-sample Forex evidence cannot activate a model;
- artifact hash mismatch disables inference;
- ML cannot bypass hard risk blockers;
- active model changes confidence within the configured bound;
- every influenced prediction is auditable;
- degradation triggers rollback;
- GET endpoints remain read-only;
- training runs only through background or explicit POST commands;
- existing Forex, equity, Learning Loop, and paper-trading tests remain green.

## Success Criteria

The sprint succeeds when:

- BLUM trains separate Forex and equity challengers from real stored outcomes;
- each model is evaluated against deterministic BLUM on identical temporal
  folds;
- rapid online learning occurs without immediate decision authority;
- only validated challengers affect paper decisions;
- model influence is bounded, explainable, and reversible;
- no performance or alpha claim is emitted without evidence-lane, sample-size,
  and benchmark context.
