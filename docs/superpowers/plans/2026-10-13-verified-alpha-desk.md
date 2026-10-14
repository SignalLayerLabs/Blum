# Verified Alpha Desk Implementation Plan

> For agentic workers: use superpowers:executing-plans for native implementation and request an independent whole-branch review before merge.

**Goal:** Release prospectively registered, provenance-aware alpha calls with independent equity and Forex evidence.

**Architecture:** Existing decision engines retain authority. An additive registration table freezes a manifest before outcomes, and a bounded read service verifies it against source accounting. The existing Alpha page renders two market panels and the call journal.

**Tech Stack:** Python/FastAPI, SQLAlchemy/Alembic/PostgreSQL, SQLite integration tests, Next.js/TypeScript, Cloudflare Workers.

**Spec:** `docs/superpowers/specs/2026-10-13-verified-alpha-desk-design.md`

## Global Constraints

- Paper-only; no paid infrastructure or weight-training jobs.
- At most 2,000 registered records per read; explicit window and exclusions.
- Separate equity and Forex evaluations; no retrospective prospective registration.
- Freshness: equities 96 hours, Forex 180 seconds. All sources available no later than decision.
- Positive paired-sample verdict: 100 observations, 30 closure dates, three assets and positive 95% lower bound.
- Confidence remains heuristic; no annualized Sharpe from irregular trades.

## Review Focus

- Repeated registration must preserve the original manifest even if source data later changes.
- An unfilled order or non-finite cost must never become a winning realized trade.
- A new source record with stale/future timestamps must remain visible but unqualified.
- A missing benchmark or inconsistent notional must remain missing, not a zero-return baseline.
- Startup must not continue after a failed logical database restore.

### Task 1: Registration and audited read model

Files: `backend/app/models.py`, migration `0045_alpha_call_registry.py`, `backend/app/services/alpha_desk.py`, `backend/tests/test_alpha_desk.py`.

Interfaces: `AlphaCallRegistry.register(db, source, *, registered_at=None)` returns the immutable registration; `AlphaDeskService.snapshot(db, *, now=None)` returns the two market panels, bounded journal and exclusions. Pure `paired_interval(rows)` returns sample/date/asset coverage and bootstrap bounds.

- [x] Write integration tests for idempotent registration and mutation rejection; observe missing-feature failure.
- [x] Add the model, migration and registry; verify those tests.
- [x] Write tests for stale/future provenance, late registration, absent benchmark, cost mismatch, rejected/unfilled calls and market separation; observe failure.
- [x] Implement bounded source adapters, verified accounting and paired-date interval; verify focused tests.

### Task 2: Capture new decisions and correct existing evidence

Files: paper creator, Forex orchestrator, paper price-context builder, `backend/app/engine/brain/trader_brain.py`, associated integration tests.

- [x] Test new registrations through the actual source engines and an older closed trade hidden by 500 newer non-fills.
- [x] Capture final frozen inputs in the original transaction; include existing provider/availability metadata.
- [x] Query closed trades independently, deduplicate IDs, remove double-counted live rows and mark unverified historical grades.
- [x] Run affected source-engine and Brain tests.

### Task 3: API, two-market product and recovery guard

Files: Alpha router, facade, shared route JSON, Alpha page/components, `scripts/start.sh`, API and restore tests.

- [x] Test read-only Desk GET and executable failed logical restore; observe failure.
- [x] Expose the bounded Desk, render market panels and journal with source/freshness/coverage, and terminate failed restore startup.
- [x] Verify API boundary and actual frontend rendering.

### Task 4: Review and production release

Files: version references, release documentation and deployment verifier.

- [x] Set version 2.3.0 consistently and add Desk smoke verification.
- [ ] Run full backend, frontend and gateway checks; obtain independent review and resolve concrete blockers.
- [ ] Commit, push PR, attach it, merge after required CI and verify exact-revision deployment.
- [ ] Capture public runtime, data/persistence limitations and live screenshots; publish GitHub 2.3.0 release.
