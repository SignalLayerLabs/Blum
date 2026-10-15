# Live Intraday Paper Scalping Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make BLUM run strict real-data intraday paper trades only from replay-promoted strategies, manage those trades with later one-minute bars, and feed closed outcomes into forward-only learning evidence.

**Architecture:** Add focused registry, data, evaluation, portfolio, and lifecycle services around the existing paper-forward ledger. Persist nullable intraday metadata and run audits, expose one explicit POST command, schedule bounded cycles, and extend existing read-only snapshots without duplicating replay, paper-game, or learning logic.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2, Alembic, pandas, APScheduler, pytest, PostgreSQL/SQLite-compatible JSON.

## Global Constraints

- Use strict `1d -> 15m -> 5m -> 1m` real-data gating; no timeframe fallback.
- Paper only; no broker integration and no real-money execution.
- Only `PROMOTED_TO_PAPER` strategies with at least 300 validated trades may create candidates.
- No fake prices, fills, stop levels, targets, alpha, or activity.
- Replay and forward intraday evidence remain separate.
- GET endpoints remain read-only and perform no recalculation.
- No frontend-triggered execution and no version bump.

---

## File Structure

- `backend/app/services/intraday_contracts.py`: immutable command/result/value objects and state constants.
- `backend/app/services/promoted_strategy_registry.py`: projection and eligibility gates over replay validations.
- `backend/app/services/intraday_market_data.py`: strict multi-timeframe refresh/load/freshness boundary.
- `backend/app/services/intraday_opportunity.py`: setup, confirmation, trigger, costs, sizing, and concentration decisions.
- `backend/app/services/intraday_paper_engine.py`: bounded command orchestration, lifecycle transitions, learning, and snapshots.
- `backend/app/models.py`: nullable intraday trade metadata and `IntradayPaperRun` audit entity.
- `backend/alembic/versions/0031_live_intraday_paper_scalping.py`: backward-compatible migration.
- `backend/app/core/config.py`: cadence, costs, session, risk, and diversification settings.
- `backend/app/api/routes.py`: explicit command route only.
- `backend/app/services/realtime.py`: bounded anti-overlap scheduler registration.
- `backend/app/engine/brain/trader_brain.py`: separate intraday Alpha evidence split.
- `backend/tests/test_live_intraday_paper_engine.py`: domain, lifecycle, snapshot, API, and scheduler tests.

### Task 1: Intraday Contracts And Promotion Registry

**Files:**
- Create: `backend/app/services/intraday_contracts.py`
- Create: `backend/app/services/promoted_strategy_registry.py`
- Test: `backend/tests/test_live_intraday_paper_engine.py`

**Interfaces:**
- Produces `PromotedIntradayStrategy`, `IntradayDataBundle`, `IntradayDecision`, and `BlumPromotedStrategyRegistry.list_eligible(db, market, asset_class)`.
- Consumes `ReplayStrategyValidation` and replay promotion settings.

- [ ] **Step 1: Write failing promotion tests**

```python
def test_registry_returns_only_latest_fully_promoted_strategy():
    promoted = seed_validation(sample_size=500, verdict="PROMOTED_TO_PAPER")
    seed_validation(sample_size=299, verdict="PROMOTED_TO_PAPER", setup_type="pullback")
    rows = BlumPromotedStrategyRegistry().list_eligible(db, market="USA", asset_class="Stock")
    assert [row.validation_id for row in rows] == [promoted.id]

def test_registry_rejects_unstable_or_negative_alpha_strategy():
    seed_validation(metrics_json={"stability_score": 20, "benchmark_excess": -1.0}, verdict="PROMOTED_TO_PAPER")
    assert BlumPromotedStrategyRegistry().list_eligible(db, market="USA", asset_class="Stock") == []
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && ../.venv/bin/python -m pytest tests/test_live_intraday_paper_engine.py -q`

Expected: import failure for missing registry/contracts.

- [ ] **Step 3: Implement immutable contracts and registry gates**

Use frozen dataclasses. Normalize market aliases, read the latest validation per setup, require `PROMOTED_TO_PAPER`, sample threshold, positive benchmark-relative/risk-adjusted evidence, stability, supported market, and exact timeframe stack. Return blocker details from `registry.status(db)` without changing validations.

- [ ] **Step 4: Run focused tests and commit**

Run: `cd backend && ../.venv/bin/python -m pytest tests/test_live_intraday_paper_engine.py -q`

Commit: `feat: add promoted intraday strategy registry`

### Task 2: Strict Multi-Timeframe Data Gateway

**Files:**
- Create: `backend/app/services/intraday_market_data.py`
- Modify: `backend/app/services/replay_data.py`
- Test: `backend/tests/test_live_intraday_paper_engine.py`

**Interfaces:**
- Produces `StrictIntradayDataGateway.load(db, asset, now) -> IntradayDataBundle`.
- Consumes `MultiProviderReplayDataService.ensure_coverage/load_bars`.

- [ ] **Step 1: Write failing strict-data tests**

```python
def test_data_gateway_requires_all_four_timeframes():
    seed_bars(asset, timeframes=("1d", "15m", "5m"))
    result = gateway.load(db, asset=asset, now=NOW)
    assert result.status == "INTRADAY_DATA_BLOCKED"
    assert "MISSING_1M_DATA" in result.blockers

def test_data_gateway_rejects_stale_one_minute_bar():
    seed_complete_stack(asset, last_1m=NOW - timedelta(minutes=20))
    result = gateway.load(db, asset=asset, now=NOW)
    assert "STALE_1M_DATA" in result.blockers
```

- [ ] **Step 2: Verify RED**

Run the two tests directly and confirm missing gateway behavior.

- [ ] **Step 3: Implement range policies and strict freshness**

Use bounded ranges (`1d`: 260 sessions, `15m`: 10 sessions, `5m`: 5 sessions, `1m`: current/recent session). Refresh missing ranges only in command execution. Require minimum bars per timeframe, latest timestamps inside configured age, non-zero prices, ordered timestamps, and minimum quality. Return provider attempts and blockers without interpolation.

- [ ] **Step 4: Verify GREEN and commit**

Commit: `feat: add strict intraday market data gateway`

### Task 3: Persistence And Migration

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/0031_live_intraday_paper_scalping.py`
- Test: `backend/tests/test_live_intraday_paper_engine.py`

**Interfaces:**
- Produces `IntradayPaperRun` and nullable intraday fields on `LiveForwardPaperTrade`.

- [ ] **Step 1: Write failing persistence test**

```python
def test_intraday_trade_persists_strategy_cost_and_lifecycle_metadata():
    trade = LiveForwardPaperTrade(..., trading_mode="INTRADAY_PAPER_FORWARD", promoted_validation_id=validation.id)
    db.add(trade); db.commit(); db.refresh(trade)
    assert trade.evidence_type == "PAPER_FORWARD_INTRADAY"
    assert trade.timeframe_stack == ["1d", "15m", "5m", "1m"]
```

- [ ] **Step 2: Verify RED**

Expected: unknown model keyword/attribute.

- [ ] **Step 3: Add nullable columns and run audit model**

Store trading mode, evidence type, promoted validation ID, market, desk, session, timeframe stack, data timestamps, spread/slippage/commission/costs, net expectancy, sizing reason, trailing stop, last managed bar, holding minutes, and intraday run ID. Add indexed run state/counts/payload. Use `JsonType` in ORM and PostgreSQL JSONB with SQLite JSON variants in Alembic.

- [ ] **Step 4: Verify isolated upgrade/downgrade and commit**

Run an isolated SQLite database stamped at `0030_hyperbolic_replay`, upgrade to head, inspect fields/indexes, downgrade, and re-upgrade.

Commit: `feat: persist intraday paper lifecycle evidence`

### Task 4: Opportunity, Costs, Diversification, And Sizing

**Files:**
- Create: `backend/app/services/intraday_opportunity.py`
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_live_intraday_paper_engine.py`

**Interfaces:**
- Produces `IntradayCostModel.evaluate`, `IntradayDiversificationGate.evaluate`, `IntradayPositionSizer.size`, and `BlumIntradayOpportunityEngine.evaluate`.
- Consumes a promoted strategy and strict data bundle.

- [ ] **Step 1: Write failing decision tests**

```python
def test_costs_kill_small_expected_move():
    decision = opportunity.evaluate(strategy, bundle_with(expected_move_bps=8, round_trip_cost_bps=12), portfolio)
    assert decision.status == "INTRADAY_BLOCKED"
    assert decision.reason_code == "COSTS_KILL_EDGE"

def test_second_open_position_same_ticker_is_rejected():
    portfolio.open_tickers = {"NVDA"}
    assert opportunity.evaluate(strategy, nvda_bundle, portfolio).reason_code == "TICKER_CONCENTRATION"

def test_position_size_falls_with_wider_stop_and_lower_liquidity():
    assert low_quality.quantity < high_quality.quantity
```

- [ ] **Step 2: Verify RED**

- [ ] **Step 3: Implement deterministic gates**

Use daily trend/regime, 15m setup, 5m confirmation, and 1m trigger from bars at or before the decision timestamp. Estimate spread from range/liquidity when no quoted spread exists and mark it as estimated. Require positive net expectancy, minimum liquidity/volatility, permitted session, stop/target, Quant Edge approval, and portfolio limits. Size from paper capital and stop distance, capped by exposure and total risk.

- [ ] **Step 4: Verify GREEN and commit**

Commit: `feat: evaluate cost-aware intraday paper opportunities`

### Task 5: Intraday Command And Lifecycle

**Files:**
- Create: `backend/app/services/intraday_paper_engine.py`
- Modify: `backend/app/services/live_forward_paper_trading.py`
- Test: `backend/tests/test_live_intraday_paper_engine.py`

**Interfaces:**
- Produces `BlumIntradayPaperEngine.run_once(db, trigger="manual") -> dict`.
- Reuses existing game creation, frozen payload, event append, ledger serialization, and feedback metadata.

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_run_opens_only_promoted_triggered_candidate_with_adverse_fill():
    result = engine.run_once(db, trigger="test")
    trade = db.scalar(select(LiveForwardPaperTrade).where(LiveForwardPaperTrade.trading_mode == "INTRADAY_PAPER_FORWARD"))
    assert result["trades_opened"] == 1
    assert trade.entry_price >= observed_trigger_price
    assert event_types(trade)[:2] == ["INTRADAY_TRADE_CANDIDATE", "INTRADAY_TRADE_OPENED"]

def test_lifecycle_uses_only_later_one_minute_bars_and_closes_stop():
    result = engine.run_once(db, trigger="test")
    assert result["trades_closed"] == 1
    assert trade.close_reason == "STOP_HIT"
    assert trade.last_managed_bar_at > trade.opened_at
```

- [ ] **Step 2: Verify RED**

- [ ] **Step 3: Implement bounded orchestration**

Create an `IntradayPaperRun`, load eligible strategies and desk assets, evaluate within max-item/runtime budgets, persist decisions idempotently, fill only from eligible 1m bars, update existing open trades before scanning new ones, and close on configured rules. Never modify frozen payload after creation. Commit once per bounded run and publish the existing paper snapshot.

- [ ] **Step 4: Verify idempotency and commit**

Commit: `feat: add intraday paper command lifecycle`

### Task 6: Closed-Trade Learning Feedback

**Files:**
- Modify: `backend/app/services/intraday_paper_engine.py`
- Test: `backend/tests/test_live_intraday_paper_engine.py`

**Interfaces:**
- Produces `IntradayPaperLearningService.apply_closed_trade(db, trade) -> dict`.

- [ ] **Step 1: Write failing feedback tests**

```python
def test_open_intraday_trade_does_not_update_memory():
    assert learning.apply_closed_trade(db, open_trade)["status"] == "not_closed"
    assert count(TradeLearningEvidence) == 0

def test_closed_intraday_trade_updates_forward_memory_once():
    first = learning.apply_closed_trade(db, closed_trade)
    second = learning.apply_closed_trade(db, closed_trade)
    assert first["status"] == "applied"
    assert second["status"] == "duplicate"
    assert evidence.supporting_trades_json["evidence_type"] == "PAPER_FORWARD_INTRADAY"
```

- [ ] **Step 2: Verify RED**

- [ ] **Step 3: Implement idempotent evidence updates**

Write `TradeLearningEvidence`, `LearningEvent`, `StrategyMemory`, `SignalPerformance`, and `FeedbackLoopAudit` only after outcome evaluation. Include strategy, market, desk, ticker, timeframe, session, regime, exit reason, costs, R, benchmark excess, and immutable evidence identity.

- [ ] **Step 4: Verify GREEN and commit**

Commit: `feat: learn from closed intraday paper trades`

### Task 7: Snapshot, Alpha Split, API, And Scheduler

**Files:**
- Modify: `backend/app/services/live_forward_paper_trading.py`
- Modify: `backend/app/engine/brain/trader_brain.py`
- Modify: `backend/app/api/routes.py`
- Modify: `backend/app/services/realtime.py`
- Modify: `backend/app/services/worker_runtime.py`
- Test: `backend/tests/test_live_intraday_paper_engine.py`

**Interfaces:**
- Adds POST `/api/paper-forward/run-intraday`.
- Extends existing read-only Paper Forward and Alpha snapshots.

- [ ] **Step 1: Write failing contract tests**

```python
def test_snapshot_explains_no_promoted_strategy_without_running_engine(monkeypatch):
    monkeypatch.setattr(BlumIntradayPaperEngine, "run_once", forbidden)
    payload = LiveForwardPaperTradingService().snapshot(db)
    assert payload["intraday_engine_status"] == "DATA_BLOCKED"
    assert payload["reason_if_no_intraday_trades"]

def test_alpha_intraday_split_counts_only_closed_intraday_forward_trades():
    payload = TraderBrainService().alpha_snapshot(db)
    split = payload["evidence_split"]["intraday_paper_forward"]
    assert split["sample_size"] == 1
    assert split["return"] is not None
```

- [ ] **Step 2: Verify RED**

- [ ] **Step 3: Implement read projections and runtime command**

Aggregate requested counts/distributions/costs/reasons from persisted rows only. Add route calling the orchestrator. Register a dedicated worker with anti-overlap through the existing runtime coordinator and schedule only when enabled. Keep all GETs read-only.

- [ ] **Step 4: Verify scheduler and API tests, then commit**

Commit: `feat: expose intraday paper evidence and scheduler`

### Task 8: Documentation, Full Verification, And Deployment

**Files:**
- Modify: `README.md`
- Create: `LIVE_INTRADAY_PAPER_ENGINE_REPORT.md`

- [ ] **Step 1: Document architecture and evidence boundaries**

Describe promotion gates, strict timeframe data, costs, diversification, lifecycle, forward learning, API, scheduler, settings, and known provider retention limits.

- [ ] **Step 2: Run focused and full verification**

```bash
cd backend
../.venv/bin/python -m pytest tests/test_live_intraday_paper_engine.py -q
PAPER_FORWARD_LIFECYCLE_ENABLED=false ../.venv/bin/python -m pytest -q
../.venv/bin/python -m compileall -q app
cd ..
git diff --check
```

- [ ] **Step 3: Run local HTTP smoke**

Start a temporary backend database, seed an eligible promoted strategy and deterministic real-bar fixtures, then call:

```bash
curl -s -X POST http://localhost:8000/api/paper-forward/run-intraday
curl -s http://localhost:8000/api/paper-forward/snapshot
curl -s 'http://localhost:8000/api/paper-forward/trades?limit=25'
curl -s http://localhost:8000/api/training/snapshot
curl -s http://localhost:8000/api/alpha/snapshot
```

Record observed status, counts, costs, evidence separation, latency, and blockers. Do not claim production alpha.

- [ ] **Step 4: Commit and deploy**

Commit tracked files without the unrelated local ZIP. Push `main` to the configured Hugging Face Space, wait for runtime SHA `RUNNING`, verify root/OpenAPI/read-only snapshots, then run at most one bounded manual intraday cycle. Report actual provider/data blockers.
