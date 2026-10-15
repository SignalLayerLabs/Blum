# Alpha Strategy Factory and Realistic Execution Design

**Date:** 2026-07-15  
**Status:** Approved design  
**Scope:** Backend intelligence, autonomous workers, persistence, read-only snapshots, tests, documentation, and deployment.  
**Version policy:** Preserve the current project version and feature-set identifiers.

## Objective

BLUM must treat every strategy as a falsifiable research hypothesis. It may promote a strategy to paper-forward only after independent, cost-aware evidence survives temporal validation, robustness testing, multiple-testing correction, and minimum-sample gates. Promoted strategies must then use a realistic paper execution lifecycle in both replay and forward evaluation so that historical edge and executable edge are comparable.

The implementation accelerates evidence generation, not indiscriminate trade creation. BLUM may open paper trades quickly only when a strategy has passed the certification contract and a later market observation satisfies its entry order.

## Existing System Boundaries

The design extends, rather than replaces, these existing components:

- `BlumHyperbolicReplayEngine` remains the point-in-time replay engine.
- `ReplayExperimentService` remains the bounded variant generator entry point.
- `ReplayWalkForwardValidator` remains the compatibility facade for validation callers.
- `ReplayStrategyValidation` remains the current strategy-level validation summary.
- `BlumPromotedStrategyRegistry` remains the only source of strategies eligible for intraday paper-forward.
- `BlumIntradayPaperEngine` remains the autonomous intraday paper worker.
- `LiveForwardPaperTrade` and `LiveForwardPaperTradeEvent` remain the paper trade and event sources of truth.
- `ReplayTrainingSnapshotService` and paper snapshots remain read-only frontend contracts.

New services must use focused domain objects and repositories. API routes may orchestrate dependencies but may not contain strategy, statistics, or execution logic.

## Bounded Context 1: Strategy Certification

### Scientific Pipeline

```text
Research hypothesis
  -> bounded strategy variants
  -> point-in-time replay
  -> purged walk-forward folds with embargo
  -> robustness and concentration tests
  -> multiple-testing correction
  -> candidate verdict
  -> champion/challenger promotion or rejection
```

### Strategy Families

The first registry contains:

- momentum
- trend following
- breakout
- pullback
- mean reversion
- volatility expansion
- earnings/news reaction
- relative strength
- cross-sectional ranking
- intraday scalping

Each family is a registered specification factory, not an empty agent. A specification declares entry, confirmation, invalidation, stop, target, holding-period, universe, benchmark, timeframe, regime filters, cost assumptions, and complexity count. Variant generation is bounded by a per-run budget and deterministic seed.

### Services

`AlphaStrategyFactory`

- consumes stored research priorities and hypotheses;
- generates a bounded set of reproducible candidate specifications;
- assigns a stable fingerprint to semantically identical candidates;
- prevents duplicate evaluation;
- records every examined, rejected, and promoted candidate.

`PurgedWalkForwardValidator`

- builds chronological train/validation folds;
- purges observations whose holding intervals overlap the validation boundary;
- applies an embargo after every validation fold;
- forbids future bars and future evidence;
- requires at least two independent validation windows;
- separates training replay, walk-forward validation, and paper-forward evidence.

`StrategyRobustnessEvaluator`

- computes net expectancy, benchmark excess, drawdown, payoff ratio, profit factor, Sharpe and Sortino proxies;
- performs deterministic block bootstrap confidence intervals;
- computes Deflated Sharpe Ratio inputs and probability;
- estimates probability of backtest overfitting from fold/ranking instability;
- measures stability by regime, market, ticker, and validation window;
- measures contribution concentration from the top asset and top three assets;
- applies a complexity penalty based on degrees of freedom and parameter count.

`MultipleTestingController`

- treats all variants in the same factory run as one hypothesis family;
- records the raw p-value or bootstrap tail probability;
- applies Benjamini-Hochberg false-discovery-rate correction;
- exposes adjusted significance and family size;
- prevents promotion when a candidate is only significant before correction.

`ChampionChallengerRegistry`

- maintains one active champion per strategy family, market, asset class, and timeframe stack;
- may register several challengers;
- promotes automatically only after all gates pass;
- records the previous champion and reversible promotion event;
- never replaces a champion from insufficient evidence;
- demotes or retires a strategy only through an auditable event.

### Certification Gates

A candidate is eligible for `PROMOTED_TO_PAPER` only when all conditions hold:

1. At least 300 evaluated trades after purging.
2. At least two validation windows and at least two tickers.
3. At least two markets for global strategies; market-specific strategies must instead pass multiple independent regimes.
4. Positive net expectancy after modeled round-trip costs.
5. Positive excess return against the declared relevant benchmark.
6. Bootstrap lower confidence bound for net expectancy is above zero.
7. Deflated Sharpe probability meets the configured threshold.
8. Backtest-overfitting probability is below the configured maximum.
9. Corrected multiple-testing significance passes the configured false-discovery rate.
10. Maximum drawdown remains within the strategy risk budget.
11. Stability scores pass across window, regime, market, and ticker dimensions.
12. No single asset dominates the configured maximum share of P/L.
13. Replay data quality and execution-cost coverage are complete.

Verdicts are explicit and mutually exclusive:

- `NEEDS_MORE_EVIDENCE`
- `REJECTED_NO_EDGE`
- `REJECTED_OVERFITTING`
- `REJECTED_COSTS`
- `REJECTED_MULTIPLE_TESTING`
- `REJECTED_CONCENTRATION`
- `REJECTED_UNSTABLE`
- `REJECTED_DATA_QUALITY`
- `PROMOTED_TO_PAPER`

## Bounded Context 2: Execution Reality

### Lifecycle

```text
Signal
  -> candidate
  -> approved strategy
  -> order submitted
  -> partially filled | filled | rejected | expired
  -> position managed
  -> closed
  -> benchmark evaluated
  -> evidence persisted
```

No service may convert a signal directly into an open trade. The execution engine owns the transition from approved candidate to order and from order to filled position.

### Services

`RealisticExecutionEngine`

- consumes immutable strategy, market-bar, account, and order inputs;
- produces deterministic execution decisions and cost breakdowns;
- does not fetch data or persist records itself;
- is shared by replay and paper-forward adapters.

`ExecutionCostModel`

- estimates bid/ask spread from stored quote data when available;
- otherwise uses an explicit liquidity, market, session, and volatility model;
- models dynamic slippage using volatility, order size, and volume participation;
- records commission, spread, slippage, FX, borrow, and gap costs independently;
- marks every estimated rather than observed cost field.

`PaperOrderLifecycleService`

- persists order submission before attempting a fill;
- applies market-session and halt checks;
- limits quantity by maximum volume participation;
- permits partial fills across later bars;
- expires unexecuted orders under strategy time rules;
- never fills a limit order unless a later bar crosses its price;
- never uses bars at or before the decision timestamp;
- applies conservative ordering when stop and target are both touched in one bar;
- preserves the theoretical signal price separately from actual average fill price.

`ExecutionEvidenceProjector`

- updates paper trade, benchmark, learning memory, and snapshots only after terminal execution events;
- records correct no-trades, missed opportunities, unfilled orders, cost-destroyed edge, and signal decay;
- keeps replay and forward evidence classes separate.

### Execution Inputs and Rules

The model supports:

- market, limit, stop, and stop-limit paper orders;
- regular session, opening auction, and closing auction states;
- latency measured in bars or configured milliseconds where quote timestamps support it;
- gap-through-stop execution at the first executable later price;
- overnight carrying state;
- optional short borrow costs only when borrow evidence exists;
- FX conversion using a stored point-in-time rate, otherwise a blocked execution;
- market halts represented by absent/flagged executable bars;
- partial fills constrained by stored bar volume and maximum participation.

No missing execution input receives a favorable default. Material missing data produces a rejected or blocked order with an evidence reason.

### Terminal Learning Outcomes

- `CORRECT_NO_TRADE`
- `MISSED_OPPORTUNITY`
- `ORDER_NOT_FILLED`
- `EDGE_DESTROYED_BY_COSTS`
- `SIGNAL_DECAY_BEFORE_ENTRY`
- `TARGET_HIT`
- `STOP_HIT`
- `THESIS_INVALIDATED`
- `TIME_EXIT`
- `PARTIAL_EXIT`
- `TRAILING_EXIT`

Every terminal state stores the strategy version, theoretical price, executed prices, quantities, costs, benchmark outcome, regime, data timestamps, and resulting lesson.

## Persistence

Additive, cross-database-safe persistence is required:

`strategy_factory_runs`

- run identity, hypothesis family, generation seed, variant count, budgets, timestamps, status, and aggregate verdict counts.

`strategy_candidate_variants`

- stable fingerprint, factory run, family, specification JSON, complexity, benchmark, lifecycle state, and final verdict.

`strategy_validation_folds`

- candidate, fold boundaries, purge and embargo boundaries, train/validation counts, market/regime/ticker coverage, metrics, and data-quality warnings.

`strategy_promotion_events`

- candidate, champion/challenger state, previous champion, promotion reason, evidence summary, reversible flag, and timestamp.

`paper_execution_orders`

- immutable decision reference, strategy validation, theoretical price, order type, side, quantity, limits/stops, session, submitted/expired timestamps, status, and rejection reason.

`paper_execution_fills`

- order, later market-data timestamp, quantity, observed reference price, executed price, spread, slippage, commission, FX, borrow, participation, and fill quality.

Existing `ReplayStrategyValidation`, `HyperbolicReplayTrade`, `LiveForwardPaperTrade`, and event rows receive only nullable compatibility fields required to link these records. Historical rows remain valid.

All JSON columns use the repository's cross-database JSON type. Migrations are additive and include indexes for current status, family, verdict, candidate fingerprint, strategy validation, order status, and event time.

## Autonomous Runtime

Two independently scheduled, sliced workers are added:

`alpha_strategy_factory`

- consumes a bounded number of research priorities;
- resumes from persisted cursor;
- generates and validates a bounded candidate batch;
- checkpoints after each candidate;
- stays within the existing 120-second runtime budget.

`paper_execution_lifecycle`

- processes submitted orders and open positions in bounded batches;
- uses only observations newer than each frozen decision;
- checkpoints after each order/trade;
- isolates failures by order;
- publishes lightweight completion events.

The existing intraday worker may create approved candidates but delegates order/fill transitions to the lifecycle service. Frontend GET routes remain read-only and never trigger either worker.

## Snapshot Contracts

Existing Training Ground and Paper Trading snapshots gain compact sections.

`strategy_factory` includes:

- examined variants;
- rejection counts by reason;
- promoted count;
- champion/challenger counts;
- current factory run;
- last promotion;
- primary blocker;
- sample and freshness warnings.

`execution_reality` includes:

- submitted, partially filled, filled, rejected, expired, and open order counts;
- closed forward sample size;
- total and average execution costs;
- unfilled and cost-destroyed edge counts;
- replay-versus-forward expectancy difference;
- primary execution blocker.

Snapshots are produced asynchronously. Existing APIs remain compatible. No page-load POST or recalculation is introduced.

## Configuration

New settings have conservative defaults and bounded validation:

- strategy variants per run;
- minimum validated trades fixed at no less than 300;
- purge and embargo bars;
- bootstrap iterations;
- false-discovery-rate threshold;
- minimum Deflated Sharpe probability;
- maximum overfitting probability;
- maximum single-asset P/L contribution;
- execution max volume participation;
- order expiry bars;
- latency bars;
- default commission schedules;
- forward promotion target of at least 100 closed trades before copy-readiness evidence can strengthen.

Settings may accelerate batch throughput but may not bypass certification gates.

## Error and Partial-Data Handling

- Missing replay data yields `REJECTED_DATA_QUALITY` or `NEEDS_MORE_EVIDENCE`, never a fabricated metric.
- A failed validation fold does not corrupt completed folds.
- A failed candidate does not terminate its factory run.
- Missing quote or FX evidence is explicit in execution costs and may block an order.
- Repeated worker runs are idempotent by candidate fingerprint, order key, fill key, and event key.
- Existing strategies remain readable but are not grandfathered into the stronger champion registry without passing the new gates.

## Testing Strategy

Tests follow red-green-refactor and include:

- deterministic bounded variant generation for every initial family;
- purged folds contain no overlapping holding intervals;
- embargo observations are excluded;
- no look-ahead data reaches a fold or fill;
- bootstrap interval and Deflated Sharpe are deterministic under a seed;
- multiple-testing correction rejects a raw-only false positive;
- 299 trades cannot promote and 300 trades alone are still insufficient without all other gates;
- concentration, costs, instability, and overfitting produce distinct verdicts;
- champion replacement is auditable and reversible;
- replay and forward adapters use the same execution model;
- orders remain unfilled without a later crossing bar;
- partial fills respect participation limits;
- gap stops use the first later executable price;
- theoretical and executed prices remain separate;
- every cost component persists per fill;
- duplicate runs do not duplicate candidates, orders, fills, or learning events;
- snapshots are read-only and do not run research or execution;
- existing replay, Learning Loop, paper-forward, intraday, Alpha, and API tests continue to pass.

## Release Gates

The implementation is operationally complete when:

1. Factory snapshots truthfully report examined, rejected, and promoted candidates.
2. Every promotion is linked to at least 300 purged out-of-sample trades and all statistical gates.
3. At least one eligible strategy can flow through the realistic paper order lifecycle when valid stored data exists.
4. No forward fill is created without a later executable observation.
5. Replay and forward evidence expose the same cost taxonomy.
6. Costs are persisted for every fill.
7. Replay-versus-forward comparison is available once forward terminal evidence exists.
8. Copy-readiness remains insufficient until at least 100 forward trades close and existing evidence gates pass.
9. Full backend tests, frontend build, migration upgrade, and production health verification pass.
10. Deployment reports measured outcomes and does not claim alpha or readiness without evidence.

## Non-Goals

- No broker integration or real-money execution.
- No guaranteed profitability or target win rate.
- No source-code self-modification.
- No lowering of evidence gates merely to generate activity.
- No frontend-triggered training, validation, or order execution.
- No replacement of existing financial logic outside the certification and execution boundaries.

