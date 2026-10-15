# Copy Readiness Evidence Engine Certification

> Historical record. This document describes an earlier implementation or audit; its counts, configuration and readiness claims are not the current release status. Start with the [documentation index](../README.md) and [current data policy](../research/data-quality.md).

## Scope

This release adds evidence-bound strategy maturity and copy-readiness evaluation without changing BLUM's version, financial execution logic or paper-trade decision payloads. It is paper research only.

## Architecture

1. `StrategyEvidenceProjector` reads bounded persisted replay, walk-forward, paper-forward and intraday-forward source rows.
2. It appends one immutable card per strategy and evidence class.
3. `BlumCopyReadinessEngine` evaluates the newest compatible cards and appends readiness history plus transition events.
4. Trade lifecycle events are mirrored into an idempotent evidence timeline.
5. Batch read projections enrich trade snapshots without N+1 queries or recalculation.
6. Compact summary snapshots feed Alpha and Paper Forward surfaces.

Persistent append-only tables:

- `strategy_evidence_snapshots`
- `strategy_readiness_history`
- `evidence_timeline_events`

Database triggers reject updates and deletes on these tables in PostgreSQL and SQLite.

## Evidence Separation

| Evidence class | Source | Can independently promote copy readiness? |
| --- | --- | --- |
| `REPLAY_EVIDENCE` | chronological historical replay | No |
| `WALK_FORWARD_EVIDENCE` | stored out-of-sample validation | No |
| `PAPER_FORWARD_EVIDENCE` | closed standard forward paper trades | Yes, with every gate satisfied |
| `INTRADAY_FORWARD_EVIDENCE` | closed intraday forward paper trades | Yes, evaluated separately |

Open, waiting, skipped and data-blocked trades do not count as closed forward evidence.

## Default Gates

Paper-copy readiness defaults: 100 global forward trades, 30 strategy forward trades, 90 days, maximum drawdown 15%, maximum replay-forward decay 35%, at least five tickers and two regimes, maximum ticker concentration 35% and market concentration 70%.

High-confidence defaults: 300 global, 100 strategy, 180 days, drawdown 12%, decay 25%, eight tickers and three regimes.

Limited external validation defaults: 500 global, 150 strategy, 270 days, drawdown 10%, decay 20%, ten tickers and three regimes. This is a research eligibility label, not permission or infrastructure for real-money execution.

Positive net expectancy after available costs and positive benchmark excess are mandatory. Missing required benchmark, cost or quality evidence is preserved as unavailable and blocks promotion.

## API Contracts

- `GET /api/copy-readiness/strategies?limit=25&offset=0`
- `GET /api/copy-readiness/strategies/{strategy_id}`
- `GET /api/copy-readiness/strategies/{strategy_id}/timeline?limit=50&offset=0`
- `POST /api/copy-readiness/recalculate?max_items=500&max_strategies=100`

All GETs are bounded and read-only. Only the POST command may project evidence, append evaluation history and refresh snapshots.

## Trade Projection

Paper trade payloads now include:

- strategy and copy-readiness status;
- maturity/quant edge score;
- replay and forward sample size;
- expected net edge and measured costs;
- confidence interval and benchmark context;
- regime and concentration context;
- reasons to copy or not copy in paper research;
- invalidation, maximum suggested paper risk and evidence warnings;
- autonomous real-capital eligibility classification.

The existing lower-case actionability/copy fields remain compatible. `frozen_decision_payload` is not modified.

## Example State

No operational local database was present in this workspace during certification, so no real performance row is claimed here. The following is a synthetic test fixture used to verify state transitions:

```json
{
  "strategy_id": "validation:1",
  "copy_readiness_status": "COPY_READY_HIGH_CONFIDENCE",
  "global_forward_trades": 500,
  "strategy_forward_trades": 500,
  "observation_days": 300,
  "net_expectancy": 0.65,
  "benchmark_excess": 0.3,
  "max_drawdown": 5.0,
  "real_capital_eligibility": "ELIGIBLE_FOR_LIMITED_EXTERNAL_VALIDATION",
  "fixture_only": true
}
```

Tests also prove that replay-only evidence remains `REPLAY_ONLY`, missing benchmark evidence blocks promotion, material forward failure suspends readiness, and a setup identity fallback warns without fabricating a validation identity.

## Safety and Non-Goals

- No broker integration or order submission.
- No real-money execution.
- No guarantee of profitability or benchmark outperformance.
- No conversion of missing metrics to zero.
- No replay/forward blending.
- No heavy GET-side recalculation.
- No source-code self-modification.

## Acceptance Checklist

- [x] Four evidence classes remain separate.
- [x] Closed terminal forward rows only drive forward maturity.
- [x] Net expectancy includes available costs and slippage.
- [x] Readiness and capital eligibility are sample-, duration-, benchmark-, drawdown-, decay- and concentration-aware.
- [x] Readiness history and lifecycle evidence are append-only and auditable.
- [x] Trade snapshots explain copy readiness without modifying frozen decisions.
- [x] Strategy and timeline GET endpoints are bounded and read-only.
- [x] Recalculation is an explicit bounded POST command.
- [x] Alpha and Paper Forward snapshots expose compact readiness.
- [x] No broker path or version change was introduced.
