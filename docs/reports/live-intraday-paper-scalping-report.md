# Live Intraday Paper Scalping Report

> Historical record. This document describes an earlier implementation or audit; its counts, configuration and readiness claims are not the current release status. Start with the [documentation index](../README.md) and [current data policy](../research/data-quality.md).

## Status

DONE for the engine, persistence, runtime integration, read models and verification. Production activity remains evidence-dependent: BLUM will not open an intraday paper trade until both a promoted strategy and a fresh complete market stack are available.

## Files Changed

- `backend/app/services/intraday_contracts.py`
- `backend/app/services/promoted_strategy_registry.py`
- `backend/app/services/intraday_market_data.py`
- `backend/app/services/intraday_opportunity.py`
- `backend/app/services/intraday_paper_engine.py`
- `backend/app/models.py`
- `backend/alembic/versions/0031_live_intraday_paper_scalping.py`
- `backend/app/core/config.py`
- `backend/app/api/routes.py`
- `backend/app/services/live_forward_paper_trading.py`
- `backend/app/services/realtime.py`
- `backend/app/services/worker_runtime.py`
- `backend/app/engine/brain/trader_brain.py`
- `backend/tests/test_live_intraday_paper_engine.py`
- `README.md`

## Promoted Strategy Integration

`BlumPromotedStrategyRegistry` is a read-only projection over `ReplayStrategyValidation`. It rejects rows below 300 samples, non-promoted rows, high overfitting, weak stability, non-positive expectancy or benchmark excess, and any timeframe stack other than `1d/15m/5m/1m`.

## Intraday Scanning Flow

```text
enabled USA/Europe market desk
-> promoted strategy
-> fresh daily regime
-> 15m setup
-> 5m confirmation
-> 1m trigger
-> Quant Edge, cost and liquidity gates
-> diversification and sizing gates
-> adverse paper fill
```

Missing or stale timeframes block the asset. No lower-timeframe substitute is used.

## Execution Cost Model

The existing replay execution model supplies market-, asset-, liquidity- and session-aware spread, slippage, commission, liquidity penalty and gap-risk estimates. Approval requires positive net expectancy and an acceptable spread-to-target ratio. Entry fills are moved against the paper position by one-way costs; exits are also moved adversely. Gross and net P/L and cost components remain separately auditable.

## Sizing And Diversification

Sizing uses capital, stop distance, ATR, liquidity, confidence, edge, data quality and regime alignment. It caps notional and risk. Gates enforce one open intraday position per ticker plus portfolio, market, desk, asset-class and total-risk limits. No position is opened merely to satisfy diversification.

## Scheduler

`intraday_paper_trading` runs independently at `BLUM_INTRADAY_PAPER_MINUTES` cadence, defaults to two minutes, has `max_instances=1`, and uses the existing runtime coordinator for same-worker overlap protection. Runtime and asset budgets default to 45 seconds and 20 assets.

## Examples From Deterministic Tests

Opened trade: a promoted NVDA setup with complete fresh `1d/15m/5m/1m` data produced an `INTRADAY_TRADE_CANDIDATE` followed by `INTRADAY_TRADE_OPENED`; the paper fill was worse than the observed trigger price.

Blocked trade: incomplete `1m` data returned `INTRADAY_DATA_BLOCKED/MISSING_1M_DATA`. A duplicate NVDA position returned `TICKER_CONCENTRATION`. Expected moves erased by costs return `EXPECTED_MOVE_TOO_SMALL` or `COSTS_KILL_EDGE`.

Closed trade: a later one-minute bar crossing the stored stop closed the position as `STOP_HIT`, preserved the frozen decision payload and created a negative net P/L after costs.

## Outcome Evidence

Only closed/expired/invalidated intraday rows can create `TradeLearningEvidence`, `LearningEvent`, `StrategyMemory`, `SignalPerformance` and `FeedbackLoopAudit`. The evidence identity is idempotent and labelled `PAPER_FORWARD_INTRADAY`. Open trades do not update memory.

## Intraday Alpha

`intraday_paper_forward` is a separate Alpha evidence split. It reads only closed intraday forward rows and reports sample size, return, benchmark return/excess, expectancy, average R, profit factor, drawdown, win rate, holding time and costs. No replay result is copied into this stream.

## Smoke Outputs

Local HTTP smoke on an empty isolated database returned HTTP 200 for the manual run, paper snapshot, trades, training snapshot and Alpha snapshot.

The manual run reported:

```json
{
  "status": "DATA_BLOCKED",
  "assets_checked": 0,
  "trades_opened": 0,
  "data_blockers": [{"reason": "NO_DESK_ASSETS_WITH_INTRADAY_DATA"}],
  "next_action": "Resolve recorded blockers; never force activity."
}
```

Alpha correctly returned `intraday_paper_forward.status = NO_DATA`, null return/alpha and `No closed intraday paper-forward trades exist yet.`

## Verification

- Focused tests: `16 passed`.
- Full backend suite: `252 passed`.
- Compile: `python -m compileall -q app` passed.
- Alembic: `0031_intraday_paper (head)`.
- Isolated SQLite migration: upgrade, downgrade and re-upgrade passed.

## Limitations

- Production paper activity requires provider-supported, fresh one-minute data and a strategy that has actually passed the replay promotion gate.
- Correlation limits are not fabricated when no reliable intraday correlation matrix exists; current hard limits cover ticker, market, desk and asset class.
- Benchmark excess remains null when the benchmark lacks aligned stored one-minute bars.
- Signal-decay and regime-change exits are represented by strict invalidation, trailing, time and market-close controls; richer dedicated decay classifiers require validated forward evidence before activation.
- This is paper research. There is no broker or real-money execution.

## Acceptance Checklist

- DONE: only promoted strategies can generate intraday trades.
- DONE: strict daily/15m/5m/1m flow.
- DONE: real, fresh stored/provider data only.
- DONE: pre-trade execution costs and positive net-edge gate.
- DONE: ticker/market/desk/asset-class/risk diversification.
- DONE: dynamic position sizing.
- DONE: later one-minute-bar management and stop/target/time/invalidation exits.
- DONE: forward-only closed-trade learning.
- DONE: replay and intraday evidence separation.
- DONE: inactivity/concentration snapshot explanation.
- DONE: closed-only intraday Alpha split.
- DONE: manual POST summary and independent scheduler.
- DONE: no automatic frontend POST, fake fills, broker integration or real money.
