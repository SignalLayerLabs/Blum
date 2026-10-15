# Live Intraday Paper Scalping Engine Design

**Date:** 2026-07-13

## Goal

Extend BLUM's existing paper-forward lifecycle so strategies promoted by the Hyperbolic Replay Engine can create, manage, close, and learn from strict real-data intraday paper trades across supported USA and European markets.

This sprint does not add broker execution, real-money trading, synthetic fills, frontend-triggered work, or a new dashboard. It preserves replay, walk-forward, and forward-paper evidence as distinct evidence classes.

## Non-Negotiable Data Policy

The engine uses the strict data gate selected by the user:

- Daily bars establish market regime.
- 15-minute bars establish the setup.
- 5-minute bars provide confirmation.
- 1-minute bars provide the entry trigger and lifecycle marks.
- Every required timeframe must be present, fresh, and internally ordered.
- Missing or stale data produces `INTRADAY_DATA_BLOCKED`.
- The engine never degrades a 1-minute strategy to a 5-minute approximation.
- A provider response is evidence only after it is normalized, timestamped, quality-scored, and persisted.

## Architecture

The implementation composes focused domain services around the existing `LiveForwardPaperTrade`, event ledger, market desk, Quant Edge, and feedback-loop infrastructure:

```text
ReplayStrategyValidation
        |
        v
BlumPromotedStrategyRegistry
        |
        +------------------+
        |                  |
StrictIntradayDataGateway  Market Desk Agents
        |                  |
        +--------+---------+
                 v
BlumIntradayOpportunityEngine
                 |
     +-----------+------------+
     |           |            |
Cost Model   Diversification  Dynamic Sizing
     |           |            |
     +-----------+------------+
                 v
BlumIntradayPaperEngine
                 |
                 v
LiveForwardPaperTrade + append-only events
                 |
                 v
Forward-only learning evidence and Alpha split
```

The orchestrator coordinates lightweight services but does not duplicate market scanning, paper-game capital, trade serialization, event persistence, or learning-memory logic.

## Components

### `BlumPromotedStrategyRegistry`

Reads the latest `ReplayStrategyValidation` per setup and exposes an immutable promoted-strategy projection. A strategy is eligible only when all gates pass:

- verdict is `PROMOTED_TO_PAPER`;
- sample size is at least `REPLAY_MIN_PROMOTION_SAMPLES` (default 300);
- overfitting risk is below the configured maximum;
- walk-forward metrics are stable;
- risk-adjusted alpha is positive;
- the requested market and timeframe stack are supported.

The registry never promotes a strategy itself. Promotion remains owned by replay validation.

### `StrictIntradayDataGateway`

Uses the existing replay provider chain and normalized replay-bar store. It refreshes only missing current ranges during command execution and returns a point-in-time `IntradayMarketFrame` containing daily, 15-minute, 5-minute, and 1-minute bars. Each frame includes provider, latest timestamp, age, quality score, liquidity proxy, volatility proxy, and explicit blockers.

Provider failures are isolated. The gateway never fabricates bars, fills gaps with interpolation, or silently substitutes timeframes.

### `BlumIntradayOpportunityEngine`

Evaluates enabled desk assets against promoted strategy rules in this sequence:

1. daily regime alignment;
2. 15-minute setup;
3. 5-minute confirmation;
4. 1-minute trigger;
5. liquidity and volatility filters;
6. spread and cost model;
7. Quant Edge validation;
8. portfolio concentration gate.

Its result is one of `INTRADAY_TRADE_CANDIDATE`, `INTRADAY_WATCHLIST`, `INTRADAY_BLOCKED`, or `INTRADAY_DATA_BLOCKED`. Every non-candidate result includes machine-readable blocker codes and a human-readable reason.

### Costs And Execution

The cost model estimates commission, half-spread on entry and exit, slippage, and total round-trip cost. Expected move and target distance must remain positive after costs. A trade is rejected as `COSTS_KILL_EDGE`, `SPREAD_TOO_WIDE`, `LIQUIDITY_TOO_LOW`, `EXPECTED_MOVE_TOO_SMALL`, or `SESSION_NOT_ALLOWED` when appropriate.

The simulated fill uses the first eligible 1-minute bar after the frozen decision timestamp plus adverse spread/slippage. It never uses a bar preceding the decision.

### Diversification And Sizing

The portfolio gate enforces configurable limits for total positions, ticker, market, desk, asset class, and correlated exposure. The default is one open intraday position per ticker. Diversification is never forced when no valid opportunity exists.

Sizing is derived from paper capital, stop distance, volatility, liquidity, confidence, edge, regime, existing exposure, and correlation. The engine stores notional, quantity, risk amount, risk percent, and sizing rationale. Total paper risk is capped.

### Intraday Lifecycle

The lifecycle freezes the original decision payload and appends events rather than rewriting evidence. Supported state events are:

- `INTRADAY_TRADE_CANDIDATE`
- `INTRADAY_TRADE_OPENED`
- `INTRADAY_TRADE_UPDATED`
- `INTRADAY_TRADE_CLOSED`
- `INTRADAY_OUTCOME_EVALUATED`

Open positions are marked only from fresh 1-minute bars later than the last processed timestamp. The lifecycle tracks current price, unrealized P/L, current R, MFE, MAE, benchmark return, benchmark excess, holding time, and costs.

Exit reasons are `STOP_HIT`, `TARGET_HIT`, `TIME_STOP`, `SIGNAL_DECAY`, `REGIME_CHANGE`, `TRAILING_STOP`, `DATA_GAP`, `MARKET_CLOSE`, and `INVALIDATED`. Overnight holding is blocked unless the promoted strategy explicitly allows it.

### Learning Feedback

Only a closed and outcome-evaluated intraday trade may update learning. One idempotent feedback operation creates or updates:

- `TradeLearningEvidence`;
- `LearningEvent`;
- `StrategyMemory`;
- `SignalPerformance`;
- setup, market, desk, timeframe, session, regime, and exit-reason evidence;
- `FeedbackLoopAudit`.

All records identify the evidence as `PAPER_FORWARD_INTRADAY`. Replay evidence is never counted as forward alpha.

## Persistence

A backward-compatible Alembic migration extends `live_forward_paper_trades` with nullable intraday fields and adds a compact `intraday_paper_runs` audit table. Existing paper-forward records remain valid.

The trade stores strategy validation identity, market, desk, session, timeframe stack, data timestamps, cost estimates, net expectancy, sizing rationale, lifecycle cursor, MFE, MAE, trailing stop, and evidence type. The run stores timing, state, counts, blockers, and summary payload.

## Runtime And API

`POST /api/paper-forward/run-intraday` runs one bounded command cycle: scan, classify, open, update, close, evaluate, and publish the paper-forward snapshot. The frontend never calls it on mount.

The scheduler runs the same bounded operation at a configurable cadence with an anti-overlap worker lock. It respects USA and European sessions and returns `RUNNING`, `MARKET_CLOSED`, `THROTTLED`, `DATA_BLOCKED`, `PAUSED_FOR_RUNTIME`, or `ERROR`. Startup is never blocked.

All GET endpoints remain read-only. `/api/paper-forward/snapshot` adds the requested intraday counters, distribution, P/L, cost, inactivity explanation, and next action. `/api/alpha/snapshot` adds a separate `intraday_paper_forward` split computed only from closed intraday paper trades.

## Failure Handling

- Provider failure is isolated per ticker and timeframe.
- Missing promoted strategies produces a truthful inactive state.
- Missing bars or stale timestamps block the candidate.
- Duplicate runs and candidates are idempotent.
- Database failures roll back the affected command without corrupting frozen decisions.
- A data gap during an open trade closes conservatively only when the configured gap policy requires it; otherwise it pauses management and records the blocker.
- Snapshot reads return partial, stale-aware state rather than triggering work.

## Testing

Tests follow red-green-refactor and cover:

- promotion and rejection gates;
- strict daily/15m/5m/1m requirements;
- anti-lookahead entry and updates;
- fresh real-data requirements;
- cost-positive expectancy;
- concentration and duplicate-position rules;
- dynamic sizing and total-risk cap;
- stop, target, trailing, time, invalidation, market-close, and data-gap exits;
- closed-only learning updates;
- replay/forward evidence separation;
- snapshot inactivity explanations;
- Alpha intraday split;
- scheduler anti-overlap and market-session behavior;
- read-only GET behavior;
- empty database and provider failure safety.

The final verification includes focused tests, the complete backend suite, compileall, migration upgrade/downgrade on an isolated database, local HTTP smoke checks, clean Hugging Face deploy, and remote read-only verification. Production activity and alpha are reported only from observed forward outcomes.

## Explicit Non-Goals

- Real-money or broker execution
- Tick or sub-minute scalping
- Synthetic or interpolated market data
- Automatic strategy promotion
- A new dashboard or frontend workflow
- Mixing replay performance with paper-forward alpha
- Opening trades merely to increase trade count
