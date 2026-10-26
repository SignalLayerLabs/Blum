# V3 verification receipt

Recorded 25–26 October 2026. This receipt distinguishes implementation checks from market-performance and operational claims.

## Executed locally

- `python -m pytest tests_v3 -q --tb=short`: 71 passed, two PostgreSQL cases skipped locally. The PostgreSQL cases require a dedicated database and use independent repository/connection pools; CI provisions that database.
- `node web_v3/tests/view.test.mjs`: 6 passing client tests covering missing monetary values, market separation, API failures, credential/idempotency transport, stable retry identity and chart gaps.
- `python -m compileall -q blum_v3` and `git diff --check`: passed.
- CLI status against a new local database: passed, reporting no invented datasets or accounts.
- Real-source smoke: 120 attributed SPY bars accepted; durable research job succeeded; 96 development observations produced; confirmation stayed closed; a distinct paper account began with its declared opening cash. See `real-source-smoke.json`. This is a functional integration check, not an alpha result.
- Archive/restore checks exercise digest rejection, journal chains, balanced postings, restored cash, nonempty-target refusal and legacy evidence with no financial authority.

The tests were written before their corresponding implementation and regression corrections. Contract fixtures are mathematical scenarios and are not displayed as live market data or published performance.

## Environment limits and CI

The local sandbox denies socket operations, including asyncio self-pipe notifications. ASGI contract tests therefore use a test-only event-loop timer and real in-memory HTTP requests. Production application code does not change its networking behavior to bypass the sandbox.

Npm dependency downloads, browser integration, a real PostgreSQL server and a new external FX data download were not available in this executor. The first [v3 CI run](https://github.com/SignalLayerLabs/Blum/actions/runs/40279916072) passed the web tests, TypeScript and production build; the generated dependency lock is now committed. Its financial job stopped before tests because the Docker health command used incompatible quoting; that command is corrected. The updated CI must verify PostgreSQL and the real-source browser workflow before declaring the branch ready to merge. No broker-grade FX verification is claimed.

The existing v2 suite was also attempted locally with `PYTHONPATH=backend`; it stopped with 84 collection errors because the isolated v3 environment lacks v2 dependencies including `psycopg2`, `alembic`, `exchange_calendars`, `filelock`, `polars` and `vaderSentiment`. A complete affected-file/error inventory is retained in `legacy-check.json`. The existing [v2 CI run](https://github.com/SignalLayerLabs/Blum/actions/runs/40279915910) subsequently passed in its declared environment. The local collection failure is retained as historical evidence rather than presented as a passing local run.

## Independent review and correction evidence

The independent review identified ten material financial/recovery issues. All ten were reproduced as failing tests in `test_review_findings.py`; after correction all ten pass alongside the complete local v3 suite. The corrections cover original-request idempotency, manual cycles, instrument contracts, settlement risk, shared capacity, durable stops, paper financing, causal source clocks, consumed confirmation intervals and trial-count invalidation. This is the author's RED→GREEN verification, not a claim that another reviewer approved the changes.

`scripts/verify_v3_browser.py` adds a CI check with the real packaged SPY source, authenticated login, a research job/report/chart, a distinct paper account, stale-reference rejection without cash changes and a narrow-screen layout. Its receipt/screenshots are uploaded by CI; execution is pending until the updated workflow completes.

## Deliberate boundaries

- Default execution is the explicitly declared bar scenario; optional native dependency checks do not silently replace it or grant new financial authority.
- Monetary journal postings use eight decimal places in account currency; average cost is derived from stored carrying value, avoiding recurring-decimal imbalance. FX mid-rate conversion is a declared modeled scenario, not an observed bank conversion fill.
- Historical data and old models never become a prospective track record through import. Quote-qualified prospective FX performance remains unestablished.
- No live broker connector, paid source purchase, production cutover, deployment or merge has been performed.
- The v2 deployment remains available; v3 is independently runnable through its CLI and dedicated deployment assets.
