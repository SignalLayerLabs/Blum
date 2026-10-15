# Evidence Acceleration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist real Brain score history and advance paper-forward decisions to deterministic outcomes faster without weakening evidence standards.

**Architecture:** Add a background-only evidence projector keyed to productive learning state, coordinate candidate scanning with lifecycle advancement, and enforce a configurable time stop for every open paper-forward position. Existing read models and evidence classes remain unchanged.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy, APScheduler, PostgreSQL/SQLite tests, pytest.

## Global Constraints

- Do not lower the 5 Brain snapshot minimum.
- Do not lower the 30 closed paper-forward trade minimum.
- Do not fabricate prices, trades, outcomes, or score history.
- Do not add computation or writes to GET endpoints.
- Do not mix replay evidence with paper-forward evidence.
- Do not change the project version.

---

### Task 1: Evidence-aware Brain Score Projector

**Files:**
- Modify: `backend/app/services/learning_intelligence.py`
- Modify: `backend/app/services/realtime.py`
- Test: `backend/tests/test_brain_evidence_acceleration.py`

**Interfaces:**
- Consumes: latest productive `LearningRun`, current trade sample, `BlumTradingPowerScoreService.calculate()`.
- Produces: `BlumTradingPowerScoreService.persist_if_evidence_changed(db) -> dict`.

- [ ] Write tests proving empty evidence is skipped, productive evidence is persisted, and unchanged evidence is deduplicated.
- [ ] Run the focused tests and confirm they fail before implementation.
- [ ] Implement a stable evidence fingerprint and persist it in `warnings_json`.
- [ ] Invoke the projector after the professional learning worker completes its bounded work.
- [ ] Run focused tests and commit.

### Task 2: Coordinated Paper-forward Worker

**Files:**
- Modify: `backend/app/services/realtime.py`
- Test: `backend/tests/test_brain_evidence_acceleration.py`

**Interfaces:**
- Consumes: `LiveForwardPaperTradingService.run_once()` and `.run_lifecycle()`.
- Produces: scheduled result with separate `scan` and `lifecycle` payloads.

- [ ] Write a failing test asserting scan executes before lifecycle when lifecycle is enabled.
- [ ] Implement the bounded two-phase worker without changing manual endpoints.
- [ ] Run focused tests and commit.

### Task 3: Deterministic Paper-forward Time Stop

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/services/live_forward_paper_trading.py`
- Test: `backend/tests/test_brain_evidence_acceleration.py`

**Interfaces:**
- Consumes: frozen `trade_plan.expected_holding_days`, `opened_at`, `decision_timestamp`.
- Produces: `PAPER_FORWARD_MAX_HOLDING_DAYS` configuration and non-null `expires_at` for open positions.

- [ ] Write failing tests for new-position expiry and legacy open-position backfill.
- [ ] Add the bounded holding-period parser and ten-day default.
- [ ] Backfill missing expiration before close evaluation and preserve deterministic time-exit behavior.
- [ ] Run focused tests and commit.

### Task 4: Regression Verification and Deployment

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: all previous tasks.
- Produces: tested and deployed evidence acceleration behavior.

- [ ] Document background score snapshots, coordinated paper-forward cycles, and time-stop behavior.
- [ ] Run `python -m pytest backend/tests/test_brain_evidence_acceleration.py -q`.
- [ ] Run the complete backend pytest suite and shell syntax checks.
- [ ] Push to the Hugging Face Space without changing hardware tier.
- [ ] Verify runtime and snapshot endpoints, then report current evidence limitations honestly.
