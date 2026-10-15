# Blum AI Financial Intelligence Roadmap

> Historical roadmap preserved before the 2.3 presentation update. Earlier goals and current-increment descriptions are not current release status. Use the [current roadmap](../../ROADMAP.md) and [documentation](../README.md).

This roadmap is the execution plan for turning Blum into a credible open-source AI financial intelligence platform. Each phase should ship with working code, API coverage, UI coverage, documentation and explicit limitations.

## Current Increment - Chart Vision Technical Analyst

Shipped in the current architecture:

- FastAPI startup launches a background APScheduler worker.
- Startup pipeline ingests public news first, then historical OHLCV, signals and ETF trends.
- Startup pipeline also scans SEC current filing feeds for IPO and prospectus evidence.
- Public news ingestion combines publisher RSS feeds, thematic Google News RSS queries and asset-specific public web-search RSS queries.
- `/news/live`, `/sentiment/market` and `/pipeline/status` expose live news, market sentiment and worker state.
- Dashboard polls live endpoints every 30 seconds and surfaces news tape, sentiment mix, source/model state and signal readiness.
- Price pipeline remains real-data-only through yfinance, Yahoo Chart API and Stooq; no synthetic OHLCV fallback is allowed.
- Stock Radar is now a first-class research surface with dedicated API, on-demand stock hydration, sector leadership, factor views, research priorities and real market snapshots.
- IPO Radar is now a first-class primary-market research surface using SEC EDGAR current filing feeds for S-1, F-1 and 424B prospectus forms.
- Market Brain is now the top-level orchestration layer combining stock signals, ETF rotation, market sentiment, public news, IPO evidence, forward scenarios, risk alerts and an evidence ledger.
- Market Brain now persists snapshot history, produces a changelog against the prior run, detects price/news/risk contradictions and emits an event graph linking themes, assets, ETFs, IPO candidates and live news.
- IPO Radar now supports official `data.sec.gov` company submissions enrichment by CIK, with optional persistence of additional IPO-related filings.
- Theme Explorer now supports theme detail with article list, source mix, linked assets and sentiment.
- The signal engine now records score version, confidence score and lifecycle state for every signal snapshot.
- `/ai/models/status` exposes configured models, observed model records and fallback policy.
- Blum Financial Brain now adds a finance-domain open model adapter. The configured default is `AdaptLLM/finance-chat`, opt-in for model loading, with deterministic evidence-bound fallback on constrained demo hardware.
- `/market-brain`, `/market-brain/run`, `/ipo-radar` and `/ipo-radar/update` expose the new intelligence layer through documented JSON APIs.
- The Accuracy And Confidence Layer now implements the 15-point audit: multi-provider checks, corporate-action review, point-in-time consistency, per-asset data quality, entity resolution, source credibility, semantic dedupe, event extraction, AI reasoning confidence, contradictions, fundamentals, macro context, ETF confirmation, historical validation and Blum Confidence Score.
- `/accuracy/overview`, `/accuracy/{ticker}`, `/accuracy/run`, `/validation/signals`, `/macro/overview`, `/macro/update`, `/fundamentals/{ticker}` and `/fundamentals/update` expose confidence, macro and fundamental evidence through JSON APIs.
- Startup and background workers now seed accuracy snapshots, repair historical OHLCV gaps, refresh public FRED macro data and refresh SEC companyfacts fundamentals where public CIK mapping is available.
- The Strategic Intelligence Layer now adds an AI Opportunity Radar, Market Narrative AI, Asset Intelligence Report, similar-case backtesting, strategic watchlist, AI Portfolio Scenario and Community & Sentiment Intelligence.
- New APIs include `/intelligence/executive`, `/intelligence/opportunities`, `/intelligence/narrative`, `/intelligence/community`, `/intelligence/watchlist`, `/intelligence/portfolio-scenario`, `/intelligence/reports/{ticker}` and `/intelligence/backtest/{ticker}`.
- The executive dashboard now opens with strategic market triage: Top Opportunities Today, Market Mood, Dominant Narrative, Risk Level, Sector Rotation, Watchlist Alerts, Best AI Reports and Last Backtests.
- Demo fallback policy is explicit: no synthetic prices are generated; if similar-case backtest sample depth is insufficient, statistics are returned as `demonstration_mode` and marked as non-production evidence.
- Blum Financial Brain now has a measurable self-learning layer: signal evaluations, outcomes, model weight versions, learning events, historical similarity cases, confidence adjustments, source reliability and ticker/sector accuracy profiles.
- New brain APIs include `/brain/status`, `/brain/accuracy`, `/brain/learning-events`, `/brain/signal-evaluations`, `/brain/asset-memory/{ticker}`, `/brain/confidence-history/{ticker}`, `/brain/evaluate-signals`, `/brain/recalculate-weights` and `/brain/run-learning-cycle`.
- The realtime worker schedules `financial_brain_learning`, which evaluates matured signal horizons, refreshes accuracy memory, updates adaptive confidence and audits weight recalibration.
- The dashboard now exposes Financial Brain status, learning state, evaluated signals, historical accuracy, 7D/30D success rates, calibration, data quality and model drift warnings.
- Asset Detail now exposes Blum Memory: similar historical setups, confidence evolution, outcome history, confidence-change reasons and what Blum learned.
- Signal Lab now exposes pre-signal confidence, post-evaluation result, learning impact and invalidating conditions for stored horizon evaluations.
- Governance is explicit: no autonomous code modification, no trading, no certainty claims, no direct financial advice and every database-only weight change is reversible.
- Chart Vision Technical Analyst adds a Qwen3-VL primary / InternVL3 fallback architecture for chart image interpretation, with deterministic OHLCV analysis as the always-on backbone.
- New chart tables include `chart_analyses`, `technical_levels`, `technical_signals` and `chart_pattern_memory`.
- New chart APIs include `/chart/analyze-image`, `/chart/analyze-ticker`, `/chart/technical-report/{ticker}`, `/chart/levels/{ticker}`, `/chart/signals/{ticker}` and `/chart/history/{ticker}`.
- The deterministic engine calculates trend structure, moving averages, RSI, MACD, Bollinger Bands, ATR, support/resistance, volume pressure, gaps, consolidation, accumulation/distribution, divergences, breakout probability, pullback quality and risk/reward geometry.
- The hybrid chart layer compares visual observations, OHLCV indicators, sentiment/news, Blum memory and similar chart setups.
- Asset Detail now includes a Chart Analyst module with timeframe selector, key-level overlays, technical snapshot, signal evidence, analyst report and historical similarity.
- A dedicated Chart Analyst page allows fast ticker-level technical analysis without opening an asset detail first.
- Default Space behavior keeps `CHART_VISION_MODE=disabled` for CPU reliability; the UI explicitly reports deterministic analysis active when the VLM is unavailable.

## Phase 0 - Stabilize Docker Space Deployment

Goal: make the Hugging Face Docker Space build and boot reliably.

Deliverables:

- Confirm Docker build succeeds on Hugging Face Spaces.
- Verify FastAPI serves the exported Next.js frontend on port `7860`.
- Verify embedded PostgreSQL starts when `DATABASE_URL` is not provided.
- Verify `/health`, `/docs`, `/assets` and `/dashboard/overview`.
- Add lightweight demo mode if model dependencies exceed Space resources.
- Add clear build/runtime troubleshooting notes.

Exit criteria:

- Public Space loads without manual intervention.
- API docs are reachable.
- Seed asset universe is visible.
- No Gradio remnants remain in runtime metadata.

## Phase 1 - Data Ingestion Reliability

Goal: make prices, assets and news ingestion reliable enough for a serious demo.

Deliverables:

- Harden yfinance provider with retries, partial failures and provider status.
- Keep real-data-only behavior: no synthetic OHLCV fallback in production or demo paths.
- Maintain a public provider chain for prices: yfinance, Yahoo Chart API and Stooq.
- Add incremental OHLCV updates instead of replacing recent rows blindly.
- Improve RSS source health diagnostics.
- Add article text extraction fallback with `newspaper3k` and BeautifulSoup.
- Add stronger duplicate detection across titles, URLs and canonical keys.
- Add source reliability and stale-data scoring.
- Add ingestion audit logs.

Exit criteria:

- `/market/update` reports per-ticker success/failure.
- `/news/update` reports source-level diagnostics.
- Duplicate articles are materially reduced.
- Failed feeds do not break the pipeline.

## Phase 2 - AI Model Productionization

Goal: make AI model usage explicit, measurable and robust under limited compute.

Deliverables:

- Add model availability endpoint.
- Add lazy loading and memory-aware fallback for FinBERT, embeddings and LLM.
- Persist model run metadata for every sentiment and AI insight.
- Add prompt templates with strict evidence-only formatting.
- Add deterministic fallback explanations for low-resource mode.
- Add batch sentiment processing for article updates.
- Add configurable model names through Space variables.

Exit criteria:

- `/ai/explain/{ticker}` returns structured JSON with models used.
- FinBERT is the primary sentiment engine when available.
- VADER is clearly labeled as baseline/fallback.
- No explanation claims facts absent from retrieved evidence.

## Phase 3 - Semantic Intelligence Layer

Goal: turn news embeddings into useful narrative intelligence, not just search.

Deliverables:

- Persist FAISS indexes by namespace or rebuild them efficiently at startup.
- Add semantic cluster snapshots in `ThemeCluster`.
- Link themes to assets, sectors, ETFs and macro drivers.
- Add theme trend over time.
- Add narrative intensity, recurrence and polarization metrics.
- Add `/themes/{label}` detail endpoint.
- Add UI for theme drill-down and related assets.

Exit criteria:

- Theme Explorer shows real cluster metadata.
- Semantic search returns relevant articles with similarity scores.
- Each high-scoring signal can cite related semantic themes.

## Phase 4 - Signal Engine Upgrade

Goal: make the Blum Intelligence Score more defensible and auditable.

Deliverables:

- Split score modules into separate files: momentum, trend, risk, technicals, sentiment, semantics, ETF and anomaly.
- Add score versioning.
- Store full score inputs and normalized factors.
- Add factor weights in config.
- Add confidence score distinct from signal score.
- Add signal lifecycle states: new, confirmed, faded, invalidated.
- Add price/sentiment divergence logic with explicit thresholds.

Exit criteria:

- Every score is reproducible from stored inputs.
- UI can show why each score changed.
- `/signals/{ticker}` includes score version and factor weights.

## Phase 5 - ETF And Sector Intelligence

Goal: make ETF confirmation a first-class intelligence layer.

Deliverables:

- Map stocks to confirming ETFs and sector proxies.
- Add stock/ETF correlation analysis.
- Add ETF rotation rankings by sector and theme.
- Add ETF confirmation score into every asset signal.
- Add sector heatmap and rotation charts.
- Add ETF vs benchmark comparison views.

Exit criteria:

- ETF Radar identifies rotation leaders.
- Asset Detail shows confirming or contradicting ETFs.
- Signal explanations reference ETF confirmation when available.

## Phase 6 - Backtesting And Validation

Goal: validate historical signal behavior without implying prediction or advice.

Deliverables:

- Add walk-forward validation by score threshold and classification.
- Add benchmark-relative forward returns.
- Add false positive analysis by signal type.
- Add max adverse/favorable excursion distributions.
- Add result storage by run configuration.
- Add backtest charts: equity curve, drawdown, forward return distribution.
- Add methodology caveats in UI and API.

Exit criteria:

- Backtest page can compare classifications historically.
- API reports hit rate, average forward return and benchmark-relative behavior.
- Disclaimer is visible on every validation output.

## Phase 7 - Frontend Intelligence UX

Goal: elevate the UI from technical demo to portfolio-grade case study.

Deliverables:

- Add skeleton loading and refined error states on every page.
- Add richer Plotly charts: RSI, MACD, Bollinger Bands, sentiment timeline, score history and correlation heatmap.
- Add sortable/filterable tables.
- Add advanced Signal Lab filters.
- Add exportable signal results.
- Add responsive refinements for tablet/mobile.
- Add real screenshots generated from a running Space build to README.

Exit criteria:

- Dashboard immediately communicates what to watch and why.
- Asset Detail explains price, sentiment, risk, news and ETF confirmation in one flow.
- UI remains dense but readable.

## Phase 8 - Provider Architecture

Goal: make the platform extensible beyond yfinance and RSS.

Deliverables:

- Define provider interfaces for market data, news, filings, transcripts, estimates and ownership.
- Add provider registry.
- Add mock provider for tests.
- Add optional adapters for filings and public company IR pages.
- Prepare connectors for future licensed data sources.

Exit criteria:

- New providers can be added without changing signal code.
- Provider status appears in API and UI.

## Phase 8A - Market Brain Deepening

Goal: evolve the Market Brain from orchestration layer into a persistent analytical operating system.

Deliverables:

- Persist scenario history and compare regime transitions over time.
- Add per-scenario evidence weights and confidence bands.
- Add an event graph linking filings, news, ETFs, sectors and assets.
- Add SEC company-submissions enrichment from `data.sec.gov` for deeper issuer filing history.
- Add exchange calendars, IPO calendars where public and legally accessible, and explicit source status.
- Add private-company watch narratives from public news only, clearly separated from SEC filing evidence.
- Add automatic contradiction detection between price, sentiment, filings and ETF confirmation.
- Add a Market Brain changelog that explains why the regime changed.

Exit criteria:

- The user can open Market Brain and understand what changed since the previous run.
- Every forward scenario has traceable source evidence and confidence drivers.
- IPO/pre-listing watch separates observed filings, public news narratives and unavailable evidence.

## Phase 9 - Testing, Observability And Quality

Goal: make the codebase credible as an open-source engineering project.

Deliverables:

- Add backend unit tests for indicators, scoring, ingestion and API.
- Add frontend component tests where practical.
- Add smoke tests for Docker startup.
- Add structured logging.
- Add error telemetry fields in API responses.
- Add CI-ready commands in README.

Exit criteria:

- Core scoring and ingestion logic are covered by tests.
- Docker smoke test catches startup regressions.
- Contributors can run checks locally.

## Phase 10 - Open Source Polish

Goal: make the repository compelling as a public case study.

Deliverables:

- Add architecture diagram.
- Add screenshots.
- Add contribution guide.
- Add issue templates.
- Add model/data limitation section.
- Add changelog.
- Add clear demo setup instructions for low-resource and full-AI modes.

Exit criteria:

- A reviewer can understand the project, run it, inspect the architecture and contribute without needing private context.

## Working Rule

Every roadmap step should ship as a complete increment:

- backend logic;
- API endpoint or schema update when needed;
- frontend visibility when user-facing;
- documentation update;
- verification command;
- explicit limitation or disclaimer when relevant.

All implementation work must follow [`ENGINEERING_STANDARDS.md`](../engineering/standards.md): no placeholders, no fabricated data, no synthetic market-data fallback, evidence-bound AI, efficient provider calls and explicit verification.
