# Changelog

## 2.3.0 — 2026-10-14

- Register new equity and Forex calls prospectively, preserving source identity, frozen inputs, timestamps and protected-code fingerprints.
- Add a read-only Alpha Desk with separate markets, explicit exclusions, net-cost reconciliation and closure-date confidence intervals.
- Include older closed trades in Alpha and exclude expired unfilled orders; remove duplicate live-forward sample counts.
- Mark unverified historical positive grades as insufficient evidence.
- Stop startup after failed database restores. Periodic embedded backups still do not guarantee zero-loss recovery.
- Verify actual protected backend/script content during automated deployment, in addition to source revision and version.


## v2.2.0 | ASCENT and canonical release

- Added bounded ASCENT calibration source experiments, frozen temporal holdouts, independent gates, persistent lineage and Evolution.
- Added Cloudflare static product delivery and a typed same-origin read-only API gateway to the persistent HF Engine.
- Made GitHub canonical for CI, release documentation and one-way verified deployment; removed automatic HF-to-main imports.
- Added locked web dependencies, gateway regression tests, exact revision readiness and production smoke checks.
- Audited packaged history, public HF data and all 95 persistent reasoning archives. Rejected five incoherent price bars, contradictory/weekend Forex records and unverifiable reasoning snapshots.
- Preserved missing volume, prevented invented daily candles and rejected old external Forex projections/advice. Accepted Forex data yields one causal example, below validation gates.
- Fixed historical test fixture timestamps without weakening production point-in-time rules.
- Preserved paper-only authority; no automatic source/model promotion or paid GPU training.

## v2.1.0 | clean-core

- Tightened the product architecture around the four primary surfaces: Brain, Training Ground, Paper Trading and Alpha.
- Added bounded API routers under `backend/app/api/routers/` for product, runtime, analyst and legacy boundaries.
- Moved the Trader Brain read model into `backend/app/engine/brain/trader_brain.py`.
- Added a cooperative Engine agent layer with 15 evidence-producing boundaries: Market, News, Technical, Fundamental, Pattern, Decision, Risk, Portfolio, Paper Trading, Learning, Research, Memory, Alpha, Validation and Dataset.
- Added `GET /api/engine/agents` for read-only structured agent evidence.
- Kept `backend/app/services/trader_brain.py` as a compatibility shim for legacy imports.
- Updated `main.py` so bounded routers are included before the legacy monolithic router.
- Added route-order and dependency-boundary tests for the clean-core release.
- Updated runtime identity to `2.1.0 | clean-core`.
- Added clean-core migration, deprecation and architecture reports.
- Preserved existing APIs and financial behavior; this release changes ownership and routing boundaries, not trading logic.

## v2.0.0 | project-split

- Introduced the formal BLUM Engine / BLUM Analyst / BLUM Runtime architecture split.
- Added `backend/app/engine` with headless Engine contracts, module catalog, event contract and `BlumEngineFacade`.
- Added `backend/app/runtime` with runtime responsibility contracts and `BlumRuntimeFacade`.
- Added `backend/app/analyst` with the future `Italianhype/Blum-Analyst` dataset contract and export pipeline wrapper.
- Added API endpoints:
  - `GET /api/engine/status`
  - `GET /api/engine/contracts`
  - `GET /api/runtime/status`
  - `GET /api/runtime/contracts`
  - `GET /api/analyst/status`
  - `GET /api/architecture/contracts`
- Updated runtime identity to `2.0.0 | project-split`.
- Kept existing application APIs and financial services backward-compatible.
- Updated the training dataset export script to route through the Analyst dataset boundary.

## v1.1.0 | trader-brain

- Re-centered BLUM around one product objective: becoming progressively better at paper-trading decisions through evidence and learning.
- Added `TraderBrainService`, a read-only master read model for Brain, Training Ground, Paper Trading and Alpha pages.
- Added API endpoints:
  - `GET /api/trader-brain/brain`
  - `GET /api/trader-brain/training-ground`
  - `GET /api/trader-brain/paper-trading`
  - `GET /api/trader-brain/alpha`
- Added runtime snapshot types for Trader Brain, Training Ground, Paper Trading and Alpha summaries.
- Simplified primary navigation to four pages: Brain, Training, Paper Trading and Alpha.
- Replaced legacy `/dashboard`, `/learning` and `/copy-trading` pages with lightweight aliases to the new product pages.
- Kept all backend engines, APIs and historical data intact for compatibility.
- Added architecture review document for the Trader Brain refactor.

## v1.0.0 | alpha-operating-system

- Promoted runtime identity from `market-sniper-engine-v1` to `alpha-operating-system`.
- Added Trading Game readiness diagnostics so the Learning page explains whether evidence is ready, building, stale, insufficient, failed or data-quality blocked.
- Added compact brain command endpoints for Command Center capability status, learning evolution, benchmark truth and copy readiness.
- Added Alpha Readiness, Edge Map and Alpha Gates read-only services.
- Added paper-copy persistent models and paper-copy operating endpoints.
- Updated Learning Trading Game tab to load readiness first and avoid permanent generic loading.
- Updated Copy Trading page to read the paper-copy operating summary.
- Preserved existing Trading Game, Learning Loop, Market Sniper, Decision Intelligence and snapshot-first runtime behavior.
