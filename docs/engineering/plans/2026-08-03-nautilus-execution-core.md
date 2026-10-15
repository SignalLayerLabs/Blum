# BLUM Deterministic Execution Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate NautilusTrader 1.230.0 as BLUM's deterministic shadow execution kernel for equity, ETF, and fiat Forex replay and paper-forward evidence.

**Architecture:** BLUM-owned immutable contracts define the execution port. A lazily imported Nautilus infrastructure adapter maps stored point-in-time bars and frozen BLUM decisions into deterministic runs, then normalizes results back into existing paper order/fill/trade projections. Shadow comparisons are persisted and can promote Nautilus to authoritative paper mode only after evidence gates pass.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL/SQLite tests, NautilusTrader 1.230.0, Parquet, pytest.

## Global Constraints

- Preserve all existing public endpoints and financial logic.
- No version bump.
- No crypto instruments, adapters, or evidence.
- No broker or real-money execution.
- No GET or frontend-triggered computation.
- No future data in replay or paper execution.
- `nautilus_trader` import failure must not prevent BLUM startup.
- Existing engine remains fallback until persisted parity gates promote Nautilus.
- Every projection, promotion, and rollback is idempotent and reversible.

---

### Task 1: Execution Kernel Contracts and Dependency Boundary

**Files:**
- Create: `backend/app/services/deterministic_execution/__init__.py`
- Create: `backend/app/services/deterministic_execution/contracts.py`
- Create: `backend/app/services/deterministic_execution/kernel.py`
- Modify: `backend/app/core/config.py`
- Modify: `requirements.txt`
- Test: `backend/tests/test_deterministic_execution_contracts.py`

**Interfaces:**
- Produces: `ExecutionKernel` protocol, `InstrumentSpec`, `MarketEvent`, `ExecutionIntent`, `KernelRunRequest`, `KernelOrderEvent`, `KernelPositionEvent`, `KernelRunResult`, and `KernelHealth`.
- Consumes: no Nautilus types.

- [ ] Write failing tests proving contracts are immutable, unknown asset classes fail, crypto fails, timestamps require timezone-neutral UTC ordering, and kernel health reports `UNAVAILABLE` when the optional import fails.
- [ ] Run `PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/test_deterministic_execution_contracts.py -q` and confirm missing-module failures.
- [ ] Implement frozen dataclasses and an `ExecutionKernel(Protocol)` with `run_replay`, `run_paper_step`, and `health`.
- [ ] Add config fields for enabled, mode, allowed asset classes, catalog path, parity thresholds, job budgets, and fallback.
- [ ] Pin `nautilus_trader==1.230.0` without crypto or broker extras.
- [ ] Re-run the focused tests and commit.

### Task 2: Canonical Instrument and Point-in-Time Data Projection

**Files:**
- Create: `backend/app/services/deterministic_execution/instruments.py`
- Create: `backend/app/services/deterministic_execution/catalog.py`
- Test: `backend/tests/test_deterministic_execution_catalog.py`

**Interfaces:**
- Consumes: `Asset`, `PriceHistory`, `ReplayMarketBar`, and Task 1 contracts.
- Produces: `BlumInstrumentMapper.map_asset(asset) -> InstrumentSpec` and `NautilusMarketDataProjector.project(db, *, cursor, limit, runtime_now) -> CatalogProjectionResult`.

- [ ] Write failing tests for equity, ETF, and fiat Forex mappings, precision, deterministic instrument IDs, crypto rejection, duplicate bar suppression, cursor resume, and exclusion of bars after `runtime_now`.
- [ ] Run the catalog tests and confirm expected failures.
- [ ] Implement canonical mappings using venue-neutral BLUM identifiers and explicit `asset_class` policy.
- [ ] Implement an incremental projector that reads bounded ORM rows, writes deterministic Parquet partitions through Nautilus `ParquetDataCatalog`, and returns a serializable cursor.
- [ ] If Nautilus is unavailable, return `UNAVAILABLE` without writing or advancing the cursor.
- [ ] Re-run tests and commit.

### Task 3: Nautilus Shadow Execution Adapter

**Files:**
- Create: `backend/app/services/deterministic_execution/nautilus_kernel.py`
- Create: `backend/app/services/deterministic_execution/normalization.py`
- Test: `backend/tests/test_nautilus_execution_kernel.py`

**Interfaces:**
- Consumes: Task 1 contracts and Task 2 instrument/data mapping.
- Produces: `NautilusExecutionKernel` implementing `ExecutionKernel`.

- [ ] Write failing tests for deterministic repeated runs, market and limit entries, stop triggers, bracket exits, no-fill expiry, partial fills where quote/bar volume permits, and strict no-look-ahead behavior.
- [ ] Run tests and verify the adapter is missing.
- [ ] Implement lazy Nautilus imports, `BacktestEngine` configuration, simulated venues/accounts, bar ingestion, and a small BLUM decision strategy which submits only frozen intents.
- [ ] Normalize Nautilus order and position events into Task 1 result types with deterministic fingerprints.
- [ ] Ensure the adapter never converts an unconfirmed plan into a market order.
- [ ] Run tests twice and assert identical fingerprints and event order; commit.

### Task 4: Persistence, Projection, and Shadow Parity

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/0042_deterministic_execution_core.py`
- Create: `backend/app/services/deterministic_execution/repository.py`
- Create: `backend/app/services/deterministic_execution/parity.py`
- Test: `backend/tests/test_deterministic_execution_parity.py`

**Interfaces:**
- Produces: `DeterministicExecutionRun`, `DeterministicExecutionEvent`, `ExecutionParityComparison`, and `ExecutionKernelState` persistence; `ExecutionParityEvaluator.compare(...)`.
- Consumes: existing `PaperExecutionOrder`, `PaperExecutionFill`, `LiveForwardPaperTrade`, and normalized kernel results.

- [ ] Write failing migration/model tests for SQLite JSON/PostgreSQL JSONB compatibility, unique run fingerprints, event uniqueness, and downgrade.
- [ ] Write failing behavior tests proving projection is idempotent, duplicate fills cannot be counted twice, and parity compares state, quantity, fill price, costs, P/L, and exit reason.
- [ ] Implement append-only repository and projection services.
- [ ] Implement parity status `MATCH`, `DIVERGED`, `INVALID`, or `INSUFFICIENT_DATA` with explicit reasons.
- [ ] Apply migration to a fresh SQLite database and run model/parity tests; commit.

### Task 5: Risk Bridge, Promotion, and Automatic Rollback

**Files:**
- Create: `backend/app/services/deterministic_execution/risk.py`
- Create: `backend/app/services/deterministic_execution/promotion.py`
- Test: `backend/tests/test_deterministic_execution_promotion.py`

**Interfaces:**
- Produces: `BlumNautilusRiskBridge.evaluate(...)`, `ExecutionKernelPromotionService.evaluate(db)`, and reversible kernel state.
- Consumes: existing BLUM risk decisions plus parity evidence from Task 4.

- [ ] Write failing tests for invalid precision, excessive notional, missing point-in-time FX, `HALTED`, `REDUCING`, stricter-gate-wins, minimum 100 samples, cross-asset/regime coverage, divergence limits, promotion, and rollback.
- [ ] Run tests and confirm expected failures.
- [ ] Implement the risk bridge without weakening existing risk gates.
- [ ] Implement automatic promotion only to `AUTHORITATIVE_PAPER`; never enable live execution.
- [ ] Implement rollback to `SHADOW` on invariant, duplicate-fill, look-ahead, or accounting violations.
- [ ] Re-run tests and commit.

### Task 6: Bounded Background Worker and Existing Paper-Forward Integration

**Files:**
- Create: `backend/app/services/deterministic_execution/worker.py`
- Modify: `backend/app/services/worker_runtime.py`
- Modify: `backend/app/services/autonomous_engine.py`
- Modify: `backend/app/services/live_forward_paper_trading.py`
- Modify: `backend/app/services/forex_trader.py`
- Test: `backend/tests/test_deterministic_execution_worker.py`

**Interfaces:**
- Produces: resumable stages `catalog`, `shadow_replay`, `paper_step`, `parity`, and `promotion`.
- Consumes: frozen paper decisions and existing background job state.

- [ ] Write failing tests proving the worker respects item/runtime budgets, resumes from cursor, survives missing Nautilus, and never runs from a GET.
- [ ] Write failing integration tests proving equity/ETF and Forex frozen decisions are shadowed without changing their current authoritative outcomes.
- [ ] Implement worker stages and register them with the autonomous scheduler.
- [ ] Add shadow submission hooks after frozen intent persistence, never before risk approval.
- [ ] In authoritative paper mode, project Nautilus events through Task 4 while retaining fallback on adapter failure.
- [ ] Run focused worker plus existing paper-forward/Forex tests and commit.

### Task 7: Snapshot, Diagnostics, and Documentation

**Files:**
- Modify: `backend/app/services/dashboard_snapshots.py`
- Modify: `backend/app/services/unified_paper_trading.py`
- Modify: `backend/app/services/central_brain_runtime.py`
- Modify: `backend/app/api/routers/runtime.py`
- Modify: `README.md`
- Test: `backend/tests/test_deterministic_execution_snapshot.py`

**Interfaces:**
- Produces: snapshot type `deterministic_execution_summary` and read-only endpoint `GET /api/runtime/execution-kernel`.

- [ ] Write failing tests for empty, unavailable, shadow, authoritative, stale, and quarantined states.
- [ ] Assert GET does not create runs, catalog rows, parity comparisons, or background jobs.
- [ ] Implement a compact snapshot with version, mode, catalog freshness, runs, throughput, parity, violations, blocker, and next action.
- [ ] Add the snapshot to runtime health and unified paper metadata without changing existing market splits.
- [ ] Document architecture, LGPL attribution, configuration, shadow gates, and exclusions.
- [ ] Run snapshot/API tests and commit.

### Task 8: Certification, Deployment, and Measurement

**Files:**
- Modify only files required by failures attributable to this integration.

**Interfaces:**
- Produces: measured build, test, replay throughput, memory, startup, and endpoint evidence.

- [ ] Run all deterministic execution tests plus existing Forex, paper-forward, unified paper, Brain, scheduler, startup, and GET-side-effect suites.
- [ ] Run `python3 -m compileall -q backend/app` and `git diff --check`.
- [ ] Run the full backend suite and distinguish new failures from reproducible baseline failures.
- [ ] Build the Docker image with the pinned wheel and measure image-size delta.
- [ ] Run a deterministic replay benchmark twice and report events/second, wall time, peak memory, and identical fingerprint status.
- [ ] Commit final documentation adjustments.
- [ ] Fast-forward `main`, push Hugging Face, wait for Space `RUNNING`, and verify health plus the execution-kernel snapshot.
- [ ] Report actual capability, measurements, parity sample count, blockers, and remaining limitations without claiming alpha.
