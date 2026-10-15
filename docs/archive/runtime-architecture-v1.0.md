# BLUM v1.0 Runtime Architecture

> Historical record. This document describes an earlier implementation or audit; its counts, configuration and readiness claims are not the current release status. Start with the [documentation index](../README.md) and [current data policy](../research/data-quality.md).

Version policy: the application version remains `v0.20.0 | market-sniper-engine-v1`.

This document describes the runtime refactor only. It does not change financial behavior, scoring logic, Learning Loop logic, Trading Game logic, Market Sniper logic or API contracts.

## Current Dependency Graph

```mermaid
graph TD
  Browser["Frontend pages"] --> ApiClient["frontend/lib/api.ts"]
  ApiClient --> Routes["FastAPI routes.py"]
  Routes --> RuntimeEndpoints["Runtime endpoints"]
  Routes --> FinanceEndpoints["Financial endpoints"]
  Routes --> TradingEndpoints["Trading Game endpoints"]
  Routes --> ModelEndpoints["Model/Reasoning endpoints"]

  Scheduler["APScheduler realtime.py"] --> MarketWorker["market_refresh"]
  Scheduler --> NewsWorker["news_refresh"]
  Scheduler --> LearningWorker["blum_professional_learning_cycle"]
  Scheduler --> SnapshotWorker["snapshot_producer"]
  Scheduler --> WatchdogWorker["runtime_snapshot_watchdog"]
  Scheduler --> AutonomousWorker["autonomous_research_engine"]

  MarketWorker --> MarketData["MarketDataService"]
  MarketWorker --> SignalEngine["SignalEngine"]
  MarketWorker --> LegacyLearning["Financial Brain Learning"]
  MarketWorker --> LearningLoop["LearningLoopService"]
  MarketWorker --> TradingGame["TradingGameSimulator"]

  LearningWorker --> LegacyLearning
  LearningWorker --> BlumModel["Blum Financial Model"]
  LearningWorker --> LearningLoop
  LearningWorker --> TradingGame
  LearningWorker --> SnapshotProducer["SnapshotProducerService"]

  SnapshotWorker --> SnapshotProducer
  SnapshotProducer --> Snapshots["dashboard_snapshots"]
  WatchdogWorker --> SnapshotWatchdog["SnapshotWatchdogService"]
  SnapshotWatchdog --> BrainEvents["brain_runtime_events"]

  RuntimeEndpoints --> CentralBrain["CentralBrainRuntime"]
  CentralBrain --> BrainEvents
  CentralBrain --> JobState["background_job_state"]
  CentralBrain --> Snapshots
  CentralBrain --> WorkerRuntime["RuntimeWorkerCoordinator"]

  FinanceEndpoints --> DB["PostgreSQL"]
  TradingEndpoints --> DB
  ModelEndpoints --> DB
  LearningLoop --> DB
  TradingGame --> DB
  SnapshotProducer --> DB
```

## Blocking Chains Found

- `routes.py` is still the largest composition root. It exposes every bounded context from one file and should eventually be split, but the current sprint preserves endpoints.
- `realtime.py` previously used one process-wide `running` flag. A slow snapshot, market refresh or learning cycle could defer unrelated jobs.
- `run_market_refresh` now owns only market prices, signals and ETF state. It does not invoke learning, model training or Trading Game work.
- Professional learning is split into independent Financial Brain, Financial Model, point-in-time Learning Loop and Trading Game workers. The legacy professional-cycle entry point is retained as a bounded compatibility alias, but the scheduler no longer runs a composite mega-job.
- The autonomous scheduler lane selects and persists research priorities; dedicated workers own the corresponding heavy computation.
- `CentralBrainRuntime` previously depended on `realtime_status()`, creating a scheduler/runtime import cycle. Learning health now reads the lightweight worker coordinator state.
- Frontend Learning Overview is already snapshot-first. Deep diagnostics and Trading Game tabs remain lazy by design.

## Target Runtime Architecture

```mermaid
graph LR
  subgraph Workers
    W1["Learning Loop Worker"]
    W2["Trading Game Worker"]
    W3["Market Data Worker"]
    W4["Snapshot Producer Worker"]
    W5["Alpha/Meta/Decision Workers"]
  end

  W1 --> EventBus["BrainEventBus"]
  W2 --> EventBus
  W3 --> EventBus
  W4 --> EventBus
  W5 --> EventBus

  W1 --> JobState["background_job_state"]
  W2 --> JobState
  W3 --> JobState
  W4 --> JobState
  W5 --> JobState

  W1 --> WorkerRuntime["RuntimeWorkerCoordinator"]
  W2 --> WorkerRuntime
  W3 --> WorkerRuntime
  W4 --> WorkerRuntime
  W5 --> WorkerRuntime

  W4 --> Snapshots["dashboard_snapshots"]
  EventBus --> Brain["CentralBrainRuntime"]
  JobState --> Brain
  WorkerRuntime --> Brain
  Snapshots --> Brain

  Brain --> RuntimeAPI["/brain/runtime-state"]
  Snapshots --> Frontend["Frontend snapshot views"]
```

Central Brain responsibilities:

- observe worker registry and worker state;
- compose runtime readiness;
- expose missing/stale snapshots;
- expose failed/stale modules;
- expose latest runtime events;
- never run financial computation directly.

Worker responsibilities:

- own its own schedule and runtime slot;
- publish start/completion/failure/deferred events;
- update durable job state;
- checkpoint through existing service-level persistence;
- produce knowledge/snapshots through its own service, not through page render.

## Worker Runtime

`RuntimeWorkerCoordinator` is an in-process worker registry and lock manager.

It replaces the scheduler-wide lock with worker-name isolation:

- duplicate `snapshot_producer` runs are deferred;
- `snapshot_producer` no longer blocks `blum_professional_learning_cycle`;
- `runtime_snapshot_watchdog` no longer blocks `market_refresh`;
- state is visible through `running_jobs`, `running_count` and `worker_registry`.
- stale `running` job rows from a previous process are marked `interrupted` on startup;
- previous-process `failed` rows are archived as `previous_failed` while their events remain audit evidence.

Registered workers include:

- `runtime_snapshot_watchdog`
- `snapshot_producer`
- `autonomous_research_engine`
- `news_refresh`
- `market_refresh`
- `data_gap_repair`
- `accuracy_audit`
- `macro_refresh`
- `fundamentals_refresh`
- `ipo_refresh`
- `financial_brain_learning`
- `blum_financial_model_cycle`
- `blum_point_in_time_learning_loop`
- `blum_trading_game`
- `blum_professional_learning_cycle`
- startup warm-up workers

## Event Flow

Events are persisted in `brain_runtime_events`.

Core event flow:

```mermaid
sequenceDiagram
  participant Scheduler
  participant WorkerRuntime
  participant JobState
  participant Worker
  participant EventBus
  participant Brain

  Scheduler->>WorkerRuntime: begin(job_name)
  alt same worker already running
    WorkerRuntime-->>Scheduler: deferred
    Scheduler->>EventBus: module_deferred
  else worker available
    WorkerRuntime-->>Scheduler: running state
    Scheduler->>JobState: start(job_name)
    Scheduler->>Worker: run financial/background work
    Worker-->>Scheduler: result
    Scheduler->>JobState: complete/fail
    JobState->>EventBus: module_completed/module_failed
    Scheduler->>WorkerRuntime: complete/fail(job_name)
  end
  Brain->>EventBus: read latest module events
  Brain->>WorkerRuntime: read running worker state
```

## Knowledge Flow

Financial modules own deep evidence. The Central Brain only consumes metadata:

- latest run state;
- latest status;
- latest snapshot freshness;
- last event per module;
- summary warnings;
- runtime bottleneck pointer.

Deep financial artifacts stay in their bounded services and tables. This avoids turning the Central Brain into another monolith.

## Snapshot Flow

```mermaid
graph TD
  Producer["SnapshotProducerService"] --> LatestRows["Latest stored evidence"]
  LatestRows --> Snapshot["dashboard_snapshots"]
  Snapshot --> SummaryAPI["Summary/read endpoints"]
  SummaryAPI --> UI["Frontend"]
  Watchdog["SnapshotWatchdogService"] --> Health["/snapshots/health"]
  Watchdog --> Events["snapshot_requested events"]
```

Rules:

- page render never recalculates;
- stale snapshots are returned with warnings;
- missing snapshots are reported, not fabricated;
- manual snapshot production remains explicit through `POST /snapshots/produce`;
- heavy recalculation remains scheduled/manual, not GET-triggered.

## Migration Notes

No destructive migration is required for this refactor. Existing runtime tables are reused:

- `brain_runtime_events`
- `background_job_state`
- `dashboard_snapshots`
- `trading_game_ledger_snapshots`
- `equity_curve_snapshots`

The new worker runtime is in-process and backward-compatible with APScheduler.

## Validation Targets

- `GET /api/learning-intelligence/summary` p95 under 300 ms after warm-up.
- Learning Overview max two initial requests.
- No heavy POST during page render.
- Different workers can run independently.
- Duplicate runs of the same worker are deferred.
- Central Brain reports active workers, missing snapshots, stale modules and readiness.

No performance improvement should be claimed without live `/performance/diagnostics` measurements after deploy and warm-up.
