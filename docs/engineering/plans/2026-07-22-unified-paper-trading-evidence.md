# Unified Paper Trading Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface Forex paper-forward activity in the canonical Paper Trading journal and include eligible Forex outcomes exactly once in BLUM's aggregate paper performance.

**Architecture:** Add a background-only unified read projector over the existing paper-forward and Forex source tables. Persist its normalized journal and metrics in `DashboardSnapshot`, make the Paper Trading GET snapshot-only, and let Brain/Alpha consume the same evidence while preserving source-specific splits.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2, PostgreSQL/SQLite, pytest, Next.js, React, TypeScript.

## Global Constraints

- No source trade row may be copied, mutated, or counted twice.
- No GET endpoint or frontend mount may generate trading, learning, or projection work.
- Historical replay cannot be mixed into forward-paper metrics.
- Missing financial values remain `null`; no fabricated prices, fills, P/L, benchmark excess, or Alpha.
- Existing paper-forward and Forex APIs remain backward compatible.
- No broker or real-money execution path.

---

### Task 1: Unified projection domain and metrics

**Files:**
- Create: `backend/app/services/unified_paper_trading.py`
- Create: `backend/tests/test_unified_paper_trading.py`

**Interfaces:**
- Produces: `UnifiedPaperTradingProjectionService.build(db, limit=50) -> dict`
- Produces: `UnifiedPaperTradingProjectionService.publish(db, limit=50) -> dict`
- Produces: `UnifiedPaperTradingProjectionService.latest(db) -> dict`
- Produces: `UnifiedPaperTradingProjectionService.detail(db, source_engine, source_trade_id) -> dict | None`

- [ ] Write failing tests creating standard, intraday and Forex records and asserting canonical source-qualified IDs, source labels and lifecycle fields.
- [ ] Run `../.venv/bin/python -m pytest tests/test_unified_paper_trading.py -q` and verify RED because the service is absent.
- [ ] Implement normalization for `LiveForwardPaperTrade`, `ForexPosition`, rejected `ForexDecision`, and linked `ForexLearningEvidence`.
- [ ] Implement deduplication by `(source_engine, source_trade_id)` and suppress a Forex decision row when its position is present.
- [ ] Implement aggregate and per-market counts, realized/unrealized P/L, win rate, average/median R, expectancy R, profit factor, drawdown and benchmark excess with contributing sample counts.
- [ ] Keep rejected/no-trade decisions out of trade P/L and retain them in decision counts.
- [ ] Run focused tests and verify GREEN.

### Task 2: Snapshot lifecycle and read API

**Files:**
- Modify: `backend/app/services/forex_trader.py`
- Modify: `backend/app/services/live_forward_paper_trading.py`
- Modify: `backend/app/api/routers/paper_trading.py`
- Test: `backend/tests/test_unified_paper_trading.py`

**Interfaces:**
- Consumes: `UnifiedPaperTradingProjectionService.publish/latest/detail`
- Produces: `GET /api/paper-trading/snapshot`
- Produces: `GET /api/paper-trading/trades/{source_engine}/{source_trade_id}`

- [ ] Add failing tests proving GET reads only `unified_paper_trading_summary` and does not write.
- [ ] Add failing tests proving Forex and generic worker completion refresh the unified snapshot.
- [ ] Publish the projection after a completed Forex cycle and after paper-forward snapshot publication.
- [ ] Make `/api/paper-trading/snapshot` return the latest persisted unified snapshot.
- [ ] Add bounded, source-aware lazy detail retrieval without lifecycle side effects.
- [ ] Run focused API and worker tests.

### Task 3: Brain and Alpha evidence integration

**Files:**
- Modify: `backend/app/engine/brain/trader_brain.py`
- Test: `backend/tests/test_unified_paper_trading.py`
- Test: `backend/tests/test_trader_brain.py`

**Interfaces:**
- Consumes: persisted `unified_paper_trading_summary`
- Produces: `brain.paper_trading_performance`
- Produces: `alpha.evidence_split.forex_paper_forward`

- [ ] Write failing tests proving Brain exposes aggregate and source breakdown from the snapshot.
- [ ] Write failing tests proving Alpha reports Forex separately and does not upgrade evidence from open/rejected trades.
- [ ] Add read-only Brain integration with freshness and contributing sample size.
- [ ] Add Forex Alpha split from terminal `ForexPosition`/`ForexLearningEvidence` evidence only.
- [ ] Include mature Forex closed outcomes in top-level paper totals without blending the separate evidence split.
- [ ] Run Trader Brain and unified projection tests.

### Task 4: Paper Trading product surface

**Files:**
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/app/paper-trading/page.tsx`

**Interfaces:**
- Consumes: `GET /api/paper-trading/snapshot`
- Consumes lazily: `GET /api/paper-trading/trades/{source_engine}/{source_trade_id}`

- [ ] Replace the two initial paper-forward requests with one unified snapshot request.
- [ ] Render aggregate cards from `metrics.aggregate` and counts from `counts.aggregate`.
- [ ] Add compact Standard, Intraday and Forex breakdown cards with sample/evidence warnings.
- [ ] Normalize source-qualified IDs and display `FOREX`, `INTRADAY`, or source market labels on every journal row.
- [ ] Add an All/Standard/Intraday/Forex market filter.
- [ ] Dispatch lazy Trade Replay through the source-aware detail endpoint.
- [ ] Preserve explicit empty, blocked, stale and partial-source states.
- [ ] Run frontend typecheck/build and verify no POST call exists on mount.

### Task 5: Regression, documentation, commit and deployment

**Files:**
- Modify: `README.md`

- [ ] Document unified paper evidence, source separation and aggregate metric rules.
- [ ] Run `../.venv/bin/python -m pytest -q` from `backend`.
- [ ] Run `../.venv/bin/python -m compileall -q app tests` from `backend`.
- [ ] Run the frontend build using the repository package manager.
- [ ] Run `git diff --check` and inspect the final diff for unrelated files.
- [ ] Commit implementation without staging `blum_market_desk_agents_audit.zip`.
- [ ] Push `main` to Hugging Face and verify runtime SHA, Paper Trading HTTP 200, unified snapshot contents and autonomous Forex projection refresh.
