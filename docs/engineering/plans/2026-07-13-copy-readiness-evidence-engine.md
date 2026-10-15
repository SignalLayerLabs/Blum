# Evidence, Trust and Copy Readiness Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an append-only, evidence-class-separated engine that measures strategy maturity, explains paper-trade copy readiness, detects replay-to-forward degradation, and publishes compact read-only snapshots.

**Architecture:** Pure metric and state-machine functions sit behind a bounded SQLAlchemy projection service. Source trading and replay rows remain immutable; the service appends evidence cards, readiness history, and timeline events, then snapshot producers expose compact projections. GET endpoints query projections only and never recalculate.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL JSONB/SQLite JSON, pytest.

## Global Constraints

- Keep `REPLAY_EVIDENCE`, `WALK_FORWARD_EVIDENCE`, `PAPER_FORWARD_EVIDENCE`, and `INTRADAY_FORWARD_EVIDENCE` separate.
- Never present replay results as forward performance.
- Never convert unavailable benchmark or evidence values to `0`.
- Copy readiness uses closed terminal forward trades only.
- No broker integration, no real-money execution, and no guaranteed-profit language.
- GET endpoints are read-only and perform no projection, lifecycle, or recalculation work.
- Existing APIs and the legacy lower-case `copy_readiness` field remain backward-compatible.
- `frozen_decision_payload` remains immutable.
- Real-capital eligibility is autonomous evidence classification only.
- No version bump.

---

### Task 1: Evidence Domain Metrics and State Machines

**Files:**
- Create: `backend/app/services/copy_readiness_metrics.py`
- Create: `backend/tests/test_copy_readiness_metrics.py`

**Interfaces:**
- Produces: `canonical_evidence_class(value: str | None, trading_mode: str | None = None) -> str`
- Produces: `wilson_interval(wins: int, sample_size: int) -> dict[str, float] | None`
- Produces: `concentration(values: list[str]) -> dict[str, float | str | None]`
- Produces: `evaluate_decay(replay: dict | None, forward: dict | None, thresholds: ReadinessThresholds) -> dict`
- Produces: `evaluate_copy_readiness(context: ReadinessContext, thresholds: ReadinessThresholds) -> ReadinessDecision`
- Produces: `evaluate_capital_eligibility(context: ReadinessContext, decision: ReadinessDecision, thresholds: ReadinessThresholds) -> str`

- [ ] **Step 1: Write failing domain tests**

```python
def test_replay_only_cannot_be_copy_ready():
    context = context_fixture(replay_sample=500, forward_sample=0)
    decision = evaluate_copy_readiness(context, ReadinessThresholds())
    assert decision.status == "REPLAY_ONLY"

def test_terminal_forward_evidence_can_reach_copy_ready():
    context = context_fixture(
        global_forward_sample=120,
        forward_sample=40,
        observation_days=120,
        net_expectancy=0.25,
        benchmark_excess=1.2,
        max_drawdown=8.0,
        decay_status="CONSISTENT",
        ticker_count=8,
        regime_count=3,
        ticker_concentration=0.25,
        market_concentration=0.60,
        costs_available=True,
    )
    assert evaluate_copy_readiness(context, ReadinessThresholds()).status == "COPY_READY_PAPER_ONLY"

def test_forward_failure_suspends_readiness():
    context = context_fixture(forward_sample=40, net_expectancy=-0.1, benchmark_excess=-1.0)
    assert evaluate_copy_readiness(context, ReadinessThresholds()).status == "SUSPENDED"

def test_missing_benchmark_stays_missing_and_blocks_promotion():
    context = context_fixture(forward_sample=40, benchmark_excess=None)
    decision = evaluate_copy_readiness(context, ReadinessThresholds())
    assert "benchmark_excess_unavailable" in decision.failed_gates

def test_intraday_legacy_class_is_normalized():
    assert canonical_evidence_class("PAPER_FORWARD_INTRADAY") == "INTRADAY_FORWARD_EVIDENCE"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && python3 -m pytest tests/test_copy_readiness_metrics.py -q`

Expected: collection fails because `app.services.copy_readiness_metrics` does not exist.

- [ ] **Step 3: Implement immutable domain values and pure functions**

```python
@dataclass(frozen=True)
class ReadinessThresholds:
    global_forward_trades: int = 100
    strategy_forward_trades: int = 30
    observation_days: int = 90
    max_drawdown: float = 15.0
    max_decay_pct: float = 35.0
    min_tickers: int = 5
    min_regimes: int = 2
    max_ticker_concentration: float = 0.35
    max_market_concentration: float = 0.70

@dataclass(frozen=True)
class ReadinessDecision:
    status: str
    maturity_score: float
    passed_gates: tuple[str, ...]
    failed_gates: tuple[str, ...]
    blockers: tuple[str, ...]
    next_milestone: str | None
```

Implement null-safe metrics, Wilson intervals, concentration, decay classifications, readiness transitions, and autonomous capital eligibility exactly as defined in the design.

- [ ] **Step 4: Run domain tests and verify GREEN**

Run: `cd backend && python3 -m pytest tests/test_copy_readiness_metrics.py -q`

Expected: all metric tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/copy_readiness_metrics.py backend/tests/test_copy_readiness_metrics.py
git commit -m "feat: add copy readiness evidence metrics"
```

### Task 2: Append-Only Evidence Schema and Migration

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/0032_copy_readiness_evidence_engine.py`
- Create: `backend/tests/test_copy_readiness_schema.py`

**Interfaces:**
- Produces ORM models: `StrategyEvidenceSnapshot`, `StrategyReadinessHistory`, `EvidenceTimelineEvent`
- Consumes canonical evidence and readiness strings from Task 1.

- [ ] **Step 1: Write failing schema tests**

```python
def test_evidence_tables_support_sqlite_json():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        row = StrategyEvidenceSnapshot(
            strategy_id="setup:momentum_breakout",
            setup_type="momentum_breakout",
            evidence_class="REPLAY_EVIDENCE",
            metrics_json={"sample_size": 50},
            warnings_json=[],
        )
        db.add(row)
        db.commit()
        assert row.metrics_json["sample_size"] == 50

def test_timeline_event_key_is_unique():
    # Insert the same event_key twice and assert IntegrityError.
```

- [ ] **Step 2: Run schema tests and verify RED**

Run: `cd backend && python3 -m pytest tests/test_copy_readiness_schema.py -q`

Expected: import failure for missing ORM models.

- [ ] **Step 3: Add models and migration**

Use `JsonType` in ORM models and:

```python
json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
```

in Alembic. Add latest-read indexes on `(strategy_id, evidence_class, evaluated_at)`, `(strategy_id, evaluated_at)`, and `(strategy_id, event_timestamp)`, plus a unique `event_key` constraint. Do not alter existing trade tables.

- [ ] **Step 4: Verify migration and schema**

Run:

```bash
cd backend
python3 -m pytest tests/test_copy_readiness_schema.py -q
DATABASE_URL=sqlite:////tmp/blum-copy-readiness.db alembic upgrade head
DATABASE_URL=sqlite:////tmp/blum-copy-readiness.db alembic downgrade 0031_intraday_paper
DATABASE_URL=sqlite:////tmp/blum-copy-readiness.db alembic upgrade head
```

Expected: tests pass and all migration commands exit 0.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/0032_copy_readiness_evidence_engine.py backend/tests/test_copy_readiness_schema.py
git commit -m "feat: persist copy readiness evidence history"
```

### Task 3: Strategy Evidence Projector

**Files:**
- Create: `backend/app/services/copy_readiness_evidence.py`
- Create: `backend/tests/test_copy_readiness_projector.py`

**Interfaces:**
- Consumes: SQLAlchemy `Session`, source ORM models, Task 1 metrics, Task 2 projections.
- Produces: `StrategyEvidenceProjector.project(db: Session, *, max_items: int = 500) -> dict`
- Produces: `StrategyEvidenceQuery.latest_cards(db: Session, *, limit: int, offset: int, strategy_id: str | None = None) -> dict`

- [ ] **Step 1: Write failing projector tests**

```python
def test_projector_keeps_all_evidence_classes_separate(db):
    seed_replay_walk_forward_and_paper_rows(db)
    result = StrategyEvidenceProjector().project(db, max_items=100)
    classes = {row.evidence_class for row in db.scalars(select(StrategyEvidenceSnapshot)).all()}
    assert classes == {
        "REPLAY_EVIDENCE",
        "WALK_FORWARD_EVIDENCE",
        "PAPER_FORWARD_EVIDENCE",
        "INTRADAY_FORWARD_EVIDENCE",
    }
    assert result["source_rows_processed"] > 0

def test_open_forward_trade_does_not_count_as_closed_evidence(db):
    seed_live_trade(db, status="OPEN")
    StrategyEvidenceProjector().project(db)
    card = latest_card(db, "PAPER_FORWARD_EVIDENCE")
    assert card.closed_trades == 0
    assert card.forward_trades == 0

def test_costs_reduce_net_expectancy(db):
    seed_closed_trade(db, gross_pnl_eur=2.0, costs_paid=0.5, r_multiple=1.0)
    StrategyEvidenceProjector().project(db)
    card = latest_card(db, "PAPER_FORWARD_EVIDENCE")
    assert card.total_costs == 0.5
    assert card.net_expectancy < card.gross_expectancy
```

- [ ] **Step 2: Run projector tests and verify RED**

Run: `cd backend && python3 -m pytest tests/test_copy_readiness_projector.py -q`

Expected: import failure for missing projector.

- [ ] **Step 3: Implement bounded append-only projection**

Implement source adapters for replay trades, walk-forward validations, standard forward trades, and intraday forward trades. Persist one new card per projection run and include source IDs, warnings, data timestamp, metric provenance, confidence interval, regime groups, and concentration.

Use stable strategy identity:

```python
def strategy_identity(setup_type: str, promoted_validation_id: int | None) -> tuple[str, list[str]]:
    if promoted_validation_id:
        return f"validation:{promoted_validation_id}", []
    return f"setup:{normalize_setup(setup_type)}", ["strategy_identity_fallback"]
```

- [ ] **Step 4: Run projector tests and verify GREEN**

Run: `cd backend && python3 -m pytest tests/test_copy_readiness_projector.py -q`

Expected: all projector tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/copy_readiness_evidence.py backend/tests/test_copy_readiness_projector.py
git commit -m "feat: project separated strategy evidence cards"
```

### Task 4: Readiness Evaluation, Decay, and Immutable Timeline

**Files:**
- Modify: `backend/app/services/copy_readiness_evidence.py`
- Modify: `backend/app/core/config.py`
- Create: `backend/tests/test_copy_readiness_engine.py`

**Interfaces:**
- Produces: `BlumCopyReadinessEngine.recalculate(db: Session, *, max_strategies: int = 100) -> dict`
- Produces: `EvidenceTimelineService.append_once(db: Session, *, event_key: str, event_type: str, strategy_id: str | None, trade_id: int | None, payload: dict) -> EvidenceTimelineEvent`
- Produces: `CopyReadinessSummaryService.summary(db: Session) -> dict`

- [ ] **Step 1: Write failing engine tests**

```python
def test_recalculate_appends_readiness_and_is_idempotent_for_timeline(db):
    seed_mature_forward_cards(db)
    first = BlumCopyReadinessEngine().recalculate(db)
    second = BlumCopyReadinessEngine().recalculate(db)
    assert first["strategies_evaluated"] == 1
    assert second["timeline_events_created"] == 0

def test_material_forward_decay_suspends_strategy(db):
    seed_replay_card(db, expectancy=0.8, profit_factor=2.0)
    seed_forward_card(db, expectancy=-0.2, profit_factor=0.7)
    BlumCopyReadinessEngine().recalculate(db)
    assert latest_readiness(db).copy_readiness_status == "SUSPENDED"

def test_external_validation_eligibility_is_autonomous(db, settings_override):
    seed_high_confidence_cards(db)
    result = BlumCopyReadinessEngine().recalculate(db)
    assert result["strategies"][0]["real_capital_eligibility"] == "ELIGIBLE_FOR_LIMITED_EXTERNAL_VALIDATION"
```

- [ ] **Step 2: Run engine tests and verify RED**

Run: `cd backend && python3 -m pytest tests/test_copy_readiness_engine.py -q`

Expected: missing engine methods/configuration fields.

- [ ] **Step 3: Add configuration and implement evaluation**

Add explicit environment-backed settings for all paper-readiness and limited-external-validation thresholds. Construct `ReadinessThresholds` from settings. Query latest evidence card per strategy/class, evaluate compatible decay, preserve previous state for `DEGRADED`, append history, and add timeline events only for material transitions.

- [ ] **Step 4: Run engine tests and verify GREEN**

Run: `cd backend && python3 -m pytest tests/test_copy_readiness_engine.py -q`

Expected: all engine tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/copy_readiness_evidence.py backend/app/core/config.py backend/tests/test_copy_readiness_engine.py
git commit -m "feat: evaluate autonomous copy readiness"
```

### Task 5: Trade-Level Evidence Enrichment and Lifecycle Events

**Files:**
- Modify: `backend/app/services/trading_intelligence_lab.py`
- Modify: `backend/app/services/live_forward_paper_trading.py`
- Modify: `backend/app/services/intraday_paper_engine.py`
- Create: `backend/tests/test_copy_readiness_trade_integration.py`

**Interfaces:**
- Consumes: latest readiness query from Task 4.
- Produces: `copy_readiness_projection(db: Session, trade: LiveForwardPaperTrade) -> dict`
- Preserves: existing `serialize_paper_forward_trade` output and `frozen_decision_payload`.

- [ ] **Step 1: Write failing trade integration tests**

```python
def test_candidate_with_immature_strategy_is_not_copy_ready(db):
    trade = seed_live_trade(db, status="CANDIDATE", setup_type="momentum_breakout")
    payload = serialize_paper_forward_trade(trade, compact=True, readiness={"status": "FORWARD_EVIDENCE_LOW"})
    assert payload["copy_readiness_status"] == "NOT_COPY_READY"
    assert payload["paper_trading_actionability"] == trade.actionability_state

def test_duplicate_lifecycle_run_does_not_change_frozen_payload(db):
    trade = seed_live_trade(db, status="CANDIDATE", frozen_decision_payload={"immutable": True})
    before = deepcopy(trade.frozen_decision_payload)
    LiveForwardPaperTradingService().run_once(db)
    db.refresh(trade)
    assert trade.frozen_decision_payload == before
```

- [ ] **Step 2: Run integration tests and verify RED**

Run: `cd backend && python3 -m pytest tests/test_copy_readiness_trade_integration.py -q`

Expected: missing evidence projection fields/signature.

- [ ] **Step 3: Enrich serialization and append lifecycle evidence**

Keep legacy actionability readiness. Add the new evidence projection fields at service boundaries, not inside the frozen payload. Append canonical evidence events for signal creation, open, update, close, outcome, benchmark, lesson, and memory using existing lifecycle hooks and `append_once`.

- [ ] **Step 4: Run integration tests and verify GREEN**

Run: `cd backend && python3 -m pytest tests/test_copy_readiness_trade_integration.py tests/test_live_forward_paper_trading.py tests/test_intraday_paper_engine.py -q`

Expected: new and existing lifecycle tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/trading_intelligence_lab.py backend/app/services/live_forward_paper_trading.py backend/app/services/intraday_paper_engine.py backend/tests/test_copy_readiness_trade_integration.py
git commit -m "feat: explain trade copy readiness from evidence"
```

### Task 6: Read-Only APIs and Compact Snapshot Integration

**Files:**
- Create: `backend/app/api/routers/copy_readiness.py`
- Modify: `backend/app/api/routers/__init__.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/engine/brain/trader_brain.py`
- Modify: `backend/app/services/live_forward_paper_trading.py`
- Modify: `backend/app/services/central_brain_runtime.py`
- Create: `backend/tests/test_copy_readiness_api.py`

**Interfaces:**
- Produces GET strategy list/detail/timeline endpoints.
- Produces bounded POST recalculation endpoint.
- Extends Alpha and Paper Forward snapshot contracts with compact copy-readiness sections.

- [ ] **Step 1: Write failing API tests**

```python
def test_strategy_get_is_paginated_and_read_only(client, db):
    seed_strategy_cards(db, count=30)
    before = count_projection_rows(db)
    response = client.get("/api/copy-readiness/strategies?limit=10&offset=0")
    assert response.status_code == 200
    assert len(response.json()["rows"]) == 10
    assert count_projection_rows(db) == before

def test_alpha_snapshot_exposes_compact_readiness_without_recalculation(client, monkeypatch):
    monkeypatch.setattr(BlumCopyReadinessEngine, "recalculate", fail_if_called)
    payload = client.get("/api/alpha/snapshot").json()
    assert "copy_readiness" in payload

def test_paper_snapshot_separates_ready_and_not_ready_candidates(client):
    payload = client.get("/api/paper-forward/snapshot").json()
    assert "copy_ready_open_candidates" in payload
    assert "not_copy_ready_open_candidates" in payload
```

- [ ] **Step 2: Run API tests and verify RED**

Run: `cd backend && python3 -m pytest tests/test_copy_readiness_api.py -q`

Expected: 404 or missing response fields.

- [ ] **Step 3: Implement routers and snapshot projections**

Register the router in `main.py`. The POST runs bounded projection/readiness work and refreshes `copy_readiness_summary`, `paper_forward_snapshot`, and `trader_alpha_summary`. GETs use `StrategyEvidenceQuery` and `CopyReadinessSummaryService` only. Snapshot candidate lists default to eight rows each.

- [ ] **Step 4: Run API and snapshot tests and verify GREEN**

Run: `cd backend && python3 -m pytest tests/test_copy_readiness_api.py tests/test_alpha_snapshot.py tests/test_paper_forward_page_snapshot.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routers/copy_readiness.py backend/app/api/routers/__init__.py backend/app/main.py backend/app/engine/brain/trader_brain.py backend/app/services/live_forward_paper_trading.py backend/app/services/central_brain_runtime.py backend/tests/test_copy_readiness_api.py
git commit -m "feat: publish evidence-bound copy readiness snapshots"
```

### Task 7: Certification, Report, and Deployment

**Files:**
- Create: `COPY_READINESS_EVIDENCE_ENGINE_REPORT.md`
- Modify: `README.md`

**Interfaces:**
- Consumes all previous deliverables.
- Produces certification evidence and deployed application artifact.

- [ ] **Step 1: Add report acceptance checklist and real runtime examples**

Document changed files, threshold defaults, evidence classes, actual stored-card example when available, a clearly labeled synthetic test fixture for states unavailable in the real database, replay-forward comparison, blockers, and every acceptance criterion.

- [ ] **Step 2: Update README architecture and configuration**

Document evidence separation, readiness semantics, autonomous limited-external-validation classification, GET read-only behavior, snapshot flow, environment variables, and explicit non-goals.

- [ ] **Step 3: Run fresh verification**

```bash
cd backend
python3 -m compileall -q app
python3 -m pytest tests/test_copy_readiness_metrics.py tests/test_copy_readiness_schema.py tests/test_copy_readiness_projector.py tests/test_copy_readiness_engine.py tests/test_copy_readiness_trade_integration.py tests/test_copy_readiness_api.py -q
python3 -m pytest -q
cd ..
git diff --check
```

Expected: compile exits 0, focused tests pass, full backend suite passes, and diff check has no errors.

- [ ] **Step 4: Verify version and no broker path**

Run:

```bash
rg -n "app_version|ENGINE_VERSION|PROJECT_FEATURE_SET" backend/app/core/config.py backend/app/engine/contracts.py
rg -n "broker|submit_order|place_order" backend/app/services/copy_readiness* backend/app/api/routers/copy_readiness.py
```

Expected: version values are unchanged; no broker or order-execution call exists in the new engine.

- [ ] **Step 5: Commit report and documentation**

```bash
git add README.md COPY_READINESS_EVIDENCE_ENGINE_REPORT.md
git commit -m "docs: certify copy readiness evidence engine"
```

- [ ] **Step 6: Deploy and verify runtime**

Push the verified `main` commit to the configured Hugging Face Space remote, wait for the build/runtime to become healthy, then verify `/api/alpha/snapshot`, `/api/paper-forward/snapshot`, and `/api/copy-readiness/strategies?limit=1` return successful evidence-bound payloads.

