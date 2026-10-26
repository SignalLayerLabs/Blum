# Blum v3

An independent research and paper trading workspace with separate equity/ETF and Forex sleeves. The application records where observations came from, freezes hypotheses before scoring, accounts for modeled execution and retains failed experiments alongside successful ones. Shipping the application does not establish trading alpha.

## Run locally

Python 3.12 and Node 24 are required. Use a separate database from v2.

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
npm install --prefix web_v3
npm --prefix web_v3 run build
export BLUM_OPERATOR_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
blum serve
```

Open `http://127.0.0.1:7860` and enter the operator token from your private shell environment. The token stays in the browser tab's memory. In a second terminal with the same database configuration, run:

```sh
blum worker --refresh-sources
```

Without a worker, requests remain queued; opening a page never starts research or paper execution. `blum worker --once` processes one available job. Public research history can fail or be restricted by provider terms; failures stay visible and never create synthetic market rows.

## Start with real observations

Request equity or FX daily history from Research, or import an attributed JSON file with `instrument`, `provenance` and `rows`. The instrument declares symbol, market (`equity` or `forex`), quote/base currencies and tick/lot increments. Each row has UTC-aware `timestamp`, `available_at`, coherent positive OHLC, optional volume and optional joint bid/ask. Provenance declares provider, rights, first-seen clock, availability policy and source revision.

The authenticated `/api/v3/schema` endpoint exposes exact request schemas. No example market prices are bundled as a working dataset. Existing accepted v2 equity prices can be independently reviewed and imported with their original dates; old quarantined Forex and reasoning archives are not new training evidence. Intake rejects future provenance/observations and overlapping availability paths against the acceptance clock.

1. Import and inspect accepted/excluded observations.
2. Register a hypothesis, source, trial family, strategy and cost settings. At least 30 accepted bars are required.
3. Let the worker produce development results. The final 20% remains sealed.
4. Inspect NAV, the predeclared benchmark, costs, exclusions and stress scenarios. Opening confirmation consumes that source's partition for new tuning.
5. Open a paper account, submit manual orders or optionally attach a completed frozen experiment. A new account starts a new epoch; historical replay does not become a forward record. Manual orders participate in paper cycles even without a strategy subscription.
6. Refresh the source to observe subsequent paper decisions and fills. Orders require an eligible observation strictly after the decision. No new data means no fabricated execution.

Equity paper begins long/cash; FX permits long/short. The default account envelope is 1x gross exposure, 20% per instrument, 2% daily loss and 10% drawdown limits, rechecked when adding risk at settlement. These are configurable paper research limits, not real-money sizing advice. A different account currency needs an eligible observed FX conversion source. Unlike currencies and incompatible contracts sharing a ticker are never silently merged. Observation capacity is reserved durably across competing orders. Ordinary stops retain activation after partial execution; declared financing accrues through idempotent journal records.

## Evidence limits

`BAR_RESEARCH` supports attributed historical analysis. `MODELED_PAPER` uses actual observations plus declared fill/cost scenarios, including optional declared financing. Price-return comparisons exclude uncertified dividends and actions. The source gate checks weekends; it does not certify every exchange holiday or corporate action. Native dependency compatibility checks are optional, and the declared bar scenario is the explicit default execution backend.

`QUOTE_QUALIFIED_PAPER` is not granted by this implementation: independent prospective quotes, complete financing/convertibility and reconciliation evidence remain required. Historical calibration, a large sample count or a language-model score is not a prospective trading advantage. Reports leave DSR/PBO unavailable when the required independent trial distribution/ranking experiment is absent. Confirmation is consumed by instrument/time interval before evaluation starts, independently of provenance refreshes; adding alternatives updates trial counts and invalidates outdated multiplicity intervals without computing research on GET.

## Production and recovery

Use external PostgreSQL, a private operator token, persistent storage and a verified backup/restore procedure. SQLite is development-only and is rejected in production. Generate unique credentials in a private `.env.v3` and run:

```sh
docker compose --env-file .env.v3 -f compose.v3.yml up --build
```

The database volume is persistent but is not itself a backup. The API is bound to localhost by default; put TLS and an appropriate access boundary in front of a deployed service. Do not expose a bare operator API publicly.

```sh
blum archive /private/backups/blum-v3.json
blum --database postgresql+psycopg://... restore /private/backups/blum-v3.json
blum legacy-import /private/backups/v2-evidence.json
```

Archives are private files, checked by digest and journal reconciliation. Restore requires an empty database and refuses overwrites. Legacy imports enter an isolated read-only evidence namespace; they create no paper accounts or authority.

For cutover: archive and verify v2, rehearse a v3 restore, compare financial journals and access controls, stop the old writer, then enable the new writer and switch read routing. A rollback retains v3 events and must never enable two writers on one account. The PR does not change the existing production Docker/deployment path or restart a live system.

## Verification

```sh
python -m pytest tests_v3 -q
node web_v3/tests/view.test.mjs
npm --prefix web_v3 run typecheck
npm --prefix web_v3 run build
python -m compileall -q blum_v3
```

Tests use mathematical instrument/order cases, not published market-performance claims. The ASGI test loop includes a test-only timer to work in sandboxes that deny event-loop self-pipe socket sends. Dependency installation, browser/network checks and live provider access need the corresponding environment capability. See the PR verification receipt for what actually ran.
