# Market Desk Agents and Cross-Market Orchestrator Report

> Historical record. This document describes an earlier implementation or audit; its counts, configuration and readiness claims are not the current release status. Start with the [documentation index](../README.md) and [current data policy](../research/data-quality.md).

## Scope

This release adds evidence-bound market desks to the existing paper-forward candidate flow. It does not change trade lifecycle execution, does not create synthetic market data, and does not promote a setup without both stored edge evidence and a valid technical invalidation.

## Implemented Agents

- Europe: FTSE MIB, DAX, CAC 40, IBEX 35, SMI, Euro Stoxx 50.
- United States: Wall Street, S&P 500, Nasdaq, Dow Jones, Russell 2000.
- Asia and emerging markets: Nikkei, Hang Seng, India Nifty, China A, Emerging Markets.
- Cross-asset: ETF, Crypto, Forex, Commodity, Rates/Bond Proxy, Volatility.

Each desk is discovered from stored `Asset` and `PriceHistory` rows. A desk runs only when eligible, sufficiently fresh price data exists. Otherwise it is returned in `agents_skipped` with one of:

- `NO_ASSETS_CONFIGURED`
- `NO_PRICE_HISTORY`
- `DATA_QUALITY_LOW`
- `PROVIDER_UNAVAILABLE`

## Cross-Market Orchestration

`BlumCrossMarketOpportunityOrchestrator`:

1. discovers only data-backed desks;
2. runs each desk independently;
3. applies the existing Market Sniper evaluation;
4. validates actionability and technical invalidation;
5. applies the Quant Edge gate using persisted evidence;
6. ranks candidates on a common 0-100 scale;
7. deduplicates tickers;
8. applies market, asset-class and ticker concentration limits;
9. passes only selected candidates into the existing paper-forward persistence flow.

The prior scanner remains available for injected providers and tests. The default production path delegates to the cross-market orchestrator when `BLUM_CROSS_MARKET_ORCHESTRATOR_ENABLED=true`.

## Quant Edge Rules

The Quant Edge Agent reads only persisted evidence from:

- `r_multiple_metrics`
- `prediction_outcomes`
- `execution_simulations`
- `signal_performance`
- `strategy_memory`
- `learning_benchmark_comparisons`

Verdicts are:

- `APPROVED_FOR_PAPER`
- `WATCHLIST_ONLY`
- `REJECTED_NO_EDGE`
- `REJECTED_INSUFFICIENT_SAMPLE`
- `REJECTED_BAD_RISK_REWARD`
- `REJECTED_OVERFITTING_RISK`
- `REJECTED_BENCHMARK_UNDERPERFORMANCE`
- `DATA_BLOCKED`

Approval requires the configured minimum sample size, positive expectancy, sufficient edge score, acceptable risk/reward, no high overfitting risk and no measured benchmark underperformance. Stored fractional rates are normalized consistently (`0.58` is reported as `58%`). Sharpe and Sortino remain `null` when no persisted source supplies them. Daily OHLCV freshness uses the end of the stored market date, preventing a Friday close from being rejected early on Monday solely because `PriceHistory.date` has no intraday timestamp.

Risk/reward uses the canonical trade-plan resolver. It reads `risk_reward_estimate.reward_to_risk` first and can derive the ratio from price, target and invalidation when the estimate is absent.

## Diversification Rules

Defaults:

- maximum 5 candidates per agent;
- maximum 8 selected candidates per market;
- maximum 12 selected candidates per asset class;
- maximum 1 selected candidate per ticker.

All values are configurable through `.env`. Repeated tickers are reported and deduplicated before persistence.

## Paper-Forward Integration

`POST /api/paper-forward/run` keeps its existing behavior and now exposes:

- enabled, running and skipped desk agents;
- opportunities and best opportunity by agent;
- global cross-market ranking;
- Quant Edge summary and rejection counts;
- diversification summary;
- repeated ticker diagnostics.

`GET /api/paper-forward/snapshot` remains read-only. It reports the latest persisted scan event and never starts scanning or learning.

## Example Evidence-Bound Result

```json
{
  "agents_run": ["NasdaqAgent"],
  "agents_skipped": [
    {
      "agent_name": "DAXAgent",
      "status": "NO_ASSETS_CONFIGURED"
    }
  ],
  "top_cross_market_opportunities": [
    {
      "ticker": "NVDA",
      "classification": "TRADE_CANDIDATE",
      "quant_edge": {
        "verdict": "APPROVED_FOR_PAPER",
        "sample_size": 60,
        "win_rate": 58.0,
        "expectancy": 0.42,
        "profit_factor": 1.85
      }
    }
  ],
  "repeated_ticker_warning": false
}
```

This is a contract example backed by automated test fixtures, not a claim about current production market opportunities.

## Verification

- Python compilation: passed.
- Market desk and orchestrator tests: passed.
- Existing live-forward paper trading tests: passed.
- Full backend suite: `204 passed`.
- Local backend smoke: `BACKEND_NOT_RUNNING` before deployment; no empty payload artifact was created.
- Hugging Face Space runtime: `RUNNING` on commit `9792e5b` before this report-only update.
- Remote snapshot: HTTP 200 in 0.55 seconds.
- Remote trades: HTTP 200 in 0.50 seconds.
- Remote paper-forward run: HTTP 200 in 23.61 seconds; 7 desks ran and 20 stored-data candidates were assessed.
- Remote Quant Edge outcome: 13 candidates rejected for insufficient risk/reward, 7 rejected for overfitting risk, 1 retained as watchlist, and no trade was forced.

## Known Limitations

- A desk can only run for assets already stored with sufficiently fresh OHLCV history.
- S&P 500, Dow Jones, Russell 2000 and emerging-market membership depends on stored asset category metadata; BLUM does not infer index membership silently.
- Quant Edge does not calculate missing Sharpe or Sortino during scanning.
- The orchestrator and Quant Edge methods remain candidates for smaller private-method extraction in a later maintainability-only sprint.
- A market-data provider outage is reported and isolated; it is not replaced by fabricated candidates.

## Acceptance Status

- Data-backed market desk discovery: **DONE**
- Explicit skip reasons for unsupported data: **DONE**
- Quant Edge evidence gate: **DONE**
- Cross-market ranking and ticker deduplication: **DONE**
- Market and asset-class concentration limits: **DONE**
- Paper-forward scanner integration: **DONE**
- Read-only snapshot diagnostics: **DONE**
- Automated tests: **DONE**
- Production deployment and remote smoke: **DONE**
