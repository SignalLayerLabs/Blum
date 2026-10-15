# BLUM FinRL-X Quant Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate a safe, optional FinRL-X-compatible challenger boundary into BLUM's existing Trading ML governance.

**Architecture:** A dependency-free BLUM contract validates external manifests and normalizes policy proposals. Optional heavy training remains a bounded subprocess; BLUM's existing registry, walk-forward validation, risk engine, and paper execution remain authoritative.

**Tech Stack:** Python 3.13, dataclasses, Pydantic settings, SQLAlchemy, pytest, existing BLUM Trading ML services.

## Global Constraints

- Do not add FinRL-X, PyTorch, or Stable-Baselines3 to application startup dependencies.
- Do not permit an external policy to bypass deterministic blockers or BLUM risk.
- Do not add broker or real-money execution.
- Do not perform training or recalculation in GET endpoints.
- Do not change the project version.
- Preserve the current public API.

---

### Task 1: Artifact and Proposal Contracts

**Files:**
- Create: `backend/app/services/trading_ml/finrlx.py`
- Test: `backend/tests/test_finrlx_quant_engine.py`

**Interfaces:**
- Produces: `FinRLXArtifactManifest`, `QuantPolicyProposal`, `FinRLXArtifactValidator`.

- [ ] **Step 1: Write failing contract tests**

Test valid manifests, hash mismatch, schema mismatch, unsupported algorithms,
market mismatch, malformed action output, and immutable proposal semantics.

- [ ] **Step 2: Run the focused test and verify missing imports fail**

Run: `python3 -m pytest backend/tests/test_finrlx_quant_engine.py -q`

- [ ] **Step 3: Implement immutable contracts and validation**

Use JSON manifests, SHA-256 artifact verification, canonical schema hashes, an
algorithm allow-list (`PPO`, `SAC`, `TD3`, `DDPG`, `A2C`, `DETERMINISTIC`), and
normalized `HOLD`, `LONG`, `SHORT`, or target-weight proposals.

- [ ] **Step 4: Run focused tests**

Run: `python3 -m pytest backend/tests/test_finrlx_quant_engine.py -q`

### Task 2: Optional Runner Boundary

**Files:**
- Modify: `backend/app/services/trading_ml/finrlx.py`
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_finrlx_quant_engine.py`

**Interfaces:**
- Produces: `FinRLXQuantEngine.status()`, `FinRLXQuantEngine.run_training()`,
  and `FinRLXQuantEngine.propose()`.

- [ ] **Step 1: Write failing unavailable, timeout, and idempotency tests**

- [ ] **Step 2: Verify the tests fail**

Run: `python3 -m pytest backend/tests/test_finrlx_quant_engine.py -q`

- [ ] **Step 3: Implement an opt-in subprocess runner**

Require an explicit executable path, bounded timeout, immutable input/output
paths, and atomic artifact publication. An unavailable runner must return
structured status without raising into the trading cycle.

- [ ] **Step 4: Run focused tests**

Run: `python3 -m pytest backend/tests/test_finrlx_quant_engine.py -q`

### Task 3: BLUM Decision Guardrails

**Files:**
- Modify: `backend/app/services/trading_ml/inference.py`
- Modify: `backend/app/services/forex_trader.py`
- Test: `backend/tests/test_finrlx_quant_engine.py`
- Test: `backend/tests/test_forex_ml_integration.py`

**Interfaces:**
- Consumes: `QuantPolicyProposal`.
- Produces: auditable external challenger metadata with zero adjustment whenever
  deterministic blockers exist.

- [ ] **Step 1: Write failing blocker and bounded-influence tests**

- [ ] **Step 2: Verify the tests fail**

- [ ] **Step 3: Add challenger advice as a separate proposal channel**

Do not change stops, targets, lots, margin decisions, or execution requests.

- [ ] **Step 4: Run focused integration tests**

Run: `python3 -m pytest backend/tests/test_finrlx_quant_engine.py backend/tests/test_forex_ml_integration.py -q`

### Task 4: Worker Status and Documentation

**Files:**
- Modify: `backend/app/services/trading_ml/worker.py`
- Modify: `README.md`
- Test: `backend/tests/test_trading_ml_worker.py`

**Interfaces:**
- Produces: snapshot-visible `finrlx` availability, last attempt, and blocker
  status without invoking training from reads.

- [ ] **Step 1: Write failing worker status tests**
- [ ] **Step 2: Verify failure**
- [ ] **Step 3: Add bounded optional worker invocation and status**
- [ ] **Step 4: Document setup, provenance pin, and paper-only limitations**
- [ ] **Step 5: Run focused worker tests**

### Task 5: Verification and Deployment

**Files:**
- No new production files.

- [ ] **Step 1: Run the full backend suite**

Run: `python3 -m pytest backend/tests -q`

- [ ] **Step 2: Verify no version change and inspect the diff**

Run: `git diff --check && git status --short`

- [ ] **Step 3: Commit the implementation**

- [ ] **Step 4: Push to the Hugging Face Space**

- [ ] **Step 5: Verify runtime readiness and that Forex/paper cycles continue**

