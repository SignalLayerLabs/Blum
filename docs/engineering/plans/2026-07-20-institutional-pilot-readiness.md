# Institutional Pilot Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make BLUM's limited-capital pilot eligibility fail-closed and auditable while accelerating valid replay evidence production through a bounded, rotating promotion-frontier research mix.

**Architecture:** Extend the existing copy-readiness domain with a pure institutional pilot evaluator, then project it through the existing read-only Brain evidence service. Upgrade `StrategyPromotionFrontierService` to allocate bounded research lanes and consume persisted selection history; `BlumAdaptiveTrainingController` checkpoints that history and exposes useful-evidence telemetry without changing financial promotion gates.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2, Pydantic settings, pytest, Next.js/React, existing DashboardSnapshot and BackgroundJobState stores.

## Global Constraints

- Do not change the project version.
- Do not lower copy-readiness, promotion, robustness, cost, or forward-evidence gates.
- Do not add broker integration or real-money execution.
- No GET endpoint or frontend render may trigger research, recalculation, or database writes.
- Missing or stale evidence must fail closed.
- Replay, walk-forward, paper-forward, and live-forward evidence remain separate.
- Existing APIs and financial behavior remain backward-compatible.

---

### Task 1: Pure Institutional Pilot Policy

**Files:**
- Create: `backend/app/services/institutional_pilot.py`
- Create: `backend/tests/test_institutional_pilot.py`

**Interfaces:**
- Produces: `PilotPolicyThresholds`, `PilotReadinessContext`, `PilotReadinessDecision`, `evaluate_pilot_readiness(context, thresholds) -> PilotReadinessDecision`.
- Consumes: stored copy-readiness status/eligibility, promoted strategy count, evidence freshness, paper risk facts, and runtime/data integrity flags.

- [ ] **Step 1: Write failing tests for fail-closed status and conservative envelope**

Tests instantiate `PilotReadinessContext` directly and prove that missing evidence returns `NOT_ELIGIBLE`, valid replay-only evidence returns at most `ELIGIBLE_FOR_SHADOW_PILOT`, and limits remain `max_capital_percent=5.0`, `max_risk_per_trade_percent=0.25`, `max_aggregate_open_risk_percent=1.0`.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest tests/test_institutional_pilot.py -q`

Expected: import failure because `app.services.institutional_pilot` does not exist.

- [ ] **Step 3: Implement immutable policy inputs and decision output**

The evaluator must build explicit gates for strict capital eligibility, promoted exact strategy, freshness, benchmark validity, modeled execution, runtime health, data integrity, and risk envelope. It must return all failed gates and the next milestone.

- [ ] **Step 4: Add kill-switch tests and implementation**

Tests cover stale data, fingerprint mismatch, daily loss, drawdown, aggregate risk, negative expectancy/benchmark excess, degraded strategy, and runtime/persistence failure. Any one critical trigger returns `SUSPENDED` when prior eligibility existed and otherwise `NOT_ELIGIBLE`; `kill_switch.active` is true and lists the trigger.

- [ ] **Step 5: Run focused tests GREEN**

Run: `python -m pytest tests/test_institutional_pilot.py -q`

Expected: all institutional pilot policy tests pass.

### Task 2: Read-Only Evidence Projection and Brain Gate

**Files:**
- Modify: `backend/app/services/copy_readiness_evidence.py`
- Modify: `backend/app/services/brain_learning_proof.py`
- Modify: `backend/tests/test_copy_readiness_engine.py`
- Modify: `backend/tests/test_trader_brain.py`
- Modify: `frontend/components/BrainEvidenceCharts.tsx`

**Interfaces:**
- Consumes: `CopyReadinessSummaryService.summary`, `BrainLearningProofService._trading_proof`, `BlumPromotedStrategyRegistry.status`, and `evaluate_pilot_readiness`.
- Produces: `institutional_pilot` in `/api/brain/snapshot` and additional strict-capital threshold fields in `copy_readiness`.

- [ ] **Step 1: Write failing backend projection tests**

Add tests proving the copy summary exposes the 500/150/270 strict thresholds and Brain returns `institutional_pilot` without invoking any training, factory, or paper lifecycle method.

- [ ] **Step 2: Verify projection tests RED**

Run: `python -m pytest tests/test_copy_readiness_engine.py tests/test_trader_brain.py -q`

Expected: assertions fail because strict threshold and pilot fields are absent.

- [ ] **Step 3: Implement compact projection**

Build pilot context entirely from bounded persisted reads. `BrainLearningProofService.snapshot` calculates trading proof once, reads promoted registry status once, evaluates the pure policy, and returns both existing `copy_readiness` and new `institutional_pilot`. Stale `evaluated_at` must activate the freshness blocker.

- [ ] **Step 4: Humanize the existing Brain gate**

Rename the panel to `Pilot Capital Gate`; display pilot status, kill-switch state, maximum capital/risk limits, strict forward progress, top blockers, and next milestone. Keep a clear research-only disclaimer and make no extra request.

- [ ] **Step 5: Verify focused backend and frontend checks**

Run: `python -m pytest tests/test_copy_readiness_engine.py tests/test_trader_brain.py -q`

Run: `npm run build`

Expected: tests and clean frontend build pass.

### Task 3: Four-Lane Evidence Acceleration and Stagnation Rotation

**Files:**
- Modify: `backend/app/services/strategy_promotion_frontier.py`
- Modify: `backend/app/services/adaptive_replay_training.py`
- Modify: `backend/tests/test_strategy_promotion_frontier.py`
- Modify: `backend/tests/test_adaptive_replay_training.py`

**Interfaces:**
- Extends: `StrategyPromotionFrontierService.research_plan(db, *, limit, seed, selection_history=None)`.
- Produces: lane reasons `promotion_frontier`, `failure_replay`, `coverage_gap`, `broad_exploration`, plus `stalled_rotations`, sample sizes, and selection mix.
- Persists: `research_selection_history` inside `BackgroundJobState.cursor_json` beside the replay `asset_id` cursor.

- [ ] **Step 1: Write failing lane-allocation tests**

With eight candidate slots, assert a 4/2/1/1 target across promotion, failure, coverage, and broad exploration when eligible candidates exist. With fewer candidates, assert no duplicate fingerprint and non-zero broad exploration whenever at least two candidates exist.

- [ ] **Step 2: Verify lane tests RED**

Run: `python -m pytest tests/test_strategy_promotion_frontier.py -q`

Expected: current `near_frontier`/`broad_exploration` mix fails the new assertions.

- [ ] **Step 3: Implement deterministic lane selection**

Classify positive candidates nearest sample maturity as promotion frontier; select diagnostic failure cases with strong data quality for failure replay; choose setup/timeframe diversity for coverage; fill one random exploration slot. Deduplicate by exact fingerprint and backfill unused lane capacity from remaining ranked candidates.

- [ ] **Step 4: Write failing stagnation and cursor tests**

Assert candidates with three unchanged selections are rotated out of the preferred lane for three cycles, retried on a periodic probe, and that controller completion stores sample/count history without losing `asset_id`.

- [ ] **Step 5: Implement persisted history and rotation**

Read history from the current job cursor, pass it to `research_plan`, update each selected fingerprint with `last_sample_size` and `consecutive_no_progress`, keep a bounded maximum of 100 entries, and checkpoint the merged cursor. Runtime pause must preserve all history untouched.

- [ ] **Step 6: Add useful-evidence telemetry**

Expose generated/validated ratio, queue-starvation state, lane mix, stalled rotation count, and minimum promotion sample gap in the existing replay snapshot. These fields report throughput and never claim alpha.

- [ ] **Step 7: Run acceleration tests GREEN**

Run: `python -m pytest tests/test_strategy_promotion_frontier.py tests/test_adaptive_replay_training.py -q`

Expected: all frontier and controller tests pass.

### Task 4: Documentation, Regression, Merge, and Deployment

**Files:**
- Modify: `README.md`
- Create: `INSTITUTIONAL_PILOT_READINESS_REPORT.md`

**Interfaces:**
- Documents: strict pilot gates, kill switches, capital envelope, acceleration lanes, current production evidence, and non-goals.

- [ ] **Step 1: Document truthful operational behavior**

State that pilot eligibility is not guaranteed, forward time cannot be compressed, and acceleration applies to valid replay/validation throughput. Include the exact conservative pilot envelope.

- [ ] **Step 2: Run formatting and full regression**

Run: `git diff --check`

Run from `backend`: `python -m pytest -q`

Run from `frontend`: `npm run build`

Expected: no diff errors, all backend tests pass, frontend production build passes.

- [ ] **Step 3: Commit implementation**

Commit focused implementation and documentation changes without staging unrelated files.

- [ ] **Step 4: Integrate into `main` and upload to Hugging Face**

Fast-forward or cherry-pick the feature commits into `main`, push `main` to the configured Hugging Face Space remote, and wait for the Space runtime to become healthy.

- [ ] **Step 5: Verify production evidence**

Read `/api/brain/snapshot`, `/api/training/snapshot`, `/api/paper-forward/snapshot`, and `/api/alpha/snapshot`. Confirm the pilot gate is visible, no fabricated eligibility appears, workers remain healthy, and the deployed SHA matches the committed SHA.
