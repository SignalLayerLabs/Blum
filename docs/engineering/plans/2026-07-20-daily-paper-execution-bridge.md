# Daily Paper Execution Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every newly opened daily paper-forward position originate from a persisted realistic execution order and fill.

**Architecture:** Add a narrow daily adapter inside `LiveForwardPaperTradingService` that maps frozen entry rules to `ExecutionOrderRequest`, converts stored `PriceHistory` to `ExecutionMarketBar`, and delegates fill decisions to `PaperOrderLifecycleService`. Existing position, ledger, capital, and event projection remains owned by the live-forward service and runs only after a persisted fill.

**Tech Stack:** Python 3, SQLAlchemy, SQLite/PostgreSQL-compatible models, pytest.

## Global Constraints

- No broker integration or real-money execution.
- No source-code self-modification.
- No GET-side execution or recalculation.
- No project version change.
- Existing APIs and historical rows remain backward-compatible.
- No fill without a stored market bar later than the frozen decision timestamp.

---

### Task 1: Daily execution adapter

**Files:**
- Modify: `backend/app/services/live_forward_paper_trading.py`
- Test: `backend/tests/test_live_forward_paper_trading.py`

**Interfaces:**
- Consumes: `PaperOrderLifecycleService.submit()`, `PaperOrderLifecycleService.process_order()`, `ExecutionOrderRequest`, `ExecutionMarketBar`, `PriceHistory`.
- Produces: `submit_or_process_candidate_order(db, game, trade, condition) -> dict` and `process_pending_daily_orders(db, game) -> dict`.

- [ ] Write failing tests proving a trigger creates one persisted order/fill, uses an executed price with costs, and duplicate lifecycle calls do not duplicate orders or fills.
- [ ] Run the tests and verify failure because daily lifecycle currently bypasses execution persistence.
- [ ] Map frozen `MARKET`, breakout, and pullback entry types to explicit market/stop/limit orders; reject unsupported mappings.
- [ ] Convert only stored later OHLCV rows to execution bars with conservative estimated spread and volatility metadata.
- [ ] Submit/process orders idempotently and project a position only after a fill.
- [ ] Mark expired unfilled orders as `ORDER_NOT_FILLED` evidence without counting a closed trade.
- [ ] Run targeted tests until green.

### Task 2: Regression verification and release

**Files:**
- Modify only files required by Task 1.

**Interfaces:**
- Consumes: the completed daily execution adapter.
- Produces: a deployable backward-compatible paper-forward lifecycle.

- [ ] Run `python -m pytest tests/test_live_forward_paper_trading.py tests/test_realistic_execution.py -q` from `backend`.
- [ ] Run `git diff --check` and inspect the scoped diff.
- [ ] Commit only the execution bridge, tests, specification, and plan.
- [ ] Push `main` to the Hugging Face Space remote and verify local/remote commit parity.
