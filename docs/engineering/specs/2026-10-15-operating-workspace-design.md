# BLUM operating workspace and prospective trading

## User outcome

Rebuild the entire graphical product so a person can understand what BLUM does, whether it is actually working and how it makes decisions. Operate a continuous paper-trading process, show P/L and effectiveness after spread and all recorded execution costs, expose actionable plans before their simulated entry, and evaluate progress toward benchmark outperformance. Equities/ETFs and Forex remain separate. This specification preserves the full objective; a UI refresh alone is not completion.

## Verified starting evidence

Main e83060a is deployed on HF and Cloudflare. Forex resumed after maintenance and produced 23 new registrations; it reports RUNNING but RESEARCH_ONLY, NO_NET_EDGE and STRATEGY_NOT_READY, with zero orders/fills. Alpha Desk has no qualified closed sample. The legacy paper snapshot reports 44 closed observations with negative expectancy, plus many unfilled terminal orders. Brain trading proof counts 120 closures including 118 apparent breakeven records; that does not establish executed profitable trades or intelligence. An observed concurrent cold Alpha Desk request returned HTTP503; the sequential verification passed. These are investigation inputs, not conclusions about every source row.

## Product information architecture

Five primary destinations: Overview, Calls, Trades, Performance, Research. Preserve existing URLs and compatibility where practical. Evolution becomes an experiment detail within Research. A persistent Paper label prevents ambiguity about execution mode.

Overview answers four questions in one screen: what is running, what is the next decision, what positions/results exist, and what evidence supports effectiveness. Use generous spacing, clear hierarchy, restrained amber branding, accessible text and explicit timestamps. Separate engine activity from trade activity. Remove synthetic intelligence percentages from the primary decision surface; heuristic diagnostics remain secondary and labeled.

Calls separates future announced plans from recorded historical decisions. Show market, direction, source time, publish time, earliest entry, entry/stop/target, expiry, estimated costs and invalidation. An old closed record is never an upcoming opportunity. No plan can fill before its publication/lead-time gate; canceled/expired plans remain visible with reasons.

Trades distinguishes candidates, unfilled orders, open positions and executed closures. Show gross P/L, cost components, net P/L and currency; do not pool currencies without a verified conversion. Missing values stay missing. An expired unfilled order is not a breakeven trade.

Performance compares causal, qualified outcomes with aligned benchmarks, separately by market. Show sample/coverage/uncertainty and cost sensitivity. Preserve unqualified legacy history in a clearly identified separate view. Calendar/holding-period mismatches, partial fills and account-currency changes must not create false alpha.

Research explains the decision process, data quality, current research focus, meaningful lessons, rejected experiments and measured changes. Job counts or generated explanations do not prove trading intelligence.

## Engine work

Investigate the actual strategy-selection and net-edge blockers before changing policy. Break any circular dependency that prevents controlled paper exploration from collecting prospective evidence, while retaining market freshness, causal input, execution/risk and portfolio constraints. If exploration is needed, use an explicit isolated paper lane with real provider observations and a declared policy; do not silently label it validated or bypass suspended/quarantined sources. Scan continuously and manage open positions even when no new setup qualifies. Constant operation means a real ongoing process with observed eligible executions, not random forced trades or merely increasing decision counters.

Audit long/short accounting independently: executable bid/ask, spread, slippage, commissions, swap credits/debits, conversions, partial fills, gaps and mark-to-market must reconcile without double-counting embedded costs. Persist the cost model and distinguish quoted values from estimates.

Add durable announced-call lifecycle and entry lead time where the current immediate transaction cannot support advance visibility. Keep registration/manifest integrity, source hashes and outcome separation. Performance and learning consume matured outcomes, never future labels at decision time.

## Runtime and evidence

Use bounded snapshot reads, partial loading and explicit stale/unavailable states. Diagnose Alpha Desk query cost and avoid a page-load request storm. No GET starts trading, training or research. Reuse the engine/facade/router boundaries. No new paid service, broker access or credential delegation is implied.

## Acceptance audit

1. All primary pages and mobile navigation are visually rebuilt and verified in the browser, with useful empty/error/stale states and no fabricated data.
2. A person can see actual worker state, current decision and explicit no-trade reasons without interpreting legacy internal scores.
3. Real provider-driven paper orders, fills, position management and closures occur under declared rules; costs and P/L reconcile in independent tests and runtime records.
4. A published plan is observed before any corresponding fill, with enough declared lead time and cancellation/freshness behavior verified.
5. Per-market effectiveness, benchmark coverage, uncertainty and intelligence evidence are accurate; no-fill rows and missing money values cannot inflate success.
6. Tests, read-only/access contracts, builds, independent review and deployed runtime checks pass for the final revision. Restart continuity is verified and paper execution is left running.
7. Benchmark outperformance remains unproven until current prospective evidence actually supports it. Do not mark the overall goal complete from UI screenshots, green tests or a plausible strategy alone.
