# Market Desk Agents and Cross-Market Orchestrator Design

## Goal

Turn the existing paper-forward scanner into a coordinated set of evidence-bound market desks without changing paper-trade lifecycle behavior, adding UI, or fabricating unsupported coverage.

## Current Architecture

`PaperForwardOpportunityScanner` currently owns market-universe discovery, candidate generation, data enrichment, actionability classification, cross-market ranking, event persistence, and learning-acceleration metadata. `LiveForwardPaperTradingService.run_once()` calls this scanner and freezes returned candidates. This public flow and all existing API contracts must remain valid.

## Chosen Architecture

The implementation uses a hybrid extraction:

1. A registry discovers desk definitions and checks stored-data readiness.
2. Only desks with eligible active assets and sufficiently fresh OHLCV execute.
3. Unavailable desks remain visible in `agents_skipped` with an explicit reason.
4. Each executing desk delegates financial evaluation to the existing `MarketSniperEngine`; desk policy controls universe, benchmark, market-specific context, and limits.
5. `BlumQuantEdgeAgent` validates actionability using stored historical evidence before a candidate can become `TRADE_CANDIDATE`.
6. `BlumCrossMarketOpportunityOrchestrator` applies global ranking, ticker deduplication, and concentration limits.
7. `PaperForwardOpportunityScanner` remains the compatibility façade and delegates its default scan to the orchestrator.
8. `LiveForwardPaperTradingService.run_once()` remains candidate-freeze-only.

## Components

### Market Desk Contract

`BaseMarketDeskAgent` exposes one `scan(db, limit)` operation and returns a stable payload containing agent identity, market, benchmark, coverage, candidates, blocked evidence, regime, quality summary, and skip reason. Concrete desks are real policy implementations, not empty wrappers.

Desk readiness is based on stored `Asset` and `PriceHistory` rows. A desk is runnable only when at least one matching asset has recent usable OHLCV. Provider calls are not used to pretend that an unavailable desk was scanned.

### Desk Policies

Named desks define asset predicates, benchmark, market family, and context tags. US, European, Asian, ETF, crypto, forex, commodity, bond-proxy, and volatility desks use distinct predicates and benchmarks. Index-specific desks may share scanning mechanics while retaining independent universe predicates and policy metadata.

### Quant Edge Gate

`BlumQuantEdgeAgent` consumes only persisted evidence from signal performance, strategy memory, historical predictions/outcomes, execution simulations, and benchmark comparisons where available. It calculates sample size, directional quality, payoff, expectancy, profit factor, drawdown, benchmark excess, stability, overfitting risk, and an edge score.

No data is synthesized. Missing evidence produces `REJECTED_INSUFFICIENT_SAMPLE` or `DATA_BLOCKED`. Only `APPROVED_FOR_PAPER` can preserve or promote a candidate to `TRADE_CANDIDATE`; all other verdicts downgrade it to watchlist or blocked status.

### Cross-Market Orchestrator

The orchestrator:

1. resolves enabled desk names from settings;
2. checks readiness and runs only data-backed desks;
3. collects desk opportunities;
4. applies Quant Edge validation;
5. normalizes scores within the available cross-market set;
6. deduplicates tickers;
7. enforces per-agent, per-market, per-asset-class, and per-ticker limits;
8. returns persistence payloads and an auditable summary.

### Snapshot and Events

The scanner persists the cross-market summary in existing `LearningEvent` records. The paper-forward snapshot reads the latest stored orchestration event and current frozen trades. Snapshot GET operations remain read-only and never run desk scans.

## Configuration

Settings are functional and have conservative defaults:

- `BLUM_ENABLED_MARKET_DESK_AGENTS`
- `BLUM_MAX_CANDIDATES_PER_AGENT`
- `BLUM_MAX_CANDIDATES_PER_MARKET`
- `BLUM_MAX_CANDIDATES_PER_ASSET_CLASS`
- `BLUM_MAX_CANDIDATES_PER_TICKER`
- `BLUM_CROSS_MARKET_ORCHESTRATOR_ENABLED`
- `BLUM_QUANT_EDGE_MIN_SCORE`
- `BLUM_QUANT_EDGE_MIN_SAMPLE_SIZE`
- `BLUM_REJECT_HIGH_OVERFITTING_RISK`

If orchestration is disabled, the existing scanner path remains available for backward compatibility.

## Error Handling

One failed desk does not fail the whole run. The orchestrator records the exception as `PROVIDER_UNAVAILABLE` or an explicit data blocker and continues. A globally empty result explains whether the cause was unavailable data, insufficient edge, concentration limits, or no actionable setup.

## Testing

Tests verify registry readiness, desk-specific predicates, unsupported desk reporting, Quant Edge verdicts, insufficient-sample rejection, ticker deduplication, concentration limits, scanner compatibility, `run_once()` integration, read-only snapshots, settings behavior, and compile/test stability.

## Non-Goals

- No broker or real-money execution.
- No frontend or dashboard changes.
- No new market-data fabrication or forced provider calls.
- No paper-forward position opening or closing in `run_once()`.
- No version change.
