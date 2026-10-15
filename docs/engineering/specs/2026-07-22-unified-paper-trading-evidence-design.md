# Unified Paper Trading Evidence Design

## Objective

Make Forex paper-forward decisions and positions visible in the primary Paper
Trading journal and include their evaluated outcomes in BLUM's general paper
performance indicators without duplicating source records, mixing evidence
classes, or performing financial computation during page render.

This remains real-time paper trading. It does not create a broker or real-money
execution path.

## Chosen Architecture

Introduce a read-side `UnifiedPaperTradingProjectionService`. It owns no trade
lifecycle logic and cannot create, update, open, or close a trade. It reads the
authoritative paper-forward and Forex stores, normalizes their records into a
single contract, calculates bounded aggregate metrics, and persists a
`unified_paper_trading_summary` `DashboardSnapshot`.

The alternatives were rejected:

- Frontend aggregation would duplicate financial logic and leave Brain and
  Alpha inconsistent with Paper Trading.
- Copying Forex trades into generic paper-forward tables would duplicate
  evidence and risk counting one outcome twice.

## Source Boundaries

Authoritative sources remain separate:

- `LiveForwardPaperTrade` and its events for standard and intraday
  paper-forward evidence.
- `ForexDecision`, `ForexPosition`, `ForexLearningEvidence`, and the existing
  Forex snapshot for Forex evidence.
- Historical replay remains excluded from forward paper performance.

Every normalized item includes:

- `trade_id`: stable source-qualified ID such as `paper:42` or `forex:17`;
- `source_trade_id`: native integer ID;
- `source_engine`: `paper_forward` or `forex_trader`;
- `market`: `equity`, `etf`, `crypto`, `forex`, or the stored asset class;
- `evidence_type`: original evidence classification;
- `mode`: always the stored paper mode;
- ticker/pair, strategy, direction, lifecycle status, timestamps, entry, exit,
  stop, targets, size, costs, P/L, R, benchmark result, decision quality,
  confidence, blockers, and lesson when available.

Unavailable values remain `null`. The projection never substitutes zero for
missing financial evidence.

## Deduplication

The canonical key is `(source_engine, source_trade_id)`. Forex decisions that
produced a position are represented by the position, with the decision linked
as supporting evidence. Rejected or no-trade Forex decisions remain journal
decisions but never count as opened or closed trades and never contribute P/L.

No source table is mutated by projection generation.

## Metrics

The unified snapshot contains:

- `metrics.aggregate`: all eligible closed/open forward paper trades;
- `metrics.by_market`: separate standard, intraday, and Forex breakdowns;
- `counts.aggregate` and `counts.by_market`;
- `trades`, bounded and sorted by latest decision/event timestamp;
- `warnings`, freshness, evidence policy, and source snapshot timestamps.

Aggregate realized P/L, win rate, expectancy R, average R, profit factor,
drawdown and benchmark excess include Forex only when the required value is
observed on an eligible paper-forward position. Open trades contribute only to
unrealized metrics. Rejected decisions contribute only to decision counts and
no-trade quality.

Mixed-currency values may be aggregated only after conversion to the configured
paper account currency. A configured approximation must remain labelled; an
unavailable conversion excludes the value and adds a warning.

Benchmark-relative metrics include only outcomes with a valid same-period
benchmark. The response reports the contributing sample size.

## Snapshot Lifecycle

Projection refresh is background-only and idempotent. It runs after:

- a paper-forward lifecycle update;
- a completed Forex trader cycle;
- scheduled snapshot production.

`GET /api/paper-trading/snapshot` reads the latest persisted unified snapshot.
If missing, it returns a partial initializing response and never recalculates.
Existing paper-forward and Forex APIs remain backward compatible.

## Product Surface

The Paper Trading page loads the unified snapshot as its single initial source.
It shows:

- aggregate cards for candidates, open, closed, P/L, win rate, average R and
  benchmark excess;
- a compact breakdown for standard, intraday and Forex evidence;
- one journal with market/source labels and a market filter;
- explicit no-data and blocker states per market.

Trade Replay remains lazy. A source-aware detail route dispatches to the
correct read-only replay service. Raw source payloads are not shown by default.

## Brain and Alpha Integration

Brain performance indicators consume the latest unified snapshot, preserving
sample size, freshness, and source breakdown.

Alpha keeps historical, walk-forward, standard paper-forward and Forex
paper-forward evidence separate. A new Forex forward split may influence the
top-level verdict only according to its own maturity and benchmark evidence.
It must not upgrade evidence grade from open positions, rejected decisions, or
insufficient samples.

## Failure Handling

- Missing unified snapshot: return `INITIALIZING` with source availability.
- Stale snapshot: return stale data with warning.
- One source unavailable: preserve the other source and mark partial coverage.
- Unsupported currency conversion: exclude affected P/L from aggregate and
  report it.
- Source duplication: reject duplicate canonical keys during projection.
- Projection failure: persist failure diagnostics without affecting trade
  workers.

## Testing

Backend tests must prove:

- Forex positions and no-trade decisions normalize correctly;
- one Forex outcome appears once;
- aggregate P/L and R include eligible closed Forex outcomes;
- open Forex positions affect only unrealized metrics;
- rejected Forex decisions never affect P/L;
- missing FX conversion is excluded and warned;
- GET is read-only and snapshot-first;
- Brain reads the unified evidence summary;
- Alpha exposes a separate Forex paper-forward split;
- existing paper-forward behavior remains compatible.

Frontend validation must prove:

- Forex rows are visible and labelled;
- aggregate and market breakdown metrics render correctly;
- market filtering works;
- replay dispatch is source-aware and lazy;
- no POST occurs on mount;
- missing Forex evidence produces an explanation rather than an empty table.

## Acceptance

- Forex paper decisions and positions are visible in Paper Trading.
- General paper performance includes eligible Forex outcomes exactly once.
- Standard, intraday and Forex evidence remain separately inspectable.
- Brain and Alpha use the same stored evidence projection.
- No source record is copied or mutated.
- No heavy GET or frontend-triggered computation is introduced.
- No broker, real-money execution, fabricated fill, P/L, or Alpha is added.
