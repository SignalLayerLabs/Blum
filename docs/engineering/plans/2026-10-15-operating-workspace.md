# Operating workspace implementation plan

> Execute inline with `superpowers:executing-plans`; one independent whole-branch review before integration.

**Goal:** Deliver the full operating-workspace and prospective-trading specification.
**Architecture:** Existing Next.js product, Python engine/facades, PostgreSQL records and read-only Cloudflare delivery. Separate view adapters from UI; evolve financial behavior through tested contracts and additive persistence.
**Tech stack:** Next.js/React/TypeScript, Node tests, FastAPI/SQLAlchemy/Alembic, pytest, existing Workers pipeline.
**Spec:** `docs/engineering/specs/2026-10-15-operating-workspace-design.md`.

## Global constraints

Paper execution; equities/ETFs and Forex evaluated separately. No invented market data or profitable placeholders. No arbitrary trade forcing, disabled risk gates, new paid compute or credentials. Missing metrics remain missing. Source/history integrity and private administration remain intact. Goal completion requires the full acceptance audit, including observed advance calls and actual outcome evidence.

## Review focus

Unfilled terminal orders incorrectly counted as profitable/breakeven trades; null money converted to zero; mixed-currency P/L; stale/cold API reads falsely presented as a running engine; historical decisions relabeled as upcoming plans; exploratory samples promoted as demonstrated alpha.

## Task 1 — Truthful overview and visual foundation

- [x] Add tested view adapters for per-market counts, qualified evidence and source availability; no aggregation of mixed currencies or null-to-zero coercion.
- [x] Build a new Overview and shared navigation/layout. Show actual work, upcoming-call availability, observed executions and current research; demote internal scores.
- [x] Verify Node contracts, TypeScript, static build and actual desktop/mobile UI with captured real snapshots.

## Task 2 — Complete the primary workspace revamp

- [x] Rebuild Calls, Trades, Performance and Research with consistent UI components, filters, disclosure/detail states and plain-language status.
- [x] Keep history separate from prospective plans and unfilled orders separate from executed closures.
- [x] Inspect real payload units/currencies; expose missing or unqualified evidence rather than manufacturing totals.
- [ ] Verify all routes, responsive layout, keyboard controls, loading/empty/stale/error states and read-only behavior.

## Task 3 — Reliable snapshot delivery

- [ ] Reproduce the observed cold/concurrent Alpha Desk failure and profile SQL/request work.
- [x] Test and implement bounded batched/persisted read models as warranted by evidence. Avoid recalculation or job launch from GET.
- [ ] Measure relevant before/after runtime behavior and retain outage visibility.

## Task 4 — Actual continuous cost-aware paper execution

- [ ] Trace strategy selection, eligibility, net-edge and freshness blockers against current runtime evidence.
- [ ] Test independent execution/accounting cases (both directions, quoted/model spread, slippage, fees, swap, conversion, gaps, expiry and partial fills).
- [ ] Implement a declared prospective paper-exploration path if needed to collect evidence without circular eligibility, preserving risk/data/quarantine boundaries.
- [ ] Verify observed provider-driven orders/fills, lifecycle management, closures and exact net P/L; keep no-trade conditions explicit.

## Task 5 — Advance calls and effectiveness

- [ ] Add durable plan publication/activation/expiry/cancellation contracts and a minimum lead-time policy.
- [ ] Test and observe publication before fill; prevent stale/invalid plans from filling retrospectively.
- [ ] Complete per-market attribution, aligned benchmark and uncertainty reporting from mature outcomes. Evaluate actual intelligence gains against declared baselines.

## Task 6 — Review, release and full completion audit

- [ ] Run affected suites and required CI/build/access checks; obtain independent whole-branch review and fix material findings.
- [ ] Publish a concrete reviewable result, integrate/deploy within the user's authorization and verify source/continuity/resumed execution.
- [ ] Audit every specification acceptance item against current code and runtime. Leave the goal active while efficacy or benchmark outperformance remains unproven.

## Increment evidence — 16 October 2026

The first workspace increment is implemented and independently reviewed. Overview, Calls, Trades, Performance and Research share the new layout. Browser inspection used actual captured 15 October runtime records; it is a local preview, not a deployment. Mobile navigation fits the viewport. Trade inspection moves keyboard focus to its detail. Snapshot-error fallback remains explicit. Full populated, deployed end-to-end and every keyboard-path checks remain pending.

`/api/runtime/operating-state` is an additive public read-only projection with three SELECTs and no runtime initialization, provider call, commands, raw private errors or credentials. Forex control/heartbeat observations are separate from last completed cycle and trade counts. GET behavior is tested through the access guard.

Financial corrections include post-acquisition live Forex decision time, separate executed-closure/unfilled buckets, partial fills as open exposure, frozen account currency for intraday/native Forex, no non-EUR amounts in EUR aliases, nested Forex valuation, swap debit signs, and suppression/grouping of mixed-currency monetary metrics. The UI shows actual open marks/unrealized results and only monetary cost fields; IDs, basis points and fill counts cannot become cash charges. Explicit charges are separate from embedded fill costs. This is not the complete independent execution/accounting audit in Task 4.

Verification: 912 backend tests, 35 frontend tests, 12 gateway tests; static export, TypeScript/gateway typecheck and diff checks pass. Eight obsolete Python tests asserting the old four-page source layout were replaced by actual React render/navigation/GET contracts and financial adapter behavior. Independent reviewer found the presentation/currency issues above; all were fixed and the final review reported no remaining material finding in this increment.

Current deployed evidence at 2026-10-16T05:17:10Z is still e83060a: 1,345 registrations, zero qualified closed calls in either market, Forex RUNNING / MARKET_SESSION_MONITOR_ONLY, zero orders/fills for the current day. Latest completed entry-session cycle is from 15 October. More registrations do not establish execution, intelligence improvement or alpha. No restart or scheduler mutation was performed during this increment.

Next work remains Tasks 3–5: snapshot performance/window integrity, prospective execution and risk/accounting validation, durable publication with entry lead time/cancellation, and measured benchmark evidence. Do not treat the current UI or green tests as completion of the goal. Do not resurrect the quarantined Forex bootstrap strategy to manufacture activity. Current tests intentionally require an empty registry to remain research-only until replay validation.

## Delivery increment — 16 October 2026

Alpha Desk public delivery now reads one stored background evaluation with no calculation fallback. Missing, stale and invalid/future evaluation clocks remain explicit. Cached eligibility cannot be a current actionable call. Both markets receive separate recent and executed-history windows and journal slots; actual registration counts are distinct from bounded performance. Migration 0046 adds only indexes. A shared frozen/execution currency contract rejects ambiguous cash units in qualified results.

A synthetic local workload of 1,000 dense Forex decisions measured full evaluation at 3.29 seconds / 64.8 MB peak Python allocation versus a stored read at 1.85 ms / 99 KB / one SELECT. This establishes lower request work, not repaired production availability or trading effectiveness. Cold/concurrent production HTTP verification remains pending deployment; Task 3 is not yet complete.

Validation: 926 backend tests, 37 frontend tests and static export/type checking pass. Independent delivery review found an explicit stale/invalid-clock status could be hidden by a recent timestamp; a failing real React rendering test reproduced it, the indicators now prioritize the source state, and the full frontend suite/build pass after the fix. No additional material finding was reported. PostgreSQL production plans/index impact, deployed latency and the later execution/publication work remain unverified within this increment.

Current read-only production capture at 2026-10-16T05:45:10Z remains e83060a: 1,346 registrations, zero qualified closures for both markets, zero orders/fills today and Forex RUNNING / MARKET_SESSION_MONITOR_ONLY. No runtime mutation or deployment was performed for this increment.

Ruling: ship a reviewable workspace/delivery increment before the remaining engine lifecycle work, subject to the original merge approval rule. Live availability and prospective execution can only be observed after deployed code runs; their absence remains visible and the full goal stays active. This costs another release boundary and must never be described as completed trading efficacy.
