# BLUM Evidence, Trust and Copy Readiness Engine Design

## Purpose

BLUM needs an evidence-bound way to determine whether a strategy has matured from historical research into repeatable forward paper evidence. The engine must keep replay, walk-forward, standard paper-forward, and intraday forward evidence separate; account for costs, benchmark performance, concentration, and degradation; and explain every readiness decision without implying guaranteed profit.

This sprint adds no broker integration and executes no real-money trades. Real-capital eligibility is an autonomous research classification only.

## Existing System Constraints

- `LiveForwardPaperTrade` and `LiveForwardPaperTradeEvent` already persist frozen forward decisions, lifecycle events, costs, benchmark outcomes, and lessons.
- `HyperbolicReplayTrade` and `ReplayStrategyValidation` already distinguish replay and walk-forward evidence.
- Alpha and paper-forward product surfaces already expose snapshot contracts.
- Existing copy-trading consumers depend on the lower-case actionability-based `copy_readiness` field.
- Dashboard reads must remain snapshot-first. GET requests must not recalculate evidence or write database state.
- Legacy `PAPER_FORWARD_INTRADAY` rows must remain readable without destructive history rewrites.

## Chosen Architecture

Use append-only evidence projections built asynchronously from persisted source records. The computation path is separated from the read path:

1. Existing trading, replay, and validation workers persist source evidence.
2. A bounded evidence worker reads new or changed source records using a cursor.
3. It produces immutable strategy evidence snapshots.
4. It compares replay and forward performance.
5. It evaluates strategy readiness and capital eligibility.
6. It appends readiness and evidence timeline events when material state changes occur.
7. It refreshes compact Alpha and Paper Forward snapshots.
8. GET endpoints read the latest projections only.

Direct calculation on page requests is rejected because it would increase latency, lose state history, and violate BLUM's snapshot-first runtime. Full event sourcing of all trading state is deferred because it would unnecessarily rewrite already certified lifecycle logic.

## Evidence Classes

The canonical evidence classes are:

- `REPLAY_EVIDENCE`
- `WALK_FORWARD_EVIDENCE`
- `PAPER_FORWARD_EVIDENCE`
- `INTRADAY_FORWARD_EVIDENCE`

Every evidence card carries exactly one class. Metrics from different classes are never added together to claim performance. The global forward sample gate may count the union of standard and intraday closed forward trades only as a maturity count; performance metrics remain class-specific.

Legacy `PAPER_FORWARD_INTRADAY` is mapped to `INTRADAY_FORWARD_EVIDENCE` in projections and API output. Existing stored rows are not rewritten.

## Strategy Identity

The projector derives a stable strategy ID as follows:

1. `validation:<promoted_validation_id>` when a promoted replay validation exists.
2. `setup:<normalized_setup_type>` when no validation ID exists.

Fallback setup IDs include a `strategy_identity_fallback` warning because they represent a broader strategy family rather than one validated strategy version.

## Components

### StrategyEvidenceProjector

Reads stored replay trades, replay validations, paper-forward trades, and intraday forward trades. It groups them by strategy and evidence class and computes evidence cards. It never changes source evidence.

Each card includes:

- strategy ID, setup type, supported markets, and evidence class;
- total, closed, and forward trade counts;
- win rate, net expectancy, average R, profit factor, Sharpe proxy, Sortino proxy, and max drawdown;
- benchmark return and excess when comparable data exists;
- total costs and average slippage;
- best and worst regime;
- ticker and market concentration;
- replay-versus-forward gap when a compatible card exists;
- Wilson win-rate confidence interval when the sample is non-empty;
- latest evaluation timestamp, source rows, and warnings.

Unavailable metrics are `null`, never synthetic zero values. Profit factor is `null` when it cannot be represented safely, such as a sample with no losing observations.

### ReplayForwardDecayEvaluator

Compares compatible replay and forward evidence without merging them. Compatibility requires the same strategy identity or setup fallback and a compatible horizon/timeframe where available.

It reports replay and forward expectancy, profit factor, Sharpe proxy, drawdown, execution-cost gap, signal failure rate, and performance decay percentage.

Statuses:

- `CONSISTENT`
- `MODERATE_DECAY`
- `HIGH_DECAY`
- `FORWARD_FAILURE`
- `INSUFFICIENT_EVIDENCE`

Material forward failure overrides favorable replay evidence and suspends copy readiness.

### BlumCopyReadinessEngine

Evaluates only persisted projections. Closed terminal forward trades count toward readiness; candidates and open trades do not.

Statuses:

- `NOT_READY`
- `REPLAY_ONLY`
- `FORWARD_EVIDENCE_LOW`
- `FORWARD_EVIDENCE_GROWING`
- `COPY_READY_PAPER_ONLY`
- `COPY_READY_HIGH_CONFIDENCE`
- `SUSPENDED`
- `DEGRADED`

Default `COPY_READY_PAPER_ONLY` gates:

- 100 closed forward trades globally;
- 30 closed forward trades for the strategy;
- 90 calendar days of forward observation;
- positive net expectancy after stored costs;
- positive benchmark excess from comparable data;
- max drawdown at or below the configured limit;
- replay-to-forward decay at or below the configured limit;
- at least 5 distinct tickers;
- at least 2 distinct market regimes;
- ticker and market concentration at or below configured limits;
- usable cost, slippage, and data-quality evidence.

`COPY_READY_HIGH_CONFIDENCE` uses stricter configurable sample, observation, diversification, drawdown, and decay gates.

State transitions are evidence-driven:

- replay without terminal forward evidence produces `REPLAY_ONLY`;
- fewer than 10 terminal forward trades produces `FORWARD_EVIDENCE_LOW`;
- a larger immature sample produces `FORWARD_EVIDENCE_GROWING`;
- a previously ready strategy with non-material deterioration becomes `DEGRADED`;
- negative forward expectancy, negative benchmark excess, material drawdown breach, or material decay produces `SUSPENDED`.

Evidence maturity is a 0-100 gate-completion score. It does not increase merely because one trade is highly profitable.

### CapitalEligibilityEngine

Computes autonomous research eligibility. It never sends orders or connects to a broker.

Statuses:

- `NOT_ELIGIBLE`
- `OBSERVE_ONLY`
- `PAPER_ONLY`
- `MANUAL_REVIEW_REQUIRED`
- `ELIGIBLE_FOR_LIMITED_EXTERNAL_VALIDATION`

BLUM operates autonomously, so no human approval is required. `MANUAL_REVIEW_REQUIRED` remains part of the public enum for compatibility but is not emitted in the default autonomous policy.

Default limited-external-validation gates:

- `COPY_READY_HIGH_CONFIDENCE` strategy status;
- 500 closed forward trades globally;
- 150 closed forward trades for the strategy;
- 270 forward observation days;
- positive net expectancy and positive benchmark excess;
- max drawdown no greater than 10%;
- replay-to-forward decay no greater than 20%;
- at least 10 tickers and 3 regimes;
- acceptable ticker and market concentration;
- complete costs, slippage, and comparable benchmark evidence.

The classification is revoked automatically when evidence deteriorates. The sprint does not provide an execution path for that classification.

### EvidenceTimelineService

Appends idempotent events for:

- signal creation;
- trade open, update, and close;
- outcome and benchmark evaluation;
- lesson and memory creation;
- strategy status change;
- copy-readiness change;
- capital-eligibility change.

An immutable event key prevents duplicate insertion. Existing event rows are never updated.

## Persistence

Migration `0032_copy_readiness_evidence_engine.py` adds three non-destructive tables.

### strategy_evidence_snapshots

Append-only strategy evidence projections with indexed strategy ID, setup, evidence class, and evaluation time. Structured metrics, source references, warnings, concentration, regimes, and confidence intervals use cross-database-safe JSON.

### strategy_readiness_history

Append-only readiness evaluations with previous and new status, maturity score, forward counts, observation duration, passed/failed gates, decay status, capital eligibility, reasons, and threshold version.

### evidence_timeline_events

Append-only, uniquely keyed events associated with optional strategy ID and trade ID. Payloads contain evidence references, not fabricated values.

The migration provides PostgreSQL JSONB with SQLite JSON compatibility, indexes for latest-projection reads, uniqueness for event idempotency, and a complete downgrade.

## Trade-Level Output

Every serialized open candidate adds an evidence projection without modifying `frozen_decision_payload`:

- `copy_readiness_status`;
- `strategy_readiness_status`;
- `quant_edge_score`;
- total and forward sample size;
- expected net edge and estimated costs;
- confidence, benchmark context, and current regime;
- concentration risk;
- reasons to copy and not to copy;
- invalidation condition;
- maximum suggested paper risk;
- evidence warning;
- real-capital eligibility classification.

Paper actionability and copy readiness remain distinct. A candidate may be valid for paper observation while returning `NOT_COPY_READY` because its strategy lacks mature forward evidence.

The legacy lower-case `copy_readiness` output remains unchanged for backward compatibility.

## APIs and Snapshots

Read-only evidence endpoints:

- `GET /api/copy-readiness/strategies?limit=25&offset=0`
- `GET /api/copy-readiness/strategies/{strategy_id}`
- `GET /api/copy-readiness/timeline?strategy_id=...&limit=50`

Explicit bounded write endpoint:

- `POST /api/copy-readiness/recalculate`

The Alpha snapshot gains a compact `copy_readiness` section containing aggregate status, autonomous capital eligibility, maturity, forward counts and required counts, observation days and requirements, ready/not-ready strategy counts, decay summary, blockers, and next milestone.

The Paper Forward snapshot gains limited lists of copy-ready and not-ready open candidates, latest readiness changes, concentration warning, and forward-evidence progress.

Snapshot production occurs only in background workers or the explicit POST. Existing GET endpoints never invoke the projector, readiness evaluator, trading lifecycle, or broker-like behavior.

## Failure and Partial-Data Behavior

- A failure in one evidence class does not suppress valid cards from other classes.
- Missing benchmark, cost, or market data is represented as `null` with a blocker.
- Failed refreshes leave the last valid projection available and mark the summary stale.
- A failed job cannot change readiness state.
- Conflicting strategy identity creates a warning and blocks high-confidence promotion.
- Samples below thresholds cannot be described as reliable or market-beating.
- Public language remains conditional and explicitly paper/research-only.

## Configuration

All readiness and capital-eligibility gates are environment-configurable. Defaults include global and per-strategy sample minimums, observation periods, drawdown and decay limits, ticker/regime diversity, concentration caps, and high-confidence external-validation thresholds.

Configuration changes are recorded with a threshold version in readiness history so historical decisions remain auditable.

## Verification Strategy

### Unit Tests

- evidence-class normalization;
- metric calculation and missing-value semantics;
- Wilson confidence interval;
- ticker and market concentration;
- replay-forward decay classification;
- readiness and capital-eligibility state machines.

### Database Tests

- four evidence classes remain separate;
- only terminal forward trades count;
- snapshots and readiness rows are append-only;
- timeline insertion is idempotent;
- benchmark absence remains null;
- costs and slippage reduce net evidence;
- frozen trade payload remains unchanged.

### Guardrail Tests

- strong replay alone cannot produce copy readiness;
- insufficient samples block promotion;
- forward failure suspends a previously ready strategy;
- limited external-validation eligibility requires all stricter gates;
- eligibility is assigned and revoked autonomously;
- no component exposes broker execution.

### API and Integration Tests

- GET endpoints are read-only and paginated;
- explicit recalculation is bounded;
- Alpha and Paper Forward snapshots expose compact summaries;
- legacy response fields remain compatible;
- trade close flows through outcome, evidence card, readiness, timeline, and snapshot;
- unavailable values are explained instead of displayed as zero.

### Final Certification

- Alembic upgrade and downgrade on SQLite;
- Python compile pass;
- focused test suite;
- complete backend test suite;
- frontend build only if snapshot consumer contracts require changes;
- project version remains unchanged;
- Hugging Face Space deployment after verification;
- `COPY_READINESS_EVIDENCE_ENGINE_REPORT.md` records actual evidence and clearly labels synthetic test fixtures.

## Non-Goals

- broker integration;
- real-money execution;
- guaranteed-profit claims;
- automatic source-code modification;
- blending replay and forward performance;
- UI redesign;
- recalculation during GET or page render.

