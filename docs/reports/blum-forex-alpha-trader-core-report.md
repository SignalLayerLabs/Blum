# BLUM Forex Alpha Trader Core Report

> Historical record. This document describes an earlier implementation or audit; its counts, configuration and readiness claims are not the current release status. Start with the [documentation index](../README.md) and [current data policy](../research/data-quality.md).

## Repository State Before Implementation

Alembic head was `0035_decision_execution_parity`. BLUM already stored Forex
assets, replay bars, generic intraday decisions, generic realistic execution,
strategy-factory validations and paper-forward evidence. It did not have an
authoritative Forex analysis-to-order core, strict 1H context, directional
bid/ask lifecycle, swap/margin accounting, currency netting or an isolated
Forex scheduler and snapshot.

The detailed classification is in `FOREX_TRADER_CURRENT_STATE.md`.

## Reused and Consolidated

- Reused immutable `ReplayMarketBar` evidence and the multi-provider replay data layer.
- Reused the Alpha Strategy Factory and promoted/experimental strategy registry.
- Reused the paper game capital record and dashboard snapshot store.
- Reused APScheduler, bounded runtime jobs and snapshot production conventions.
- Preserved `BlumIntradayPaperEngine` for non-Forex and legacy Forex contracts.
- Restricted the new Forex core to strategies explicitly validated on `1h/15m/5m/1m`.
- Kept generic execution unchanged; dedicated Forex execution owns bid/ask, margin and swap semantics.

## Architecture Implemented

```text
stored market bars + broker profile + strategy evidence
  -> context / price action / macro agents
  -> scalping proposal
  -> contrarian veto
  -> portfolio risk and currency netting
  -> realistic paper execution
  -> minute position management
  -> terminal outcome evidence
  -> readiness recalibration
  -> persisted snapshot
```

Only `BlumForexTraderCore` can create a Forex paper position. Agents return
typed immutable outputs and cannot open a trade.

## Persistence and Migration

Migration: `0036_autonomous_forex_alpha_trader.py`.

New additive tables:

- `forex_trader_cycles`
- `forex_decisions`
- `forex_positions`
- `forex_learning_evidence`
- `forex_strategy_readiness`
- `forex_trader_runtime_state`

JSON uses PostgreSQL JSONB with a SQLite JSON variant. Learning evidence is
append-only. Historical replay and paper-forward evidence use separate tables
and evidence classes.

## Agent Contracts

- `BlumForexMarketContextAgent`: regime, direction, session, liquidity, freshness and quality.
- `BlumForexPriceActionAgent`: measurable aligned trend/breakout geometry and 1m trigger.
- `BlumForexMacroAgent`: observed macro/cross-asset fields only; absent evidence receives zero confidence.
- `BlumForexScalpingExpertAgent`: LONG, SHORT or ABSTAIN with gross/cost/net pips and R.
- `BlumForexContrarianRiskAgent`: mandatory independent objections and veto.
- `BlumForexPositionManagerAgent`: observed bid/ask valuation, MFE/MAE, stop, target, time stop, costs and terminal learning.

## Broker and Execution Model

The versioned `paper_eu_30x` profile has a EUR paper account, broker leverage
30x, stricter internal leverage, margin, commission, pair/session spread,
slippage, swap, triple-swap day, micro-lot rules and supported order types.

The execution estimate is dynamic: spread and adverse slippage respond to the
pair, active session, observed liquidity, volatility and event risk. Open
positions are marked against the executable quote side and persist unrealized
gross/net P/L, current R and spread impact. The configured price precision and
minimum lot are separate named fields; this prevents price precision from being
misread as an execution-size constraint.

Long entry fills at ask or worse and exits at bid or worse. Short entry fills at
bid or worse and exits at ask or worse. MARKET, LIMIT, STOP and STOP_LIMIT
orders have CREATED, SUBMITTED, ACKNOWLEDGED, PARTIALLY_FILLED, FILLED,
REJECTED, EXPIRED and CANCELLED-compatible state contracts. No midpoint fill is
the default. Theoretical P/L is separated from execution costs to prevent cost
double counting.

## Risk and Currency Netting

- Maximum risk per new position: 0.5% of current paper equity.
- Daily realized-loss stop: 2%.
- Maximum open Forex positions: 4.
- One open position per pair.
- No martingale or loss-recovery sizing.
- Position size derives from stop distance and configured pip value.
- Size is reduced by low confidence, high execution cost and active drawdown.
- Margin and stricter internal leverage are both enforced.
- Pair-correlation exposure is bounded before a new position can be approved.
- Base and quote currency exposures are signed and netted, so EUR/USD long,
  GBP/USD long and USD/CHF short are recognized as a short-USD cluster.

## Scheduler

`BlumForexTradingScheduler` is an independent one-minute job with APScheduler
`max_instances=1`, a persistent heartbeat, a 55-second lease, idempotent minute
key, stale-lock recovery and backoff state. It refreshes one rotating live 1m
pair per cycle together with its strict `1h/15m/5m/1m` context stack. Replay
workers continue deeper research independently. It scans all stored eligible
pairs. PAUSED and EMERGENCY_STOP prevent entries but continue position
monitoring.

## Learning and Alpha Readiness

Only terminal outcome labels enter `forex_learning_evidence`. Each row preserves
expected and realized result, difference, likely cause, lesson, strength and
whether an update is justified. Readiness remains one of TRAINING_SIGNAL,
PAPER_TRADE_ELIGIBLE, ALPHA_SIGNAL_ELIGIBLE, DEGRADED or SUSPENDED.

Alpha eligibility requires at least 100 closed Forex paper-forward outcomes,
positive net expectancy, positive benchmark-relative result, a positive
confidence-interval lower bound, acceptable drawdown, multiple pairs, sessions
and regimes, controlled replay-to-forward decay, bounded currency
concentration, and no active blocker. A negative or materially decayed forward
sample degrades or suspends prior eligibility.

High-impact news windows are configurable with
`BLUM_FOREX_NEWS_BLOCK_BEFORE_MINUTES` and
`BLUM_FOREX_NEWS_BLOCK_AFTER_MINUTES`. A missing event timestamp blocks
conservatively unless the selected strategy is explicitly validated for news.

## Deterministic Certification Examples

### Complete long/short trade

The test market has aligned 1H/15m/5m/1m structure, London session, a 0.8-pip
quoted spread and an eligible strategy. LONG enters at ask plus adverse
slippage; SHORT enters at bid minus adverse slippage. Target exits use the
opposite quote side. Entry and exit spread, slippage, commission and swap are
deducted before terminal WIN/LOSS/BREAKEVEN evidence is appended.

### Spread rejection

A 20-pip spread against a 10-pip expected move is rejected as
`SPREAD_TOO_WIDE` / `NO_NET_EDGE`; no position is created and
`EDGE_DESTROYED_BY_COSTS` evidence is stored.

### News rejection

A normal strategy inside a HIGH_IMPACT window is vetoed as
`NEWS_WINDOW_BLOCKED`. A strategy flagged as an already validated news strategy
may proceed through the remaining gates.

### Correlation netting

Existing GBP/USD LONG and USD/CHF SHORT positions produce the same short-USD
cluster. A new EUR/USD LONG is reduced or rejected rather than counted as an
independent pair.

## Snapshot Contract

`GET /api/forex-trader/snapshot` returns only the latest persisted
`forex_trader_summary`. A missing snapshot returns INITIALIZING and a precise
next action. A normal snapshot contains cycle/session/freshness, monitored and
blocked pairs, setup/order/fill counts, open/closed positions, gross/net P/L,
all costs, margin and currency exposure, readiness counts, no-trade evidence,
active blockers and the exact inactivity reason. Unavailable values are null.

## Verification Status

### Defect found and fixed

The initial pair metadata constructor passed the intended price precision into
the minimum-lot field. That required 5 lots for EUR/USD and 3 lots for USD/JPY,
so valid risk-sized orders failed the margin gate. Pair configuration now uses
explicit named fields. Regression tests require `minimum_lot == 0.01` and the
correct 5/3 price precision.

Production deployment also exposed a PostgreSQL-specific migration constraint:
the original revision identifier exceeded `alembic_version.version_num`'s
32-character limit. The file remains `0036_autonomous_forex_alpha_trader.py`,
while its revision ID is the compatible `0036_forex_alpha_trader`. The migration
suite now rejects every oversized revision ID before deployment.

### Measured verification

- Focused Forex core: `16 passed`.
- Related replay, runtime and paper suites: `144 passed`.
- Complete backend suite: `511 passed` in `50.02s`.
- Python compilation: passed.
- Patch whitespace validation: passed.
- Migration round trip `0035 -> 0036 -> 0035 -> 0036`: passed.
- Model/migration column tie-out for all six new tables: passed.
- Snapshot GET smoke: HTTP 200 in `7.6ms` on an empty database and `2.3ms`
  after a persisted cycle.
- Explicit guarded run smoke: HTTP 200 in `18ms`.
- Non-paused real cycle smoke: HTTP 200 in `910ms`; the cycle persisted
  `TIMEFRAME_UNAVAILABLE` instead of inventing a trade.

Alembic's global schema-autogeneration check still reports pre-existing drift
outside migration 0036. This sprint certifies the new migration with an actual
upgrade/downgrade round trip and exact model-column tie-out; it does not claim
the older global drift is resolved.

Implementation commits: `78f7cc2` and `662965e`. No broker or real-money path
exists.

## Known External Blockers

- Provider retention and outages can leave strict 1m evidence stale. BLUM blocks rather than substitutes data.
- Cross-currency conversion without an observed account-currency cross is explicitly marked as configured approximation.
- Alpha eligibility cannot be accelerated by replay rows; it requires 100 real-time closed paper-forward Forex outcomes.
- High-impact event quality depends on available persisted calendar metadata. Missing macro inputs are not fabricated.
- A strategy remains `STRATEGY_NOT_READY` until Strategy Factory evidence meets the configured validation gates.
- Profitable operation and benchmark outperformance remain hypotheses until enough closed forward evidence exists.

## Acceptance Result

- Autonomous bounded scheduler: DONE.
- Strict point-in-time multi-timeframe contract: DONE.
- Independent agent evidence and mandatory contrarian veto: DONE.
- Realistic paper execution, margin, costs and position lifecycle: DONE.
- Dynamic risk sizing and currency exposure netting: DONE.
- Append-only learning evidence and readiness recalibration: DONE.
- Snapshot-only GET API and explicit POST controls: DONE.
- Migration, regression tests and runtime smoke certification: DONE.
- Real-money trading or guaranteed alpha: intentionally NOT IMPLEMENTED.
