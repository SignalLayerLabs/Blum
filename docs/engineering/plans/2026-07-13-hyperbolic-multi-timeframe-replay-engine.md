# Hyperbolic Multi-Timeframe Replay Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a persisted, chronological, multi-timeframe replay engine that trains BLUM on real stored/free OHLCV data, validates strategies walk-forward, feeds validated evidence into learning memory, and truthfully reports progress toward 5,000 validated replay trades per day.

**Architecture:** Add a replay-specific OHLCV and coverage store beside the existing daily `PriceHistory` model. A DB-first provider service supplies verified bars to an isolated replay engine; bounded execution, validation, feedback, adaptive scheduling, and snapshots remain separate services with explicit contracts.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy 2, Alembic, pandas, NumPy, requests/yfinance, psutil, APScheduler, pytest, SQLite/PostgreSQL-compatible JSON.

## Global Constraints

- Do not modify the existing daily `PriceHistory` uniqueness contract.
- Do not fabricate bars, outcomes, provider coverage, alpha, or throughput.
- Do not read future bars while creating a replay decision.
- Keep `REPLAY_EVIDENCE`, `WALK_FORWARD_EVIDENCE`, and `PAPER_FORWARD_EVIDENCE` separate.
- Do not trigger replay work from GET endpoints or frontend rendering.
- Do not add dashboards, broker integration, or real-money execution.
- Preserve all existing APIs and financial behavior.
- Do not bump the project version.
- Use bounded transactions, bounded experiments, resumable jobs, and truthful partial results.

---

## File Structure

### New files

- `backend/app/providers/replay_data_provider.py`: replay provider protocol, requests/results, provider capability metadata, and existing free-provider adapters.
- `backend/app/services/replay_data.py`: DB-first coverage inspection, missing-range acquisition, validation, normalization, and persistence.
- `backend/app/services/replay_execution.py`: execution-cost profiles and dynamic position sizing.
- `backend/app/services/hyperbolic_replay.py`: chronological setup detection, replay clock, trade state transitions, and run persistence.
- `backend/app/services/replay_validation.py`: bounded experiments, multi-window validation, promotion verdicts, and feedback persistence.
- `backend/app/services/adaptive_replay_training.py`: CPU/RAM/runtime-aware controller and training snapshot writer.
- `backend/alembic/versions/0030_hyperbolic_replay_engine.py`: additive replay schema.
- `backend/tests/test_replay_data_engine.py`: provider, coverage, normalization, and migration-facing model tests.
- `backend/tests/test_hyperbolic_replay_engine.py`: anti-look-ahead, execution, experiment, validation, and feedback tests.
- `backend/tests/test_adaptive_replay_training.py`: controller, snapshot, API, and scheduler tests.
- `HYPERBOLIC_REPLAY_ENGINE_REPORT.md`: measured final implementation report.

### Modified files

- `backend/app/models.py`: replay ORM records.
- `backend/app/core/config.py`: bounded replay settings.
- `backend/app/engine/facade.py`: explicit replay command and read-only snapshot boundary.
- `backend/app/engine/brain/trader_brain.py`: merge stored replay snapshot into Training Ground output.
- `backend/app/api/routers/training.py`: manual POST endpoint only.
- `backend/app/services/realtime.py`: bounded scheduler job.
- `backend/app/services/worker_runtime.py`: replay worker registration if registry is explicit.
- `requirements.txt`: add `psutil` for portable resource telemetry.
- `README.md`: document replay evidence and operational controls.

---

### Task 1: Add Replay Persistence Schema

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/0030_hyperbolic_replay_engine.py`
- Test: `backend/tests/test_replay_data_engine.py`

**Interfaces:**
- Produces: `ReplayMarketBar`, `ReplayDataCoverage`, `HyperbolicReplayRun`, `HyperbolicReplayTrade`, `ReplayStrategyValidation` ORM models.
- Consumes: existing `Asset`, `BlumLearningExperiment`, `JsonType`, and SQLAlchemy `Base`.

- [ ] **Step 1: Write failing schema tests**

```python
def test_replay_bar_keeps_intraday_timestamp_and_timeframe():
    with setup_db() as db:
        asset = seed_asset(db, "NVDA")
        timestamp = datetime(2026, 7, 10, 14, 31)
        db.add(ReplayMarketBar(
            asset_id=asset.id,
            source_symbol="NVDA",
            normalized_symbol="NVDA",
            market="USA",
            timeframe="1m",
            bar_timestamp=timestamp,
            open=160.0,
            high=161.0,
            low=159.5,
            close=160.5,
            volume=250_000,
            provider="test",
            acquired_at=datetime.utcnow(),
            data_quality_score=98.0,
            source_metadata={"license": "test fixture"},
        ))
        db.commit()
        row = db.scalar(select(ReplayMarketBar))
    assert row.bar_timestamp == timestamp
    assert row.timeframe == "1m"


def test_replay_bar_unique_key_prevents_duplicate_provider_bar():
    with setup_db() as db:
        asset = seed_asset(db, "NVDA")
        values = replay_bar_values(asset.id)
        db.add(ReplayMarketBar(**values))
        db.commit()
        db.add(ReplayMarketBar(**values))
        with pytest.raises(IntegrityError):
            db.commit()
```

- [ ] **Step 2: Run the schema tests and verify RED**

Run: `python3 -m pytest backend/tests/test_replay_data_engine.py -q`

Expected: collection fails because the replay models do not exist.

- [ ] **Step 3: Add focused ORM models**

Use these persistent contracts:

```python
class ReplayMarketBar(Base):
    __tablename__ = "replay_market_bars"
    __table_args__ = (
        UniqueConstraint("asset_id", "timeframe", "provider", "bar_timestamp", name="uq_replay_bar_source"),
        Index("ix_replay_bars_asset_timeframe_timestamp", "asset_id", "timeframe", "bar_timestamp"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    source_symbol: Mapped[str] = mapped_column(String(48), index=True)
    normalized_symbol: Mapped[str] = mapped_column(String(48), index=True)
    market: Mapped[str] = mapped_column(String(40), index=True)
    timeframe: Mapped[str] = mapped_column(String(8), index=True)
    bar_timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    provider: Mapped[str] = mapped_column(String(48), index=True)
    acquired_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    data_quality_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    source_metadata: Mapped[dict] = mapped_column(JsonType, default=dict)
```

Add corresponding bounded JSON-bearing models for coverage, runs, trades, and strategy validations. Use explicit indexes for status/date and run/trade foreign keys.

- [ ] **Step 4: Add the cross-database Alembic migration**

Set:

```python
revision = "0030_hyperbolic_replay"
down_revision = "0029_learning_accel"
json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
```

Create all five tables additively with indexes and a complete reverse-order `downgrade()`.

- [ ] **Step 5: Run tests and migration checks**

Run: `python3 -m pytest backend/tests/test_replay_data_engine.py -q`

Expected: schema tests pass.

Run from `backend/`: `DATABASE_URL=sqlite:////tmp/blum_replay_migration.db alembic upgrade head`

Expected: migration reaches `0030_hyperbolic_replay` without error.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/0030_hyperbolic_replay_engine.py backend/tests/test_replay_data_engine.py
git commit -m "feat: add hyperbolic replay persistence"
```

---

### Task 2: Implement DB-First Multi-Provider Replay Data

**Files:**
- Create: `backend/app/providers/replay_data_provider.py`
- Create: `backend/app/services/replay_data.py`
- Modify: `backend/app/providers/yfinance_provider.py`
- Test: `backend/tests/test_replay_data_engine.py`

**Interfaces:**
- Produces: `ReplayDataRequest`, `ProviderBars`, `ReplayDataProvider`, `MultiProviderReplayDataService.ensure_coverage()`.
- Consumes: replay models from Task 1 and existing Yahoo/yfinance/Stooq/Nasdaq provider behavior.

- [ ] **Step 1: Write failing provider and coverage tests**

```python
def test_db_coverage_is_used_before_provider_fetch():
    provider = RecordingProvider()
    with setup_db() as db:
        asset = seed_asset(db, "NVDA")
        seed_replay_bars(db, asset, timeframe="5m", count=24)
        result = MultiProviderReplayDataService([provider]).ensure_coverage(
            db, asset=asset, timeframe="5m", start=dt(2026, 7, 10, 14, 30), end=dt(2026, 7, 10, 16, 25)
        )
    assert provider.requests == []
    assert result.status == "READY"


def test_missing_range_uses_fallback_and_persists_blockers():
    primary = FailingProvider("PROVIDER_UNAVAILABLE")
    fallback = StaticProvider(timeframe="15m", bars=valid_bars("15m", 8))
    with setup_db() as db:
        asset = seed_asset(db, "ENI.MI", market="ITALY")
        result = MultiProviderReplayDataService([primary, fallback]).ensure_coverage(
            db, asset=asset, timeframe="15m", start=dt(2026, 7, 10, 8, 0), end=dt(2026, 7, 10, 10, 0)
        )
    assert result.provider == fallback.name
    assert result.rows_available == 8
    assert "PROVIDER_UNAVAILABLE" in result.provider_attempts[0]["blockers"]


def test_yahoo_intraday_adapter_does_not_normalize_timestamp_to_midnight():
    frame = yahoo_payload_to_frame(yahoo_intraday_payload())
    assert frame.index[0].hour == 14
    assert frame.index[0].minute == 31
```

- [ ] **Step 2: Verify RED**

Run: `python3 -m pytest backend/tests/test_replay_data_engine.py -q`

Expected: failures identify missing replay provider and coverage services.

- [ ] **Step 3: Add provider contracts and adapters**

Implement:

```python
@dataclass(frozen=True)
class ReplayDataRequest:
    source_symbol: str
    normalized_symbol: str
    market: str
    timeframe: str
    start: datetime
    end: datetime


class ReplayDataProvider(Protocol):
    name: str
    supported_timeframes: frozenset[str]
    source_metadata: dict
    def fetch(self, request: ReplayDataRequest) -> ProviderBars: ...
```

Adapters must return blocker-bearing results instead of empty success. Correct Yahoo intraday conversion by removing `.normalize()` from replay parsing while retaining daily compatibility in existing daily code paths.

- [ ] **Step 4: Implement coverage validation and idempotent persistence**

`MultiProviderReplayDataService.ensure_coverage()` must:

```python
def ensure_coverage(
    self,
    db: Session,
    *,
    asset: Asset,
    timeframe: str,
    start: datetime,
    end: datetime,
) -> ReplayCoverageResult:
```

It must query local min/max/count first, derive missing ranges, fetch only gaps, reject malformed OHLC, score duplicate/null/gap quality, insert with conflict-safe lookup, and persist `ReplayDataCoverage` even when blocked.

- [ ] **Step 5: Verify GREEN and regression safety**

Run: `python3 -m pytest backend/tests/test_replay_data_engine.py backend/tests/test_market_data.py -q`

Expected: replay data tests and existing daily market-data tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/providers/replay_data_provider.py backend/app/services/replay_data.py backend/app/providers/yfinance_provider.py backend/tests/test_replay_data_engine.py
git commit -m "feat: add replay market data adapters"
```

---

### Task 3: Add Realistic Execution Costs and Dynamic Sizing

**Files:**
- Create: `backend/app/services/replay_execution.py`
- Test: `backend/tests/test_hyperbolic_replay_engine.py`

**Interfaces:**
- Produces: `ExecutionCostProfile`, `ReplayExecutionModel`, `ReplayPositionSizer`.
- Consumes: market, asset type, liquidity, ATR, stop distance, confidence, edge, data quality, and regime.

- [ ] **Step 1: Write failing cost and sizing tests**

```python
def test_execution_costs_differ_between_liquid_us_and_less_liquid_europe():
    model = ReplayExecutionModel()
    us = model.profile(market="USA", asset_type="Stock", liquidity_score=90, session="regular")
    eu = model.profile(market="ITALY", asset_type="Stock", liquidity_score=35, session="regular")
    assert eu.total_round_trip_bps > us.total_round_trip_bps


def test_position_size_decreases_when_quality_or_liquidity_falls():
    sizer = ReplayPositionSizer(max_risk_fraction=0.01)
    high = sizer.size(capital=10_000, entry=100, stop=96, atr=2, liquidity_score=90, confidence=70, edge_score=70, data_quality=95, regime_alignment=80)
    low = sizer.size(capital=10_000, entry=100, stop=96, atr=2, liquidity_score=30, confidence=70, edge_score=70, data_quality=45, regime_alignment=35)
    assert low.units < high.units
    assert low.risk_amount <= high.risk_amount
```

- [ ] **Step 2: Verify RED**

Run: `python3 -m pytest backend/tests/test_hyperbolic_replay_engine.py -q`

Expected: missing execution module.

- [ ] **Step 3: Implement immutable profiles and capped sizing**

Use explicit base profiles and bounded multipliers. Persist the applied components in returned payloads. Enforce `position_size = 0` with a blocker when stop distance is invalid, data quality is below threshold, or notional liquidity is insufficient.

- [ ] **Step 4: Verify GREEN**

Run: `python3 -m pytest backend/tests/test_hyperbolic_replay_engine.py -q`

Expected: execution and sizing tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/replay_execution.py backend/tests/test_hyperbolic_replay_engine.py
git commit -m "feat: model replay execution and sizing"
```

---

### Task 4: Implement the Chronological Hyperbolic Replay Engine

**Files:**
- Create: `backend/app/services/hyperbolic_replay.py`
- Test: `backend/tests/test_hyperbolic_replay_engine.py`

**Interfaces:**
- Produces: `ReplayRunRequest`, `ReplayClock`, `ReplaySetup`, `BlumHyperbolicReplayEngine.run_cycle()`.
- Consumes: `MultiProviderReplayDataService`, `ReplayExecutionModel`, `ReplayPositionSizer`, and replay ORM records.

- [ ] **Step 1: Write failing anti-look-ahead and degraded-timeframe tests**

```python
def test_signal_never_reads_bar_after_replay_clock():
    bars = deterministic_breakout_bars()
    engine = BlumHyperbolicReplayEngine(data_service=StaticReplayDataService(bars))
    with setup_db() as db:
        result = engine.run_cycle(db, ReplayRunRequest(asset_ids=[seed_asset(db, "NVDA").id], max_assets=1, max_trades=4))
        trade = db.scalar(select(HyperbolicReplayTrade))
    assert trade.decision_timestamp < trade.entry_timestamp
    assert max(trade.decision_payload["feature_bar_timestamps"]) <= trade.decision_timestamp.isoformat()
    assert result["lookahead_violations"] == 0


def test_daily_and_15m_replay_continues_when_1m_is_unavailable():
    service = PartialReplayDataService(available={"1d", "15m"})
    with setup_db() as db:
        asset = seed_asset(db, "ENI.MI", market="ITALY")
        result = BlumHyperbolicReplayEngine(data_service=service).run_cycle(
            db, ReplayRunRequest(asset_ids=[asset.id], max_assets=1, max_trades=10)
        )
    assert set(result["timeframes_used"]) == {"1d", "15m"}
    assert any(row["code"] == "UNSUPPORTED_TIMEFRAME" and row["timeframe"] == "1m" for row in result["blockers"])
    assert result["trades_generated"] > 0
```

- [ ] **Step 2: Verify RED**

Run: `python3 -m pytest backend/tests/test_hyperbolic_replay_engine.py -q`

Expected: missing replay engine contracts.

- [ ] **Step 3: Implement replay clock and setup requirements**

Define setup requirements explicitly:

```python
SETUP_REQUIREMENTS = {
    "intraday_breakout": ("1d", "15m", "5m", "1m"),
    "intraday_trend": ("1d", "15m", "5m"),
    "mean_reversion": ("15m", "5m"),
    "pullback": ("1d", "15m"),
    "swing_breakout": ("1d",),
}
```

All rolling indicators must use closed bars and `.shift(1)` where the current close creates the signal. Execution occurs on the next available executable bar.

- [ ] **Step 4: Implement bounded state transitions and outcomes**

Persist transitions through `REPLAY_CANDIDATE -> REPLAY_OPEN -> REPLAY_CLOSED -> REPLAY_EVALUATED`. Persist rejection states with evidence. Stop processing when `max_trades`, `max_assets`, or `deadline_monotonic` is reached and write the next cursor into the run payload.

- [ ] **Step 5: Verify GREEN**

Run: `python3 -m pytest backend/tests/test_hyperbolic_replay_engine.py -q`

Expected: chronological, partial-timeframe, state, and idempotency tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/hyperbolic_replay.py backend/tests/test_hyperbolic_replay_engine.py
git commit -m "feat: implement chronological hyperbolic replay"
```

---

### Task 5: Add Bounded Experiments and Walk-Forward Validation

**Files:**
- Create: `backend/app/services/replay_validation.py`
- Modify: `backend/app/services/hyperbolic_replay.py`
- Test: `backend/tests/test_hyperbolic_replay_engine.py`

**Interfaces:**
- Produces: `ReplayExperimentService.propose_and_run()`, `ReplayWalkForwardValidator.validate()`.
- Consumes: `BlumLearningExperiment`, replay trades, cost payloads, benchmarks, and validation models.

- [ ] **Step 1: Write failing experiment and promotion tests**

```python
def test_experiment_grid_is_bounded():
    variants = ReplayExperimentService(max_experiments=5).bounded_variants(default_hypothesis())
    assert 1 <= len(variants) <= 5


def test_strategy_cannot_promote_below_300_validated_trades():
    result = ReplayWalkForwardValidator().verdict(validation_fixture(sample_size=299, markets=["USA", "GERMANY"], excess_return=4.2))
    assert result["verdict"] == "NEEDS_MORE_EVIDENCE"


def test_strategy_requires_multiple_markets_and_windows():
    one_market = ReplayWalkForwardValidator().verdict(validation_fixture(sample_size=500, markets=["USA"], windows=3, excess_return=4.2))
    one_window = ReplayWalkForwardValidator().verdict(validation_fixture(sample_size=500, markets=["USA", "GERMANY"], windows=1, excess_return=4.2))
    assert one_market["verdict"] == "REJECTED_UNSTABLE"
    assert one_window["verdict"] == "REJECTED_UNSTABLE"
```

- [ ] **Step 2: Verify RED**

Run: `python3 -m pytest backend/tests/test_hyperbolic_replay_engine.py -q`

Expected: missing validation service.

- [ ] **Step 3: Implement bounded variant generation and chronological windows**

Generate no more than configured combinations and persist the exact hypothesis, train windows, test windows, benchmark, cost profile, and parameters. Split by chronological date boundaries; do not randomly shuffle observations.

- [ ] **Step 4: Implement metrics and verdict order**

Evaluate blockers in this order: insufficient evidence, overfitting, no edge, bad drawdown, instability, promotion. Persist each result as `ReplayStrategyValidation` and update the linked `BlumLearningExperiment` without converting completion alone into promotion.

- [ ] **Step 5: Verify GREEN**

Run: `python3 -m pytest backend/tests/test_hyperbolic_replay_engine.py -q`

Expected: experiment bounds, windows, metrics, and promotion gates pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/replay_validation.py backend/app/services/hyperbolic_replay.py backend/tests/test_hyperbolic_replay_engine.py
git commit -m "feat: validate replay strategies walk forward"
```

---

### Task 6: Connect Validated Replay Evidence to BLUM Learning

**Files:**
- Modify: `backend/app/services/replay_validation.py`
- Test: `backend/tests/test_hyperbolic_replay_engine.py`

**Interfaces:**
- Produces: `ReplayLearningFeedbackService.apply_evaluated_trade()` and `apply_validation()`.
- Consumes: `LearningEvent`, `StrategyMemory`, `SignalPerformance`, `LearningFocusPriority`, `FeedbackLoopAudit`, and existing Research Planner conventions.

- [ ] **Step 1: Write failing evidence-separation and feedback tests**

```python
def test_evaluated_replay_updates_memory_with_replay_evidence_only():
    with setup_db() as db:
        trade = seed_evaluated_replay_trade(db, evidence_type="REPLAY_EVIDENCE")
        result = ReplayLearningFeedbackService().apply_evaluated_trade(db, trade)
        memory = db.scalar(select(StrategyMemory).where(StrategyMemory.memory_key == result["memory_key"]))
    assert memory.evidence["evidence_type"] == "REPLAY_EVIDENCE"
    assert "PAPER_FORWARD_EVIDENCE" not in json.dumps(memory.evidence)


def test_model_version_is_not_promoted_without_out_of_sample_improvement():
    with setup_db() as db:
        seed_validation(db, sample_size=500, verdict="NEEDS_MORE_EVIDENCE", out_of_sample_improvement=False)
        before = db.scalar(select(func.count(ModelVersion.id)))
        ReplayLearningFeedbackService().apply_validation(db, latest_validation(db))
        after = db.scalar(select(func.count(ModelVersion.id)))
    assert after == before
```

- [ ] **Step 2: Verify RED**

Run: `python3 -m pytest backend/tests/test_hyperbolic_replay_engine.py -q`

Expected: feedback service absent.

- [ ] **Step 3: Implement idempotent feedback writes**

Use stable evidence keys derived from replay trade/validation IDs. Increment memory and signal sample counts only once. Store replay run, experiment, market, regime, timeframe, costs, benchmark, and validation status in every payload.

- [ ] **Step 4: Gate model promotion**

Only create/activate a `ModelVersion` when verdict is `PROMOTED_TO_PAPER`, sample size is at least 300, multi-market/window gates pass, and out-of-sample score exceeds the active baseline. Store previous weights and a reversible change log.

- [ ] **Step 5: Verify GREEN**

Run: `python3 -m pytest backend/tests/test_hyperbolic_replay_engine.py backend/tests/test_learning_feedback_loop.py -q`

Expected: replay feedback and existing feedback-loop tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/replay_validation.py backend/tests/test_hyperbolic_replay_engine.py
git commit -m "feat: feed validated replay evidence into learning"
```

---

### Task 7: Implement Adaptive Replay Training and Snapshots

**Files:**
- Create: `backend/app/services/adaptive_replay_training.py`
- Modify: `requirements.txt`
- Test: `backend/tests/test_adaptive_replay_training.py`

**Interfaces:**
- Produces: `RuntimeResourceSample`, `BlumAdaptiveTrainingController.run_once()`, `ReplayTrainingSnapshotService.snapshot()`.
- Consumes: replay engine, `BackgroundJobStateService`, `DashboardSnapshotService`, performance recorder, and `psutil`.

- [ ] **Step 1: Write failing state and checkpoint tests**

```python
def test_controller_throttles_under_high_load():
    controller = BlumAdaptiveTrainingController(resource_monitor=StaticResourceMonitor(cpu=91, memory=87, api_p95_ms=2400))
    with setup_db() as db:
        result = controller.run_once(db)
    assert result["adaptive_training_state"] == "THROTTLED"
    assert result["resource_limits_applied"]["max_assets"] < controller.settings.max_assets_per_cycle


def test_controller_pauses_when_runtime_is_degraded_without_losing_cursor():
    controller = BlumAdaptiveTrainingController(resource_monitor=StaticResourceMonitor(cpu=98, memory=94, api_p95_ms=6000))
    with setup_db() as db:
        seed_background_cursor(db, "hyperbolic_replay_training", {"asset_id": 42, "timestamp": "2026-01-03T10:00:00"})
        result = controller.run_once(db)
        cursor = load_background_cursor(db, "hyperbolic_replay_training")
    assert result["adaptive_training_state"] == "PAUSED_FOR_RUNTIME"
    assert cursor["asset_id"] == 42
```

- [ ] **Step 2: Verify RED**

Run: `python3 -m pytest backend/tests/test_adaptive_replay_training.py -q`

Expected: missing adaptive controller.

- [ ] **Step 3: Add portable resource monitoring**

Add `psutil==6.1.1`. Sample process/system CPU and memory without retaining mutable global samples. Include API p95 and active background jobs from existing diagnostics.

- [ ] **Step 4: Implement bounded state policy and snapshot write**

Use deterministic thresholds and never exceed configured `max_seconds_per_cycle`, `max_assets_per_cycle`, or `max_trades_per_cycle`. Write snapshot type `hyperbolic_replay_training_summary` after every cycle, including real today counts and target-miss reason.

- [ ] **Step 5: Verify GREEN**

Run: `python3 -m pytest backend/tests/test_adaptive_replay_training.py -q`

Expected: resource state, budget, checkpoint, resume, and snapshot tests pass.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt backend/app/services/adaptive_replay_training.py backend/tests/test_adaptive_replay_training.py
git commit -m "feat: add adaptive replay training controller"
```

---

### Task 8: Add Manual Replay API and Read-Only Training Snapshot

**Files:**
- Modify: `backend/app/engine/facade.py`
- Modify: `backend/app/engine/brain/trader_brain.py`
- Modify: `backend/app/api/routers/training.py`
- Test: `backend/tests/test_adaptive_replay_training.py`

**Interfaces:**
- Produces: `BlumEngineFacade.run_training_replay()`, `POST /api/training/run-replay`, extended `GET /api/training/snapshot`.
- Consumes: adaptive controller and stored replay snapshot only.

- [ ] **Step 1: Write failing endpoint and read-only tests**

```python
def test_training_snapshot_reads_replay_snapshot_without_running_controller(monkeypatch):
    monkeypatch.setattr(BlumAdaptiveTrainingController, "run_once", lambda *args, **kwargs: pytest.fail("GET started replay"))
    with setup_db() as db:
        seed_replay_training_snapshot(db, validated_trades_today=125)
        payload = BlumEngineFacade().training_snapshot(db)
    assert payload["validated_trades_today"] == 125


def test_manual_replay_endpoint_returns_bounded_real_summary(client, monkeypatch):
    monkeypatch.setattr(BlumAdaptiveTrainingController, "run_once", static_run_summary)
    response = client.post("/api/training/run-replay")
    assert response.status_code == 200
    assert response.json()["resource_limits_applied"]["max_seconds"] <= 120
```

- [ ] **Step 2: Verify RED**

Run: `python3 -m pytest backend/tests/test_adaptive_replay_training.py -q`

Expected: endpoint and facade method are missing.

- [ ] **Step 3: Add explicit command method and router**

```python
def run_training_replay(self, db: Session) -> dict:
    return BlumAdaptiveTrainingController().run_once(db, trigger="manual")


@router.post("/api/training/run-replay")
def training_run_replay(db: Session = Depends(get_db)) -> dict:
    return BlumEngineFacade().run_training_replay(db)
```

- [ ] **Step 4: Merge snapshot fields without computation**

Read `hyperbolic_replay_training_summary` through `DashboardSnapshotService.latest()`. Add all required replay fields at top level and under `hyperbolic_replay`, using truthful `INITIALIZING` values when absent. Do not query raw bars from the GET path.

- [ ] **Step 5: Verify GREEN**

Run: `python3 -m pytest backend/tests/test_adaptive_replay_training.py backend/tests/test_trader_brain.py -q`

Expected: manual command, read-only GET, and existing Trader Brain tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/engine/facade.py backend/app/engine/brain/trader_brain.py backend/app/api/routers/training.py backend/tests/test_adaptive_replay_training.py
git commit -m "feat: expose bounded replay training API"
```

---

### Task 9: Register Bounded Scheduler Execution and Configuration

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/services/realtime.py`
- Modify: `backend/app/services/worker_runtime.py`
- Test: `backend/tests/test_adaptive_replay_training.py`

**Interfaces:**
- Produces: replay environment settings and `run_hyperbolic_replay_training_job()`.
- Consumes: `BlumAdaptiveTrainingController.run_once()` and existing `_run_job()` isolation.

- [ ] **Step 1: Write failing scheduler tests**

```python
def test_replay_scheduler_registers_bounded_background_job():
    source = Path("backend/app/services/realtime.py").read_text()
    assert 'job_id="hyperbolic_replay_training"' in source
    assert "BlumAdaptiveTrainingController().run_once" in source
    assert "/api/training/run-replay" not in source


def test_replay_defaults_are_bounded():
    settings = Settings()
    assert settings.replay_target_validated_trades_per_day == 5000
    assert settings.replay_max_seconds_per_cycle <= 120
    assert settings.replay_max_experiments_per_cycle <= 8
```

- [ ] **Step 2: Verify RED**

Run: `python3 -m pytest backend/tests/test_adaptive_replay_training.py -q`

Expected: replay settings/job absent.

- [ ] **Step 3: Add environment settings**

Add settings for enabled state, interval, target, cycle seconds/assets/trades/experiments, minimum quality, promotion sample size, provider priority, market list, timeframe list, and resource thresholds. Defaults must enforce 5,000 target, 300 promotion minimum, and at most 120 seconds per cycle.

- [ ] **Step 4: Register isolated scheduler work**

Schedule only when enabled, use `max_instances=1`, and execute through `_run_job("hyperbolic_replay_training", ...)`. Do not add replay to `market_refresh` or page startup.

- [ ] **Step 5: Verify GREEN**

Run: `python3 -m pytest backend/tests/test_adaptive_replay_training.py backend/tests/test_runtime_architecture.py -q`

Expected: scheduler and runtime tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/config.py backend/app/services/realtime.py backend/app/services/worker_runtime.py backend/tests/test_adaptive_replay_training.py
git commit -m "feat: schedule bounded replay training"
```

---

### Task 10: Document Architecture and Produce Measured Report

**Files:**
- Modify: `README.md`
- Create: `HYPERBOLIC_REPLAY_ENGINE_REPORT.md`

**Interfaces:**
- Produces: operator documentation and evidence-based acceptance report.
- Consumes: actual test, migration, endpoint, throughput, coverage, and smoke outputs from Tasks 1-9.

- [ ] **Step 1: Add README operational documentation**

Document DB-first acquisition, partial timeframe behavior, provider blockers, anti-look-ahead invariants, evidence classes, scheduler settings, manual endpoint, snapshot fields, and why 5,000/day remains a measured target.

- [ ] **Step 2: Run a bounded local replay and capture measured facts**

Run:

```bash
python3 -m compileall backend/app
python3 -m pytest backend/tests/test_replay_data_engine.py backend/tests/test_hyperbolic_replay_engine.py backend/tests/test_adaptive_replay_training.py -q
```

Record actual durations, generated/validated counts, provider coverage, blockers, and snapshot values. Do not extrapolate a daily rate unless both elapsed runtime and validated count are available.

- [ ] **Step 3: Write the final report with explicit acceptance states**

Every requirement must be marked `DONE`, `BLOCKED`, or `NOT DONE`. Include `BACKEND_NOT_RUNNING` if HTTP smoke checks cannot run. Never substitute empty JSON files for unavailable endpoint responses.

- [ ] **Step 4: Commit**

```bash
git add README.md HYPERBOLIC_REPLAY_ENGINE_REPORT.md
git commit -m "docs: report hyperbolic replay evidence"
```

---

### Task 11: Full Verification, Smoke Checks, Review, and Deploy

**Files:**
- Modify only files needed to fix failures caused by Tasks 1-10.

**Interfaces:**
- Produces: verified backend, measured smoke evidence, and deployed Hugging Face Space revision.
- Consumes: all preceding tasks.

- [ ] **Step 1: Run formatting and static integrity checks**

Run:

```bash
git diff --check
python3 -m compileall backend/app
```

Expected: no whitespace errors and all backend modules compile.

- [ ] **Step 2: Run focused tests**

Run:

```bash
python3 -m pytest backend/tests/test_replay_data_engine.py backend/tests/test_hyperbolic_replay_engine.py backend/tests/test_adaptive_replay_training.py -q
```

Expected: all focused tests pass.

- [ ] **Step 3: Run the complete backend suite**

Run: `python3 -m pytest -q`

Expected: all existing and new tests pass; warnings are recorded separately from failures.

- [ ] **Step 4: Apply migration to an existing-compatible database**

Run from `backend/`: `alembic upgrade head`

Expected: current database reaches `0030_hyperbolic_replay` without dropping existing data.

- [ ] **Step 5: Start the backend and execute required smoke checks**

Run:

```bash
curl -s -X POST http://localhost:8000/api/training/run-replay
curl -s http://localhost:8000/api/training/snapshot
curl -s http://localhost:8000/api/alpha/snapshot
```

Expected: POST returns a bounded real summary; Training returns stored replay progress; Alpha remains evidence-separated. If unavailable, report `BACKEND_NOT_RUNNING`.

- [ ] **Step 6: Review conceptual integrity and regressions**

Use `brooks-lint` to verify responsibilities remain separated, no GET side effects exist, no oversized service hides unrelated behavior, and the replay engine does not duplicate existing Trading Game ownership.

- [ ] **Step 7: Deploy cleanly to Hugging Face Space**

Use `hugging-face:hf-cli` to sync tracked application files to the configured BLUM Space, excluding `.git`, local databases, caches, test artifacts, secrets, and the unrelated audit ZIP. Confirm the Space reaches `RUNNING` on the deployed commit.

- [ ] **Step 8: Update report with final measured evidence and commit fixes**

Record tests, migration, smoke payloads, deployed revision, measured validated trades/day, remaining provider limitations, and all blocked acceptance items.

```bash
git add HYPERBOLIC_REPLAY_ENGINE_REPORT.md
git commit -m "chore: certify hyperbolic replay engine"
```

---

## Plan Self-Review

- Every design requirement maps to a task.
- Provider coverage and partial-timeframe behavior are tested before replay logic.
- Anti-look-ahead is asserted from persisted feature timestamps and entry timestamps.
- Cost, sizing, validation, feedback, adaptive runtime, API, scheduler, and snapshot responsibilities remain separate.
- GET behavior is read-only and POST execution is explicit.
- Promotion cannot bypass the 300-trade, multi-window, multi-market, benchmark, drawdown, or overfitting gates.
- The report cannot claim 5,000 validated trades/day without measured evidence.
