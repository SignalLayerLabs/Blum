# Alpha Strategy Factory and Realistic Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Certify strategy candidates through statistically defensible replay and execute promoted candidates through an auditable paper order/fill lifecycle shared by replay and forward evaluation.

**Architecture:** Add pure statistical and execution domain services, additive SQLAlchemy persistence, and thin orchestration adapters around the existing replay, promoted-strategy registry, and intraday paper worker. Heavy work remains sliced and scheduled; existing GET snapshots only read precomputed state.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy 2, Alembic, NumPy, SciPy, APScheduler, pytest, SQLite/PostgreSQL-compatible JSON.

## Global Constraints

- Preserve current project version and feature-set identifiers.
- Keep existing APIs and financial behavior backward-compatible.
- Minimum candidate sample size is 300 evaluated trades.
- Replay and paper-forward must share the same cost taxonomy.
- No broker integration, real-money execution, invented fill, look-ahead data, or page-render computation.
- Existing unrelated untracked files must remain untouched.

---

### Task 1: Strategy Statistics Domain

**Files:**
- Create: `backend/app/services/strategy_factory_statistics.py`
- Test: `backend/tests/test_alpha_strategy_factory.py`

**Interfaces:**
- Produces: `PurgedFold`, `StrategyRobustnessResult`, `build_purged_folds()`, `block_bootstrap_interval()`, `benjamini_hochberg()`, `deflated_sharpe_probability()`, `backtest_overfitting_probability()`, `evaluate_strategy_robustness()`.

- [ ] Write failing tests proving purge/embargo exclusion, deterministic bootstrap intervals, multiple-testing correction, concentration penalties, and minimum-sample rejection.
- [ ] Run `python3 -m pytest backend/tests/test_alpha_strategy_factory.py -q` and verify failures refer to missing domain interfaces.
- [ ] Implement frozen domain records and pure deterministic functions. Use seeded NumPy generators and SciPy distributions; no database access.
- [ ] Run the focused tests and refactor duplicated numeric guards without changing outputs.

### Task 2: Additive Persistence

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/0033_alpha_strategy_factory_execution.py`
- Test: `backend/tests/test_alpha_strategy_factory.py`
- Test: `backend/tests/test_realistic_execution.py`

**Interfaces:**
- Produces ORM models `StrategyFactoryRun`, `StrategyCandidateVariant`, `StrategyValidationFold`, `StrategyPromotionEvent`, `PaperExecutionOrder`, and `PaperExecutionFill`.

- [ ] Add failing persistence tests for candidate fingerprint uniqueness, fold linkage, reversible promotion events, order uniqueness, and fill uniqueness.
- [ ] Run focused tests and confirm schema/model failures.
- [ ] Add SQLAlchemy models with indexed state fields and cross-database `JsonType` columns.
- [ ] Add migration `0033_alpha_factory_execution` after `0032_copy_readiness_evidence`, with JSON/JSONB variants, indexes, constraints, nullable compatibility links on existing replay and paper trade tables, and complete downgrade.
- [ ] Run model tests and an Alembic SQLite upgrade/downgrade smoke test.

### Task 3: Alpha Strategy Factory Orchestration

**Files:**
- Create: `backend/app/services/alpha_strategy_factory.py`
- Modify: `backend/app/services/replay_validation.py`
- Modify: `backend/app/services/promoted_strategy_registry.py`
- Modify: `backend/app/services/adaptive_replay_training.py`
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_alpha_strategy_factory.py`

**Interfaces:**
- Consumes: statistical interfaces and persistence models from Tasks 1-2.
- Produces: `StrategyFamilyRegistry`, `AlphaStrategyFactory.run_once()`, `ChampionChallengerRegistry.promote()`, and `strategy_factory_snapshot()`.

- [ ] Add failing tests for all ten family registrations, bounded deterministic variants, idempotent fingerprints, distinct rejection verdicts, automatic promotion, and champion replacement audit.
- [ ] Run focused tests and verify behavior failures.
- [ ] Implement specification factories as registered callables and persist bounded candidate batches.
- [ ] Adapt `ReplayWalkForwardValidator` to the stronger evaluator while preserving its public methods and legacy evidence compatibility.
- [ ] Strengthen `BlumPromotedStrategyRegistry` so only active champion promotions or compatible legacy validations passing all gates are eligible.
- [ ] Extend replay snapshots with examined/rejected/promoted/champion counts and primary blocker.
- [ ] Run factory, replay, promoted registry, and adaptive replay tests.

### Task 4: Realistic Execution Domain and Ledger

**Files:**
- Create: `backend/app/services/realistic_execution.py`
- Modify: `backend/app/services/replay_execution.py`
- Test: `backend/tests/test_realistic_execution.py`

**Interfaces:**
- Produces: immutable `ExecutionOrderRequest`, `ExecutionMarketBar`, `ExecutionDecision`, `ExecutionCostBreakdown`, and `RealisticExecutionEngine.evaluate()`.
- Produces: `PaperOrderLifecycleService.submit()`, `.process_order()`, and `.process_batch()`.

- [ ] Add failing tests for no future fill, unfilled limit order, volume-constrained partial fills, gap-through-stop, conservative same-bar stop/target ordering, dynamic slippage, explicit FX blocking, and separate theoretical/executed prices.
- [ ] Run focused tests and verify domain failures.
- [ ] Implement deterministic execution calculation without persistence or data fetching.
- [ ] Implement a persistence lifecycle service that writes submitted orders before fills, deduplicates events, and projects fills to linked paper trades.
- [ ] Adapt `ReplayExecutionModel` to expose the shared cost taxonomy while retaining its existing profile API.
- [ ] Run focused execution and existing replay tests.

### Task 5: Intraday Paper and Learning Integration

**Files:**
- Modify: `backend/app/services/intraday_paper_engine.py`
- Modify: `backend/app/services/intraday_opportunity.py`
- Modify: `backend/app/services/live_forward_paper_trading.py`
- Modify: `backend/app/services/copy_readiness_evidence.py`
- Test: `backend/tests/test_live_intraday_paper_engine.py`
- Test: `backend/tests/test_realistic_execution.py`

**Interfaces:**
- Consumes: promoted strategy and paper order lifecycle services.
- Produces: persisted execution orders/fills and terminal learning outcomes linked to `LiveForwardPaperTrade`.

- [ ] Add failing integration tests proving signals create orders rather than direct fills, later bars drive fills, costs persist per fill, partial/open states survive retries, and frozen decision payload remains immutable.
- [ ] Run focused integration tests.
- [ ] Delegate entry execution from `BlumIntradayPaperEngine` to the order lifecycle while retaining existing public run summaries and events.
- [ ] Map terminal execution outcomes to Learning Loop evidence: `CORRECT_NO_TRADE`, `MISSED_OPPORTUNITY`, `ORDER_NOT_FILLED`, `EDGE_DESTROYED_BY_COSTS`, and `SIGNAL_DECAY_BEFORE_ENTRY`.
- [ ] Preserve copy-readiness separation between replay and forward evidence.
- [ ] Run intraday, paper-forward, copy-readiness, and Alpha tests.

### Task 6: Runtime, Snapshot, and Documentation Integration

**Files:**
- Modify: `backend/app/services/realtime.py`
- Modify: `backend/app/services/worker_runtime.py`
- Modify: `backend/app/engine/brain/trader_brain.py`
- Modify: `README.md`
- Test: `backend/tests/test_alpha_strategy_factory.py`
- Test: `backend/tests/test_realistic_execution.py`
- Test: `backend/tests/test_live_intraday_paper_engine.py`

**Interfaces:**
- Produces sliced workers `alpha_strategy_factory` and `paper_execution_lifecycle` and compact read-only snapshot sections `strategy_factory` and `execution_reality`.

- [ ] Add failing tests that workers are independently registered, snapshots are read-only, and GET snapshot paths never execute factory or lifecycle work.
- [ ] Register bounded scheduler jobs with failure isolation and persisted worker state.
- [ ] Add compact snapshot payloads and maintain existing response fields.
- [ ] Document strategy certification, execution assumptions, evidence separation, configuration, and known limits.
- [ ] Run focused runtime and read-only tests.

### Task 7: Certification, Measurement, and Deployment

**Files:**
- Modify only files required by failures discovered in this task.

**Interfaces:**
- Produces verified migration, passing regression suite, production deployment, and measured production status.

- [ ] Run `python3 -m pytest backend/tests/test_alpha_strategy_factory.py backend/tests/test_realistic_execution.py backend/tests/test_hyperbolic_replay_engine.py backend/tests/test_live_intraday_paper_engine.py -q`.
- [ ] Run `python3 -m pytest -q`.
- [ ] Run the frontend production build without changing product routes.
- [ ] Run Alembic upgrade against a temporary SQLite database and verify downgrade/upgrade round trip.
- [ ] Run `git diff --check` and review the complete diff for conceptual integrity, hidden side effects, and accidental version changes.
- [ ] Commit implementation, push to the configured Hugging Face Space, and wait for runtime readiness.
- [ ] Verify production health, strategy factory snapshot, execution snapshot, and worker timestamps.
- [ ] Report actual examined/rejected/promoted counts and execution activity without claiming alpha or copy readiness.

