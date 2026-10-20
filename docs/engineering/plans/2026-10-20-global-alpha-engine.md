# Connected Global Alpha Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and operate a source-attributed, information-driven paper trading and learning cycle in USA equities/ETFs and Forex, then test whether it actually adds net value over the market.

**Architecture:** Repair the existing execution/accounting boundary first. Immutable source evidence feeds versioned as-of contexts, canonical executable strategies and calibrated numerical advice; frozen decisions go to the existing native paper engines and matured outcomes feed the same learning system. Research, prospective controls and qualification retain separate provenance and account evaluation.

**Tech Stack:** Existing Python/FastAPI, SQLAlchemy/Alembic/PostgreSQL, requests/feedparser, scikit-learn 1.6.0, numpy/scipy, exchange_calendars 4.13.2, APScheduler, Next.js and the Cloudflare gateway. No additional product dependency is planned.

**Spec:** `docs/engineering/specs/2026-10-20-global-alpha-engine-design.md`, approved 20 October 2026; baseline `a555f97b4b032b6e87b51bef25470d79b83f4df3`.

## Global Constraints

- “Paper-only operation and existing financial truth remain authoritative.” No second position ledger, real-money routing or fabricated fills.
- “Equities/ETFs and Forex retain separate evaluations.” The first integrated delivery crosses the complete operating chain in both families.
- “Paid services, new persistent credentials and any real-money routing require their own authorization.” Reuse existing authorized credentials only.
- “The original explicit approval requirement for each merge/deploy remains in force.” A reviewed plan does not authorize merging its future PR.
- “No open or unknown result becomes a win/loss.” Retrospective examples cannot become PAPER_FORWARD because they were inserted today.
- “Every nonzero fill immediately becomes an accounted, marked and risk-managed position.” Unfilled remainder cancellation cannot erase exposure.
- “UNKNOWN is not CLEAR.” Missing calendar, consensus, conversion, source dates and model support remain explicit missingness.
- Execution/position work at least every 60 seconds during relevant sessions requires fresh observations and actual management, not a stale-cache heartbeat. Source context processing target: two scheduled decision cadences.
- Prospective final review: 40 market sessions; at least 100 closed observations across at least 20 distinct sessions per claimed market; positive lower 95% corrected paired-excess interval plus complete accounts, cost stress and declared risk budget. These are review minimums, not proof by themselves.
- “The full strict-durability criterion remains open until an authorized durable database/recovery mechanism is configured and tested.” An embedded fresh-backup preflight only mitigates controlled deployments.
- Preserve journals, model artifacts, historical evidence semantics and all failed trials. No secrets, private dumps or restricted raw data enter Git.
- A failed financial trial remains a failed research result. Engineering delivery is not completion of the user's market-outperformance goal.

## Review Focus

1. A partially filled position hits its stop while its remainder is pending: manage the filled quantity immediately and cancel only the remainder (Tasks 1–2).
2. A provider changes content at the same URL or DNS/redirect target: preserve revisions and reject private-network retrieval, without rewriting prior decisions (Tasks 3–4).
3. An event arrives late, is syndicated, or maps to both an issuer and its ETF: retain availability and exposure semantics without counting it three times (Task 5).
4. A worker restarts after recording an outcome but before publishing its model: recover without duplicating labels, changing a frozen checkpoint or losing a cursor (Tasks 8, 10, 13).
5. The 40-session review has too few independent observations or a trial is extended after looking at results: keep it unqualified and record a new predeclared trial rather than polling until positive (Task 12).

---

## Execution workspace and conventions

Use the existing clean linked worktree `work/Blum-lean-nav`, branch `feat/global-alpha-engine`; preserve the separate unmerged Forex WIP `31544a3eea5338a877b90eab13c7ceb058752066`. Inspect current HEAD, migrations and applicable instructions before implementation. Do not copy WIP wholesale or reset either checkout.

All commands below run from repository root with project dependencies installed and `PYTHONPATH=backend`. Local verified runtime, if the project venv is unavailable: `PYTHONPATH=backend:../test-deps:../arrow24:../curriculum-deps '/Users/renatovinai/Documents/New project/.venv/bin/python' -m pytest ...`. This runtime is read-only: do not install into it. CI uses Python 3.12 and the existing requirements files.

For every task: first add the named assertions using temporary SQLite/Postgres databases, a frozen clock and local HTTP fixtures; run its exact test command and confirm the expected failure; implement; run the same command until it passes; inspect the diff and commit only that task's files using the stated commit message. No live requests or real money in correctness tests. Fixture helper names in examples below belong in that task's test module or shared `conftest.py`; they are not new production APIs.

Implementation is sequential because accounting, context hashes, inference schema and outcome identities are shared contracts. Each numbered task has an independent test/review boundary. Tasks 1–2 are independently useful correctness fixes; Tasks 3–9 create the connected decision path; Tasks 10–15 make it operational and reviewable; Task 16 releases and observes it. Do not substitute shipping the first group alone for the approved integrated delivery.

## File ownership and shared contracts

| Area | New focused files | Existing integration points |
| --- | --- | --- |
| Clock/execution/accounting | `backend/app/services/market_clock.py`, `forex_cash_accounting.py`, `forex_order_lifecycle.py` | `realistic_execution.py`, `paper_execution_lifecycle.py`, `intraday_paper_engine.py`, `forex_execution.py`, `forex_trader.py`, `models.py` |
| Information acquisition | `backend/app/services/information/{__init__,contracts,repository,fetch,providers,worker}.py` | `ingestion/news_ingestor.py`, `services/macro.py`, `core/config.py`, `models.py` |
| As-of context/decisions | `backend/app/services/information/{context,policy,decisions}.py`, `forex_strategy_signal.py` | `forex_contracts.py`, `forex_agents.py`, `intraday_opportunity.py`, `alpha_desk.py`, `live_forward_paper_trading.py` |
| Model/feedback/replay | `backend/app/services/information/{model,feedback,replay}.py` | `trading_ml/{contracts,features,training,validation,registry,inference,worker,feature_store}.py`, `learning_loop.py`, `market_sniper.py`, `curriculum_worker.py` |
| Runtime/evaluation | `backend/app/services/{work_budget,alpha_trials,alpha_evaluation,release_checkpoint}.py` | `realtime.py`, `worker_runtime.py`, `central_brain_runtime.py`, `data_continuity.py`, `persistence.py` |
| Public product/release | `scripts/{evaluate_global_alpha,verify_global_alpha_release}.py`, focused tests | `api/routers/alpha.py`, `data/public_api_routes.json`, `frontend/components/workspace/Performance.tsx`, `frontend/lib/api.ts`, deploy workflow/scripts |

Paths in the table are relative to `backend/app/services/` unless fully prefixed. New files hold focused behavior; existing large engines delegate to them rather than absorbing another subsystem. Migrations remain linear, assigned in task order after the then-current Alembic head. Below names assume no intervening main migration; rebase and renumber if needed.

Shared immutable contracts in `information/contracts.py`:

- `MarketFamily = Literal["equity", "forex"]`; all boundary timestamps normalize to UTC; database writes follow existing naive-UTC storage, never local wall time.
- `SourceEvidence`: `evidence_id`, `family_id`, `provider`, `canonical_url`, `content_hash`, `language`, `published_at`, `observed_at`, `available_at`, `revision_of`, `historical_availability_verified`, `extraction_version`, `payload`; frozen dataclass. Unknown source time remains `None`.
- `EvidenceLink`: `evidence_id`, `entity_key`, `kind` (issuer/currency/sector/commodity/ETF exposure), `confidence`, `reason`, `mapping_version`.
- `ProviderResult`: `provider`, `status` (AVAILABLE/EMPTY/UNAVAILABLE/QUOTA_LIMITED/ENTITLEMENT_REQUIRED), tuple of evidence, cursor, retry-at, source/observed times and error code. Never include credentials/raw authorization headers.
- `OpportunityContext`: `context_uid`, `market_family`, `asset_key`, `decision_at`, price references, evidence IDs, tuple of links, calendar state (KNOWN_CLEAR/KNOWN_EVENT_WINDOW/UNKNOWN), feature mapping, coverage, schema version, `max_available_at`, hash. `features` contains numeric/string/None values compatible with `TradingMLExample`.
- `InformationAdvice`: existing `TradingMLAdvice` plus feature-schema hash, artifact/checkpoint hash, training cutoff, calibration support and whether returned R is already net of costs. Unsupported numeric advice remains `None`.
- `FrozenAlphaDecision`: decision UID, trial UID, market/asset, decision/expiry clocks, context/hash, executable-spec payload/fingerprint, model/checkpoint, action/reason, geometry, sizing, expected-outcome fields, evidence lane and policy version. No post-registration mutation.
- `MaturedAlphaOutcome`: unique native source UID, decision UID, outcome timestamp, actual net R/account return, cost breakdown, benchmark reference and original evidence lane. Open/unknown results are ineligible.

### Task 1: Repair observation clocks, expiry and stop-limit semantics

**Files:** Modify `realistic_execution.py`, `paper_execution_lifecycle.py`, `intraday_market_data.py`, `intraday_opportunity.py`, `forex_trader.py`; create `market_clock.py`; tests `backend/tests/test_realistic_execution.py`, new `test_market_clock.py`.

**Interfaces:** Preserve `RealisticExecutionEngine.evaluate(request, bars) -> ExecutionDecision` and `PaperOrderLifecycleService.process_order(db, order, bars, *, now=None) -> dict`. Extend execution request/result with optional persisted `stop_activated_at` and `last_observation_at`. Add `MarketClock.session(market: str, at: datetime) -> str` and `eligible_bar(row, *, decision_at: datetime | None, as_of: datetime, mode: str) -> bool` for completed, actually available bars; execution mode additionally requires a later observation. Reuse exchange_calendars for USA, zoneinfo for declared FX trading/session hours.

- [ ] Add failing cases `test_lifecycle_excludes_future_and_post_expiry_bars`, `test_stop_limit_activation_survives_restart`, `test_gap_execution_obeys_limit_and_observed_prices`, `test_latency_not_reset_on_poll`, `test_dst_holiday_and_half_day_session`. Pin expiry as exclusive: bar observation at expiry is ineligible; bars genuinely available before expiry may still be processed on a delayed poll. Exclude observations after `now`; preserve existing fills.

```python
assert after_expiry.filled_quantity == 0
assert future_bar.filled_quantity == 0
assert gap_stop_limit.fills == ()  # stop=100, limit=100.005, whole bar=109..111
assert clock.session("USA", thanksgiving_half_day_after_close) == "closed"
```

- [ ] Run `python -m pytest backend/tests/test_realistic_execution.py backend/tests/test_market_clock.py -q`; confirm the new assertions fail against baseline.
- [ ] Implement eligibility before engine evaluation, persistent stop/latency/observation state and adverse gap handling. Same-bar ambiguous trigger/cross yields no fill; later unambiguous limit crossing may fill. Apply bounds to final executed limit price, not only its pre-slippage reference. Wire actual acquired/available times into both gateways.
- [ ] Re-run that command and relevant `test_live_intraday_paper_engine.py`; require all PASS.
- [ ] Commit `fix: enforce paper execution clocks and stop limit bounds`.

### Task 2: Account and protect every partial fill in both native engines

**Files:** Modify `paper_execution_lifecycle.py`, `intraday_paper_engine.py`, `forex_trader.py`, `forex_execution.py`, `forex_risk.py`, `models.py`; create `forex_cash_accounting.py`, `forex_order_lifecycle.py`, migration `0048_forex_order_accounting.py`; tests new `test_partial_fill_management.py`, `test_forex_order_lifecycle.py`, existing `test_forex_intraday_accounting.py`.

**Interfaces:** `ForexOrderLifecycle.submit(db, *, decision_id: int, order: ForexOrderRequest, expires_at: datetime) -> ForexPendingOrder`; `process(db, *, order_uid: str, quote: ForexQuote, as_of: datetime) -> dict`. Persist order activation/remainder separately from `ForexPosition`; fills have unique `(order_uid, observation_uid)` identities and only later eligible quotes execute. `ForexCashAccounting.apply_fill(db, *, fill_uid: str, position_id: int, delta_lots: float, executed_price: float, commission: float, conversion: dict) -> dict`; `reconcile(db, *, account_id: str, as_of: datetime) -> dict`. Conversion includes actual rate, direction, provider, observation and availability clocks.

- [ ] Add failing tests for first 10/100 fill becoming managed immediately, a stop before the other 90 fill, expiry releasing only the 90 remainder, two concurrent/repeated polls, weighted-average entry/costs and stop-out with partial quantity. Parameterize EURUSD, USDJPY, AUDJPY in EUR accounts; missing cross conversion blocks new risk rather than using 1.0. Tests must reconcile cash + positions − liabilities to NAV and assert P/L exactly once.

```python
assert first.position_quantity == 10 and first.remaining_quantity == 90
assert stopped.closed_quantity == 10 and stopped.remaining_order_quantity == 0
assert repeated.total_cost == stopped.total_cost
assert missing_conversion.reason == "ACCOUNT_CONVERSION_UNAVAILABLE"
```

- [ ] Run `python -m pytest backend/tests/test_partial_fill_management.py backend/tests/test_forex_order_lifecycle.py backend/tests/test_forex_intraday_accounting.py -q`; confirm expected failures.
- [ ] Review WIP commit `31544a3` read-only; port only reviewed conversion/cash logic under the above interfaces. Apply incremental deltas per fill, manage every positive quantity and cancel remainder on position exit. FX submit becomes pending until a later eligible quote; do not create another monetary ledger. Bid/ask and slippage already embedded in executable prices are reported as attribution, not subtracted twice. Remove configured pip-value conversion fallbacks from qualified accounting.
- [ ] Run the same tests plus `test_forex_trader_core.py`, `test_live_intraday_paper_engine.py` and migration-chain tests; require PASS and unchanged legacy journal IDs.
- [ ] Commit `fix: manage partial exposure and reconcile forex cash`.

### Task 3: Persist immutable information evidence and provider state

**Files:** Create `information/__init__.py`, `contracts.py`, `repository.py`; modify `models.py`; migration `0049_information_evidence.py`; create `backend/tests/test_information_repository.py`.

**Interfaces:** Define shared contracts above. `InformationRepository.ingest(db, result: ProviderResult) -> dict`; `eligible(db, *, market_family: MarketFamily, asset_key: str, as_of: datetime, historical: bool=False) -> tuple[SourceEvidence, ...]`. Tables: `information_evidence` (evidence_id primary key, family_id, provider, content hash, three clocks, revision, payload); `information_links` (unique evidence/entity/kind/mapping_version); `information_provider_states` (provider primary key, cursor, status, retries, last success and coverage). Source identity hashes provider + canonical identity + content hash; revision rows append.

- [ ] Add missing-date, duplicate-ingestion, changed-content/same-URL, concurrent insert and late-acquisition tests; assert immutable old hashes and no historical inclusion of merely current revised macro.

```python
assert first.evidence_id != revision.evidence_id
assert revision.revision_of == first.evidence_id
assert late.evidence_id not in ids(repo.eligible(db, market_family="equity", asset_key="AAPL", as_of=before_arrival))
```

- [ ] Run `python -m pytest backend/tests/test_information_repository.py -q`; confirm missing-contract failures.
- [ ] Implement hash canonicalization, DB uniqueness/upsert retry and bounded indexed as-of reads. Do not backfill invented publication/availability dates into legacy news.
- [ ] Run the same tests plus `backend/tests/test_migration_chain.py`; require PASS for upgrade from 0047 through new migrations and rollback on a disposable DB.
- [ ] Commit `feat: persist versioned source evidence and availability`.

### Task 4: Connect real global sources with bounded, secure retrieval

**Files:** Create `information/fetch.py`, `providers.py`, `worker.py`; modify `ingestion/news_ingestor.py`, `macro.py`, `core/config.py`; tests new `test_information_providers.py`, `test_information_fetch.py`.

**Interfaces:** `PublicEvidenceFetcher.fetch(url: str, *, deadline: float, etag: str | None=None) -> FetchResult`; `FetchResult` contains status, bounded bytes, content type, final public URL, headers limited to cache/retry metadata and observed time. `InformationProvider.fetch(*, cursor: dict, as_of: datetime, deadline: float) -> ProviderResult` protocol; adapters `ExistingNewsProvider`, `CentralBankProvider`, `FredVintageProvider`, `SecFilingsProvider`, `GdeltDiscoveryProvider`. `InformationWorker.run_once(db, *, as_of: datetime, deadline: float, max_items: int=50) -> dict` persists results/cursors and fair provider rotation.

- [ ] Add fixture-server tests for 200/304/empty/403/429/timeout, Retry-After, conditional requests, oversized/gzip bodies, bad XML, missing dates, multilingual UTF-8 and redirect/DNS public→private. Assert 403/429 become failures, optional missing keys become ENTITLEMENT_REQUIRED, and a failed source does not stop successful Fed/ECB evidence ingestion.

```python
assert quota.status == "QUOTA_LIMITED" and quota.retry_at > now
assert denied.status == "UNAVAILABLE" and not denied.items
assert private_redirect.error_code == "NON_PUBLIC_DESTINATION"
```

- [ ] Run `python -m pytest backend/tests/test_information_providers.py backend/tests/test_information_fetch.py -q`; confirm failures.
- [ ] Implement per-host concurrency=1, request total budget<=10 seconds, decompressed body<=2 MiB, at most 3 validated redirects, 429 backoff persisted across restart. Use requests with explicit timeout/streaming and destination-pinned validated transport; block loopback, private, link-local and metadata targets including IPv6/redirect/rebinding. Reuse existing news intelligence; add official Fed/ECB, FRED current/vintage distinction, SEC accessions and GDELT cursors. No synthetic feed success. Extraction treats document text as evidence only.
- [ ] Re-run fixture tests; run an explicit read-only source probe with `--max-items 5` when Task 15's CLI exists. Report actual accessible providers separately from implemented ones.
- [ ] Commit `feat: acquire global evidence with provider budgets and provenance`.

### Task 5: Build causal issuer/currency contexts and versioned information features

**Files:** Create `information/context.py`; modify `forex_contracts.py`, `forex_agents.py`, `intraday_market_data.py`; new `backend/tests/test_opportunity_context.py`.

**Interfaces:** `OpportunityContextBuilder.build(db, *, market_family: MarketFamily, asset_key: str, decision_at: datetime, price_refs: tuple[dict, ...], historical: bool=False) -> OpportunityContext`. Features v2 add `event_novelty`, `issuer_sentiment`, `sector_sentiment`, `base_currency_policy_delta_bps`, `quote_currency_policy_delta_bps`, `release_age_seconds`, `information_coverage`, `calendar_known`, `event_window`, each nullable with explicit units. Calendar UNKNOWN until a schedule source proves coverage, never inferred clear from an empty news query.

- [ ] Add tests for same story in three publishers, exact issuer versus substring ticker, ETF exposure versus issuer, EUR/USD sign alignment, late event exclusion, future revision, unavailable consensus and current-revised macro excluded from historical context.

```python
assert syndicated.features["event_novelty"] == single.features["event_novelty"]
assert unknown.calendar_state == "UNKNOWN"
assert "employment_count" not in policy_delta_bps_inputs
assert frozen.hash == context_rebuilt_without_newly_arrived_evidence.hash
```

- [ ] Run `python -m pytest backend/tests/test_opportunity_context.py -q`; confirm failures.
- [ ] Implement deterministic family dedup, unit-aware normalized deltas and explicit entity/exposure mapping, with versioned reasons and missingness. Hash price refs, evidence IDs, feature schema and decision clock. Join the actual FX context instead of expecting unpopulated ReplayMarketBar macro metadata.
- [ ] Re-run tests; require no future source time and stable context hash on repeated reads.
- [ ] Commit `feat: build as of information contexts for stocks and currencies`.

### Task 6: Execute the exact validated strategy in Forex

**Files:** Create `forex_strategy_signal.py`; modify `forex_contracts.py`, `forex_trader.py`, `forex_agents.py`, `executable_strategy.py` only where shared evaluation needs explicit direction; tests new `test_forex_strategy_parity.py`, existing `test_deterministic_execution_parity.py`.

**Interfaces:** Extend `ForexStrategyEvidence` with canonical `executable_strategy: dict`, `strategy_fingerprint: str`, required feature-schema hash and holding horizon. `ForexStrategySignal.evaluate(market: AgentMarketInput, *, strategy: ForexStrategyEvidence) -> PriceActionOutput` delegates to `StrategySignalEvaluator.evaluate(spec, bars_by_timeframe, as_of=..., market="FOREX")` and its geometry. Contrarian/short behavior must be an explicit validated rule, not a post-validation sign flip.

- [ ] Add parity tests with distinct breakout, mean-reversion and trend rules on identical bars; missing/corrupt spec blocks; altering stop ATR or maximum holding bars changes executed geometry/horizon. Assert replay/live fingerprint equality and that legacy generic 5/10-pip rules cannot inherit certification.

```python
assert decision.strategy_fingerprint == validated_spec.fingerprint
assert decision.stop_level == replay_geometry.stop_price
assert missing_spec.blockers == ("EXECUTABLE_SPEC_UNAVAILABLE",)
```

- [ ] Run `python -m pytest backend/tests/test_forex_strategy_parity.py backend/tests/test_deterministic_execution_parity.py -q`; confirm failures.
- [ ] Preserve the full selected spec in the repository DTO, adapt eligible frames to the shared evaluator and propagate fingerprint/geometry/horizon through decisions and exits. Preserve readiness/quarantine checks.
- [ ] Run these tests plus `test_forex_trader_core.py`; require PASS and no inherited badge for a changed contract.
- [ ] Commit `fix: execute forex strategies with validated contract parity`.

### Task 7: Calibrate information-aware numerical predictions without fabricated confidence

**Files:** Create `information/model.py`, `policy.py`; modify `trading_ml/contracts.py`, `training.py`, `validation.py`, `registry.py`, `inference.py`; tests new `test_information_model.py`, existing trading-ML training/validation/inference tests.

**Interfaces:** `InformationOutcomeAdvisor.advise(db, *, context: OpportunityContext, strategy_fingerprint: str, baseline: dict, as_of: datetime, model_uid: str | None=None) -> InformationAdvice`; `InformationPolicy.apply(*, baseline: dict, context: OpportunityContext, advice: InformationAdvice, risk_multiplier: float) -> dict`. Add `TradingMLModelRegistry.load_as_of(db, market_family: str, *, as_of: datetime, schema_hash: str, model_uid: str | None=None) -> LoadedModel`. Store training/outcome cutoffs and feature schema in artifact metadata; never load incompatible v1 artifacts as v2.

- [ ] Add tests for chronological fit/calibration separation, overlapping-label embargo, future model rejection, constant/one-class labels, no supported sample, cost double-subtraction and fixed-price event ablation. Use deterministic fitted miniature models for correctness only; they never become financial evidence.

```python
assert unsupported.probability_positive_r is None
assert advice.training_cutoff < context.decision_at
assert event_policy["rank"] != price_only_policy["rank"]
assert costed.predicted_net_r == stored_net_label_prediction
```

- [ ] Run `python -m pytest backend/tests/test_information_model.py backend/tests/test_trading_ml_training.py backend/tests/test_trading_ml_validation.py backend/tests/test_trading_ml_inference.py -q`; confirm failures.
- [ ] Reuse HGB classifier/regressor and SGD online machinery. Reserve chronological calibration after training and before evaluation; purge complete outcome horizons and embargo at least the maximum configured holding horizon. Save Brier/log-loss/calibration support per market/setup/regime; unsupported probabilities/R stay missing. Target distance and modeled costs remain separate. A supported model may change rank/veto or reduced-risk size within existing risk caps; a deterministic novelty/risk rule supplies explicit information influence before calibrated outcome support exists, without masquerading as probability.
- [ ] Re-run tests and verify event-only ablation plus blocked-data gates remain deterministic.
- [ ] Commit `feat: calibrate information aware trading advice`.

### Task 8: Connect matured native outcomes to exactly-once learning

**Files:** Create `information/feedback.py`; modify `trading_ml/features.py`, `feature_store.py`, `worker.py`, `online.py`, `learning_loop.py`, `market_sniper.py`, `models.py`; new `backend/tests/test_information_feedback.py`, migration `0050_information_feedback.py`; extend existing feature/online tests.

**Interfaces:** `InformationFeedback.project(db, *, as_of: datetime, max_items: int=100) -> dict` emits existing `TradingMLExample` using `MaturedAlphaOutcome`, frozen context/spec/checkpoint and native source UID. Persist an outbox/consumption table with unique `(consumer_version, source_uid)` and publication status in this task’s migration. The decision UID is a stable string here; Task 9 adds the registered-decision record without reclassifying old outcomes. `load_as_of` from Task 7 governs historical PredictionEngine state too.

- [ ] Add tests: open outcome excluded; historical prediction created today stays historical; duplicated closures/reliability updates counted once; conflicting same-UID content quarantined; crash after DB outcome before feature/model publication resumes exactly once; old decision features survive later news or active-model change.

```python
assert second["new_examples"] == 0
assert historical.evidence_lane != "PAPER_FORWARD"
assert resumed.source_uid_count == uninterrupted.source_uid_count
assert prediction.checkpoint_hash == frozen_decision.checkpoint_hash
```

- [ ] Run `python -m pytest backend/tests/test_information_feedback.py backend/tests/test_trading_ml_features.py backend/tests/test_trading_ml_online_queue.py -q`; confirm failures.
- [ ] Implement transactional outbox + idempotent consumer, atomic artifact publication and scoped memory lookup. Correct decision timestamp to original market decision, not created_at. Deduplicate reliability updates by native outcome UID. Historical queries require available model/memory cutoffs; missing cutoff invalidates qualified historical evidence.
- [ ] Run those tests plus `test_learning_feedback_loop.py`; require repeat/restart equivalence and no current-state leakage.
- [ ] Commit `feat: learn once from frozen native paper outcomes`.

### Task 9: Freeze and register information-driven decisions before native submission

**Files:** Create `information/decisions.py`; modify `models.py`, `alpha_desk.py`, `intraday_opportunity.py`, `intraday_paper_engine.py`, `forex_trader.py`, `live_forward_paper_trading.py`; migration `0051_information_decisions.py`; new `backend/tests/test_information_decisions.py`.

**Interfaces:** `InformationDecisionService.freeze(db, decision: FrozenAlphaDecision) -> AlphaDecisionRecord`; `submit(db, *, decision_uid: str, as_of: datetime) -> dict` delegates to native engine adapter and Tasks 1–2. `AlphaCallRegistry.register_decision(db, decision: FrozenAlphaDecision, *, source_id: int, registered_at: datetime) -> AlphaCallRegistration`. Persist `alpha_decisions` (UID unique, market, action, clocks, immutable JSON/hash, native order link) and links to the existing feedback outbox. Registration supports all decisions, including no-action/no-fill, without creating fake trade rows. Existing paper/FX registration methods remain compatible.

- [ ] Add tests for registry preceding order submission in the same transaction, retries and concurrent calls returning one order, mutated manifest rejected, model/context/spec attribution, abstention without trade and closed legacy trades forbidden from prospective backfill. Hold bars fixed; eligible event changes rank/veto/size in both families while price-only control remains unchanged.

```python
assert registration.registered_at <= order.submitted_at
assert retried.order_uid == first.order_uid
assert no_action.native_order_id is None
assert changed.decision_effect["information_applied"] is True
```

- [ ] Run `python -m pytest backend/tests/test_information_decisions.py backend/tests/test_alpha_desk.py backend/tests/test_live_intraday_paper_engine.py backend/tests/test_forex_trader_core.py -q`; confirm failures.
- [ ] Wire context and advice into actual native candidate generation, not only a snapshot. Use `intraday_experimental_risk_multiplier` (default 0.25), existing global/per-market exposure/drawdown gates and no trade quota. Keep unsupported model status explicit; repair daily memory adjustments so only applied matching adjustments are attributed. Preserve target-distance compatibility field but stop labeling it model expectancy in new contracts. Trial/control IDs and source times follow each actual order/outcome.
- [ ] Re-run tests plus migrations. Require at least one correctness fixture per market traversing context→registered decision→later native fill→exit→Task 8 feedback, without synthetic fixture outcomes entering production samples.
- [ ] Commit `feat: route attributed alpha decisions into native paper trading`.

### Task 10: Reserve execution capacity and enforce bounded research work

**Files:** Create `work_budget.py`; modify `realtime.py`, `worker_runtime.py`, `central_brain_runtime.py`, `curriculum_worker.py`, `data_continuity.py`, `market_data.py`, `information/worker.py`; new `backend/tests/test_alpha_runtime_priority.py`; extend `test_curriculum_worker.py`.

**Interfaces:** `WorkBudget(deadline: float, max_items: int)` with `remaining_seconds() -> float`, `check() -> None` (raises `WorkBudgetExceeded`) and resumable cursor. `ExecutionPriorityCycle.run_once(db, *, as_of: datetime, budget: WorkBudget) -> dict` lives in `work_budget.py` only as orchestration of native managers; it hydrates existing exposure before discovery. Worker results use explicit productive/no_signal/market_closed/data_blocked/deferred/timed_out/failed classifications.

- [ ] Add tests for a hung provider, discovery exhausting budget, CPU/memory deferral, process restart mid-page and stale cache at execution heartbeat. Assert management precedes discovery and requires a fresh observation for success; data repair cannot finish an unbounded whole-universe scan.

```python
assert calls.index("hydrate_existing_exposure") < calls.index("discover")
assert slow_repair.status == "timed_out" and slow_repair.cursor
assert stale_management.status == "data_blocked"
assert resource_measurement.scope in {"process", "container"}
```

- [ ] Run `python -m pytest backend/tests/test_alpha_runtime_priority.py backend/tests/test_curriculum_worker.py backend/tests/test_runtime_architecture.py -q`; confirm failures.
- [ ] Schedule management every 60 seconds with isolated execution capacity; move synchronous research/model fitting to bounded supervised worker processes using spawn and child-owned DB sessions, terminate/join on deadlines and persist cursors between chunks. Apply DB statement/lock timeouts and remaining-budget network deadlines. Avoid daemon-thread cancellation claims. Record explicit process/cgroup resource scope and preserve low-resource deferral without calling it productive completion. Source decisions run after fresh hydration; feedback/research follow.
- [ ] Re-run tests with frozen monotonic clock and an actual disposable slow child process; require no surviving child and management capacity under research pressure.
- [ ] Commit `fix: reserve execution capacity and bound research jobs`.

### Task 11: Train on random historical dates with causal context and native parity

**Files:** Create `information/replay.py`; modify `curriculum_worker.py`, `trading_curriculum.py`, `learning_loop.py`; new `backend/tests/test_information_replay.py`.

**Interfaces:** `InformationReplay.run_episode(db, *, market_family: MarketFamily, asset_key: str, start_at: datetime, end_at: datetime, seed: int, model_uid: str | None, partition: str) -> dict`; `sample_episode(db, *, market_family: MarketFamily, seed: int, partition: str) -> dict`. Returns frozen strategy/context/checkpoint hashes, actual source IDs, decisions, costed outcomes and explicit historical evidence lane; uses the same strategy evaluator and repaired execution kernel, isolated from the prospective ledger.

- [ ] Add tests for reproducible random-date selection, future model/macro/news exclusion, missing bars withholding results, confirmation partition never sampled for training, and replay/live contract parity. Established techniques include existing breakout_close, trend_continuation, mean_reversion_deviation and pullback_to_mean, with parameters/trials recorded; unsupported short variants stay unavailable.

```python
assert replay_a["manifest_hash"] == replay_b["manifest_hash"]
assert sampled["partition"] == "development"
assert all(item["available_at"] <= item["decision_at"] for item in replay_a["inputs"])
```

- [ ] Run `python -m pytest backend/tests/test_information_replay.py backend/tests/test_trading_curriculum.py -q`; confirm failures.
- [ ] Implement seeded sampling over valid contiguous context windows, full horizon embargo and frozen model snapshots. Use source-valid archive/vintage data only where actually available; price-only historical context remains explicitly price-only rather than reconstructed “known news.” Persist experiment hashes/cursors and failed trials. Replay labels may seed research models, never prospective counts.
- [ ] Re-run tests plus existing deterministic parity tests; require identical repeated manifest hashes and no confirmation-window consumption.
- [ ] Commit `feat: replay established strategies with causal historical context`.

### Task 12: Predeclare trials and continuously measure net progress

**Files:** Create `alpha_trials.py`, `alpha_evaluation.py`, migration `0052_alpha_trials.py`, `scripts/evaluate_global_alpha.py`; modify `models.py`, `trading_ml/registry.py`, `alpha_desk.py`; new `backend/tests/test_global_alpha_evaluation.py`.

**Interfaces:** `AlphaTrialService.declare(db, *, definition: dict, declared_at: datetime) -> AlphaTrial`; `evaluate(db, *, trial_uid: str, as_of: datetime) -> dict`. Definition fixes market universe, 40-session final boundary, primary hypothesis, permitted online update rule, policy/schema/risk/cost hashes and multiplicity allocation before first decision. `evaluate_paired_accounts(*, treatment: tuple[dict, ...], control: tuple[dict, ...], passive: tuple[dict, ...], trial: dict, as_of: datetime) -> dict`. Tables store immutable definitions, checkpoint lineage, one-use confirmation opening and failed/continued trials.

- [ ] Add tests: interim profit cannot promote; 99 closures or 19 sessions cannot qualify; failed/missing benchmark bars cannot be dropped selectively; repeated policy selection increases trial accounting; changed update rule starts new trial but a permitted matured-outcome update does not. Test raw-return underperformance despite positive risk-adjusted results, paired daily dependence, missing FX conversion, complete open-position NAV and post-inspection trial extension.

```python
assert interim["promotion_allowed"] is False
assert insufficient["status"] == "INSUFFICIENT_PROSPECTIVE_EVIDENCE"
assert extension["trial_uid"] != original["trial_uid"]
assert raw_underperformer["market_beaten"] is False
```

- [ ] Run `python -m pytest backend/tests/test_global_alpha_evaluation.py backend/tests/test_curriculum_valuation.py -q`; confirm failures.
- [ ] Implement matched-capital/time/risk accounts for event-aware, price-only, seeded strategies, cash and passive references; report raw return and exposure-matched excess separately. Primary net-excess interval uses session moving-block bootstrap (5-session blocks, 10,000 draws, seed 3407), with preallocated familywise alpha<=0.05 across the finite declared trial family (Bonferroni per-trial allocation recorded before outcomes). Additional trials require remaining preallocated alpha or a new declared family; never erase old trials. Block-size sensitivity 1/10 sessions and 1x/2x execution-cost stress are diagnostic and cannot replace a failed primary. Promotion also requires declared risk/drawdown budget; minimum sample alone never qualifies. Interim harm controls may disable risk without declaring success. CLI produces JSON/artifact hashes, never fitting on confirmation data.
- [ ] Re-run tests; run `python scripts/evaluate_global_alpha.py --help` and a fixture-manifest reproducibility check. Assert changing a single source/account row changes report hash; missing data yields incomplete, not zero-return success.
- [ ] Commit `feat: predeclare alpha trials and benchmark complete accounts`.

### Task 13: Protect controlled releases and verify strict persistence honestly

**Files:** Create `release_checkpoint.py`, migration `0053_release_leases.py`; modify `persistence.py`, `realtime.py`, `api/routers/runtime.py`, `models.py`, `scripts/deploy_huggingface.py`, `.github/workflows/deploy.yml`; new `backend/tests/test_release_checkpoint.py`; extend `test_persistence_backup.py`.

**Interfaces:** `ReleaseCheckpoint.prepare(db, *, revision: str, lease_seconds: int=600) -> dict`; `verify(db, *, checkpoint_uid: str) -> dict`; `release(db, *, checkpoint_uid: str) -> dict`. Protected POST endpoints `/api/runtime/release-checkpoint/{prepare,verify,release}` use existing admin authorization. Persist lease/quiescence state, full journal/outcome/checkpoint/queue fingerprints and backup identity, not just counts. Lease renews while a bounded backup/deploy is actively observed; expiration resumes scheduling.

- [ ] Add tests for an old backend without checkpoint endpoints (must fail closed), backup failure, timeout, stale/empty backup, writes during quiescence, full restoration with identical journal/outcome hashes, artifact hashes and outbox cursors, and lease expiry after deployment abort. External DB URL alone cannot assert strict recovery: verify actual durable service/backup/recovery evidence.

```python
assert failed_backup["publication_allowed"] is False
assert restored["financial_fingerprint"] == before["financial_fingerprint"]
assert expired_lease["scheduling_resumed"] is True
```

- [ ] Run `python -m pytest backend/tests/test_release_checkpoint.py backend/tests/test_persistence_backup.py -q`; confirm failures.
- [ ] Implement drained write workers, fresh consistent dump, atomic backup/checksum publication and lease-aware restart. Release script verifies checkpoint before source push; workflow always releases lease on abort, rechecks revision/content identity afterward and blocks CF activation on backend failure. The baseline has only `/system/persistence/backup`, not the new quiescence endpoints: an ordinary online backup cannot bootstrap this guarantee. The first transition must either use an explicitly authorized maintenance session in the existing container to drain writers, take/verify a fresh backup and hold a bounded deployment lease, or first configure and verify authorized durable external PostgreSQL. Detect missing capability as `CHECKPOINT_BOOTSTRAP_REQUIRED`; do not merge/deploy into a workflow that silently bypasses it. Prepare the exact maintenance commands/rollback against the available authorized transport during this task; if neither transport nor durable service is available, report that concrete release blocker before requesting merge approval. Subsequent deployments use the new endpoints. Existing admin credential remains secret and confined to exact backend origin. If CI lacks that authorized secret, prepare concrete secret wiring for user authorization rather than weaken the preflight. For external durable Postgres, prepare configuration/recovery procedure using existing DATABASE_URL; do not purchase/provision an account. Keep strict-durability status false until actual authorized recovery proof exists.
- [ ] Re-run tests plus public access guards; perform a disposable Postgres restore drill with hash equality, not production reset. Record embedded recovery-point limitations explicitly.
- [ ] Commit `fix: require verified release checkpoints and recovery evidence`.

### Task 14: Expose stored engine evidence and progress in the product

**Files:** Modify `api/routers/alpha.py`, `data/public_api_routes.json`, `frontend/components/workspace/Performance.tsx`, `frontend/lib/api.ts`, `frontend/lib/alphaDeskView.mjs` and declarations; add `backend/tests/test_information_public_api.py`, `frontend/tests/information-alpha-view.test.mjs`; update `README.md`, relevant `docs/` operating guide.

**Interfaces:** GET `/api/alpha/information` returns bounded stored provider coverage, latest causal decision/effect, native order/fill/outcome/feedback lineage, operational freshness and separate trial reports per market. Reads never invoke retrieval/training/order submission; admin raw source/dump data stays private. Existing `/api/alpha/desk` remains compatible.

- [ ] Add tests for an empty cold-start report, unavailable/limited providers, UNKNOWN calendar, no-fill versus trade, partial exposure, model unsupported, expired trial and stale stored snapshot. Assert public mutation/refresh rejected and repeated GET leaves DB/model/network state unchanged.

```python
assert payload["equity"]["trial_status"] != "MARKET_BEATEN"  # no proof
assert payload["forex"]["positions"][0]["filled_quantity"] > 0
assert calls_to_network_or_training == 0
```

- [ ] Run `python -m pytest backend/tests/test_information_public_api.py -q` and `npm --prefix frontend test`; confirm new assertions fail.
- [ ] Render source→decision→order→outcome→learning progress and event-vs-price-only results with honest statuses and denominators. Link exact strategy/model/source hashes, use no win-rate guarantees, and report what information actually changed. Preserve existing page design rather than unrelated rebranding.
- [ ] Re-run tests and `npx tsc --noEmit` in frontend; build static output and inspect desktop/mobile empty, blocked, active and completed fixtures.
- [ ] Commit `feat: show attributable alpha operations and benchmark progress`.

### Task 15: Verify the whole operating chain before opening a release PR

**Files:** Create `backend/tests/test_global_alpha_vertical_slice.py`, `scripts/verify_global_alpha_release.py`; modify `.github/workflows/ci.yml`, `scripts/verify_deployment.py` only to add bounded release contracts; document `docs/engineering/global-alpha-acceptance.md`.

**Interfaces:** Verifier CLI accepts `--backend`, `--site`, `--expected-revision`, `--expected-content-hash`, `--read-only`, `--output`; source probe mode `--probe-sources --max-items 5`. Uses exact-origin admin header from environment only when explicitly running private acceptance reads; never follows an authenticated redirect. Output distinguishes fixture engineering proof, deployed observations and financial trial conclusions.

- [ ] Add one full local fixture per market: actual adapter contract→source row→eligible context→event-dependent frozen proposal→pre-order registration→later native fill/justified no-fill→partial protection/marks→costed close→exactly-once learning→paired account report. Include source failure, execution outage and restart during feedback; no-fill alone cannot prove fills/learning. A local HTTP source is a correctness fixture, never live market evidence.
- [ ] Run `python -m pytest backend/tests/test_global_alpha_vertical_slice.py -q`; confirm failure before all integrations are connected.
- [ ] Implement verifier identity/lineage checks, SLO observation checks and CI fixtures. Capture source successes/errors and preactivation fingerprints without changing production. Complete self-review against every spec section, then independent whole-branch review using the selected execution method; fix actionable findings and rerun affected checks.
- [ ] Run full backend `python -m pytest -q --tb=short`, `python scripts/check_space_metadata.py`, `python scripts/audit_historical_sources.py --check`, frontend tests/typecheck/build, gateway tests/types/typecheck and disposable migration/restore drills. Require successful outputs; do not quote historical test counts as current verification.
- [ ] Commit `test: verify connected alpha trading and recovery end to end`; push feature branch and create one reviewable integrated PR with real limitations, observed source access and no alpha claim. Attach the PR to this chat. Request explicit approval of its exact head commit for merge/deploy only after CI and review pass.

### Task 16: Release the approved revision and collect genuine prospective evidence

**Files:** Runtime evidence outside Git in task `outputs/BLUM-global-alpha/`; update acceptance doc with public/redacted evidence only in subsequent reviewed commits when needed.

**Interfaces:** Reuse verified release workflow and Task 15 verifier. No merge without explicit human approval of the final PR head; any intervening material change requires renewed approval.

- [ ] Verify approved head SHA, required checks and clean base. Verify Task 13 checkpoint capability, including its first-transition prerequisite, and capture fingerprints before merge; abort on failed freshness/backup/drain.
- [ ] Merge only the approved PR; observe exact main CI/deploy handles to terminal state, then verify backend and CF revision/content hashes, read-only boundaries and restored journal/model/feedback/trial fingerprints. Do not restart a deployment merely because one observation request times out.
- [ ] Activate the versioned reduced-risk paper candidate producer in both markets with predeclared trials and frozen controls. Existing exposure management stays running even if candidate production is rolled back. Check reachable source coverage and real per-decision information influence.
- [ ] Observe session-appropriate actual source→decision→native order→later fill/no-fill→marks/close→matured feedback in both markets. Persist factual times, UIDs, hashes, costs and failures. If eligibility yields no trade, diagnose the real blocked stage; never force an order or fabricate later observations.
- [ ] Keep researching within the predeclared development process while prospective outcomes mature. Evaluate untouched confirmation once and prospective results at their fixed boundary. If net advantage fails, record failure and revise the hypothesis under a new trial; do not call the user's objective complete on deployment alone.
- [ ] For any remaining strict persistence, feed entitlement or measured capacity gap, prepare concrete configuration/cost/scope for the required user decision. Full completion still requires the spec's actual financial, operational and durability evidence, which can extend beyond this coding session.

## Self-review and scope coverage

Spec §§1–3 map to Tasks 9, 14–16; §4 to Tasks 3–4; §5 to Task 5; §6 to Tasks 6–7 and 9; §7 to Tasks 1–2 and 9; §8 to Tasks 8 and 11; §9 to Tasks 10 and 13; §10 to Task 12 and observed Task 16; §11 to Tasks 15–16; §12 to this planning handoff. All five Review Focus failures have explicit owning tests. New shared types are defined above; no later task may invent a second ledger or rename their fields silently.

This plan does not assume SEC/GDELT requests will succeed, that public data supplies consolidated quotes/consensus, that an approved durable database already exists, or that the fitted model will beat the benchmark. Those are measured capability/financial gates; synthetic values cannot satisfy them. Existing implemented adapters are expanded as real sources succeed; the full goal stays open until its evidence is present.

## Execution handoff

**Status:** written specification approved; this implementation plan awaits user review and execution-method selection. No product implementation has started.

Recommended method: **Native execution** in this session, tasks in order, with one independent whole-branch review before the PR. The core tasks share clock, evidence, model and ledger contracts; sequential implementation limits integration churn and avoids a fresh context for every small change. **Subagent-driven execution** remains available if the user prefers fresh implementation/review contexts per task. Neither choice authorizes a merge, paid service or real-money trading.
