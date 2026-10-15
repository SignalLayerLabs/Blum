# Decision Execution Parity Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make BLUM execute the exact strategy contract it validated, while directing bounded replay toward executable candidates closest to an evidence-backed paper-forward promotion.

**Architecture:** Add an immutable executable strategy specification and a pure point-in-time evaluator shared by replay and paper-forward. Persist strategy identity per replay trade, validate factory candidates by fingerprint, and use a read-only promotion frontier to select bounded replay research without weakening certified gates.

**Tech Stack:** Python 3, FastAPI service layer, SQLAlchemy 2, Alembic, PostgreSQL/SQLite JSON compatibility, pytest.

## Global Constraints

- Keep project version unchanged.
- No broker or real-money execution.
- No forced paper trade or guaranteed profitability.
- Certified promotion remains at least 300 validated trades and all existing robustness gates.
- Existing APIs remain backward compatible.
- No heavy computation in GET endpoints or frontend page loads.
- Replay, experimental paper, certified paper, and copy-readiness evidence remain separate.

---

### Task 1: Executable strategy contract and point-in-time evaluator

**Files:**
- Create: `backend/app/services/executable_strategy.py`
- Create: `backend/tests/test_executable_strategy.py`

**Interfaces:**
- Produces: `ExecutableStrategySpec.from_payload(payload: dict) -> ExecutableStrategySpec`
- Produces: `ExecutableStrategySpec.to_payload() -> dict`
- Produces: `ExecutableStrategySpec.fingerprint -> str`
- Produces: `StrategySignalEvaluator.evaluate(spec, bars_by_timeframe) -> StrategySignalEvaluation`
- Produces: `StrategySignalEvaluator.geometry(spec, entry_price, execution_history) -> TradeGeometry`

- [ ] **Step 1: Write failing tests** for deterministic fingerprints, supported rule validation, point-in-time breakout evaluation, distinct parameter behavior, and deterministic stop/target geometry.
- [ ] **Step 2: Run** `python3 -m pytest backend/tests/test_executable_strategy.py -q` and verify failures are caused by the missing module.
- [ ] **Step 3: Implement** frozen dataclasses and pure evaluator supporting `breakout_close` and `trend_continuation`, relative-volume filters, higher-timeframe alignment, ATR stops, target R, regime and market filters.
- [ ] **Step 4: Run** the focused tests and verify they pass.
- [ ] **Step 5: Commit** `feat: add executable strategy contract`.

### Task 2: Strategy-aware replay identity

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/0035_decision_execution_parity.py`
- Modify: `backend/app/services/hyperbolic_replay.py`
- Modify: `backend/tests/test_hyperbolic_replay_engine.py`

**Interfaces:**
- Adds: `HyperbolicReplayTrade.strategy_fingerprint: str`
- Adds: `ReplayRunRequest.strategy_specs: tuple[dict, ...] | None`
- Replay uniqueness becomes `(asset_id, strategy_fingerprint, timeframe, decision_timestamp)`.

- [ ] **Step 1: Write failing tests** proving two distinct strategy fingerprints can evaluate the same asset/timestamp and that replay persists the frozen strategy specification without future feature bars.
- [ ] **Step 2: Run** the focused replay tests and verify the expected failures.
- [ ] **Step 3: Add migration** with deterministic legacy backfill and cross-database batch alteration of the uniqueness constraint.
- [ ] **Step 4: Integrate evaluator** into replay; canonical defaults remain available when no explicit specs are supplied.
- [ ] **Step 5: Run** migration/model/replay tests and verify green.
- [ ] **Step 6: Commit** `feat: persist executable replay strategy identity`.

### Task 3: Real strategy variants and fingerprint-bound validation

**Files:**
- Modify: `backend/app/services/alpha_strategy_factory.py`
- Modify: `backend/app/services/promoted_strategy_registry.py`
- Modify: `backend/tests/test_alpha_strategy_factory.py`

**Interfaces:**
- Factory specifications include `executable_strategy` and `strategy_fingerprint`.
- Candidate evidence queries replay rows by fingerprint.
- Registry metrics expose the exact frozen executable strategy.

- [ ] **Step 1: Write failing tests** proving generated intraday variants have distinct executable parameters, unsupported labels are excluded, and evidence from one fingerprint cannot validate another.
- [ ] **Step 2: Run** the focused factory tests and verify the failures.
- [ ] **Step 3: Replace metadata-only intraday variants** with bounded combinations of breakout lookback, relative volume, trend threshold, ATR stop, target R, and holding bars.
- [ ] **Step 4: Bind evidence and registry projection** to the executable fingerprint and persist the exact contract in validation metrics.
- [ ] **Step 5: Run** factory and registry tests.
- [ ] **Step 6: Commit** `feat: validate real executable strategy variants`.

### Task 4: Replay-to-paper execution parity

**Files:**
- Modify: `backend/app/services/intraday_opportunity.py`
- Modify: `backend/app/services/intraday_contracts.py`
- Modify: `backend/app/services/intraday_paper_engine.py`
- Modify: `backend/tests/test_live_intraday_paper_engine.py`

**Interfaces:**
- `PromotedIntradayStrategy.executable_strategy` carries the frozen contract.
- Paper decisions include `strategy_fingerprint` and evaluator evidence.

- [ ] **Step 1: Write failing parity tests** showing identical bars/spec/entry produce identical trigger state, stop, and target through replay and paper adapters.
- [ ] **Step 2: Run** focused intraday tests and verify failures.
- [ ] **Step 3: Replace hard-coded live signal and geometry** with `StrategySignalEvaluator`; retain session, liquidity, cost, concentration, position-sizing, and future-fill gates.
- [ ] **Step 4: Freeze exact contract and fingerprint** into the paper candidate, order, trade, and ledger payloads.
- [ ] **Step 5: Run** intraday, execution, and paper lifecycle tests.
- [ ] **Step 6: Commit** `fix: enforce replay paper strategy parity`.

### Task 5: Promotion frontier and adaptive research focus

**Files:**
- Create: `backend/app/services/strategy_promotion_frontier.py`
- Modify: `backend/app/services/adaptive_replay_training.py`
- Modify: `backend/app/services/alpha_strategy_factory.py`
- Create: `backend/tests/test_strategy_promotion_frontier.py`
- Modify: `backend/tests/test_adaptive_replay_training.py`

**Interfaces:**
- Produces: `StrategyPromotionFrontierService.snapshot(db, limit=20) -> dict`
- Produces: `StrategyPromotionFrontierService.research_specs(db, limit, seed) -> tuple[dict, ...]`
- Training snapshot adds `promotion_frontier` and `research_strategy_fingerprints`.

- [ ] **Step 1: Write failing tests** for sample gap, cost/expectancy blockers, near-frontier prioritization, and preserved broad exploration.
- [ ] **Step 2: Run** focused tests and verify failures.
- [ ] **Step 3: Implement read-only frontier projection** from persisted candidate/validation evidence.
- [ ] **Step 4: Feed bounded specs into replay** using a deterministic blend of exploration, near-frontier exploitation, and failure replay.
- [ ] **Step 5: Persist research reason** in replay run and snapshot metadata.
- [ ] **Step 6: Run** frontier and adaptive replay tests.
- [ ] **Step 7: Commit** `feat: focus replay on promotion frontier`.

### Task 6: Regression, deployment, and production evidence

**Files:**
- Modify: `README.md`

**Interfaces:**
- Documents executable strategy parity, promotion frontier, evidence separation, and copy-readiness limitations.

- [ ] **Step 1: Update README** with architecture and operational behavior.
- [ ] **Step 2: Run** `python3 -m pytest -q` and record exact output.
- [ ] **Step 3: Run** `git diff --check` and inspect all changed files.
- [ ] **Step 4: Commit** documentation and any final test-only corrections.
- [ ] **Step 5: Push** `main` to the Hugging Face `hf` remote.
- [ ] **Step 6: Verify** Space SHA, runtime readiness, replay snapshot, factory frontier, scanner, lifecycle, and open-position state.
- [ ] **Step 7: Report** measured behavior; do not claim a position or alpha unless production evidence confirms it.

