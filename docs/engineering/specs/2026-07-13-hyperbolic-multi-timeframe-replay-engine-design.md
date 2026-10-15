# Hyperbolic Multi-Timeframe Replay Engine Design

**Date:** 2026-07-13  
**Status:** Approved for implementation planning  
**Scope:** Backend replay training, persisted snapshots, and manual bounded execution  
**Out of scope:** Dashboards, broker integration, real-money execution, unrelated refactors, synthetic market data

## Objective

Build a real accelerated replay training engine that allows BLUM to study stored and freely obtainable USA and European OHLCV history without look-ahead bias. The engine targets 5,000 validated replay trades per day, but reports measured throughput and blockers rather than fabricating coverage or outcomes.

The engine must preserve the distinction between:

- `REPLAY_EVIDENCE`
- `WALK_FORWARD_EVIDENCE`
- `PAPER_FORWARD_EVIDENCE`

Replay evidence can influence stored learning memory after validation. It can never be presented as paper-forward or live-forward alpha.

## Architectural Decision

Intraday replay data will use a dedicated normalized store instead of extending the existing daily `PriceHistory` table.

```text
Free market-data providers
        |
        v
MultiProviderReplayDataService
        |
        v
ReplayMarketBar + ReplayDataCoverage
        |
        v
BlumHyperbolicReplayEngine
        |
        +--> ReplayExecutionModel
        +--> ReplayPositionSizer
        +--> ReplayExperimentService
        |
        v
ReplayWalkForwardValidator
        |
        v
ReplayLearningFeedbackService
        |
        v
ReplayTrainingSnapshotService
```

This boundary keeps existing daily financial behavior compatible, preserves true intraday timestamps, and prevents intraday bars from colliding with the daily unique key on `PriceHistory`.

## Data Model

### ReplayMarketBar

Stores normalized OHLCV bars with:

- asset reference;
- source symbol and normalized symbol;
- market and exchange;
- timeframe (`1d`, `15m`, `5m`, `1m`);
- timezone-aware bar timestamp normalized to UTC;
- open, high, low, close, and volume;
- provider;
- acquisition timestamp;
- data quality score;
- source and license metadata.

The natural uniqueness boundary is asset, timeframe, provider, and bar timestamp. Queries used by replay must be indexed by asset, timeframe, and timestamp.

### ReplayDataCoverage

Stores the requested and observed coverage for an asset/provider/timeframe:

- requested and available date ranges;
- row count and coverage percentage;
- missing intervals;
- freshness and data quality;
- acquisition status;
- explicit blockers;
- provider/source/license metadata.

Supported blocker codes are:

- `PROVIDER_UNAVAILABLE`
- `UNSUPPORTED_TIMEFRAME`
- `NO_INTRADAY_HISTORY`
- `STALE_DATA`
- `COVERAGE_INCOMPLETE`
- `DATA_QUALITY_LOW`

### Replay Runs, Trades, and Validation

Replay runs persist resource budgets, cursors, selected markets/assets, timeframes, counts, duration, blockers, and evidence type. Replay trades persist the full frozen decision context, cost model, position sizing, timestamps, state transitions, outcome, benchmark-relative metrics, and validation window.

Experiment and validation records extend the existing `BlumLearningExperiment` contract where compatible. Additional replay-specific payloads must remain bounded and auditable.

## Provider Architecture

`ReplayDataProvider` is a small provider contract that accepts symbol, timeframe, start, and end and returns normalized source bars plus metadata. `MultiProviderReplayDataService` owns orchestration:

1. inspect local coverage;
2. calculate missing ranges;
3. fetch only missing ranges;
4. try configured providers in priority order;
5. validate and normalize bars;
6. persist accepted bars and coverage metadata;
7. return truthful partial coverage and blockers.

Initial adapters reuse existing free sources where their actual capabilities permit:

- Yahoo Chart and optional yfinance for supported intraday/daily ranges;
- Stooq and Nasdaq historical adapters for daily fallback;
- future providers through the same interface.

The existing Yahoo normalization must be corrected for replay use so intraday timestamps are not converted to calendar dates. The replay adapter must not resample a larger timeframe into fake smaller-timeframe observations.

If a provider cannot supply twelve months of intraday history, the engine continues with the genuinely covered timeframe combinations and records unsupported combinations as `DATA_BLOCKED`. A missing `1m` series must not block a valid `daily/15m/5m` study, but that study cannot claim one-minute execution evidence.

## Replay Semantics

The chronological pipeline is:

```text
daily regime available at T
  -> closed 15m setup context available at T
  -> closed 5m confirmation available at T
  -> closed 1m execution trigger available at T
  -> first legally executable fill
  -> chronological trade management
  -> outcome evaluation after closure
```

Supported setup families are intraday trend, mean reversion, breakout, pullback, and daily-context swing. Each setup declares the minimum timeframe combination it requires. Unsupported combinations are rejected explicitly.

Replay trade states are:

- `REPLAY_CANDIDATE`
- `REPLAY_OPEN`
- `REPLAY_CLOSED`
- `REPLAY_EVALUATED`
- `REJECTED_NO_EDGE`
- `REJECTED_OVERFITTING`
- `DATA_BLOCKED`

### Anti-Look-Ahead Invariants

- Every feature and indicator is calculated only from bars with timestamps less than or equal to the replay clock.
- A signal based on a bar close cannot receive an earlier fill; the next executable bar or an explicitly modeled close fill is used.
- Point-in-time context is frozen before the outcome horizon is read.
- Future bars are queried only by the outcome evaluator after the prediction/trade record is flushed.
- Validation windows are chronological and non-overlapping where required.
- Replay, walk-forward, and paper-forward evidence labels are immutable.
- Missing lower-timeframe data is never synthesized from higher-timeframe bars.

## Execution and Position Sizing

`ReplayExecutionModel` applies explicit cost profiles for:

- US equities;
- European equities;
- ETFs;
- liquid large caps;
- less-liquid assets;
- regular and less-liquid market sessions.

Each profile models spread, slippage, commission, liquidity penalty, and gap risk. Entry and exit prices persist both theoretical and modeled execution values.

`ReplayPositionSizer` computes an informational paper size from:

- volatility and ATR risk;
- liquidity;
- confidence;
- validated edge score;
- data quality;
- regime alignment;
- distance to invalidation;
- maximum risk budget.

Lower data quality, weak liquidity, or hostile regimes can only reduce size or block a trade. They cannot increase confidence or exposure.

## Bounded Strategy Experiments

`ReplayExperimentService` completes the current experiment-manager behavior without uncontrolled brute force. Each cycle has strict limits for runtime, assets, experiments, and combinations.

Experiments may vary:

- entry trigger;
- stop method;
- target method;
- maximum holding period;
- confidence threshold;
- risk/reward threshold;
- timeframe combination;
- market and regime filter.

Each experiment persists its hypothesis, market, setup, training and validation windows, sample size, cost profile, benchmark, metrics, overfitting score, verdict, and next action.

## Walk-Forward Validation and Promotion

`ReplayWalkForwardValidator` measures:

- benchmark excess;
- expectancy and average R;
- Sharpe and Sortino proxies;
- profit factor;
- maximum drawdown;
- win rate;
- stability across windows;
- stability across USA and Europe;
- regime dependence;
- overfitting risk.

Promotion to paper requires all of the following:

- at least 300 validated trades;
- positive risk-adjusted alpha after modeled costs;
- multiple independent walk-forward windows;
- evidence from more than one market;
- acceptable drawdown;
- acceptable stability;
- acceptable overfitting risk.

Verdicts are:

- `PROMOTED_TO_PAPER`
- `NEEDS_MORE_EVIDENCE`
- `REJECTED_NO_EDGE`
- `REJECTED_OVERFITTING`
- `REJECTED_UNSTABLE`
- `REJECTED_BAD_DRAWDOWN`

No `ModelVersion` is created merely because a replay cycle completed. Promotion requires measured out-of-sample improvement against the active baseline and sufficient evidence.

## Adaptive Training Runtime

`BlumAdaptiveTrainingController` runs resumable, time-bounded replay slices. It observes CPU, memory, API latency, active jobs, average batch duration, and dataset size.

States are:

- `RUNNING`
- `THROTTLED`
- `PAUSED_FOR_RUNTIME`
- `BUDGET_WAIT`
- `ERROR`

Low load permits a gradual increase in batch size or parallelism. Medium load maintains normal throughput. High load or degraded API health reduces intensity or pauses heavy work. Every slice persists its cursor and heartbeat so the next scheduler cycle resumes instead of restarting.

The daily target is 5,000 validated replay trades. The system reports actual validated trades, throughput percentage, and a concrete reason when the target is missed. The target does not authorize fabricated trades or relaxed validation.

## Learning Feedback

Only evaluated replay outcomes may update:

- `LearningEvent`;
- `StrategyMemory`;
- `SignalPerformance`;
- `LearningFocusPriority`;
- Research Planner priorities;
- `FeedbackLoopAudit`.

Every update stores evidence type, replay run, experiment, model version, weights, market, regime, timeframe, sample size, and validation status. Research priorities can alter future sampling, but the broad exploration allocation remains present.

## API and Snapshot Contracts

### POST /api/training/run-replay

Runs one bounded replay slice and returns:

- selected assets and markets;
- timeframes actually used;
- generated and validated trades;
- experiments run;
- promoted and rejected strategies;
- runtime;
- resource limits;
- blockers;
- next action.

This endpoint performs explicit work and is never called automatically by frontend rendering.

### GET /api/training/snapshot

Remains read-only and snapshot-first. It adds:

- replay engine status;
- replayed and validated trades today;
- 5,000-trade target and throughput;
- markets and timeframes replayed;
- experiment and verdict counts;
- CPU and memory budgets;
- adaptive state;
- latest replay and productive run timestamps;
- target-miss reason.

If no replay snapshot exists, it returns a truthful initializing or blocked state without triggering computation.

## Error Handling

Provider failures are isolated by provider and range. A failed asset or timeframe does not abort unrelated replay work. Database writes use bounded transactions and idempotent uniqueness constraints. A controller failure persists status, cursor, last successful checkpoint, and error details before yielding to the scheduler.

Partial data is usable only by setup configurations whose declared requirements are satisfied. Data quality and blocker decisions are persisted so they can be audited later.

## Verification Strategy

Implementation follows test-driven development. Tests must prove:

- DB-first reads and missing-range fallback;
- true intraday timestamp preservation;
- idempotent OHLCV persistence;
- explicit partial-coverage blockers;
- chronological replay with no access to future candles;
- no execution before signal availability;
- cost differences by market and liquidity;
- dynamic sizing reductions under worse conditions;
- bounded experiments;
- multi-window and multi-market promotion gates;
- minimum 300-trade promotion threshold;
- immutable evidence-class separation;
- resource throttling, pause, checkpoint, and resume;
- read-only training snapshot;
- manual endpoint summary from persisted real simulation results;
- SQLite and PostgreSQL-safe migration types;
- compatibility with the complete backend suite.

Smoke verification includes:

```bash
python3 -m compileall backend/app
curl -s -X POST http://localhost:8000/api/training/run-replay
curl -s http://localhost:8000/api/training/snapshot
curl -s http://localhost:8000/api/alpha/snapshot
```

If the backend is unavailable, the report states `BACKEND_NOT_RUNNING` and does not create empty response artifacts.

## Delivery and Reporting

The implementation will include an Alembic migration, focused backend tests, configuration defaults, scheduler integration, API changes, and `HYPERBOLIC_REPLAY_ENGINE_REPORT.md`.

The report must list changed files, architecture, provider capabilities, measured coverage, replay behavior, costs, experiments, validation gates, resource behavior, endpoint examples, measured validated trades per day, blockers, and an acceptance checklist marked `DONE`, `BLOCKED`, or `NOT DONE`.

Deployment follows successful migration, focused tests, full backend tests, compile checks, smoke checks, and clean Hugging Face Space deployment. Completion cannot be claimed if the engine only creates plans without executing persisted replay simulations.
