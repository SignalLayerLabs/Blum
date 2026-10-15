# Market Desk Agents and Cross-Market Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add evidence-bound market desks, Quant Edge validation, and diversified cross-market orchestration to the existing paper-forward candidate flow.

**Architecture:** Data-backed desk agents delegate asset evaluation to the existing Market Sniper engine, then a stored-evidence Quant Edge gate and a global orchestrator classify and rank candidates. The existing scanner and paper-forward service remain compatibility façades.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy 2, Pydantic settings, pytest.

## Global Constraints

- Do not add dashboards or pages.
- Do not add broker integration or real-money execution.
- Do not fabricate market data or opportunities.
- Run only desks with stored, recent market data; report skipped desks explicitly.
- Preserve existing APIs and paper-forward lifecycle separation.
- Do not change the project version.

---

### Task 1: Market Desk Registry and Contracts

**Files:**
- Create: `backend/app/services/market_desks.py`
- Test: `backend/tests/test_market_desk_orchestrator.py`

**Interfaces:**
- Produces: `MarketDeskResult`, `MarketDeskPolicy`, `BaseMarketDeskAgent.scan(Session, int)`, `MarketDeskRegistry.available(Session)`.
- Consumes: stored `Asset` and `PriceHistory`, plus an injected candidate evaluator callable.

- [ ] Write failing tests proving that a data-backed Nasdaq desk runs and an empty DAX desk is returned as skipped with `NO_ASSETS_CONFIGURED`.
- [ ] Run `python3 -m pytest backend/tests/test_market_desk_orchestrator.py -q` and verify missing imports fail.
- [ ] Implement immutable desk policies, result serialization, registry discovery, and distinct market predicates.
- [ ] Re-run the focused tests and verify they pass.

### Task 2: Stored-Evidence Quant Edge Gate

**Files:**
- Create: `backend/app/services/quant_edge.py`
- Modify: `backend/tests/test_market_desk_orchestrator.py`

**Interfaces:**
- Produces: `QuantEdgeAssessment`, `BlumQuantEdgeAgent.assess(Session, dict) -> dict`.
- Consumes: `SignalPerformance`, `StrategyMemory`, `HistoricalPrediction`, `PredictionOutcome`, `ExecutionSimulation`, and benchmark evidence where present.

- [ ] Add failing tests for `APPROVED_FOR_PAPER`, `REJECTED_INSUFFICIENT_SAMPLE`, and `REJECTED_OVERFITTING_RISK`.
- [ ] Run the focused tests and confirm the expected behavioral failures.
- [ ] Implement bounded aggregate queries and deterministic edge scoring without synthetic evidence.
- [ ] Re-run focused tests and verify all Quant Edge cases pass.

### Task 3: Cross-Market Orchestration and Diversification

**Files:**
- Create: `backend/app/services/cross_market_orchestrator.py`
- Modify: `backend/tests/test_market_desk_orchestrator.py`

**Interfaces:**
- Produces: `BlumCrossMarketOpportunityOrchestrator.run(Session, int | None) -> dict`.
- Consumes: `MarketDeskRegistry`, desk results, `BlumQuantEdgeAgent`, and orchestration settings.

- [ ] Add failing tests for enabled-agent invocation, ticker deduplication, market limits, asset-class limits, and quant-gated promotion.
- [ ] Run focused tests and verify the orchestrator is absent.
- [ ] Implement score normalization, global ranking, concentration limits, and detailed rejection summaries.
- [ ] Re-run focused tests and verify deterministic diversified output.

### Task 4: Scanner and Paper-Forward Integration

**Files:**
- Modify: `backend/app/services/paper_forward_opportunity_scanner.py`
- Modify: `backend/app/services/live_forward_paper_trading.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/tests/test_accelerated_global_trader_brain.py`
- Modify: `backend/tests/test_live_forward_paper_trading.py`

**Interfaces:**
- Preserves: `PaperForwardOpportunityScanner.scan()` and `LiveForwardPaperTradingService.run_once()`.
- Adds: orchestration settings and cross-market summary fields.

- [ ] Add failing compatibility tests asserting the scanner delegates to the orchestrator and `run_once()` freezes but does not open candidates.
- [ ] Run the affected tests and verify expected failures.
- [ ] Wire orchestration behind the existing scanner façade, with the legacy path retained when disabled.
- [ ] Re-run affected tests and ensure no lifecycle opening/closing occurs.

### Task 5: Snapshot Projection and Audit Report

**Files:**
- Modify: `backend/app/services/live_forward_paper_trading.py`
- Modify: `backend/tests/test_live_forward_paper_trading.py`
- Create: `MARKET_DESK_AGENTS_ORCHESTRATOR_REPORT.md`

**Interfaces:**
- Adds read-only snapshot fields required by the sprint while preserving existing payload keys.

- [ ] Add failing tests proving snapshot GET exposes latest stored desk/orchestrator evidence without scanning.
- [ ] Run the focused test and confirm missing fields fail.
- [ ] Extend the latest-event projection and snapshot payload; document measured examples and blockers.
- [ ] Re-run focused tests and confirm snapshot reads remain side-effect free.

### Task 6: Full Verification and Deployment

**Files:**
- Modify only files required by failures found during verification.

- [ ] Run `python3 -m compileall backend/app`.
- [ ] Run `python3 -m pytest backend/tests/test_market_desk_orchestrator.py backend/tests/test_accelerated_global_trader_brain.py backend/tests/test_live_forward_paper_trading.py -q`.
- [ ] Run `python3 -m pytest -q`.
- [ ] Start or inspect the backend; run the requested curl smoke checks, or record `BACKEND_NOT_RUNNING`.
- [ ] Rebuild and deploy the Hugging Face Space using the repository's established deployment procedure.
- [ ] Verify deployed paper-forward run, snapshot, and trades endpoints before reporting completion.
