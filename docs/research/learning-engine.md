# Persistent learning and dataset acceptance

The trading ML worker now retains incremental classifier and robust net-R regression weights across cycles and process restarts. Equity and Forex have separate checkpoints, identities and measurements. This improves learning continuity and backlog processing; it does not establish predictive or trading superiority.

## What changed

Previously `OnlineShadowTrainer` rebuilt its preprocessor and classifier on each call, ignored sample weights and learned only the supplied recent window. Optional FinRL-X initialization could consume the cycle before either core market ran. A production capture on 16 October 2026 showed an 80.4-second cycle with both markets reporting `BUDGET_EXHAUSTED` and zero new source rows considered.

The worker now projects source records, processes unread immutable partitions, updates the two persistent shadow learners, then considers expensive challengers and optional FinRL-X work. Each learner uses fixed hashed coordinates, signed logarithmic numeric features, missing-value flags, sample weights and chronological updates. Unchanged identities perform no optimizer updates; changed evidence under the same identity fails explicitly.

`TRADING_ML_ONLINE_MAX_ROWS_PER_SLICE` defaults to **10,000 per market**, independently of the existing **500-row** challenger/projection limit (`TRADING_ML_MAX_ROWS_PER_SLICE`). Both online lanes run before hyperparameter search. These are bounded row capacities, not a promise of twenty times better forecasts. Stable challengers retain their original evidence and promotion gates; online models remain `SHADOW_ONLY`.

The stored worker report exposes `new_examples_learned` and, for each market, `online.new_samples`, `total_samples`, duplicate/rejected counts, queue exhaustion, checkpoint lineage, historical measurements and baseline measurements. A failed later artifact/cursor publication retains the count of updates already committed. An entirely skipped cycle reports `BUDGET_EXHAUSTED` rather than completion.

## Persistence and recovery

The configured `TRADING_ML_ARTIFACT_ROOT` defaults to `/data/trading_ml`. Its `shadow/` directory contains one SQLite checkpoint/identity database and reader JSON per market. A single SQLite transaction commits model weights, source identities, lineage and measurements. A checksum covers the model, version contract and measurements. The reader advances atomically only after that transaction commits; interrupted reader publication replays and deduplicates the same page.

The cursor records its associated model sample count and lineage. Missing, older or conflicting checkpoints fail closed rather than silently reconstructing only the latest window. Schema, algorithm-state, seed or scikit-learn version changes also require explicit migration/rebuild; they never silently discard learning.

Retention requires the files to survive. Process-restart tests are not proof of recovery after storage loss. Keep `/data` persistent and preserve the whole feature store plus `shadow/` together for recovery; a PostgreSQL-only backup does not include these model files. If recovery cannot retain a consistent checkpoint/cursor, rebuild the shadow learner from the immutable feature store in an isolated directory and verify its lineage before replacing it. Do not reset financial evidence or edit old outcome records to repair a model checkpoint.

## Dataset decision

The audited Hugging Face candidate is [Twelve Data Financial World Model](https://huggingface.co/datasets/twelvedata/financial-world-model/tree/a13200d8cc7537a9096e0d8c54eccd17dde8721e), revision `a13200d8cc7537a9096e0d8c54eccd17dde8721e`. Across its daily train/validation/test files, basic validation found **517,286 rows / 51 current large-cap US stocks**, zero duplicate symbol/date keys, invalid OHLC rows or missing/negative volumes. These checks do not independently verify the prices, historical investability or vendor arrival times.

The publisher distinguishes its MIT metadata/code license from underlying Twelve Data market-data terms. Raw files and model checkpoints therefore remain local; this change neither republishes them nor automatically ingests them into production. The source also has a current-universe/survivorship bias, restated prices and no executable historical spreads or fills. The subscription-gated Papers With Backtest Forex source is excluded. No new Forex financial-performance claim is made.

The executable adapter reads only pinned local OHLCV files, ignoring publisher targets, text, macro proxies and precomputed indicators. It rebuilds features using completed prior bars and assumes daily bars available at 18:00 New York time, converted to UTC. This is a conservative research assumption, not a historical arrival receipt. Each example models one LONG next-session open-to-close hypothesis, normalized by relative ATR known at the decision, with a declared round-trip cost. It is neither an order nor a simulated stop-fill ledger. Only known past adjustment/discontinuity windows affect eligibility; future returns cannot remove a preceding decision. Labels are assigned to train/validation/test by outcome date.

## Reproducible local experiment

With rights to use the source files locally, place the pinned `bars_1day/train.parquet` and `val.parquet` in a private directory and run from the repository root:

```sh
PYTHONPATH=backend python scripts/benchmark_learning_engine.py \
  --data-root /private/path/to/pinned-daily-bars \
  --output-root /private/path/to/new-experiment
```

The script verifies SHA-256, refuses an existing experiment directory, purges overlapping labels with a one-day embargo, trains the most recent 100,000 eligible examples, freezes the models and evaluates 12,852 validation examples from 2024. Its declared nonlinear parameters are fixed; there is no validation-driven hyperparameter search. The final 2025–2026 test file is not opened by the experiment. Earlier source-quality checks read its schema/OHLC only. Never recycle this validation period as a new unseen test.

The [recorded v2 experiment](../evidence/learning-engine-evaluation.json) produced:

| Frozen validation model | Brier score (lower is better) | Net-R mean absolute error |
| --- | ---: | ---: |
| Training-only constant baseline | 0.24954474 | 0.46478058 |
| Persistent online classifier/regressor | 0.24957225 | 0.46463015 |
| Fixed histogram gradient boosting | 0.24967177 | 0.46516009 |

Neither classifier improved Brier score. The small regression-error change is not evidence of a tradable advantage, and no promotion or runtime ingestion followed. Further model selection on this validation period would require a new untouched confirmation period.

On the local development machine, 200 incremental blocks learned 100,000 unique examples in **7.83 seconds**; a repeated 500-row block took **0.0073 seconds** and performed **zero** optimizer updates. Data loading, feature reconstruction and the nonlinear comparison brought the complete experiment to the duration in the receipt. These are local measurements, not production latency or a before/after speedup ratio.

Cumulative test-before-update metrics cover only decisions after all previously consumed outcomes are mature. Overlapping groups remain learnable but are excluded from measurement. Commit order and page boundaries can reduce this conservative historical subset; they do not turn it into decision-time prospective predictions. Frozen chronological validation is reported separately.

The next justified step is an immutable forward prediction/outcome stream for each actual strategy and market, followed by calibration and cost-aware candidate selection against untouched outcomes. Adding more packages or importing unvalidated history does not substitute for that evidence.
