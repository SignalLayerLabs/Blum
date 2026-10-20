# LEAN-inspired curriculum valuation

BLUM now reports the value and drawdown of open research positions on each observable bar close, alongside its existing closed-trade statistics. A delayed-entry hold benchmark uses the same starting capital, development window and execution-cost model. USA and Forex lanes remain separate; each Forex pair is labeled in its quote currency.

This is a measurement improvement. It does not establish profitable alpha, change expert selection, train on the reserved confirmation partition, or route real-money orders.

## Reference and engineering decisions

Reviewed upstream: [QuantConnect/Lean at 61c598b](https://github.com/QuantConnect/Lean/tree/61c598b66ed8051d156bba10001eab4f3e86bcb9), dated 19 October 2026. The references below identify the reviewed revision rather than a moving branch. Upstream code and selected tests were inspected; the .NET test suite was not run.

| LEAN mechanism | BLUM decision |
| --- | --- |
| [Portfolio value includes cash and open holdings](https://github.com/QuantConnect/Lean/blob/61c598b66ed8051d156bba10001eab4f3e86bcb9/Common/Securities/SecurityPortfolioManager.cs), with [equity statistics](https://github.com/QuantConnect/Lean/blob/61c598b66ed8051d156bba10001eab4f3e86bcb9/Common/Statistics/PortfolioStatistics.cs) | Add a separate, versioned bar-close valuation report using frozen BLUM fills. Preserve existing closed-trade statistics. |
| [Fill model checks time, sessions and data](https://github.com/QuantConnect/Lean/blob/61c598b66ed8051d156bba10001eab4f3e86bcb9/Common/Orders/Fills/EquityFillModel.cs) | Retain BLUM's later-bar clock, collars, participation limits and partial-fill accounting. A framework dependency does not replace execution evidence. |
| [Consolidation boundaries](https://github.com/QuantConnect/Lean/blob/61c598b66ed8051d156bba10001eab4f3e86bcb9/Common/Data/Consolidators/PeriodCountConsolidatorBase.cs) | Reuse BLUM's exchange calendar, canonical openings and declared availability clocks. Reject missing or invalid valuation intervals. |
| [Insight lifetimes](https://github.com/QuantConnect/Lean/blob/61c598b66ed8051d156bba10001eab4f3e86bcb9/Common/Algorithm/Framework/Alphas/Insight.cs) | Separate follow-up: audit delayed-worker order expiry, stop-limit price constraints and partial-order expiry. They are not changed by this valuation increment. |
| [Framework portfolio risk management](https://github.com/QuantConnect/Lean/blob/61c598b66ed8051d156bba10001eab4f3e86bcb9/Algorithm.Framework/Risk/MaximumDrawdownPercentPortfolio.py) | Measure open-position risk first. A durable portfolio-wide drawdown stop requires reconciled cash and FX conversion; this report does not introduce a new trading gate. |

The implementation is independent Python, inspired by those contracts. No LEAN source or market dataset is bundled. LEAN is [Apache-2.0 licensed](https://github.com/QuantConnect/Lean/blob/61c598b66ed8051d156bba10001eab4f3e86bcb9/LICENSE); that does not grant rights to third-party market data. Adding the .NET engine as a second runtime would duplicate execution ownership and is unnecessary for this increment.

## What the numbers mean

`curriculum-valuation-v1` consumes the existing frozen execution outcomes. Entry deducts filled notional and entry commission once; an exit changes cash only at its recorded exit clock. Before that clock, NAV is remaining cash plus quantity times the observable close. Future bars, future exits and their P/L cannot change the visible prefix or its hashes.

Maximum **bar-close drawdown** is computed over the full-resolution NAV path before the public curve is reduced to at most 128 points. It includes open positions, but does not claim to capture intrabar losses. Existing `max_closed_trade_drawdown` retains its original meaning.

**Estimated net liquidation** additionally models a hypothetical sale at each close using BLUM's execution costs and capacity. It is an estimate, not a recorded sell. When capacity cannot cover the position, the mark NAV can remain known while liquidation value and liquidation-path drawdown are withheld. Missing or invalid mark intervals withhold current NAV, return and drawdown. Zero is never substituted for unknown risk.

The modeled hold waits for the first executable opening strictly after the initial development decision. Its size is cash-bounded with the existing 10bp entry collar, commission, prior-observed volatility, spread and participation model. Partial fills retain residual cash. Zero usable equity volume leaves an unfilled order and cash; Forex uses the declared 100,000-unit OTC capacity scenario. If the opening has occurred but its close is not observable, value is withheld rather than showing cash as unexposed.

Hold is a cash-notional opening scenario: sizing and its affordability collar use the execution opening price, rather than fixed shares submitted before an auction. That is a simulation assumption, not timestamp-certified broker execution.

Hold's terminal position remains `OPEN_MARKED`. Comparisons use estimated net-liquidation returns only when both reports are complete and terminal liquidation estimates exist. Starting capital, window and cost assumptions match; exposure can differ and is displayed. `sample_exposure_fraction` is a fraction of bar samples, not calendar time or a risk-adjusted performance statistic. Cash is a zero-interest reference. Dividends, carry, borrowing, taxes and independently audited corporate actions remain outside this model.

Prospective valuation covers **the current research episode only**, starting from its frozen cash budget. It does not consolidate prior episodes or replace the native paper journal. A blocked path retains the existing reservation and cannot create a learning outcome.

## Persistence and compatibility

The worker stores valuation alongside each development report and current forward episode. Public GETs read stored summaries and never trigger valuation or training. Existing exhausted packs receive one report-version refresh from their immutable source: source identity, expert outcomes, checkpoint, training count, episode journal and return-change history are preserved. Subsequent scheduler runs reuse the current report version. No migration or new dependency is required.

Old snapshots continue to render without the optional valuation fields. Per-pair quote currency is derived from the pair contract (for example EUR/GBP uses GBP), rather than the asset's reporting currency. No cross-currency sum is presented.

## Reproduction and observed results

Run from the repository with the development dependencies installed:

```sh
PYTHONPATH=backend python scripts/verify_curriculum_source_recovery.py \
  --forex 'EURUSD=X=/path/to/eurusd-yahoo.json' \
  --forex 'GBPUSD=X=/path/to/gbpusd-yahoo.json' \
  --output /tmp/blum-lean-nav-full.json
```

The existing source-recovery runner exercises the actual worker in a fresh SQLite database, resumes it through a new session and produces the full stored valuation. Raw FX input stays outside Git. Input hashes and summary reports are preserved in [the evaluation receipt](../evidence/lean-nav-evaluation.json); curves are omitted from that summary, while full-resolution curve hashes and sample counts remain.

All four source hashes, model checkpoints, training counts, learned counts and original policy/fixed-expert metrics match [the prior recovery receipt](../evidence/curriculum-source-recovery.json) exactly. The 1,109 dependent expert outcomes are unchanged; restart adds zero duplicate updates. This is isolated verification, not evidence that the production scheduler is learning.

| Lane | Policy return | Policy bar-close drawdown | Modeled hold net-liquidation return | Hold bar-close drawdown |
| --- | ---: | ---: | ---: | ---: |
| QQQ daily | +0.345% | 1.110% | +66.472% | 21.895% |
| SPY daily | −0.345% | 0.345% | +42.131% | 17.011% |
| EUR/USD daily | Withheld | Withheld | Withheld | Withheld |
| GBP/USD daily | Withheld | Withheld | Withheld | Withheld |

The USA policy underperforms the modeled hold in both development comparisons. FX full-path valuation is withheld because the preserved source contains invalid bars; legacy closed-trade results do not prove that the complete account path is valued. Confirmation remains unopened. These results provide better measurement, not a win-rate or alpha claim.
