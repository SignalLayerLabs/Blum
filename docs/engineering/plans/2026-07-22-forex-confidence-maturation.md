# Forex Confidence Maturation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Forex confidence informative and evidence-driven while restoring a clear equity/Forex split in Paper Trading.

**Architecture:** Extend the existing Forex contracts and agents with component confidence, keep actionability vetoes separate, make the bounded refresh scheduler satisfy its own freshness window, and filter the existing unified snapshot client-side. Strategy promotion continues through the existing validated registry.

**Tech Stack:** FastAPI, SQLAlchemy, Python dataclasses, pytest, Next.js/React, TypeScript.

## Global Constraints

- Do not inflate confidence or lower strategy promotion gates.
- Do not permit stale evidence to execute.
- Do not add computation or writes to GET endpoints.
- Do not add frontend-triggered learning.
- Do not change the project version.

---

### Task 1: Paper Trading market tabs

**Files:**
- Modify: `frontend/app/paper-trading/page.tsx`
- Test: `backend/tests/test_trader_brain.py`

**Interfaces:**
- Consumes: existing unified snapshot `trades[].market_group` and `trades[].asset_type`.
- Produces: client-side `equities` and `forex` filtered views with no new request.

- [ ] Add a failing source test requiring `Azioni / ETF`, `Forex`, default equity state, and one snapshot fetch.
- [ ] Run the focused test and confirm failure.
- [ ] Add the tab control and filter all three journal sections from the selected market rows.
- [ ] Run the focused test and frontend build.

### Task 2: Confidence ladder

**Files:**
- Modify: `backend/app/services/forex_contracts.py`
- Modify: `backend/app/services/forex_agents.py`
- Modify: `backend/app/services/forex_trader.py`
- Modify: `backend/app/services/unified_paper_trading.py`
- Test: `backend/tests/test_forex_trader_core.py`
- Test: `backend/tests/test_unified_paper_trading.py`

**Interfaces:**
- Produces: `confidence_components` and normalized `decision_confidence` in `proposal_json`.
- Preserves: `EvaluationOutcome.approved` as the only execution eligibility result.

- [ ] Add failing tests proving a blocker does not erase analytical component scores.
- [ ] Add failing tests proving stale data still prevents approval.
- [ ] Add failing tests proving strategy confidence is sample-aware.
- [ ] Implement component calculation and persist it in the frozen proposal.
- [ ] Project component values into Paper Trading detail.
- [ ] Run focused tests.

### Task 3: Freshness-aware pair refresh

**Files:**
- Modify: `backend/app/services/forex_trader.py`
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_forex_trader_core.py`

**Interfaces:**
- Produces: deterministic oldest-first selected assets and refresh coverage metadata.
- Uses: `AgentMarketInput.blockers()` three-minute one-minute freshness contract.

- [ ] Add failing tests for a minimum four-pair batch with twelve configured pairs.
- [ ] Add failing tests for oldest-first ordering.
- [ ] Implement dynamic batch sizing and stale-first selection within bounded limits.
- [ ] Persist selected-pair and freshness-budget diagnostics in cycle output.
- [ ] Run focused tests.

### Task 4: Forex strategy evidence bridge

**Files:**
- Modify: existing strategy factory/replay metadata builder identified by tests.
- Modify: `backend/app/services/promoted_strategy_registry.py` only if projection metadata is incomplete.
- Test: strategy factory and Forex repository tests.

**Interfaces:**
- Produces: stored validations with `markets_json=["FOREX"]`, `supported_asset_classes=["Forex"]`, and `timeframe_stack=["1h","15m","5m","1m"]`.
- Consumes: existing 50-sample experimental and 300-sample certified gates.

- [ ] Add a failing test showing a valid Forex replay row reaches `ForexStrategyRepository`.
- [ ] Add a failing test showing incomplete evidence remains training-only.
- [ ] Add Forex metadata to existing replay candidates without changing statistical gates.
- [ ] Run focused tests.

### Task 5: Certification and deployment

**Files:**
- Modify: `README.md` with confidence semantics and Paper Trading tabs.

- [ ] Run `PYTHONPATH=backend .venv/bin/python -m pytest -q`.
- [ ] Run the Next.js production build.
- [ ] Run `git diff --check`.
- [ ] Commit only sprint files and push `main` to the Hugging Face Space.
- [ ] Verify the public snapshot and Paper Trading page after background refresh.
