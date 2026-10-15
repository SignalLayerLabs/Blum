# Hyperbolic Multi-Timeframe Replay Engine Report

> Historical record. This document describes an earlier implementation or audit; its counts, configuration and readiness claims are not the current release status. Start with the [documentation index](../README.md) and [current data policy](../research/data-quality.md).

## Scope

This sprint adds a real, persisted replay training path. It does not add dashboards, broker connectivity, real-money execution, synthetic prices or synthetic outcomes. Project version was not changed.

## Architecture

```text
PriceHistory / free providers
  -> MultiProviderReplayDataService
  -> ReplayMarketBar + ReplayDataCoverage
  -> BlumHyperbolicReplayEngine
  -> ReplayExecutionModel + ReplayPositionSizer
  -> ReplayExperimentService + ReplayWalkForwardValidator
  -> ReplayLearningFeedbackService
  -> ReplayTrainingSnapshotService
  -> read-only Training Ground snapshot
```

The scheduler runs bounded slices through `BlumAdaptiveTrainingController`. `background_job_state` stores the asset cursor, duration and item count so later slices continue instead of restarting at the first ticker.

## Files Changed

- `backend/alembic/versions/0030_hyperbolic_replay_engine.py`
- `backend/app/api/routers/training.py`
- `backend/app/core/config.py`
- `backend/app/engine/brain/trader_brain.py`
- `backend/app/engine/facade.py`
- `backend/app/models.py`
- `backend/app/providers/replay_data_provider.py`
- `backend/app/services/adaptive_replay_training.py`
- `backend/app/services/hyperbolic_replay.py`
- `backend/app/services/realtime.py`
- `backend/app/services/replay_data.py`
- `backend/app/services/replay_execution.py`
- `backend/app/services/replay_validation.py`
- `backend/app/services/worker_runtime.py`
- `backend/tests/test_adaptive_replay_training.py`
- `backend/tests/test_hyperbolic_replay_engine.py`
- `backend/tests/test_replay_data_engine.py`
- `requirements.txt`
- `README.md`

## Data Providers and Coverage

Adapters: Yahoo Chart, yfinance, Stooq daily and Nasdaq daily. The local replay store is checked first. Existing daily `PriceHistory` rows are imported without changing their source table contract. A timestamp is unique per asset/timeframe, so fallback providers cannot duplicate the same market bar.

Measured HTTP smoke run on 13 July 2026:

- assets replayed: `SPY`, then `QQQ` through the persisted cursor;
- stored real daily rows: 2,506 across two assets;
- observed range: 14 July 2021 to 10 July 2026;
- provider used: yfinance fallback after Yahoo Chart was unavailable;
- coverage status: partial at 99.78% because the requested end fell after the latest completed market session;
- explicit blockers retained: `PROVIDER_UNAVAILABLE`, `COVERAGE_INCOMPLETE`.

No 12-month intraday coverage claim was made during this smoke run. Free-provider retention remains provider-dependent.

## Replay and Execution Logic

Setup requirements are explicit:

- intraday breakout: `1d + 15m + 5m + 1m`, execution on `1m`;
- intraday trend: `1d + 15m + 5m`, execution on `5m`;
- mean reversion: `15m + 5m`, execution on `5m`;
- pullback: `1d + 15m`, execution on `15m`;
- swing breakout: `1d`, execution on `1d`.

Each persisted decision stores context timestamps, required timeframes and state transitions from candidate through evaluated. Tests assert that every context timestamp is at or before the decision and every entry is later than the signal.

Higher-timeframe confirmation is operational, not decorative: a contradictory daily/15m/5m context blocks an intraday trigger. A unique asset/setup/timeframe/decision key prevents repeated universe passes from counting the same historical decision twice.

Execution costs differ for liquid US equities, less-liquid US equities, European equities and ETFs. Position sizing is reduced by volatility, liquidity, confidence, edge, data quality and regime alignment.

## Experiments and Validation

Experiment combinations are bounded and include entry, stop, target, holding period, confidence, risk/reward, timeframe and regime filter. Experiment identity uses a stable SHA-256 digest, so restarts do not create process-dependent duplicates.

Validation records sample size, chronological windows, benchmark excess, expectancy, average R, win rate, profit factor, Sharpe/Sortino proxies, drawdown, stability, regime dependency and overfitting risk.

Promotion requires:

1. at least 300 evaluated trades;
2. positive benchmark-relative and risk-adjusted evidence;
3. multiple independent windows;
4. evidence from more than one market;
5. acceptable drawdown and overfitting;
6. explicit out-of-sample improvement over the active model baseline;
7. reversible candidate weights.

## Adaptive Runtime

The controller monitors CPU, RAM, API p95, active jobs, recent batch duration and replay dataset size. It throttles, waits, pauses or records an isolated error without discarding the cursor. No default slice exceeds 120 seconds.

## Measured Smoke Evidence

Two productive HTTP replay slices produced:

- 20 generated trades;
- 20 evaluated trades;
- 20 idempotent feedback audits;
- 20 memory applications;
- 2 persisted experiments;
- 0 strategy promotions;
- 1.8095 seconds total replay-engine runtime across three runs, including the initial blocked configuration check;
- average R: -0.2786 in the small smoke sample;
- average benchmark excess: +0.4034 percentage points where synchronized benchmark bars were available.

The first productive slice returned 10 validated trades in 1.1784 seconds. The second resumed at QQQ and returned another 10 in 0.6292 seconds. These short runs do not prove 5,000 validated trades per day and are not extrapolated into a daily claim.

## Snapshot Example

```json
{
  "replay_engine_status": "COMPLETED",
  "trades_replayed_today": 20,
  "validated_trades_today": 20,
  "target_trades_per_day": 5000,
  "throughput_percent": 0.4,
  "markets_replayed": ["United States"],
  "timeframes_replayed": ["1d"],
  "adaptive_training_state": "RUNNING",
  "reason_if_target_missed": "Daily target remains in progress; continue bounded replay cycles."
}
```

## Migration Verification

`0030_hyperbolic_replay` upgraded and downgraded successfully in an isolated SQLite compatibility database with the required parent tables. A clean full SQLite migration chain remains blocked by pre-existing migration `0003_signal_metadata`, whose `ALTER COLUMN ... DROP DEFAULT` syntax is not supported by SQLite. This sprint did not rewrite that unrelated historical migration.

## Verification

- `git diff --check`: passed.
- `python -m compileall app`: passed.
- focused replay suite: 31 passed before the final contradiction guard; all replay tests are included in the complete result below.
- complete backend suite: 236 passed, 0 failed in 20.21 seconds with `PAPER_FORWARD_LIFECYCLE_ENABLED=false`.
- migration `0030` isolated SQLite upgrade, downgrade and re-upgrade: passed.
- required HTTP smoke checks: POST replay, GET training snapshot and GET alpha snapshot all returned HTTP 200.

## Acceptance Status

- DONE: DB-first multi-provider fallback and cached normalized OHLCV.
- DONE: daily, 15m, 5m and 1m chronological replay contracts and full-path test.
- DONE: anti-look-ahead assertions and later executable entry.
- DONE: USA and European market configuration and cursor-based universe traversal.
- DONE: market/liquidity-sensitive costs and dynamic sizing.
- DONE: bounded persisted experiments.
- DONE: multi-window, multi-market, 300-sample and out-of-sample promotion gates.
- DONE: replay evidence separated from walk-forward and paper-forward evidence.
- DONE: adaptive CPU/RAM/API/job-budget states, checkpoint and resume.
- DONE: read-only snapshot and explicit manual POST endpoint.
- DONE: no broker integration, real-money execution, synthetic data or synthetic outcomes.
- BLOCKED: 12 months of complete 1m/5m/15m history cannot be guaranteed by free providers; coverage is reported per provider.
- BLOCKED: 5,000 validated trades/day is configured and measured, but not yet certified by a continuous 24-hour production run.
- BLOCKED: full SQLite migration from revision zero is stopped by pre-existing revision `0003`; migration `0030` itself is SQLite/PostgreSQL-safe.

## Next Operational Step

Run the deployed scheduler for 24 hours, inspect provider/timeframe coverage, and certify actual validated trades/day. Do not relax data quality or promotion gates merely to reach the throughput target.
