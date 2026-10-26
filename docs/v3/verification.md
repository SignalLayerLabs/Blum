# V3 verification receipt

Recorded 25 October 2026. This receipt distinguishes implementation checks from market-performance and operational claims.

## Executed locally

- `python -m pytest tests_v3 -q --tb=short`: 61 passing tests before the two optional PostgreSQL cases were added. The new cases require a dedicated PostgreSQL database and are expected to skip locally; CI provisions that database.
- `node web_v3/tests/view.test.mjs`: 4 passing client tests covering missing monetary values, market separation, API failures and credential/idempotency transport.
- `python -m compileall -q blum_v3` and `git diff --check`: passed.
- CLI status against a new local database: passed, reporting no invented datasets or accounts.
- Real-source smoke: 120 attributed SPY bars accepted; durable research job succeeded; 96 development observations produced; confirmation stayed closed; a distinct paper account began with its declared opening cash. See `real-source-smoke.json`. This is a functional integration check, not an alpha result.
- Archive/restore checks exercise digest rejection, journal chains, balanced postings, restored cash, nonempty-target refusal and legacy evidence with no financial authority.

The tests were written before their corresponding implementation and regression corrections. Contract fixtures are mathematical scenarios and are not displayed as live market data or published performance.

## Environment limits and CI

The local sandbox denies socket operations, including asyncio self-pipe notifications. ASGI contract tests therefore use a test-only event-loop timer and real in-memory HTTP requests. Production application code does not change its networking behavior to bypass the sandbox.

Npm dependency downloads, the web production build/type check, browser integration, a real PostgreSQL server and a new external FX data download were not available in this executor. The PR's v3 workflow installs the declared dependencies, provisions PostgreSQL, runs financial checks and builds the static web application. Its results must be inspected before declaring the branch ready to merge. No successful web build or broker-grade FX verification is claimed by this local receipt.

The existing v2 suite was also attempted with `PYTHONPATH=backend`; it stopped with 84 collection errors because the isolated v3 environment lacks v2 dependencies including `psycopg2`, `alembic`, `exchange_calendars`, `filelock`, `polars` and `vaderSentiment`. A complete affected-file/error inventory is retained in `legacy-check.json`. This is not a passing legacy regression run. Existing v2 CI remains responsible for its original dependency/runtime checks.

## Deliberate boundaries

- Default execution is the explicitly declared bar scenario; optional native dependency checks do not silently replace it or grant new financial authority.
- Monetary journal postings use eight decimal places in account currency; average cost is derived from stored carrying value, avoiding recurring-decimal imbalance. FX mid-rate conversion is a declared modeled scenario, not an observed bank conversion fill.
- Historical data and old models never become a prospective track record through import. Quote-qualified prospective FX performance remains unestablished.
- No live broker connector, paid source purchase, production cutover, deployment or merge has been performed.
- The v2 deployment remains available; v3 is independently runnable through its CLI and dedicated deployment assets.

## Independent review status — 26 October 2026

The independent review found ten material correctness/recovery issues. See `review-findings.md`. Passing the initial test suite does not override those findings. This branch remains draft and is not merge-ready until regression tests and corrections are verified.
