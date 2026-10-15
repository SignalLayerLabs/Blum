# Institutional Pilot Readiness and Evidence Acceleration Design

## Purpose

BLUM must become eligible for a controlled, limited-capital pilot only after stored evidence demonstrates that its decisions, execution assumptions, benchmark-relative edge, and risk controls are sufficiently mature. The system must accelerate the production of valid research evidence without lowering gates, fabricating forward time, forcing trades, or treating historical replay as forward proof.

The current production verdict is correctly negative: BLUM has four closed paper-forward trades, no promoted intraday strategy, no mature replay-to-forward comparison, and insufficient evidence quality. This release creates a measurable path from that state to limited external validation. It does not claim that the path has already been completed.

## Design Decision

Extend the existing copy-readiness domain instead of creating a second readiness system. `BlumCopyReadinessEngine`, immutable strategy evidence snapshots, strategy promotion, executable strategy fingerprints, and the Brain snapshot remain the authoritative evidence chain.

The release adds two focused capabilities:

1. an institutional pilot policy that converts verified copy-readiness evidence into a conservative capital eligibility decision and automatic kill-switch state;
2. an evidence acceleration controller that keeps bounded background research productive and prioritizes candidates closest to promotion while preserving broad exploration.

No broker integration or real order submission is part of this release.

## Pilot Readiness Policy

The policy produces one of five states:

- `NOT_ELIGIBLE`: required evidence is absent or invalid;
- `EVIDENCE_BUILDING`: valid evidence exists but maturity gates are incomplete;
- `ELIGIBLE_FOR_SHADOW_PILOT`: a promoted strategy can be observed under frozen pilot controls, without real capital;
- `ELIGIBLE_FOR_LIMITED_PILOT`: all existing limited-external-validation gates pass and no kill switch is active;
- `SUSPENDED`: a previously eligible strategy or portfolio has degraded or breached a safety condition.

`ELIGIBLE_FOR_LIMITED_PILOT` requires the existing strict capital gates, not reduced substitutes:

- at least 500 terminal global forward trades;
- at least 150 terminal forward trades for the exact executable strategy fingerprint;
- at least 270 calendar days of forward observation;
- positive net expectancy and benchmark excess after measured costs;
- maximum drawdown no greater than 10 percent;
- replay-to-forward decay no greater than 20 percent;
- at least 10 distinct tickers and 3 regimes;
- ticker concentration no greater than 30 percent;
- market concentration no greater than 60 percent;
- costs, slippage, and data-quality evidence present;
- a promoted strategy whose replay and paper execution share the same immutable fingerprint.

Historical replay and walk-forward evidence may unlock `ELIGIBLE_FOR_SHADOW_PILOT`, but never limited-capital eligibility by themselves.

## Capital Envelope

The first limited pilot remains an informational policy contract. It does not execute capital.

Default limits:

- maximum deployable capital: 5 percent of the configured pilot account;
- maximum risk per trade: 0.25 percent of pilot equity;
- maximum aggregate open risk: 1 percent of pilot equity;
- maximum correlated-theme risk: 0.50 percent of pilot equity;
- maximum five simultaneous positions;
- no position may open without entry trigger, invalidation, executable size, modeled costs, and matched benchmark.

The output includes the allowed limits, current measured values, hard blockers, and the next measurable milestone. Absence of a metric is a failed gate, never a zero-risk assumption.

## Kill Switch

The kill switch is deterministic, explainable, and fail-closed. It activates when any critical condition is present:

- stale or missing decision data;
- invalid benchmark methodology;
- executable strategy fingerprint mismatch;
- unmodeled costs or slippage;
- daily loss at or above 1 percent of pilot equity;
- pilot drawdown at or above 5 percent;
- aggregate open risk above 1 percent;
- ticker, sector, market, or factor concentration above policy;
- forward expectancy non-positive;
- benchmark excess negative;
- replay-to-forward decay above the accepted threshold;
- strategy state suspended, degraded, retired, or no longer promoted;
- worker failure, persistence failure, or incomplete frozen decision evidence.

The assessment returns `active`, `triggers`, `activated_at` when persisted evidence provides it, and `required_recovery_evidence`. Clearing a switch requires a subsequent complete assessment; it is never cleared because a field is missing.

## Evidence Acceleration

BLUM must run quickly during the day, but speed is measured as validated information throughput rather than generated signal count.

The acceleration controller uses existing bounded background workers and promotion-frontier research contracts. It will:

- keep replay slices resumable and within runtime budgets;
- prioritize exact strategy fingerprints closest to promotion;
- rotate away from variants that repeatedly produce no edge or cost failure;
- allocate a fixed exploration share to new regimes, markets, and setup families;
- direct more samples to low-sample positive candidates, confidence failures, cost-sensitive candidates, and replay/forward disagreements;
- checkpoint after each slice and resume from persisted cursors;
- publish throughput, useful-evidence ratio, queue starvation, promotion-distance reduction, and runtime throttling reasons;
- request the next bounded slice automatically through the scheduler, never through a GET or page render.

Default batch composition:

- 50 percent promotion-frontier candidates;
- 20 percent replay/forward disagreement and failure analysis;
- 20 percent regime and market coverage gaps;
- 10 percent broad random exploration.

The controller may increase bounded work while runtime health is good. It must throttle on CPU, memory, API, persistence, or provider pressure. It may not manufacture forward outcomes, duplicate samples, reuse future data, or count training replay as paper-forward evidence.

Target operational measurements:

- no idle scheduler interval when actionable research work is queued and runtime health is good;
- at least 80 percent of completed replay slices produce terminal, deduplicated outcome evidence;
- promotion frontier distance is recalculated after every factory cycle;
- stalled candidates rotate after a configurable number of non-improving slices;
- every pause exposes the exact runtime or evidence blocker;
- paper-forward scanning continues on its real-time cadence independently of replay acceleration.

These are throughput targets, not alpha claims.

## Data Flow

1. Strategy Factory persists executable strategy variants and immutable fingerprints.
2. Promotion Frontier ranks exact candidates by evidence gap and quality.
3. Evidence Acceleration selects a bounded mix and dispatches replay research in the background.
4. Replay and walk-forward outcomes update strategy evidence without being reclassified as forward evidence.
5. Promoted strategies become eligible for paper-forward scanning under the same evaluator and fingerprint.
6. Closed forward outcomes update immutable evidence snapshots and decay comparisons.
7. Institutional Pilot Policy evaluates the latest stored evidence and kill-switch inputs.
8. Brain snapshot reads the latest assessment and renders status, blockers, limits, and progress without recalculation.

## Interfaces

The domain layer exposes pure inputs and outputs:

- `PilotPolicyThresholds`: immutable capital and kill-switch limits;
- `PilotReadinessContext`: copy-readiness result, strategy promotion, execution, benchmark, risk, runtime, and data-quality facts;
- `PilotReadinessDecision`: status, score, capital envelope, failed gates, kill-switch state, next milestone, and evidence timestamp;
- `evaluate_pilot_readiness(context, thresholds)`: pure fail-closed evaluation.

The application service reads only persisted evidence and produces a compact `institutional_pilot` block for the existing Brain snapshot. Background orchestration consumes the existing promotion frontier and writes acceleration telemetry into background job state or the existing snapshot mechanism. GET endpoints remain read-only.

## Brain Presentation

The current Copy Trading Gate becomes a Pilot Capital Gate. It shows:

- current pilot status;
- whether the kill switch is active;
- maximum eligible capital percentage;
- maximum risk per trade;
- forward evidence progress;
- promoted-strategy status;
- the three most important blockers;
- the next measurable milestone;
- explicit text that eligibility means controlled external validation, not guaranteed profit.

No new page is required. Raw diagnostics remain available only in existing developer surfaces.

## Error and Missing-Data Behavior

- Missing evidence fails the corresponding gate.
- Invalid benchmark methodology blocks learning-based eligibility.
- A stale readiness snapshot is shown as stale and cannot authorize a pilot.
- Background acceleration failures are isolated, checkpointed, and exposed; they do not affect snapshot reads.
- If no promoted strategy exists, the system reports that blocker and continues targeted research instead of forcing a paper trade.

## Testing

Tests must prove:

- the current four-trade state remains not eligible;
- replay-only evidence cannot authorize capital;
- all strict forward gates are required for limited pilot eligibility;
- any critical kill-switch trigger suspends eligibility;
- missing metrics fail closed;
- the capital envelope never exceeds conservative defaults;
- promotion-frontier candidates receive priority while exploration remains non-zero;
- repeated non-improving candidates rotate;
- runtime pressure throttles work without losing the persisted cursor;
- Brain snapshot exposes the assessment without running research or recalculation;
- existing copy-readiness, Learning Loop, paper-forward, Strategy Factory, and Alpha tests remain green.

## Explicit Non-Goals

- no broker connection;
- no real-money order execution;
- no claim of Warren Buffett-level judgment;
- no guaranteed-profit language;
- no lowering of readiness or promotion thresholds;
- no synthetic forward history;
- no frontend-triggered training;
- no version change.

## Success Criterion

This release succeeds when BLUM can state, from stored evidence, either:

> Not eligible. The exact blockers are X, Y, and Z; the background research queue is currently reducing X at a measured rate.

or:

> Eligible for a limited pilot under a 5 percent capital cap, 0.25 percent risk per trade, and the listed automatic kill switches.

The software implementation can make the second state reachable and auditable. Only future market evidence can make it true.
