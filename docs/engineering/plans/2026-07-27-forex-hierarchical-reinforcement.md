# Forex Hierarchical Reinforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make robust Forex paper outcomes influence later confidence and risk decisions through hierarchical, auditable policy memory.

**Architecture:** Extend the current contextual bandit with four backoff scopes stored in existing policy states and scope-specific immutable updates. Resolve eligible parent and child memories in the Decision Agent and expose a negative-edge veto to the Risk Agent.

**Tech Stack:** Python 3.11, SQLAlchemy 2, Alembic, FastAPI service layer, pytest.

## Global Constraints

- Do not change the BLUM version.
- Keep all execution paper-only.
- Do not weaken spread, slippage, liquidity, event or portfolio risk controls.
- Do not perform writes or policy recalculation in GET endpoints.
- Preserve existing policy history and API compatibility.

---

### Task 1: Scope-Specific Persistence

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/0039_forex_hierarchical_reinforcement.py`
- Test: `backend/tests/test_forex_reinforcement_policy.py`

**Interfaces:**
- Produces: `ForexPolicyUpdate.policy_scope: str`
- Produces: `ForexPolicyState.cause_counts_json: dict`
- Constraint: one update per `(evidence_id, policy_scope)`

- [ ] Write a failing schema test that stores four updates for one evidence.
- [ ] Run the focused test and verify the current unique evidence constraint fails.
- [ ] Add the model fields and cross-database Alembic migration.
- [ ] Run the focused schema test and verify it passes.

### Task 2: Hierarchical Policy Updates

**Files:**
- Modify: `backend/app/services/forex_reinforcement.py`
- Test: `backend/tests/test_forex_reinforcement_policy.py`

**Interfaces:**
- Produces: `ForexReinforcementPolicyService.observe(db, evidence) -> dict`
- Produces four scopes: `STRATEGY`, `SETUP`, `REGIME_SETUP`, `FULL_CONTEXT`
- Produces: `ForexReinforcementPolicyService.replay_pending(db, limit=50) -> dict`

- [ ] Write failing tests for four-scope updates, idempotency and incremental backfill.
- [ ] Run the tests and confirm they fail because only one exact state exists.
- [ ] Implement scope generation, scoped audit checks and cause aggregation.
- [ ] Implement asymmetric evidence gates: 30 positive, 12 negative.
- [ ] Run focused tests and verify all policy tests pass.

### Task 3: Decision Resolution and Risk Veto

**Files:**
- Modify: `backend/app/services/forex_agents.py`
- Modify: `backend/app/services/forex_trader.py`
- Test: `backend/tests/test_forex_trader_core.py`

**Interfaces:**
- Consumes: policy cells containing `policy_scope`, `sample_size`, `q_value` and `confidence_adjustment`
- Produces: proposal `knowledge_context.hierarchical_policy_adjustment`
- Produces: `POLICY_NEGATIVE_EDGE` risk objection

- [ ] Write failing tests for parent backoff, insufficient positive evidence and negative-policy veto.
- [ ] Run focused tests and verify failures reflect missing hierarchical resolution.
- [ ] Implement deterministic policy matching and bounded weighted resolution.
- [ ] Add scope and cause fields to strategy memory projection.
- [ ] Add the negative eligible policy veto without bypassing existing gates.
- [ ] Run focused tests and verify the decision output records its complete policy trace.

### Task 4: Regression, Migration and Deployment

**Files:**
- Modify only files required by failures found in verification.

**Interfaces:**
- Verifies all existing APIs and scheduler behavior remain compatible.

- [ ] Run Alembic head validation.
- [ ] Run all Forex tests.
- [ ] Run `python3 -m pytest backend/tests -q`.
- [ ] Run frontend production build to detect cross-surface regressions.
- [ ] Commit the implementation.
- [ ] Push to Hugging Face and wait for the deployed SHA.
- [ ] Verify runtime health and read-only Paper Trading snapshots in production.
