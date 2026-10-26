# Blum v3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver an independently runnable research and paper trading application with one financial journal and separate equity and Forex evaluation.

**Architecture:** A new modular Python application and new web client coexist with the archived v2 application. PostgreSQL serializes financial writes; immutable datasets and frozen experiment configurations support causal replay and prospective paper operation. No legacy financial services are imported.

**Tech Stack:** Python 3.12, Decimal, SQLAlchemy 2, PostgreSQL/psycopg, FastAPI/Pydantic, NumPy/SciPy, optional pinned matching adapter, Next.js/React/TypeScript.

**Spec:** `docs/superpowers/specs/2026-10-23-blum-v3-design.md`

## Global Constraints

- Equity/ETF and Forex accounts, evaluation and training remain separate.
- No real-money broker path, synthetic market fallback, hidden cost assumptions or prospective relabeling.
- All financial mutations require authentication; GET routes only read stored state.
- Decimal money, UTC-aware clocks, immutable IDs, closed versioned contracts and durable idempotency.
- Gross exposure <=1x, instrument <=20%, daily loss stop 2%, drawdown stop 10% by default in paper; configuration changes require a new frozen identity.
- BAR_RESEARCH / MODELED_PAPER / QUOTE_QUALIFIED_PAPER have different eligibility.
- No legacy service imports; preserve v2 evidence and rollback.
- English product/code/documentation, without comparative origin claims; mandatory dependency notices retained.

## Review Focus

- Competing/retried commands must neither overspend nor double-post; crash after acceptance must be reconcilable.
- FX conversion freshness, signs, units and account currencies must not leak into another sleeve.
- Future data and same-bar execution must not affect visible decisions or returns.
- Missing/zero volume, partial fills, stops, expiry and stale marks must not become invented fills or zero risk.
- Unauthorized requests, secret-bearing errors and unavailable data must not create work or expose private state.

---

### Task 1: Accepted observations and durable source registry

**Files:** `pyproject.toml`, `blum_v3/domain.py`, `blum_v3/data.py`, `blum_v3/storage.py`, `tests_v3/test_data.py`.

**Interfaces:** `Bar`, `Instrument`, `SourceManifest`; `accept_dataset(instrument, rows, provenance) -> AcceptedDataset`; `Repository(url)` with immutable dataset/source storage. Input timestamps are timezone-aware; conflicting duplicate keys reject the group.

- [ ] Write acceptance tests: invalid OHLC rejected, exact duplicates deduplicated, conflicts excluded, future/naive clocks rejected, zero versus unknown volume retained, deterministic dataset identity and restart-safe reads.
- [ ] Run `.venv-v3/bin/python -m pytest tests_v3/test_data.py -q` and observe missing-contract failures.
- [ ] Implement typed contracts, source validation, versioned database schema and immutable dataset registry.
- [ ] Rerun tests, confirm all expected cases pass, then commit the data boundary.

### Task 2: Transactional account journal and paper order lifecycle

**Files:** `blum_v3/portfolio.py`, `blum_v3/orders.py`, `tests_v3/test_portfolio.py`.

**Interfaces:** `PortfolioService(repository)` exposes `open_account`, `submit_order`, `cancel_order`, `apply_fill`, `mark`, `snapshot`; repository transaction locks per account and stores journal/event/idempotency state atomically.

- [ ] Write tests for balanced monetary postings, opening cash, reservation, partial fill, cancellation, repeated and conflicting command keys, overspend, short/currency constraints, missing/stale conversion, concurrent submissions and restart recovery.
- [ ] Run task tests RED; implement decimal accounting, frozen risk profile, cash reservations and lifecycle transitions.
- [ ] Run GREEN and commit. Checks include literal cash after fills/fees, not self-derived expected values.

### Task 3: Causal execution and benchmark replay

**Files:** `blum_v3/execution.py`, `blum_v3/strategies.py`, `blum_v3/replay.py`, `blum_v3/native.py`, `tests_v3/test_execution.py`.

**Interfaces:** `ExecutionProfile`, `simulate_order(order, next_bar, profile) -> FillOutcome`; `run_replay(dataset, config) -> ReplayReport`; optional `native_health()` / bounded matching parity check. Reuses Task 1 observations and Task 2 journal contracts.

- [ ] Write tests: next-observation-only fills, partial capacity, no equity volume fill, declared FX capacity, stop/limit gap handling, expiry, fees, prefix invariance and missing FX valuation withheld.
- [ ] Run RED; implement order matching, causal momentum/trend strategy, NAV path and aligned cash/hold/simple-rule benchmark with 1x/2x cost scenarios.
- [ ] Verify engine compatibility explicitly; native unavailable is an explicit state, never a hidden substitute.
- [ ] Run GREEN and commit execution and replay contracts.

### Task 4: Frozen experiments, model challengers and evaluation

**Files:** `blum_v3/research.py`, `blum_v3/evaluation.py`, `blum_v3/learning.py`, `tests_v3/test_research.py`.

**Interfaces:** immutable experiment/trial family records; `purged_splits`, `score_returns`, `paired_interval`, `fit_challenger`; `ResearchService.create/run/confirm`. Consumes datasets/replay and produces stored reports, not account authority.

- [ ] Write tests for train-only fitting, purged label horizons, untouched holdout, complete trial counts, per-observation statistics, grouped uncertainty, benchmark alignment, losing results, concentration and missing inputs.
- [ ] Run RED; implement frozen configs, regularized baseline and nonlinear challenger, outcome qualification, robust scorecards and available/unavailable statistical measures.
- [ ] Run GREEN and commit. No threshold alone certifies alpha.

### Task 5: Authenticated API and recoverable background operations

**Files:** `blum_v3/api.py`, `blum_v3/jobs.py`, `blum_v3/worker.py`, `blum_v3/providers.py`, `blum_v3/cli.py`, `tests_v3/test_api.py`, `tests_v3/test_jobs.py`.

**Interfaces:** `/api/v3` dataset/experiment/account/order/job/operations endpoints; token-protected mutations and private reads by default; `claim_job` leases, retry/cancel and bounded paper stepping. Reads only consume stored projections.

- [ ] Write API/worker tests covering authentication, data import, accepted experiment jobs, retries and expired leases, idempotent steps, no GET-side computation, invalid payloads and redacted errors.
- [ ] Run RED; implement durable jobs and file/public-history adapters, explicit operator commands and paper subscriptions.
- [ ] Run GREEN and commit. Remote provider tests use complete recorded protocol fixtures or opt-in real data, never invented market output.

### Task 6: New research and paper workspaces

**Files:** `web_v3/app`, `web_v3/components`, `web_v3/lib`, `web_v3/tests`, `web_v3/package.json` and lock/config.

**Interfaces:** typed `/api/v3` client, immutable report/account views, operator token in session memory and explicit submissions; static export served by API at the same origin.

- [ ] Write client/view tests for currency formatting, unavailable metrics, API failures, frozen settings and market filters; run RED.
- [ ] Implement research intake/run/compare, paper orders/portfolio, performance charts and operations/job views. Expose data tiers and costs in context, with details on drill-down.
- [ ] Run client tests, TypeScript and production export; inspect narrow/wide pages and a real API research-to-paper flow, then commit.

### Task 7: Independent runtime, archive and release contracts

**Files:** `Dockerfile.v3`, `compose.v3.yml`, `.env.v3.example`, `.github/workflows/v3.yml`, `scripts/v3_archive.py`, `docs/v3`, `README.md`, `tests_v3/test_archive.py`.

**Interfaces:** reproducible v3 image, external PostgreSQL, API+worker commands, immutable archive/restore manifests and explicit writer cutover checklist. Existing Docker/deployment paths remain v2 until an authorized cutover.

- [ ] Write archive/recovery tests and production SQLite rejection check; run RED.
- [ ] Implement run/deploy assets, safe legacy export/import receipt, database restore verification instructions and product-focused docs.
- [ ] Run GREEN, image/build checks where available and commit. No production restart or deployment occurs in the PR.

### Task 8: End-to-end verification, independent review and GitHub PR

**Files:** targeted regression tests and `docs/v3/verification.md`.

**Interfaces:** entire branch against the approved scope; final report distinguishes verified behavior from unavailable operational evidence.

- [ ] Exercise accepted real equity and FX history through intake, jobs, replay, paper orders and report reads; retain source hashes and limits, not restricted raw files.
- [ ] Run all v3 tests/builds and applicable existing suites; record failures by name. Check no unrelated legacy source changes or credential artifacts.
- [ ] Obtain one fresh whole-branch review; reproduce and fix material findings with RED→GREEN tests.
- [ ] Commit verification receipts, push the isolated branch and open a PR against `main` with concrete behavior, checks and limitations. Do not merge or deploy.
