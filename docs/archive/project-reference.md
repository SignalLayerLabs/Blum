# BLUM Project Reference Archive

> Historical record. This document describes an earlier implementation or audit; its counts, configuration and readiness claims are not the current release status. Start with the [documentation index](../README.md) and [current data policy](../research/data-quality.md).

This document preserves the cumulative architecture, release and subsystem
reference that previously occupied the repository homepage. Start with the
concise [root README](../../README.md), then use this archive when tracing a legacy
endpoint, migration or historical design decision.

---
title: Blum AI Financial Intelligence
emoji: 📈
colorFrom: yellow
colorTo: gray
sdk: docker
app_port: 7860
short_description: Open-source AI market intelligence case study.
tags: [financial-analysis, finance, stock-market, ai, fastapi, nextjs, postgresql, sentiment-analysis, time-series, data-visualization]
pinned: false
---

# BLUM v2.0 Project Split

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](../../LICENSE)
[![Hugging Face Space](https://img.shields.io/badge/Hugging%20Face-Space-yellow)](https://huggingface.co/spaces/Italianhype/Blum)
[![BLUM Finance Model](https://img.shields.io/badge/Model-BLUM%20Finance-orange)](https://huggingface.co/Italianhype/Blum)

## Open-Source Project

[`BlumFinancialLab/Blum`](https://github.com/BlumFinancialLab/Blum) is the
canonical public source repository. The application code is licensed under
[Apache-2.0](../../LICENSE); contributions follow [CONTRIBUTING.md](../../CONTRIBUTING.md),
[GOVERNANCE.md](../../GOVERNANCE.md) and [SECURITY.md](../../SECURITY.md).

The public surfaces have distinct responsibilities:

- **GitHub**: source code, issues, pull requests and engineering history.
- **Hugging Face Space**: public, paper-only deployment of the Runtime.
- **Hugging Face Models**: downloadable BLUM Finance model artifacts.
- **Hugging Face Datasets**: versioned reasoning and opt-in community-memory
  datasets with their own dataset cards and provenance constraints.

BLUM sends no usage telemetry by default. Community evidence is contributed
only through an explicit, redacted workflow and is quarantined before review;
downloads never modify active model weights automatically.

## BLUM v2.1 Clean Core Release

BLUM v2.1 tightens the v2.0 split around the four product surfaces that matter to the trader brain:

1. **Brain**: answers whether BLUM is becoming a better trading decision system.
2. **Training Ground**: shows what the Learning Loop is studying and what evidence it has accumulated.
3. **Paper Trading**: shows auditable paper decisions, outcomes and copyability evidence.
4. **Alpha**: shows whether BLUM is beating realistic benchmarks with sufficient evidence.

The release is intentionally a cleanup sprint, not a new financial-feature sprint. The main change is dependency direction:

`Frontend product page -> bounded router -> BLUM Engine facade -> Engine read model -> stored evidence`

New bounded routers live under `backend/app/api/routers/`:

- `brain.py`
- `training.py`
- `paper_trading.py`
- `alpha.py`
- `runtime.py`
- `analyst.py`
- `legacy.py`

The old `backend/app/api/routes.py` is still mounted last as a legacy compatibility router. Do not add new product endpoints there.

The Trader Brain read model was moved from `backend/app/services/trader_brain.py` to `backend/app/engine/brain/trader_brain.py`. The old path remains as a compatibility shim so existing tests, jobs and legacy routes continue to work.

### v2.1 Clean-Core Rules

- Product routes must call `BlumEngineFacade`, not low-level services.
- Runtime routes own application state, snapshots, health and diagnostics, not financial truth.
- Analyst routes expose dataset/model-boundary contracts, not market-data authority.
- Frontend product navigation stays reduced to Brain, Training, Paper Trading and Alpha.
- Legacy endpoints remain available, but new code should move behind bounded routers and facades.

### Agent-Based Engine Structure

BLUM now exposes a lightweight cooperative-agent boundary inside the Engine. Agents are not UI components and do not start jobs. They publish structured evidence that other Engine components can inspect.

Implemented agent boundaries:

- Market Agent
- News Agent
- Technical Agent
- Fundamental Agent
- Pattern Agent
- Decision Agent
- Risk Agent
- Portfolio Agent
- Paper Trading Agent
- Learning Agent
- Research Agent
- Memory Agent
- Alpha Agent
- Validation Agent
- Dataset Agent

Endpoint:

- `GET /api/engine/agents`

Optional query parameters:

- `agent=learning_agent`
- `agent=alpha_agent`
- `limit=8`

Design rule: no empty agent wrappers. Each registered agent owns a real evidence collection responsibility and returns a structured payload with status, evidence type, sample size, confidence and warnings where available.

Additional sprint documents:

- `CLEAN_CORE_REPORT_v2.1.md`
- `MIGRATION_v2.1.md`
- `DEPRECATION_REPORT.md`

---

BLUM is now organized as a Financial Intelligence Operating System with three independent layers:

1. **BLUM Engine**: the headless source of truth. It owns learning, decisions, alpha validation, paper trading, portfolio intelligence, confidence calibration, meta-learning, historical memory and dataset export.
2. **BLUM Analyst**: the future trainable reasoning model hosted as `Italianhype/Blum-Analyst`. It learns how BLUM reasons from curated Engine datasets. It does not own market data and is never the source of truth.
3. **BLUM Runtime**: the application layer. It owns API delivery, scheduling, snapshots, observability and the product interface. It asks the Engine; it never decides.

The operating principle is strict:

`Market -> Engine evidence -> Decision -> Paper outcome -> Learning -> Better Engine decision -> Analyst dataset -> Validated reasoning assistant`

The Runtime is replaceable. The Engine must continue learning if the frontend disappears.

## v2.0 Layer Contracts

New contract endpoints:

- `GET /api/engine/status`
- `GET /api/engine/contracts`
- `GET /api/runtime/status`
- `GET /api/runtime/contracts`
- `GET /api/analyst/status`
- `GET /api/architecture/contracts`

The split is intentionally backward-compatible. Existing APIs remain available, but new development must follow the layer boundary:

| Layer | Owns | Must Not Own |
| --- | --- | --- |
| Engine | financial truth, decisions, learning, alpha evidence, paper outcomes, knowledge, datasets | frontend, pages, visual state, product navigation |
| Analyst | reasoning model dataset contract and future model-training target | market data truth, execution, database authority |
| Runtime | API, workers, scheduler, snapshots, cache, monitoring, pages | intelligence, alpha logic, trade decisions |

## v2.0 Architecture

```mermaid
graph TD
  subgraph Engine["BLUM Engine - Headless Truth Layer"]
    MarketListener
    SignalGenerator
    DecisionEngine
    PaperTrading
    OutcomeEvaluator
    LearningLoop
    KnowledgeGraph
    ConfidenceCalibration
    PortfolioIntelligence
    AlphaValidation
    BrainScore
    DatasetExport
  end

  subgraph Analyst["BLUM Analyst - Future Model Layer"]
    ReasoningDataset
    QualityValidation
    TrainingDataset
    BlumAnalystModel["Italianhype/Blum-Analyst"]
  end

  subgraph Runtime["BLUM Runtime - Application Layer"]
    FastAPI
    Scheduler
    Snapshots
    Monitoring
    NextUI
  end

  MarketListener --> SignalGenerator --> DecisionEngine --> PaperTrading --> OutcomeEvaluator --> LearningLoop
  LearningLoop --> KnowledgeGraph
  LearningLoop --> ConfidenceCalibration
  LearningLoop --> PortfolioIntelligence
  LearningLoop --> AlphaValidation
  AlphaValidation --> BrainScore
  BrainScore --> DatasetExport
  DatasetExport --> ReasoningDataset --> QualityValidation --> TrainingDataset --> BlumAnalystModel
  Runtime -->|contract read| Engine
  Engine -->|curated dataset| Analyst
  Analyst -->|reasoning assistant only| Engine
  NextUI --> FastAPI --> Snapshots
```

## v2.0 Rules

- Engine is the only source of truth.
- Runtime reads contracts and snapshots; it never owns intelligence.
- Analyst learns reasoning only; Engine validates all Analyst output.
- No frontend render may trigger training, recalculation or heavy intelligence.
- No source-code self-modification.
- No real broker execution.
- No alpha claim without benchmark-relative evidence.

## v2.0 Migration Notes

The current codebase still contains legacy services under `backend/app/services` for compatibility. v2.0 introduces the durable split through:

- `backend/app/engine`: Engine contracts and headless facade.
- `backend/app/runtime`: Runtime contracts and application facade.
- `backend/app/analyst`: Analyst dataset/model-boundary contracts.

Future migrations should move legacy service implementations behind these boundaries module by module. New code should not import intelligence services directly from product pages or runtime endpoints unless it is adapting them behind an Engine contract.

---

# BLUM v1.1.0 Trader Brain

BLUM is no longer organized as a collection of financial dashboards. BLUM is an autonomous trader-brain research system whose only product objective is to become progressively better at making paper-trading decisions through evidence, outcomes, learning and self-correction.

The runtime philosophy is:

`Market -> Analysis -> Decision -> Paper Trade -> Outcome -> Learning -> Better Decision -> Repeat`

Everything else is internal infrastructure.

## Product Surface

BLUM now exposes only four primary pages:

1. **Brain**: answers whether BLUM is becoming a better trader.
2. **Training Ground**: shows what the Learning Loop is testing, rejecting and learning.
3. **Paper Trading**: shows conditional paper-only decisions, outcomes and lessons.
4. **Alpha**: answers whether BLUM is beating benchmarks with sufficient evidence.

Legacy pages and diagnostic modules are retained for compatibility and engineering inspection, but they are no longer primary product pages. The frontend is a snapshot-first observer. It must not trigger training, recalculation, broker actions or heavy backend work during page render.

## Master Scores

BLUM v1.1.0 introduces a Trader Brain read model:

- **Brain Score**: decision quality, evidence quality, calibration, learning stability, risk management, alpha readiness, reproducibility, explainability, market coverage, portfolio intelligence and knowledge quality.
- **Decision Quality**: quality of the decision process, not just whether the outcome won.
- **Learning Velocity**: how quickly validated knowledge improves per experiment.
- **Knowledge Quality**: validated lessons and meta-cognition evidence, not raw data volume.
- **Alpha Readiness**: strict benchmark-relative evidence with sample-size and live-evidence gates.

## Architecture

## Architecture

| Layer | Stack |
| --- | --- |
| Frontend | Next.js, React, Plotly, dark financial intelligence UI |
| Backend | FastAPI, Pydantic, APScheduler live services |
| Database | PostgreSQL, SQLAlchemy, Alembic |
| Market data | yfinance, Yahoo Chart API and Stooq provider chain |
| News ingestion | RSS feeds, public web-search RSS, deduplication, ticker linking |
| Filing intelligence | SEC EDGAR current filing feeds for S-1, F-1 and 424B prospectus forms |
| Accuracy layer | multi-provider checks, data quality, source credibility, macro/fundamental context and Blum Confidence Score |
| Strategic intelligence | Opportunity Radar, Market Narrative AI, Asset Intelligence Reports, watchlist, portfolio scenarios and community sentiment |
| Self-learning layer | signal outcome evaluation, accuracy memory, adaptive confidence, model weight versions and historical similarity cases |
| Chart intelligence | Qwen3-VL/InternVL3-ready visual chart analyst plus deterministic OHLCV technical engine |
| AI sentiment | FinBERT primary, VADER baseline |
| Semantic layer | sentence-transformers embeddings, semantic search, theme discovery |
| Reasoning | lightweight Qwen-compatible LLM evidence-only explanation layer |
| Financial Brain | finance-domain open model adapter, default `AdaptLLM/finance-chat` when enabled |
| BLUM Learning Loop | point-in-time historical simulation lab, outcome evaluation, mistake taxonomy, adaptive signal reliability and strategy memory |
| Market Sniper Engine | market regime detection, setup classification, conditional entry/exit planning, no-trade filtering, execution simulation and R-multiple learning |
| Reproducible Trading Game | 100 EUR paper bankroll, position sizing, P/L learning, benchmark comparison, risk of ruin and capital management lessons |
| Reasoning Precision Core | thesis survival, conviction decay, regime-aware reliability, thesis competition, ensemble evolution, benchmark-relative evaluation and training-data quality gates |
| Time-series intelligence | statistical fallback compatible with future Chronos, TimesFM or PatchTST adapters |
| Deployment | Hugging Face Docker Space |

## AI Model Routing

Blum does not use one generic AI model for everything.

- FinBERT: financial sentiment for headlines, article summaries and company-linked news.
- VADER: baseline comparator and fallback.
- sentence-transformers: embeddings for semantic search, narrative clustering, recurring themes and links between assets, sectors and macro trends.
- Qwen-compatible lightweight LLM: structured explanations from retrieved evidence only.
- Blum Financial Brain: finance-domain reasoning adapter for regime interpretation, opportunity hypotheses, risk hypotheses and monitoring plans.
- Chart Vision Technical Analyst: Qwen3-VL primary VLM for visual chart interpretation when configured, InternVL3 fallback for low-confidence or failed primary visual reads.
- Deterministic Technical Analysis Engine: OHLCV-derived trend structure, levels, moving averages, RSI, MACD, Bollinger Bands, ATR, volume, gaps, divergences, volatility compression and risk/reward.
- Statistical time-series module: anomalies, volatility regimes and scenario bands, ready for Chronos, TimesFM or PatchTST integration.
- Rule-based quantitative engine: scoring, ranking, risk controls and classifications.

## Data Workflow

1. Seed the asset universe with stocks, ETFs, sectors, countries, industries and descriptions.
2. Download OHLCV price history from yfinance, Yahoo Chart API and Stooq public daily data, using maximum available history when requested.
3. Store prices in PostgreSQL.
4. Start the live pipeline on application boot.
5. Fetch public RSS news plus dynamic public web-search RSS queries for assets and financial themes.
6. Deduplicate articles.
7. Link articles to tickers and sectors.
8. Run FinBERT sentiment and VADER baseline.
9. Generate embeddings for semantic retrieval.
10. Compute technical indicators and time-series anomalies.
11. Generate signal snapshots with a Blum Intelligence Score.
12. Scan SEC EDGAR current filings for IPO and final prospectus evidence.
13. Score IPO/pre-listing candidates through a separate readiness, probability, narrative and risk model.
14. Build a Market Brain snapshot that combines stocks, ETFs, news, sentiment, IPO evidence, scenarios and risk alerts.
15. Run the 15-point accuracy and confidence audit.
16. Build the Strategic Intelligence dashboard: opportunity radar, narrative, watchlist alerts, portfolio scenario and similar-case validation.
17. Evaluate matured signal outcomes after 1D, 3D, 7D, 14D and 30D.
18. Update signal accuracy memory, source reliability, ticker/sector profiles and adaptive confidence adjustments.
19. Version scoring weights in the database when real matured outcomes justify recalibration.
20. Generate professional chart analysis from deterministic OHLCV evidence and optional Qwen3-VL/InternVL3 visual interpretation.
21. Persist chart analyses, technical levels, technical signals and chart pattern memory.
22. Run BLUM Learning Loop point-in-time simulations on random historical asset/date samples.
23. Hide future prices during prediction generation, then reveal future OHLCV only during outcome evaluation.
24. Classify mistakes, update strategy memory, recalibrate signal reliability and persist reversible model-weight versions.
25. Convert prediction memory into execution-quality R-multiple learning through the Market Sniper Engine.
26. Run the Reproducible Trading Game with 100 EUR paper capital, risk-managed sizing, P/L tracking and benchmark comparison.
27. Run the Reasoning Precision Core: thesis survival, conviction decay, bull/bear/neutral thesis competition, benchmark-relative evaluation, engine voting and training-data quality scoring.
28. Produce AI explanations using only retrieved evidence.

## Live Runtime

When the FastAPI application starts, APScheduler launches a background intelligence worker:

- `startup_pipeline`: news ingestion, historical price collection, signal generation and ETF trend update.
- `news_refresh`: public news refresh every 10 minutes by default.
- `market_refresh`: recent OHLCV refresh and signal regeneration every 45 minutes by default.
- `ipo_refresh`: SEC current filing refresh every 120 minutes by default.
- `data_gap_repair`: historical OHLCV continuity repair every 180 minutes by default.
- `accuracy_audit`: 15-point confidence audit every 240 minutes by default.
- `macro_refresh`: FRED public macro context refresh every 240 minutes by default.
- `fundamentals_refresh`: SEC companyfacts refresh every 720 minutes by default.
- `financial_brain_learning`: self-learning evaluation, memory refresh and confidence calibration every 360 minutes by default.
- `blum_point_in_time_learning_loop`: random historical point-in-time simulation, outcome evaluation and strategy-memory refresh every 360 minutes by default.
- `market_sniper_engine`: conditional setup actionability, entry/exit plans, no-trade decisions, execution simulations and R-multiple reliability memory during each autonomous research cycle.

The dashboard polls live JSON endpoints every 30 seconds and shows worker state, latest public news, sentiment distribution, source/model diagnostics and signal readiness. No generated headlines, generated prices or fabricated sentiment are shown.

Every equity and ETF surface includes an explicit market snapshot when real OHLCV data is available: last price, currency, date, provider, volume and 1D/5D/1M performance. If public providers have not returned usable prices yet, the UI shows a real-data pending state instead of a fabricated value.

## Performance Diagnostics

Blum includes a `/performance` diagnostics page focused on measurement before optimization.

The backend instruments:

- FastAPI request timing for every endpoint through middleware.
- SQLAlchemy query timing for every database statement through engine listeners.
- Application startup phases, including database bootstrap and realtime-service startup.
- APScheduler/background worker durations, including startup pipeline, market refresh, news refresh, learning loop and trading game jobs.
- Dashboard widget timings for the main command-center payload.
- Browser-side dashboard widget probes from the diagnostics page.

The diagnostics API is available at `/performance/diagnostics`. It reports startup duration breakdown, slowest endpoints, slowest SQL queries, slowest dashboard widgets, average and p95 response times, cache hit rate, dashboard snapshot freshness, background task durations, rowcount/scan visibility, initial Learning page load requests, duplicate request counts, heavy POST calls triggered during page load and the top 10 measured bottlenecks.

Rows scanned are reported conservatively: DBAPI cursor timing is exact, but exact scanned rows require `EXPLAIN/ANALYZE`. The diagnostics layer does not run optimizer probes automatically, so it exposes driver rowcount when available and marks unknown scan depth explicitly.

## Performance Architecture

The Learning / Trading Intelligence surface is snapshot-first and read-only by default. It is designed so frontend visualization never interferes with backend learning, training, Trading Game, Reasoning Core, Capital Allocation or Decision Intelligence jobs.

- Overview: loads only `GET /api/learning-intelligence/summary` on first render.
- Trading Game: loads only when the user opens the tab, with paginated ledger defaults and latest 25 trades.
- Deep Diagnostics: all model, thesis, reliability, training-quality, decision, business, portfolio, capital-allocation and performance panels stay behind explicit `Load panel` actions.

The frontend request wrapper deduplicates in-flight GET requests, applies request timeouts, keeps a short in-memory route-session cache and reports Learning-page browser timings, cache hits and dedupe events to Performance Diagnostics. Heavy recalculation POST endpoints are not called automatically during Learning page render. During the initial Learning render window, accidental heavy POST calls are blocked and logged as `blocked_heavy_frontend_recalculation`.

Dashboard snapshots provide stale-but-usable payloads for fast UI surfaces. The snapshot API is `/api/dashboard-snapshots/{snapshot_type}`. The startup status API is `/startup/status`, allowing the UI to distinguish API readiness from background warm-up.

Trading Game runtime surfaces now use dedicated snapshots for the expensive read paths:

- `trading_game_ledger_snapshot` backs `GET /api/trading-game/ledger`.
- `equity_curve_snapshot` backs `GET /api/trading-game/equity/annotated`.
- `dashboard_overview_summary` backs `GET /dashboard/overview`.

Each Trading Game snapshot stores payload size, object counts and phase timings for base query, attribution loading, evidence loading, benchmark loading, quality loading, prediction loading, serialization and JSON generation. If a snapshot is stale, the UI can still show it with a warning instead of recalculating during page render.

The Trading Game extraction audit is documented in `TRADING_GAME_NPLUS1_REPORT.md`.

Blum prioritizes fast visible intelligence first, then progressive deep detail. Existing APIs, tables, Learning Loop logic, Trading Game logic and Decision Intelligence logic remain backward compatible.

## Lightweight Learning Control Room

The Learning page is intentionally reduced to three modes:

- **Overview = fast truth.** One lightweight summary endpoint returns Learning Loop status, latest run timestamp, Trading Power Score, capital cycle, current capital, win rate, expectancy R, benchmark summary, live-vs-historical state, top weakness, latest lesson, Truth Panel, backend training status and last snapshot timestamp.
- **Trading Game = focused evidence.** The tab loads equity curve, cycle progress, latest 25 ledger rows, win/loss/missed-entry summary, benchmark summary and reality-check warnings only after the user opens it.
- **Deep Diagnostics = optional advanced analysis.** Heavy reasoning/model panels never load automatically. Each panel has its own explicit load action and failure state.

Backend learning remains independent through APScheduler/autonomous jobs or explicit manual actions. The frontend observes snapshots and evidence; it does not train, recalculate, repair data or run pipelines during page render. If snapshots are stale while background recalculation is running, the UI shows the last snapshot timestamp and a stale-data warning instead of blocking first paint.

The production scheduler runs professional learning as four independent lanes: Financial Brain learning, Financial Model learning, point-in-time Learning Loop and Trading Game evidence. They share the configured professional cadence but use staggered first-run offsets, independent worker state and failure isolation. Market refresh never invokes these lanes, and snapshot/Brain evidence refreshes remain separate workers. This prevents duplicate computation and avoids the former multi-minute `blum_professional_learning_cycle` mega-job.

The autonomous scheduler lane now persists the next research plan only. Market data, news, model learning, replay, paper trading and snapshots continue through their dedicated workers. The backward-compatible `run_professional_learning_cycle_job` entry point remains available as one bounded point-in-time slice, but it is not the scheduled production orchestrator.

Professional learning configuration:

```bash
export BLUM_PROFESSIONAL_LEARNING_ENABLED=true
export BLUM_PROFESSIONAL_LEARNING_MINUTES=30
export BLUM_PROFESSIONAL_LEARNING_BATCH_SIZE=20
```

The Learning Loop still enforces anti-overfitting budgets. When a requested batch would exceed `LEARNING_MAX_DAILY_RUNS`, BLUM now consumes the remaining daily budget as a smaller partial batch. Only a fully exhausted daily budget is reported as `budget_wait`, not as a silent skipped training failure.

## Deep Diagnostics UX

Deep Diagnostics remains lazy-loaded and human-readable by default. Each advanced panel is opened explicitly with `Load panel`; no model, thesis, reliability, training-quality, decision, business, portfolio, capital-allocation or performance payload is fetched during the initial Learning Overview render.

Diagnostic payloads are rendered as analytical summaries instead of API dumps:

- metric cards expose the headline state, sample size and core scores;
- evidence badges and reliability badges mark weak evidence, stale state and warning conditions;
- Reliability by Regime renders a summary plus engine/signal/setup/regime tables;
- Ensemble Status renders active engine counts, highest/lowest weighted engines, weight distribution and disagreement warnings;
- unknown or newer diagnostic payloads fall back to a clean key-value summary and capped table view;
- raw JSON is hidden behind `Show raw JSON` for developer inspection only.

Weak sample sizes are treated as first-class evidence warnings. Deep Diagnostics is designed to answer what the payload means, whether the evidence is strong or weak, whether BLUM appears to be improving, what warning matters most and what should be checked next.

## Accuracy And Confidence Layer

Blum separates opportunity scoring from evidence quality. The **Blum Intelligence Score** ranks research candidates. The **Blum Confidence Score** measures whether the evidence behind an asset is complete, current and internally consistent.

The 15-point audit covers multi-provider price validation, corporate-action review, point-in-time consistency, per-asset data quality, entity resolution, source credibility, semantic news deduplication, structured event extraction, confidence-aware AI reasoning, contradiction checks, SEC fundamentals where available, FRED macro context, sector/ETF confirmation, historical signal validation and the final confidence label.

Missing public data lowers confidence instead of creating placeholders. No synthetic prices, headlines, filings, fundamentals, macro values or scores are generated.

## Strategic Intelligence Layer

Blum now exposes an **AI Market Intelligence Officer** surface. It answers: what should be monitored today, why it matters, which data confirms it and which risks limit conviction.

Strategic modules:

- **AI Opportunity Radar** ranks equities and ETFs for research attention using opportunity, trend, momentum, sentiment, news and risk scores.
- **Market Narrative AI** summarizes the dominant theme, emerging subthemes, beneficiary sectors, macro risks and contrary signals.
- **Asset Intelligence Report** builds a professional asset brief with overview, technical levels, sentiment, recent news, bullish/bearish scenarios, risks and similar-case validation.
- **Similar-Case Backtesting** uses real stored OHLCV when enough history exists. If sample depth is insufficient, it returns `demonstration_mode` statistics clearly labeled as non-production evidence.
- **Strategic Watchlist** stores monitored assets, score baseline, alert rules and simulated alerts.
- **AI Portfolio Scenario** produces a non-consultative hypothetical allocation with rationale, risk context, monitoring plan and defensive alternative.
- **Community & Sentiment Intelligence** summarizes public-news sentiment themes, discussed assets and possible hype-bubble review flags.

The wording policy explicitly avoids `buy`, `sell`, guaranteed profit or trading instructions. Surfaces use language such as monitor, observe, setup, scenario, risk review and research candidate.

## BLUM Chat

BLUM Chat is the conversational voice of the Blum analytical engine. It is not a generic chatbot and it must not force an answer. It detects the user language, validates the requested entity, retrieves only relevant Blum evidence and speaks in a concise analyst style when data is missing.

Supported languages:

- Italian
- English
- German
- French
- Spanish

The chat pipeline:

1. Detects the user language.
2. Detects intent: technical analysis, fundamental analysis, full analysis, comparison, opportunity search, narrative analysis, reasoning-memory question, private-company request, unknown-asset request, educational question, portfolio question or chatbot debug feedback.
3. Extracts and classifies entities as public stock, ETF, index, crypto, private company, ambiguous company, unknown asset or general market topic.
4. Validates that the resolved ticker matches the requested entity and that OHLCV exists before producing technical analysis.
5. Blocks unsupported analysis instead of substituting unrelated tickers. For example, SpaceX and OpenAI are treated as private companies; BLUM can discuss listed proxies but cannot invent direct RSI, MACD or support/resistance levels.
6. Retrieves Blum context only after validation: ranking, signals, OHLCV snapshots, deterministic technical analysis, SEC companyfacts fundamentals, news, sentiment, narratives, semantic evidence, learning memory and Reasoning Precision Core memory.
7. Selects a response builder by intent instead of using one universal template. Simple missing-data questions get concise answers; validated public assets get structured analysis.
8. Runs a quality gate for language match, entity match, duplicate tickers, data availability, impossible technical analysis, repeated sections and disclaimer discipline.
9. Stores chat sessions and messages in PostgreSQL for future personalization and training-memory workflows.

Response-builder modules include:

- `build_private_company_response()`
- `build_technical_analysis_response()`
- `build_fundamental_analysis_response()`
- `build_full_analysis_response()`
- `build_comparison_response()`
- `build_opportunity_search_response()`
- `build_reasoning_memory_response()`
- `build_error_response()`

Debug diagnostics are hidden by default. When `mode=debug`, `mode=developer` or `mode=chatbot_debug_feedback`, the API can return detected language, detected intent, entity resolution, validation result, duplicate count, data freshness and response template used.

BLUM Chat includes an internal **Market Sniper Mode**. This is a selective research mode, not a trading signal. It identifies informational setup zones, confirmation conditions, invalidation, target zones, risk/reward geometry, confidence and what could go wrong. It never presents an order and never guarantees an outcome.

Open-source model interface:

- `LLMProvider` contract for OpenAI-compatible APIs, local models, Hugging Face Inference, Ollama, vLLM and llama.cpp.
- Deterministic evidence-bound fallback when no external model is configured.
- Future-compatible with Llama, Mistral, Qwen, DeepSeek, Phi, FinGPT and finance models hosted on Hugging Face.

Chat persistence tables:

- `chat_sessions`
- `chat_messages`

Primary endpoints:

- `POST /api/chat`
- `GET /api/chat/context`
- `GET /api/chat/assets/{ticker}`
- `GET /api/chat/signals/{ticker}`
- `GET /api/chat/history`
- Legacy compatible: `POST /chat/financial`

## Self-Learning Financial Brain

Blum now includes a measurable self-learning layer called **Blum Financial Brain**. This is not artificial consciousness and not autonomous trading. It is a controlled financial intelligence memory that checks whether prior signals were useful after real market outcomes arrive.

The learning engine evaluates each signal after:

- 1 trading-day horizon proxy;
- 3-day horizon;
- 7-day horizon;
- 14-day horizon;
- 30-day horizon.

Each evaluation stores ticker, signal type, initial confidence, initial sentiment, initial momentum, news evidence, expected direction, price at signal, price after horizon, max drawdown, max upside, realized return, post-signal volatility, outcome, explanation quality and data quality.

The memory layer persists:

- `signal_evaluations`
- `signal_outcomes`
- `model_weight_versions`
- `learning_events`
- `historical_similarity_cases`
- `confidence_adjustments`
- `source_reliability_scores`
- `ticker_accuracy_profiles`
- `sector_accuracy_profiles`

Adaptive confidence combines historical accuracy, sector and ticker memory, linked source reliability, price/news coherence, volatility and similar past cases. The system can increase or reduce confidence, but every adjustment is logged and explainable.

Weight recalibration is database-only and reversible. Blum can create a new `model_weight_versions` row after enough matured outcomes exist, but it does not modify source code, execute trades or generate deterministic financial recommendations. If there is not enough historical evidence, it explicitly returns `insufficient_sample`.

The UI exposes:

- Dashboard: Financial Brain status, learning state, historical accuracy, 7D/30D success rate, calibration, best/weakest signal types, data quality and drift warning.
- Asset Detail: Blum Memory, historical similarity, confidence evolution, outcome history and what was learned.
- Signal Lab: pre-signal confidence, post-evaluation result, learning impact, weight status, similar past evidence and invalidating conditions.

Governance rules are enforced in product language and API output: no absolute certainty, no direct financial advice, no autonomous trading, no self-modifying code and clear separation between observed data, inference and hypothesis.

## BLUM Learning Loop

BLUM Learning Loop is a separate point-in-time simulation lab. It does not try to create a fake 100% win rate. Its objective is to improve statistical edge, reduce false positives, calibrate confidence and document which reasoning patterns work or fail under different regimes.

Each cycle:

1. Selects a random active stock or ETF with sufficient stored historical OHLCV.
2. Selects a historical analysis date with enough future data available for later evaluation.
3. Builds a point-in-time packet using only data known on or before that date.
4. Generates short, mid and long horizon predictions.
5. Persists the forecast before outcome evaluation.
6. Reveals future OHLCV only to evaluate the forecast.
7. Measures direction correctness, target hit, invalidation hit, max favorable excursion, max adverse excursion, drawdown, realized return, false positives, false negatives, missed opportunities and confidence calibration.
8. Classifies mistakes such as weak volume confirmation, sentiment overestimation, volatility expansion, support/resistance failure, overconfidence or insufficient data.
9. Updates strategy memory and signal-factor reliability.
10. Writes a new model-weight version when enough historical outcomes justify a gradual recalibration.

New persistence tables:

- `learning_runs`
- `historical_predictions`
- `prediction_outcomes`
- `mistake_analysis`
- `signal_performance`
- `strategy_memory`
- `model_versions`
- `learning_metrics`

Configuration:

```bash
export LEARNING_LOOP_ENABLED=true
export LEARNING_BATCH_SIZE=100
export LEARNING_MAX_DAILY_RUNS=1000
export BLUM_PROFESSIONAL_LEARNING_ENABLED=true
export BLUM_PROFESSIONAL_LEARNING_MINUTES=30
export BLUM_PROFESSIONAL_LEARNING_BATCH_SIZE=20
export LEARNING_RANDOM_SEED=
export LEARNING_MIN_HISTORY_YEARS=3
export LEARNING_ASSET_UNIVERSE=stocks,etfs
export LEARNING_EVALUATION_MODE=walk_forward
```

The loop includes anti-overfitting controls:

- temporal point-in-time sampling;
- walk-forward evaluation;
- sample-size guardrails;
- multi-ticker, multi-sector and multi-regime coverage metrics;
- warnings for suspiciously perfect small-sample hit rates;
- confidence updates that are gradual and reversible;
- no self-modifying source code;
- no autonomous trading.

The chatbot reads BLUM Learning Loop memory when answering setup-quality questions such as: “This setup has worked in the past?”, “What is the historical false-positive risk?”, “What has BLUM learned about this pattern?” and “Which factor should reduce confidence?”.

## Market Sniper Engine

The **Market Sniper Engine** upgrades BLUM from “interesting asset” detection to conditional actionability analysis. It does not issue orders and does not claim certainty. Its job is to answer whether a setup is actionable, should wait for confirmation, should be avoided, or should be reduced/invalidated.

Core modules:

- `MarketRegimeService`: classifies risk appetite, trend, volatility, breadth and sector rotation from stored public OHLCV.
- `SetupClassifierService`: maps evidence into setup types such as `momentum_breakout`, `pullback_to_trend`, `trend_continuation`, `volatility_squeeze`, `reversal_from_support` or `avoid_no_edge`.
- `EntryExitEngine`: creates informational entry zones, confirmation triggers, invalidation levels, stop logic, target zones, trailing logic and no-trade conditions.
- `RiskEngine`: scores ATR risk, invalidation distance, volatility, liquidity, gap risk, regime risk and risk/reward.
- `ExecutionSimulatorService`: tests historical execution feasibility using persisted point-in-time predictions and outcomes.
- `NoTradeFilter`: rejects setups with poor risk/reward, wide invalidation, hostile regime, weak volume, extended RSI, low reliability or poor data quality.
- `ExitEngine`: monitors stop/invalidation, partial-profit, trailing, momentum-decay, volume-climax and thesis-invalidation exit signals.

The final **Sniper Score** measures actionability, not generic attractiveness. An asset can have a strong Opportunity Score and still receive a low Sniper Score if the entry is late, invalidation is too wide, the regime is hostile or historical expectancy is weak.

Actionability states:

- `avoid`
- `watch`
- `wait_for_trigger`
- `actionable_if_confirmed`
- `active_setup`
- `exit_or_reduce`

New persistence tables:

- `market_regime_snapshots`
- `setup_library`
- `sniper_scores`
- `trade_plans`
- `trade_plan_outcomes`
- `execution_simulations`
- `r_multiple_metrics`
- `signal_reliability_matrix`
- `no_trade_decisions`
- `exit_signals`
- `portfolio_risk_context`

API endpoints:

- `GET /api/sniper/status`
- `GET /api/sniper/candidates`
- `GET /api/sniper/candidates/{ticker}`
- `POST /api/sniper/evaluate`
- `POST /api/sniper/simulate`
- `GET /api/sniper/setups`
- `GET /api/sniper/regimes`
- `GET /api/sniper/metrics`
- `GET /api/sniper/lessons`

Frontend:

- `/sniper` shows Market Regime, Top Sniper Candidates, Active Setups, Wait For Trigger, Avoid List, Best Risk/Reward, Setup Reliability, Recent Learning Lessons, Entry/Exit Plans, No-Trade Reasons and Execution Simulation Results.

BLUM Chat can now answer questions such as “È entrabile adesso?”, “Meglio aspettare?”, “Dove si invalida il setup?”, “Dove avrebbe senso prendere profitto?” and “Perché BLUM dice wait invece di active setup?” using conditional, risk-aware language.

Guardrails:

- no guaranteed profit;
- no direct financial advice;
- no active setup without confirmation;
- no entry plan without invalidation;
- no target without risk/reward;
- no real-time claim without timestamp;
- R-multiple expectancy is preferred over raw win rate;
- insufficient samples lower reliability.

## Reproducible Trading Game

The **Reproducible Trading Game** turns Sniper and Learning Loop evidence into paper P/L learning. It starts with a virtual 100 EUR bankroll and evaluates whether BLUM's setups are repeatable, risk-managed and benchmark-aware. It is not an execution bot and it never claims guaranteed market outperformance.

Core modules:

- `TradingKnowledgeBase`: structured rules for market structure, technical analysis, professional setups, risk management, performance metrics and behavioral filters.
- `ReproducibleTradePlanEngine`: converts Sniper candidates into reproducible plans with entry condition, confirmation, invalidation, stop, target, holding period, no-trade conditions and data timestamp.
- `CapitalManagementEngine`: applies fixed-fractional, volatility/reproducibility/drawdown-adjusted sizing. Default risk is 1% and capped at 2%.
- `TradingGameSimulator`: consumes point-in-time execution simulations, applies realistic R-multiple P/L, tracks equity, drawdown, benchmark comparison, failure modes and capital lessons.

The simulator explicitly rejects or penalizes low-reproducibility logic:

- no 10-second scalping;
- no tick-level, latency-arbitrage or HFT assumptions;
- no trade without invalidation;
- no trade without position sizing;
- no full-capital risk;
- no benchmark outperformance claim from a small sample.

New persistence tables:

- `trading_games`
- `trading_game_trades`
- `trading_game_equity_curve`
- `trading_game_failures`
- `capital_management_lessons`

API endpoints:

- `GET /api/trading-game/status`
- `POST /api/trading-game/run`
- `POST /api/trading-game/reset`
- `GET /api/trading-game/equity`
- `GET /api/trading-game/trades`
- `GET /api/trading-game/failures`
- `GET /api/trading-game/lessons`
- `GET /api/trading-game/benchmark`
- `GET /api/trading-game/reproducibility`

Configuration:

- `TRADING_MIN_TIMEFRAME=4h`
- `TRADING_DEFAULT_TIMEFRAME=daily`
- `TRADING_ALLOW_MICROSCALPING=false`
- `TRADING_REQUIRE_REPRODUCIBLE_SETUP=true`
- `TRADING_GAME_INITIAL_CAPITAL=100`
- `TRADING_GAME_DEFAULT_RISK_PERCENT=1`
- `TRADING_GAME_MAX_RISK_PERCENT=2`
- `TRADING_GAME_BENCHMARK=SPY`

The Learning Loop dashboard shows current game capital, equity curve, benchmark equity curve, recent trade decisions, expectancy, profit factor, drawdown, risk of ruin, reproducibility score and capital management lessons.

## Blum Financial Model

Blum now includes the foundation for a proprietary reasoning model called **Blum Financial Model**. This is not another chatbot layer and it does not train automatically inside the Space. It is the infrastructure that preserves, evaluates and exports Blum's accumulated financial reasoning so a future **Blum Analyst** model can be trained from Blum's own thesis history.

The model layer captures every persisted asset thesis into a proprietary knowledge record with:

- market context: timestamp, market regime, volatility regime, sector context, macro placeholders, breadth context and risk sentiment;
- asset context: ticker, sector, industry, price action, volume profile, technical indicators, sentiment indicators and news indicators;
- Blum reasoning: executive thesis, why now, supporting evidence, contradicting evidence, risks, invalidation conditions, narrative analysis, confidence and conviction score;
- prediction horizons: 1D, 3D, 7D, 14D and 30D outcome-evaluation slots;
- thesis quality: reasoning depth, consistency, contradiction handling, confidence calibration, historical alignment, narrative quality and explainability quality;
- self critique: analyst view, skeptic view, historical view and balanced final view;
- training sample: JSON-ready input/output and chat messages for future supervised fine-tuning or preference learning.

New persistence tables include:

- `blum_knowledge_records`
- `blum_thesis_outcomes`
- `blum_reasoning_memory`
- `blum_training_examples`
- `blum_thesis_quality_scores`
- `blum_self_critiques`
- `blum_narrative_memory`
- `blum_regime_memory`
- `thesis_lifecycle_events`
- `model_reliability_matrix`
- `confidence_calibration_buckets`
- `meta_learning_events`
- `thesis_survival_metrics`
- `thesis_conviction_history`
- `model_reliability_by_regime`
- `thesis_competitions`
- `competing_theses`
- `engine_votes`
- `ensemble_weight_versions`
- `training_example_quality_scores`
- `benchmark_relative_outcomes`
- `blum_knowledge_graph_nodes`
- `blum_knowledge_graph_edges`
- `blum_dataset_exports`
- `blum_model_training_jobs`

The reasoning model APIs are backend-only:

- `GET /model/status`
- `POST /model/capture/{ticker}`
- `POST /model/capture-all`
- `POST /model/evaluate-outcomes`
- `POST /model/run-learning-cycle`
- `GET /model/knowledge`
- `GET /model/knowledge/{record_id}`
- `GET /model/memory/search?q=...`
- `POST /model/dataset/build`
- `POST /model/training/export`
- `GET /model/training/manifest`
- `POST /model/training/jobs`
- `GET /model/quality`
- `GET /model/self-critique/{record_id}`
- `GET /model/narratives`
- `GET /model/regimes`
- `GET /model/graph`
- `GET /model/reasoning-core/status`
- `POST /model/reasoning-core/run`
- `GET /model/reasoning-core/latest`
- `GET /model/reasoning-core/diagnostics`
- `GET /model/thesis-lifecycle`
- `GET /model/reliability-matrix`
- `GET /model/confidence-calibration`
- `GET /model/meta-learning`
- `GET /model/thesis-survival`
- `GET /model/thesis-survival/{thesis_id}`
- `POST /model/thesis-survival/evaluate`
- `GET /model/conviction-decay`
- `GET /model/conviction-decay/{thesis_id}`
- `POST /model/conviction-decay/evaluate`
- `GET /model/reliability-by-regime`
- `GET /model/reliability-by-regime/{engine_name}`
- `POST /model/reliability-by-regime/recalculate`
- `GET /model/thesis-competitions`
- `GET /model/thesis-competitions/{ticker}`
- `POST /model/thesis-competitions/run/{ticker}`
- `POST /model/thesis-competitions/evaluate`
- `GET /model/ensemble/status`
- `POST /model/ensemble/vote/{ticker}`
- `POST /model/ensemble/recalculate`
- `GET /model/ensemble/weights`
- `GET /model/ensemble/disagreements`
- `GET /model/benchmark-relative`
- `GET /model/benchmark-relative/{ticker}`
- `POST /model/benchmark-relative/evaluate`
- `GET /model/training/quality`
- `POST /model/training/quality/evaluate`
- `POST /model/training/export/high-quality`

Training export uses JSONL and targets future Hugging Face training workflows for Qwen, Llama or Mistral with LoRA, full fine-tuning, DPO or preference learning. The Space only creates dataset and job-plan records; it does not launch fine-tuning automatically.

The objective is not to predict stock prices. The objective is to learn how Blum reasons: explain, contextualize, compare, critique, calibrate confidence and improve future thesis quality.

The autonomous Blum Financial Model cycle is server-side and evidence-bound. When `BLUM_ENABLE_LEARNING_LOOP=true`, it runs on startup, during market refresh and on its own interval controlled by `BLUM_MODEL_CYCLE_MINUTES` and `BLUM_MODEL_CYCLE_LIMIT`. Each cycle captures recent signal reasoning, evaluates matured thesis outcomes, refreshes training examples and logs a `blum_model_autonomous_cycle` learning event.

The **Reasoning Precision Core** extends this cycle from static score memory to thesis memory:

- every thesis receives a lifecycle status: `ACTIVE`, `STRENGTHENING`, `WEAKENING`, `INVALIDATED`, `COMPLETED` or `EXPIRED`;
- thesis survival measures how long a thesis remains valid, when it weakens, when it expires and whether it beats the relevant benchmark;
- conviction decay updates confidence gradually from fresh evidence, stale evidence, contradictions, price confirmation, sector/regime confirmation and benchmark-relative behavior;
- reliability is measured by engine, signal type, setup type, thesis type, sector, industry, asset class, horizon, market regime, volatility regime and breadth regime;
- thesis competition stores bull, bear and neutral alternatives so BLUM is not forced into one opinion when uncertainty is high;
- ensemble evolution records each internal engine vote, penalizes disagreement and stores reversible weight versions only when sample size is sufficient;
- benchmark-relative intelligence checks whether a thesis beats SPY, QQQ, VTI or sector proxies instead of merely moving with the market;
- training dataset quality gates decide which examples are good enough for future SFT, preference learning or DPO export;
- meta-learning events explain repeated reasoning errors, overconfidence, underconfidence and engine reliability changes.

It updates database memory only; it does not self-modify source code, it does not execute trades and it does not claim guaranteed market outperformance.

## Autonomous Research Engine

Blum now runs a server-side autonomous research cycle by default. Manual refresh buttons are diagnostics; normal operation does not require user input. The default cycle is controlled by:

```bash
export BLUM_ENABLE_AUTONOMOUS_ENGINE=true
export BLUM_AUTONOMOUS_CYCLE_MINUTES=20
export BLUM_AUTONOMOUS_REPAIR_LIMIT=20
```

The autonomous cycle executes in this strict order:

1. Refresh Hugging Face financial dataset catalog.
2. Update macro context.
3. Update SEC companyfacts fundamentals.
4. Repair historical market-memory gaps for missing, short or stale OHLCV assets.
5. Run an incremental price refresh. Deep `max` backfill is used only when the stored memory is not sufficiently hydrated.
6. Ingest public news and sentiment.
7. Generate signal snapshots.
8. Update ETF intelligence.
9. Update IPO radar.
10. Run accuracy audit.
11. Run Blum Financial Model reasoning, outcome learning and Reasoning Precision Core orchestration.
12. Run BLUM Learning Loop point-in-time historical simulation batch.
13. Persist embedded PostgreSQL backup when configured.

Every cycle creates an `autonomous_engine_runs` row and a `learning_events` audit entry. `/pipeline/status` exposes the current stage, completed stages and compact stage diagnostics while the worker is running. Deep historical backfill is processed in batches so startup remains observable and the engine keeps cycling. If a provider fails, the run is marked `degraded` with the failing stage and traceback, rather than hiding the issue.

New APIs:

- `GET /autonomous/status`
- `POST /autonomous/run`
- `GET /datasets/sources`
- `POST /datasets/refresh`

## Hugging Face Dataset Intelligence

Blum catalogs real Hugging Face datasets for historical prices, SEC filings, earnings transcripts, finance reasoning and benchmark evidence. The catalog is metadata-first and incremental by design: large corpora are validated through Dataset Viewer/parquet metadata before any targeted ingestion is attempted.

Initial curated sources include:

- `defeatbeta/yahoo-finance-data`
- `paperswithbacktest/Stocks-Daily-Price`
- `TeraflopAI/SEC-EDGAR`
- `kurry/sp500_earnings_transcripts`
- `glopardo/sp500-earnings-transcripts`
- `paperswithbacktest/Stocks-Quarterly-Earnings`
- `c3po-ai/edgar-corpus`
- `PatronusAI/financebench`
- `BUPT-Reasoning-Lab/FinanceReasoning`
- `jlh-ibm/earnings_call`
- `younginpiniti/us-stocks-daily-all`
- `sfd-anonymous/edgar-forecast-benchmark`

The catalog is stored in `external_dataset_sources` with dataset id, source domain, license, priority, ingestion mode, Dataset Viewer status, parquet metadata and usage policy. Blum does not copy massive datasets blindly and does not fabricate missing evidence.

## Chart Vision Technical Analyst

Blum includes a dedicated technical chart intelligence module. It is designed to read financial chart images when a vision model is configured, but it never relies only on visual interpretation.

The module combines:

- **Qwen3-VL** as the primary configurable vision-language model for chart screenshots.
- **InternVL3** as a fallback model for low-confidence or failed visual interpretation.
- A deterministic OHLCV technical analysis engine for objective indicator and level calculation.
- Blum Financial Brain memory for historical context and similarity.
- Existing sentiment/news context for confirmation or contradiction checks.

The deterministic engine calculates:

- trend direction;
- higher highs, higher lows, lower highs and lower lows;
- support and resistance zones;
- EMA 9/21/50/200 and SMA 20/50/200;
- RSI, MACD, Bollinger Bands and ATR;
- relative volume and volume pressure;
- volatility regime and compression;
- gaps, consolidation zones and pullback quality;
- accumulation/distribution bias;
- price/RSI and price/MACD divergences;
- breakout probability;
- trend strength;
- risk/reward geometry.

The hybrid layer outputs trend summary, key levels, bullish/bearish/neutral evidence, confirmation signals, contradiction signals, invalidation level, risk zone, opportunity zone, confidence, scenarios, what to watch next and historical chart similarity.

Model serving is configurable:

```bash
export CHART_VISION_MODEL=Qwen/Qwen3-VL
export CHART_VISION_FALLBACK_MODEL=OpenGVLab/InternVL3
export CHART_VISION_MODE=disabled   # local | remote | disabled
export CHART_VISION_MIN_CONFIDENCE=0.70
export CHART_VISION_REMOTE_URL=
export CHART_VISION_REMOTE_TOKEN=
```

Default Docker demo behavior is `CHART_VISION_MODE=disabled`, so the app remains reliable on CPU Spaces. The UI displays: `Vision model unavailable, deterministic analysis active`. Use `remote` mode for a production VLM endpoint.

## Market Brain

The Market Brain is Blum's high-level reasoning orchestrator. It is not a single model that invents an answer. It combines:

- latest stock signal snapshots;
- ETF rotation and thematic confirmation;
- market-wide FinBERT/VADER sentiment records;
- live public news intensity;
- stored OHLCV-derived trend and risk metrics;
- SEC IPO/pre-listing filing evidence;
- explicit evidence gaps and source diagnostics.

The output includes current regime, forward scenarios, opportunity stack, risk alerts, model stack and an evidence ledger. It is a research-priority engine, not a recommendation system.

The Brain also persists snapshot history and compares each run with the previous one. The change log highlights regime changes, score movement, top stock/ETF/IPO leader changes and risk-count shifts. A contradiction engine flags price/sentiment conflicts, overbought high-risk setups and market-wide narrative conflicts. An event graph links themes, stocks, ETFs, IPO candidates and live news into a compact intelligence map.

### Blum Financial Brain

Blum includes a dedicated financial-domain AI brain adapter. The default configured open model is `AdaptLLM/finance-chat`, a finance-domain chat model. It is opt-in through `BLUM_ENABLE_FINANCIAL_BRAIN_MODEL=true` because 7B finance models can exceed free CPU Space resources. When the model is disabled or cannot load, Blum serves the same JSON contract through a deterministic evidence engine, clearly labeled as fallback.

The Financial Brain produces market thesis, regime interpretation, opportunity hypotheses, risk hypotheses, contradictions to resolve, monitoring plan, confidence and limitations. It receives only the Market Brain evidence packet and is instructed not to invent prices, target prices, listing dates, valuations, forecasts or recommendations.

## IPO And Pre-Listing Intelligence

IPO Radar scans SEC EDGAR current filing feeds for `S-1`, `S-1/A`, `F-1`, `F-1/A`, `424B1` and `424B4` forms. It also surfaces stored public news narratives that mention IPOs, listings, prospectuses, market debuts and SPACs.

For deeper issuer history, the backend can query the official SEC company submissions API at `data.sec.gov`. The IPO Radar UI exposes SEC filing history and can persist additional IPO-related filings into PostgreSQL.

The IPO score separates:

- readiness score;
- listing probability proxy;
- narrative heat;
- filing quality;
- valuation or risk-term pressure;
- final opportunity score.

No listing date, valuation, ticker or private-company claim is fabricated. Empty radar sections mean no public evidence has been stored yet.

## Signal Methodology

The signal engine combines:

- momentum: 1D, 5D, 1M, 3M, 6M, YTD and relative strength;
- trend quality: SMA/EMA structure, slopes, ADX, persistence and drawdown;
- volatility and risk: historical volatility, ATR, beta, downside volatility, gaps and volume spikes;
- technical indicators: RSI, MACD, Bollinger Bands, support and resistance;
- news and sentiment: FinBERT sentiment, VADER baseline, 7D/30D sentiment trend and news intensity;
- semantic themes: recurring narratives such as AI, rates, earnings, guidance, geopolitics, M&A, regulation, supply chain and innovation;
- ETF intelligence: ETF momentum, thematic confirmation and rotation;
- anomaly detection: price, volume, news and narrative divergences.

The final score is called the **Blum Intelligence Score**. It produces explainable classifications:

- Strong Watch
- Watch
- Neutral
- Avoid / Too Risky
- Contrarian Setup
- Narrative Breakout
- Technical Breakout
- Sentiment Divergence

## API Endpoints

FastAPI exposes clean JSON endpoints:

- `GET /assets`
- `GET /assets/{ticker}`
- `POST /market/update`
- `POST /news/update`
- `GET /news/live`
- `GET /sentiment/market`
- `GET /data/coverage`
- `POST /data/repair`
- `GET /accuracy/overview`
- `POST /accuracy/run`
- `GET /accuracy/{ticker}`
- `GET /validation/signals`
- `GET /macro/overview`
- `POST /macro/update`
- `GET /fundamentals/{ticker}`
- `POST /fundamentals/update`
- `GET /intelligence/executive`
- `GET /intelligence/opportunities`
- `GET /intelligence/narrative`
- `GET /intelligence/community`
- `GET /intelligence/watchlist`
- `POST /intelligence/watchlist/{ticker}`
- `GET /intelligence/portfolio-scenario`
- `GET /intelligence/reports/{ticker}`
- `GET /intelligence/backtest/{ticker}`
- `POST /api/chat`
- `GET /api/chat/context`
- `GET /api/chat/assets/{ticker}`
- `GET /api/chat/signals/{ticker}`
- `GET /api/chat/history`
- `POST /chat/financial`
- `GET /brain/status`
- `GET /brain/accuracy`
- `GET /brain/learning-events`
- `GET /brain/signal-evaluations`
- `GET /brain/asset-memory/{ticker}`
- `GET /brain/confidence-history/{ticker}`
- `POST /brain/evaluate-signals`
- `POST /brain/recalculate-weights`
- `POST /brain/run-learning-cycle`
- `GET /learning/status`
- `GET /learning/dashboard`
- `GET /learning/runs`
- `GET /learning/predictions`
- `GET /learning/memory`
- `POST /learning/run-cycle`
- `POST /chart/analyze-image`
- `POST /chart/analyze-ticker`
- `GET /chart/technical-report/{ticker}`
- `GET /chart/levels/{ticker}`
- `GET /chart/signals/{ticker}`
- `GET /chart/history/{ticker}`
- `POST /signals/run`
- `POST /pipeline/run`
- `GET /pipeline/status`
- `GET /signals/top`
- `GET /signals/{ticker}`
- `GET /sentiment/{ticker}`
- `POST /semantic-search`
- `GET /related-news?ticker=NVDA`
- `GET /themes`
- `GET /themes/{label}`
- `GET /etf-trends`
- `GET /stock-radar`
- `POST /stock-radar/update`
- `GET /ipo-radar`
- `POST /ipo-radar/update`
- `GET /ipo-radar/sec-submissions/{cik}`
- `GET /market-brain`
- `GET /market-brain/latest`
- `GET /market-brain/history`
- `POST /market-brain/run`
- `GET /ai/models/status`
- `GET /dashboard/overview`
- `GET /ai/explain/{ticker}`
- `POST /backtest/{ticker}`

Interactive API docs are available at `/docs`.

`GET /ai/explain/{ticker}` is auto-hydrating: if no signal snapshot exists yet, the backend attempts on-demand real public price hydration, ticker-specific news ingestion and signal generation before returning an explanation. If verified data is still insufficient, it returns an `Insufficient Evidence` explanation with provider diagnostics instead of fabricating a signal.

## Frontend Pages

- Case Study Home
- Intelligence Dashboard
- Executive Dashboard
- AI Opportunity Radar
- Market Narrative AI
- Asset Intelligence Report
- AI Portfolio Scenario
- Market Brain
- BLUM Learning Loop
- Chart Analyst
- BLUM Chat
- Asset Detail
- Blum Memory
- Stock Radar
- ETF Radar
- IPO Radar
- Narratives / Theme Explorer (`/narratives`, backed by `/themes` API)
- Signal Lab
- Backtest
- Methodology

The UI is intentionally dense, dark and technical: Bloomberg-style information density, Linear/Vercel-style cleanliness, TradingView-style chart clarity and OpenBB-style open-source posture.

Signal surfaces include score version, confidence score and lifecycle state (`new`, `confirmed`, `strengthening`, `active`, `faded`, `invalidated`) so the platform can show whether a signal is emerging, durable or deteriorating.

## Trading Game Transparency

BLUM now treats the Reproducible Trading Game as an auditable evidence system, not a black-box P/L counter. Every simulated paper trade can be traced through:

- Trade Ledger: ticker, setup, entry, exit, position size, stop/invalidation, targets, P/L, R-multiple, benchmark excess and outcome label.
- Trade Replay: entry decision, exit decision, thesis link, risk plan, same-period benchmark comparison and learning outcome.
- Trade Attribution: Technical Engine, Sniper Engine, Regime Engine, Learning Loop, Capital Manager and Benchmark Evaluator contributions.
- Trade Quality Score: process-quality scoring separated from raw P/L, so lucky profitable trades can be penalized and rule-following losses can still be useful evidence.
- Annotated Equity Curve: entry/exit, wins, losses, stop hits, missed entries, bankruptcy and other learning events are attached to the capital curve.
- Learning Evidence Log: each trade can create structured observations for setup confirmation, setup failure, entry timing, exit logic, no-trade filters and benchmark-relative learning.
- Reality Check: sample size, profit concentration, sector/regime coverage, fractional-share simplification, slippage/spread assumptions and possible overfitting warnings.
- P/L Breakdown: total and per-trade P/L, fees/slippage/spread estimates, P/L by setup, ticker, sector, regime, engine contribution and holding-period bucket.

Simulated P/L is research evidence only. Strong numbers are not considered robust until sample size, regime coverage, benchmark fairness and execution realism pass the reality checks. BLUM does not claim guaranteed profit or provide financial advice.

## Trading Intelligence Lab

BLUM now extends the Learning Loop and Reproducible Trading Game into a measurable Trading Intelligence Lab. The goal is not to show an impressive capital number in isolation; the goal is to make every simulated decision auditable and to measure whether BLUM is becoming better at selecting setups, timing entries, managing exits, controlling risk and comparing results against benchmarks.

Core additions:

- Advanced Trade Ledger: filterable ledger analytics by trade, ticker, setup, outcome, market regime, benchmark, R-multiple, P/L, trade quality, reproducibility score and capital cycle.
- Capital Cycles: each paper cycle starts at 100 EUR and targets 10,000 EUR by default. When the target is reached, the cycle is closed, counted and a new 100 EUR cycle starts. When capital reaches zero, the bankruptcy cycle is closed, counted and restarted.
- Cycle Metrics: target cycles completed, bankrupt cycles, active cycle progress, average days to target, average days to bankruptcy, target hit rate, survival rate, best cycle and worst cycle.
- Outcome Metrics: win rate, loss rate, missed-entry rate, target-hit rate, stop-hit rate, invalidation hits, no-trade correct rate, no-trade missed-opportunity rate, average R, median R, expectancy R and profit factor.
- Decision Quality Metrics: entry timing, exit timing, sizing quality, risk/reward quality, benchmark-relative quality, reproducibility quality, process quality and trade quality.
- Intelligence Growth Metrics: rolling 30/100-trade measurements, improvement by setup, regime and sector, repeated-mistake reduction and benchmark-relative progress.
- Live Forward Paper Mode: current-market decisions are timestamp-frozen, tracked as paper-only positions and evaluated only after future market refreshes. It uses the same risk management, ledger, benchmark comparison and quality evaluation as historical simulation.
- Historical vs Live Comparison: historical simulation is useful backtest-like evidence, while live forward paper trading is stronger evidence once enough timestamp-frozen trades close. The UI shows both with sample-size warnings.
- Statistical Reality Warnings: panels warn on too few trades, too few live trades, too few tickers, too few regimes, profit concentration, historical-only evidence, unrealistic capital growth, high profit factor with low sample size, missing slippage/spread context and benchmark gaps.
- Chat Integration: BLUM Chat can answer questions about the best/worst cycle, 100 EUR to 10,000 EUR completions, bankrupt cycles, missed entries, stop hits, target hits, live-vs-historical results and whether the evidence is statistically reliable. It must use actual ledger and metrics data; if data is missing it must say so.

Important constraints:

- Historical simulation is not enough to prove edge.
- Live forward paper trading is stronger evidence, but only after enough closed trades.
- Capital cycles prevent infinite, unrealistic equity growth from hiding risk.
- Every trade remains paper research with entry, exit, thesis, outcome, benchmark comparison, attribution, quality score and learning evidence.
- Every performance number must be read with sample-size and realism context.
- BLUM does not execute real trades, does not provide financial advice and does not claim guaranteed outperformance.

## Learning Intelligence Benchmark Dashboard

BLUM now adds a Learning Intelligence Control Room on top of the Trading Intelligence Lab. This release is deliberately truth-first: BLUM does not assume it is good, does not hide benchmark underperformance and does not treat historical simulation as proof of alpha.

The dashboard measures whether BLUM is becoming a better trading-reasoning system through:

- Trading Power Score: a strict 0-100 composite score with classification from `Not usable` to `Exceptional, requires external validation`. It combines benchmark-relative evidence, expectancy, drawdown control, win/loss quality, missed-entry penalty, risk management, capital-cycle behavior, live paper validation, regime robustness, setup diversity, statistical confidence, reproducibility, decision quality and learning velocity.
- Official Benchmark Comparison: BLUM is compared against SPY, QQQ, VTI, DIA, IWM, sector ETFs and simple practical baselines such as cash/no-trade, random-selection proxy, random-entry/random-exit proxy, momentum proxy, moving-average proxy and sector-rotation proxy.
- Learning Progress: rolling 30/100/250-action views for win rate, expectancy, benchmark excess, missed entries, stop hits, target hits and overall intelligence growth.
- Strength and Weakness Map: setup, regime, sector and engine-level weakness detection, including high missed-entry rate, excessive stop hits, benchmark underperformance, low sample size and weak evidence coverage.
- Self-Improvement Action Engine: measured weaknesses are converted into auditable improvement proposals such as increasing Learning Loop sampling, testing pullback-retest entries, penalizing late breakout entries or comparing against passive benchmarks before confidence increases.
- Live vs Historical Validation: historical results are marked as backtest-like evidence; live forward paper results are treated as stronger evidence only when enough timestamp-frozen trades close.
- Truth Panel: a short, blunt explanation of whether BLUM is currently outperforming or underperforming relevant benchmarks, whether the sample is reliable and what the system should study next.

Important safeguards:

- Every performance claim is benchmarked, sample-size aware and statistically cautious.
- If BLUM underperforms SPY, QQQ, VTI or a simple baseline, the dashboard says so.
- If live forward evidence is immature, the dashboard says `not reliable yet`.
- Self-improvement actions are logged, reversible and do not modify source code.
- Low-risk actions can be queued for testing, but risky changes require review.
- BLUM does not claim guaranteed outperformance, does not provide financial advice and does not execute real trades.

API surface:

- `GET /api/learning-intelligence/dashboard`
- `GET /api/learning-intelligence/trading-power`
- `POST /api/learning-intelligence/trading-power/recalculate`
- `GET /api/learning-intelligence/benchmarks`
- `GET /api/learning-intelligence/benchmarks/{benchmark_name}`
- `POST /api/learning-intelligence/benchmarks/recalculate`
- `GET /api/learning-intelligence/progress`
- `GET /api/learning-intelligence/progress/rolling`
- `GET /api/learning-intelligence/progress/by-setup`
- `GET /api/learning-intelligence/progress/by-regime`
- `GET /api/learning-intelligence/weakness-map`
- `GET /api/learning-intelligence/weakness-map/by-setup`
- `GET /api/learning-intelligence/weakness-map/by-regime`
- `GET /api/learning-intelligence/weakness-map/by-sector`
- `GET /api/learning-intelligence/weakness-map/by-engine`
- `GET /api/learning-intelligence/self-improvement/actions`
- `POST /api/learning-intelligence/self-improvement/generate`
- `POST /api/learning-intelligence/self-improvement/apply/{action_id}`
- `POST /api/learning-intelligence/self-improvement/evaluate/{action_id}`

## Local Setup

```bash
cd hf-blum-mvp
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm --prefix frontend install
npm --prefix frontend run build
export DATABASE_URL=postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/blum
PYTHONPATH=backend uvicorn app.main:app --host 0.0.0.0 --port 7860
```

Optional full Financial Brain model loading:

```bash
export BLUM_ENABLE_FINANCIAL_BRAIN_MODEL=true
export BLUM_FINANCIAL_BRAIN_MODEL=AdaptLLM/finance-chat
```

Keep this disabled on constrained CPU demos unless enough memory is available. The deterministic Financial Brain fallback remains evidence-bound and transparent.

Optional self-learning cadence:

```bash
export BLUM_ENABLE_LEARNING_LOOP=true
export BLUM_LEARNING_LOOP_MINUTES=360
export LEARNING_BATCH_SIZE=100
export LEARNING_MAX_DAILY_RUNS=1000
export LEARNING_MIN_HISTORY_YEARS=3
export LEARNING_ASSET_UNIVERSE=stocks,etfs
export LEARNING_EVALUATION_MODE=walk_forward
export BLUM_MODEL_CYCLE_MINUTES=5
export BLUM_MODEL_CYCLE_LIMIT=120
export BLUM_ENABLE_HF_DATASET_CATALOG=true
export BLUM_HF_DATASET_REFRESH_HOURS=24
export TRADING_GAME_INITIAL_CAPITAL=100
export TRADING_GAME_TARGET_CAPITAL=10000
export TRADING_GAME_RESET_ON_TARGET=true
export TRADING_GAME_RESET_ON_BANKRUPTCY=true
export TRADING_GAME_MAX_CYCLE_DAYS=365
export LIVE_TRADING_GAME_ENABLED=true
export LIVE_TRADING_GAME_INITIAL_CAPITAL=100
export LIVE_TRADING_GAME_TARGET_CAPITAL=10000
export LIVE_TRADING_GAME_MAX_OPEN_POSITIONS=5
export LIVE_TRADING_GAME_MAX_RISK_PER_TRADE=1
export LIVE_TRADING_GAME_REQUIRE_ACTIONABLE_SETUP=true
export LIVE_TRADING_GAME_ALLOW_FRACTIONAL_SHARES=true
export LIVE_TRADING_GAME_BENCHMARK=SPY
export SELF_IMPROVEMENT_ENABLED=true
export SELF_IMPROVEMENT_AUTO_APPLY=false
export SELF_IMPROVEMENT_AUTO_APPLY_LOW_RISK=true
export SELF_IMPROVEMENT_MIN_SAMPLE_SIZE=50
export SELF_IMPROVEMENT_REQUIRE_BENCHMARK_CHECK=true
export SELF_IMPROVEMENT_REQUIRE_LIVE_CONFIRMATION=false
export SELF_IMPROVEMENT_ROLLBACK_ENABLED=true
```

The learning loops only update database memory, confidence adjustments, proprietary reasoning examples and reversible scoring-weight versions.

## Decision Superiority, Business Quality and Portfolio Intelligence

This release upgrades BLUM from trade-outcome analysis to decision-quality analysis.

The core question is no longer only:

> Did this trade work?

The new question is:

> Was this the best available decision at that moment, considering alternative opportunities, business quality, portfolio context and benchmark alternatives?

### Decision Superiority Engine

`DecisionSuperiorityEngine` evaluates every comparable BLUM decision against the opportunity set available in the same decision window.

It measures:

- Opportunity Recall: how many future outperformers BLUM identified before they outperformed.
- Opportunity Precision: how many selected opportunities became outperformers.
- Alpha Capture Rate: how much available alpha BLUM captured versus what was available.
- Ranking Accuracy: whether BLUM ranked the best future performers near the top.
- Missed Opportunities: candidates BLUM ignored that later performed better.
- Best Decisions and Worst Decisions: auditable evidence, not narrative claims.

Main API:

- `GET /api/decision-intelligence/dashboard`
- `GET /api/decision-intelligence/superiority`
- `POST /api/decision-intelligence/superiority/recalculate`
- `GET /api/decision-intelligence/universe-snapshots`
- `POST /api/decision-intelligence/universe-snapshots/recalculate`
- `GET /api/decision-intelligence/missed-opportunities`

### Business Quality Engine

`BusinessQualityEngine` scores company quality from stored fundamental evidence. If fundamentals are missing, BLUM explicitly marks the company as `insufficient_fundamental_evidence` and penalizes the score.

It evaluates:

- growth quality;
- profitability quality;
- cash-flow quality;
- balance-sheet quality;
- capital-allocation quality;
- moat quality;
- management-quality proxies;
- fundamental alpha patterns from historical outcomes.

Main API:

- `GET /api/business-quality/dashboard`
- `GET /api/business-quality/scores`
- `POST /api/business-quality/recalculate`

### Portfolio Intelligence Engine

`PortfolioIntelligenceEngine` measures whether a position improves the simulated portfolio, not only whether the position made money.

It evaluates:

- return contribution;
- risk contribution;
- drawdown contribution;
- alpha contribution;
- portfolio concentration;
- correlation between positions;
- position-sizing outcomes;
- portfolio quality score.

Main API:

- `GET /api/portfolio-intelligence/dashboard`
- `GET /api/portfolio-intelligence/quality`
- `POST /api/portfolio-intelligence/recalculate`

### Adaptive Capital Allocation Intelligence

`AdaptiveCapitalAllocationEngine` upgrades BLUM from trade evaluation to capital allocation research. It does not create trades and does not rewrite the Trading Game. It studies the evidence already produced by Trading Game, Decision Superiority, Business Quality and Portfolio Intelligence to answer:

- how much simulated capital each opportunity deserved;
- when capital should stay in cash;
- whether capital was underallocated to winners or overallocated to losers;
- which sizing logic produced better risk-adjusted alpha;
- how positions interact through correlation, sector concentration and combined exposure;
- whether the portfolio could have been allocated better than it was.

The layer persists an auditable history in:

- `capital_allocation_snapshots`
- `opportunity_capital_scores`
- `cash_allocation_decisions`
- `allocation_efficiency_audits`
- `sizing_logic_allocations`
- `capital_interaction_risks`

Main API:

- `GET /api/capital-allocation/dashboard`
- `GET /api/capital-allocation/plan`
- `GET /api/capital-allocation/opportunities`
- `GET /api/capital-allocation/cash-policy`
- `GET /api/capital-allocation/efficiency`
- `GET /api/capital-allocation/sizing`
- `GET /api/capital-allocation/interactions`
- `POST /api/capital-allocation/recalculate`

The engine treats cash as an active research decision. Cash reserve rises when sample size is weak, expectancy is negative, benchmark excess is poor, drawdown is elevated or stop-hit rates are high. Capital weights are capped when evidence is thin, drawdown is high or position interaction risk is elevated.

### Alpha Loss & Recovery Engine

`Alpha Loss & Recovery Engine` upgrades BLUM from measuring underperformance to explaining why alpha was lost and what should be tested next. It is evidence-bound and snapshot-safe: dashboards read stored rows or `alpha_recovery_summary`; heavy attribution runs only through explicit backend recalculation or scheduled jobs.

It adds:

- `BenchmarkMethodologyValidator`: blocks learning from invalid benchmark comparisons, including missing periods, inconsistent horizons, weak sample size, return mismatches and proxy-only baselines.
- `AlphaLossAttributionEngine`: decomposes validated benchmark underperformance into measurable causes such as missed entry, wrong asset selection, premature exit, poor exit, excessive cash and weak capital allocation.
- `MissedWinnersEngine`: stores assets BLUM ignored or underweighted that later outperformed, including rank, rejection reason, confidence, blocked rule and suggested learning action.
- `AlphaRecoveryActionEngine`: converts repeated alpha-loss evidence into reversible recovery experiments such as pullback-retest replay, ranking threshold tests, allocation replay and exit-logic audits.
- `alpha_loss_replay`: a Learning Loop trigger that prioritizes missed winners and rejected outperformers while preserving the existing point-in-time and anti-overfitting guardrails.
- Truth Layer: exposes when evidence is insufficient, benchmark methodology is invalid, performance is not statistically reliable or recovery conclusions are not yet justified.

Persisted evidence:

- `benchmark_methodology_validations`
- `alpha_loss_attributions`
- `missed_winners`
- `alpha_recovery_actions`
- dashboard snapshot type `alpha_recovery_summary`

Main API:

- `GET /api/alpha-recovery/dashboard`
- `POST /api/alpha-recovery/recalculate`
- `GET /api/alpha-recovery/methodology`
- `POST /api/alpha-recovery/methodology/validate`
- `GET /api/alpha-recovery/attribution`
- `POST /api/alpha-recovery/attribution/calculate`
- `GET /api/alpha-recovery/missed-winners`
- `POST /api/alpha-recovery/missed-winners/detect`
- `GET /api/alpha-recovery/actions`
- `POST /api/alpha-recovery/actions/generate`
- `GET /api/alpha-recovery/replay-priorities`

What it does:

- explains benchmark-relative alpha loss using stored trade, benchmark, allocation and decision evidence;
- identifies missed or rejected winners for targeted replay;
- generates testable recovery actions with expected impact, affected module, prior metric and rollback capability;
- routes alpha-loss evidence back into Learning Loop sampling;
- gives BLUM Chat evidence for questions such as why BLUM is losing against SPY/QQQ or which opportunities were missed.

What it does not do:

- it does not claim BLUM found alpha;
- it does not guarantee recovery or benchmark outperformance;
- it does not fabricate missed winners without stored future outcome evidence;
- it does not learn from invalid benchmark methodology;
- it does not self-modify source code or apply irreversible rule changes.

### Meta-Cognition Engine

`Meta-Cognition Engine` teaches BLUM how to evaluate its own reasoning process. It does not ask only whether a trade worked; it asks which reasoning factor created value, which factor destroyed value, which factor was noisy and where the Learning Loop should focus next.

It adds:

- `LearningImportanceEngine`: measures factor-level contribution across technicals, momentum, volume, sentiment, narrative, fundamentals, business quality, regime, decision superiority, sniper score, entry/exit timing, no-trade filters, capital allocation, position sizing, portfolio interaction, alpha recovery and confidence calibration.
- `CapitalPreservationAlphaEngine`: measures value created by not acting, separating avoided losses from missed gains and scoring no-trade quality.
- `MetaCognitionEngine`: evaluates whether learning events, recovery actions and rule experiments improved future metrics or degraded them.
- `LearningFocusOptimizer`: converts factor importance, alpha-loss evidence, missed winners, failed actions and no-trade mistakes into active Learning Loop sampling priorities.
- `ReasoningNoiseDetector`: flags weak evidence, tiny-sample effects, overvalued factors, unstable factor contribution and false-confidence risk.

Persisted evidence:

- `learning_factor_importance`
- `meta_cognition_events`
- `capital_preservation_alpha`
- `learning_focus_priorities`
- `reasoning_noise_flags`
- dashboard snapshot type `meta_cognition_summary`

Main API:

- `GET /api/meta-cognition/summary`
- `GET /api/meta-cognition/factor-importance`
- `POST /api/meta-cognition/factor-importance/recalculate`
- `GET /api/meta-cognition/events`
- `POST /api/meta-cognition/evaluate`
- `GET /api/meta-cognition/capital-preservation`
- `POST /api/meta-cognition/capital-preservation/evaluate`
- `GET /api/meta-cognition/learning-focus`
- `POST /api/meta-cognition/learning-focus/generate`
- `GET /api/meta-cognition/noise`
- `POST /api/meta-cognition/noise/detect`
- `POST /api/meta-cognition/recalculate`

Learning Loop integration remains blended and anti-overfit:

- 40% broad random coverage;
- 30% alpha-loss replay;
- 20% factor-importance focus;
- 10% no-trade / capital-preservation replay.

The ratios are configurable through `LEARNING_RANDOM_SAMPLE_RATIO`, `LEARNING_ALPHA_LOSS_SAMPLE_RATIO`, `LEARNING_FACTOR_FOCUS_SAMPLE_RATIO` and `LEARNING_CAPITAL_PRESERVATION_SAMPLE_RATIO`.

Frontend integration is snapshot-first. The Learning Overview shows a lightweight `What BLUM Should Learn Next` panel from `GET /api/learning-intelligence/summary`. Full factor tables, capital preservation evidence, focus priorities, noise flags and meta-cognition events are loaded only inside Deep Diagnostics through an explicit `Load panel` action.

BLUM Chat can answer questions such as:

- which factor is creating or destroying alpha;
- which module is noisy;
- what BLUM should study next;
- which no-trade rule preserved the most capital;
- whether learning actions improved or degraded outcomes.

What it does not do:

- it does not self-modify source code;
- it does not apply risky factor-weight changes automatically;
- it does not claim a factor creates alpha without benchmark-relative evidence;
- it does not optimize from invalid benchmark methodology;
- it does not hide insufficient sample size, noise or overfitting risk.

### Guardrails

- No decision-superiority claim is valid with insufficient comparable samples.
- BLUM must say when a better opportunity existed.
- Business quality is not inferred as fact when fundamentals are missing.
- Portfolio quality is penalized when P/L is concentrated in too few positions.
- Capital allocation must remain evidence-bound: no opportunity receives larger simulated capital without sample-size, benchmark, sizing and interaction context.
- Cash allocation is valid output when the evidence does not justify deployment.
- Allocation efficiency is ex-post research evidence, not a future promise.
- Alpha recovery actions must remain reversible and must not be treated as proof of future alpha.
- Chat responses use stored dashboard evidence only. If the evidence is missing, BLUM must answer `Insufficient evidence`.

## BLUM v1.0 Runtime Architecture

BLUM v1.0 separates financial reasoning from runtime orchestration. The goal is to keep the backend autonomous and measurable while the frontend remains light and snapshot-driven.

The detailed runtime dependency graph, worker architecture, event flow, knowledge flow, snapshot flow and migration notes are maintained in `RUNTIME_ARCHITECTURE.md`.

### Central Brain Runtime

`CentralBrainRuntime` is a read-only operational view. It does not score assets, train models or run financial computation. It composes:

- latest module events;
- stale and failed modules;
- missing or stale dashboard snapshots;
- background job state;
- learning health;
- current measured bottleneck from performance diagnostics;
- system readiness.

Endpoint:

- `GET /brain/runtime-state`

### Independent Worker Runtime

`RuntimeWorkerCoordinator` turns the APScheduler runtime into named, independently observable workers. It does not replace APScheduler and it does not compute financial logic. Its job is to prevent duplicate runs of the same worker while allowing unrelated workers to proceed independently.

Before this extraction, one process-wide `running` flag could defer every scheduled task behind any long-running job. The runtime now blocks only duplicate executions of the same worker and exposes:

- `running_jobs`;
- `running_count`;
- `worker_registry`;
- per-worker queue name;
- per-worker max item/time budgets;
- duplicate-worker deferrals as `module_deferred` events.

Core registered workers:

- `runtime_snapshot_watchdog`
- `snapshot_producer`
- `autonomous_research_engine`
- `news_refresh`
- `market_refresh`
- `data_gap_repair`
- `accuracy_audit`
- `macro_refresh`
- `fundamentals_refresh`
- `ipo_refresh`
- `financial_brain_learning`
- `blum_financial_model_cycle`
- `blum_point_in_time_learning_loop`
- `blum_trading_game`
- `blum_professional_learning_cycle`

This keeps the Central Brain as an orchestrator/observer. Learning, Trading Game, Market Data, Snapshot Producer and research workers remain owners of their own state and evidence.

### Event Bus

`BrainEventBus` persists module lifecycle events in `brain_runtime_events`.

Event examples:

- `module_started`
- `module_completed`
- `module_failed`
- `learning_cycle_completed`
- `trading_game_updated`
- `benchmark_updated`
- `alpha_recovery_updated`
- `meta_cognition_updated`
- `capital_allocation_updated`
- `snapshot_requested`
- `snapshot_refreshed`
- `snapshot_failed`
- `module_deferred`
- `worker_recovered`

Events are evidence for observability, not triggers for hidden trading or hidden model changes.

### Background Job State

`BackgroundJobStateService` stores resumable job state in `background_job_state`.

Tracked fields include:

- job and stage name;
- status;
- cursor;
- items processed;
- item budget;
- duration;
- last start/completion;
- next run timestamp;
- error message;
- enabled flag.

Default runtime budgets:

- `BLUM_AUTONOMOUS_MAX_SECONDS_PER_JOB=120`
- `BLUM_AUTONOMOUS_MAX_ITEMS_PER_JOB=50`
- `BLUM_MARKET_REFRESH_MAX_ITEMS_PER_JOB=10`
- `BLUM_MARKET_PROVIDER_VALIDATION_MAX_ITEMS=2`
- `BLUM_DB_RESTORE_JOBS=4`

These budgets make long jobs visible and constrain new runtime work. Existing financial engines are not rewritten by this layer.

On process startup, stale `running` rows left by a previous container are marked `interrupted`, and previous-process `failed` rows are archived as `previous_failed`. This prevents a restarted Space from reporting dead workers or old failures as current-process health failures while keeping the audit trail in `brain_runtime_events`.

### Snapshot Producer

`SnapshotProducerService` writes UI-ready snapshots from stored evidence only. It does not trigger benchmark recalculation, training, Learning Loop runs or Trading Game runs.

Tracked snapshot types:

- `learning_summary`
- `trading_game_summary`
- `benchmark_summary`
- `intelligence_growth_summary`
- `truth_panel_summary`
- `decision_intelligence_summary`
- `business_quality_summary`
- `portfolio_intelligence_summary`
- `capital_allocation_summary`
- `alpha_recovery_summary`
- `meta_cognition_summary`
- `dashboard_overview_summary`
- `trading_game_ledger_snapshot`
- `equity_curve_snapshot`

Snapshots support:

- partial payloads;
- timestamps;
- stale state;
- warnings;
- `missing_sections_json`;
- fast read paths.

Endpoint:

- `POST /snapshots/produce`

This endpoint is explicit and should not be called by page render.

The lightweight startup batch prioritizes first-screen readiness. `learning_summary` and `dashboard_overview_summary` are generated first, then the same background warm-up continues through every critical snapshot type, including Trading Game ledger/equity snapshots and deeper intelligence summaries. This keeps the API/UI responsive while preventing the Central Brain Runtime from staying degraded after deploy because critical snapshots were never produced.

### Snapshot Watchdog

`SnapshotWatchdogService` checks missing snapshots, stale snapshots, failed producers and long-running jobs.

Endpoint:

- `GET /snapshots/health`

The `GET` endpoint is read-only. Background workers can request lightweight snapshot rebuilds without blocking page render.

### Startup Light Mode

Startup now separates API readiness from heavy research.

Configuration:

- `BLUM_STARTUP_RUN_FULL_AUTONOMOUS=false`
- `BLUM_ENABLE_LIVE_STARTUP=true`

With the default configuration, startup warms runtime snapshots and scheduler state instead of running the full autonomous engine immediately. Heavy work remains scheduled/background-first.

Historical OHLCV startup seeding is resilient. If the packaged cache is missing, unresolved as a Git LFS pointer or not a valid gzip payload, BLUM reports `missing`, `git_lfs_pointer` or `invalid`, creates no synthetic prices and continues booting so live/background hydration can repair the data gap.

### Read-Only Frontend Rule

The Learning page remains:

1. Overview
2. Trading Game
3. Deep Diagnostics

Overview calls only:

- `GET /api/learning-intelligence/summary`

Deep runtime diagnostics are lazy-loaded through explicit buttons:

- Central Brain Runtime;
- Snapshot Watchdog;
- Learning Health;
- Performance Diagnostics;
- Deep model panels.

The frontend request wrapper blocks heavy Learning-page POST calls during initial render and treats `/snapshots/produce` as heavy.

### GET Endpoint Hygiene

GET endpoints must not write data. The runtime now records a warning when a `GET` request contains `persist=true`:

- event: `GET_ENDPOINT_SIDE_EFFECT_DETECTED`
- header: `X-BLUM-GET-SIDE-EFFECT-RISK: true`

This preserves backward compatibility while making side-effect risk visible.

### Learning Health

Endpoint:

- `GET /learning/health`

Returns:

- `healthy`, `degraded`, `stale` or `failed`;
- worker alive state;
- current job and stage;
- last successful learning cycle;
- last successful trading game cycle;
- last successful alpha recovery cycle;
- last successful meta-cognition cycle;
- learning events in the last 24 hours;
- errors in the last 24 hours;
- missing snapshots;
- stale modules.

### Performance Targets

Targets for future measurement:

- `/api/learning-intelligence/summary` p95 under 300ms;
- `/dashboard/overview` p95 under 500ms;
- `/api/trading-game/ledger?limit=25` p95 under 800ms;
- no default background job over 120 seconds;
- cache hit rate over 50%;
- Learning Overview max 2 initial requests;
- no heavy POST during page load;
- no missing critical snapshots after warm-up.

Do not claim these targets are met unless `/performance/diagnostics` confirms them in the running environment.

## Docker

```bash
cd hf-blum-mvp
docker build -t blum-ai-financial-intelligence .
docker run --rm -p 7860:7860 blum-ai-financial-intelligence
```

If `DATABASE_URL` is not set, the Docker demo starts an embedded PostgreSQL instance inside the container. For production-like use, provide an external PostgreSQL database:

```bash
docker run --rm -p 7860:7860 \
  -e DATABASE_URL=postgresql+psycopg2://user:password@host:5432/blum \
  blum-ai-financial-intelligence
```

For Hugging Face Docker demos without an external database, the startup script writes periodic embedded PostgreSQL backups to `/data/blum/embedded_postgres_blum.sql` and restores them on startup when the public schema is empty. This protects the learning memory only when Hugging Face persistent storage is enabled for the `/data` mount. The strict no-reset configuration is still an external `DATABASE_URL`.

## Hugging Face Spaces Deployment

Use a Docker Space. Upload the repository with:

- `Dockerfile`
- `requirements.txt`
- `backend/`
- `frontend/`
- `scripts/`
- `package.json`
- `README.md`

## Deployment Visibility

The UI exposes `/system/status` in the sidebar and dashboard. If the GUI looks unchanged after an upload, check:

- `app_version` must show the latest deployed version.
- `feature_set` must show the expected feature bundle.
- `persistence.mode` must be `external_postgres` for strict no-reset durability, or `embedded_postgres` with a populated backup file plus persistent `/data` storage for demo durability.
- `GET /autonomous/status` shows the latest autonomous run, stage diagnostics, readiness score and dataset catalog status.
- `POST /system/persistence/backup` exists as an administrative recovery endpoint; normal operation persists through the autonomous worker.
- `Financial Brain` shows `fallback mode` unless `BLUM_ENABLE_FINANCIAL_BRAIN_MODEL=true`.
- Hugging Face serves the previous Docker image until the new build finishes successfully.
- Existing Market Brain snapshots are refreshed by the autonomous worker after deployment.
- Hard-refresh the browser if old static Next.js chunks are cached.

The Space serves the FastAPI backend and the exported Next.js frontend on port `7860`.

## Backtesting and Validation

Backtesting is included for research validation only. It reports historical hit rate, average forward return over 5D/20D/60D, max adverse excursion, max favorable excursion and false positives. It does not predict or guarantee future returns.

## BLUM v1.0.0 Alpha Operating System

`v1.0.0 | alpha-operating-system` turns BLUM's existing learning, trading, benchmark and meta-cognition layers into a clearer operating layer:

- `GET /brain/command-summary` returns the compact Command Center brain state.
- `GET /brain/capabilities` exposes capability rows for trading, decision, business, portfolio, alpha and paper-copy readiness.
- `GET /brain/evolution` reads stored Trading Power snapshots.
- `GET /trading-game/readiness` explains why Trading Game evidence is ready, building, stale, insufficient, failed or data-quality blocked.
- `GET /alpha/readiness`, `GET /alpha/edge-map` and `GET /alpha/gates` expose strict alpha-readiness evidence without running recalculation.
- `GET /paper-copy/summary`, `GET /paper-copy/strategies`, `GET /paper-copy/positions`, `GET /paper-copy/readiness` and `GET /paper-copy/portfolio/{id}` expose paper-only copy intelligence state.

The release preserves the snapshot-first runtime architecture: Command, Learning and Copy surfaces read lightweight stored evidence and do not trigger training, recalculation, broker activity or heavy Trading Game rebuilds during render.

## Trading Game Readiness

The Learning page now asks `GET /api/trading-game/readiness` before loading equity, ledger and benchmark details. The UI must never remain in generic loading. It shows one of:

- `READY`
- `BUILDING`
- `WAITING_FOR_SOURCE_DATA`
- `STALE_BUT_USABLE`
- `FAILED`
- `INSUFFICIENT_EVIDENCE`
- `DATA_QUALITY_BLOCKED`

Readiness includes source decision counts, source trade counts, eligible trade counts, ledger/equity/benchmark snapshot status, worker status, blocker, next required action, evidence grade and methodology version. It is diagnostic evidence, not a trading signal.

## Command Brain Level

The Command Center includes a lightweight `BLUM Brain Level` panel powered primarily by `GET /brain/command-summary`. It is snapshot-first and shows:

- current learning status and latest run timestamp;
- Trading Power / evidence classification when precomputed;
- Trading Game capital progress, win rate and expectancy R;
- benchmark pressure versus stored market benchmarks;
- latest weakness, latest lesson and next learning focus;
- alpha readiness and paper-copy readiness.

This panel does not run training, recalculation or heavy diagnostics. It is intended to answer quickly whether BLUM's learning evidence is improving, deteriorating or still insufficient.

## Paper Copy Trading Intelligence

`/copy-trading` is a paper-only intelligence surface for conditional mirror plans. The backend keeps the original compatibility endpoints:

- `GET /api/copy-trading/status`
- `GET /api/copy-trading/candidates`
- `GET /api/copy-trading/dashboard`

and adds the v1.0 paper-copy operating endpoints:

- `GET /paper-copy/summary`
- `GET /paper-copy/readiness`
- `GET /paper-copy/strategies`
- `GET /paper-copy/positions`
- `GET /paper-copy/portfolio/{portfolio_id}`

The service reads persisted `TradePlan`, `SniperScore` and Trading Game evidence. It does not recalculate signals, connect to brokers, place orders or claim performance. A candidate is downgraded when it is missing entry trigger, invalidation or target/risk-plan evidence.

The output is designed to answer:

- which setups are theoretically mirrorable only if confirmation triggers;
- which setups should remain watch-only;
- which setups are blocked by risk-plan gaps or weak actionability;
- what BLUM has learned from recent paper trades tied to the same ticker.

Paper Copy Trading Intelligence is a decision-audit layer and paper portfolio research surface, not an execution system. It never connects to a broker and never emits direct financial advice.

## Hyperbolic Multi-Timeframe Replay Engine

BLUM trains on persisted market history through a bounded, background-first replay pipeline. The replay engine checks the local `ReplayMarketBar` store first, imports compatible daily rows from `PriceHistory`, and then uses free Yahoo Chart, yfinance, Stooq and Nasdaq adapters only for missing coverage. Provider failures, unsupported timeframes, partial history and low-quality data are recorded as blockers; missing bars are never synthesized.

Replay decisions are chronological. Features and multi-timeframe context contain only bars closed at or before the decision timestamp, while entry uses a later executable bar. Supported evidence paths include daily swing, pullback, mean-reversion, intraday trend and 1-minute breakout execution when the required `1d`, `15m`, `5m` and `1m` data actually exist. If a lower timeframe is unavailable, BLUM degrades to a compatible setup instead of claiming false precision.

Execution applies market-, asset- and liquidity-sensitive spread, slippage, commission and gap assumptions. Position size is capped by stop distance, ATR, liquidity, confidence, edge, data quality and regime alignment. Replay outcomes update `StrategyMemory`, `SignalPerformance`, `LearningEvent`, `LearningFocusPriority` and `FeedbackLoopAudit` idempotently under the immutable `REPLAY_EVIDENCE` label.

Operational boundaries:

- `POST /api/training/run-replay` runs one explicit, time- and item-bounded replay slice.
- `GET /api/training/snapshot` only reads the latest stored snapshot and never starts training.
- The scheduler runs `hyperbolic_replay_training` independently and persists its asset cursor in `background_job_state`.
- Runtime states are `RUNNING`, `THROTTLED`, `PAUSED_FOR_RUNTIME`, `BUDGET_WAIT` and `ERROR`.
- Strategy promotion requires at least 300 trades, multiple chronological windows, more than one market, acceptable drawdown/overfitting, positive benchmark-relative evidence and measured out-of-sample improvement over the active baseline.
- Replay, walk-forward and paper-forward evidence remain separate. Replay output is not live alpha.

Key environment controls:

```text
BLUM_REPLAY_TRAINING_ENABLED=true
BLUM_REPLAY_TRAINING_MINUTES=15
BLUM_REPLAY_TARGET_VALIDATED_TRADES_PER_DAY=5000
BLUM_REPLAY_MAX_SECONDS_PER_CYCLE=120
BLUM_REPLAY_MAX_ASSETS_PER_CYCLE=20
BLUM_REPLAY_MAX_TRADES_PER_CYCLE=500
BLUM_REPLAY_MAX_EXPERIMENTS_PER_CYCLE=5
BLUM_REPLAY_MIN_PROMOTION_SAMPLES=300
BLUM_REPLAY_MARKETS=UNITED STATES,USA,ITALY,GERMANY,FRANCE,EUROPE
BLUM_REPLAY_TIMEFRAMES=1d,15m,5m,1m
```

The 5,000-trade daily value is a target, not a claimed result. Training Ground exposes measured daily throughput and the exact reason whenever verified data, eligible setups or runtime budgets prevent reaching it.

## Live Intraday Paper Scalping Engine

BLUM can promote replay-validated strategies into a separate intraday paper-forward stream. Promotion requires `PROMOTED_TO_PAPER`, at least 300 validated trades, positive benchmark-relative expectancy, acceptable stability and overfitting risk, and the exact `1d -> 15m -> 5m -> 1m` stack.

The scheduled `intraday_paper_trading` worker and explicit `POST /api/paper-forward/run-intraday` command:

- discover supported USA and European assets through enabled market desk agents;
- require fresh real bars on all four timeframes, with no interpolation or timeframe fallback;
- apply regime, setup, confirmation, trigger, liquidity, volatility, session, execution-cost and concentration gates;
- use volatility- and risk-adjusted fractional paper sizing;
- model adverse spread, slippage and commission fills;
- manage positions only from later one-minute bars and close on stop, invalidation, target, trailing stop, time stop or market close;
- create forward-only learning evidence after a trade is closed, never while it is open.

`GET /api/paper-forward/snapshot` is read-only and explains current activity or its exact blocker. `GET /api/alpha/snapshot` reports `intraday_paper_forward` separately from replay, walk-forward and generic paper-forward evidence. Empty streams return `NO_DATA` with null metrics; they are never backfilled from replay results.

Key controls include `BLUM_INTRADAY_PAPER_ENABLED`, `BLUM_INTRADAY_PAPER_MINUTES`, `BLUM_INTRADAY_MAX_ASSETS_PER_RUN`, `BLUM_INTRADAY_MAX_RUNTIME_SECONDS`, `BLUM_INTRADAY_MAX_OPEN_POSITIONS`, `BLUM_INTRADAY_MAX_HOLDING_MINUTES`, `BLUM_INTRADAY_MIN_EXPECTED_MOVE_BPS`, `BLUM_INTRADAY_MIN_LIQUIDITY_SCORE` and `BLUM_INTRADAY_MAX_ONE_MINUTE_AGE_MINUTES`.

This engine is paper-only. It has no broker integration, performs no real-money execution and does not force trades when promotion, data or execution-quality gates fail.

## Alpha Strategy Factory and Realistic Execution

BLUM now treats strategy research as a bounded scientific pipeline rather than promoting a setup from an attractive backtest. The scheduled `alpha_strategy_factory` worker generates deterministic variants across momentum, trend, breakout, pullback, mean reversion, volatility expansion, event reaction, relative strength, cross-sectional ranking and intraday scalping families. It evaluates persisted point-in-time replay evidence and records every rejection, challenger and reversible champion promotion.

Promotion requires at least 300 evaluated trades, purged chronological folds with embargo, positive net expectancy and benchmark excess, a positive block-bootstrap lower bound, multiple-testing significance, acceptable Deflated Sharpe and backtest-overfitting probabilities, multi-window/market/regime stability, controlled drawdown, complete execution-cost coverage and non-concentrated P/L. A stored `PROMOTED_TO_PAPER` row is not sufficient by itself: the paper registry accepts only an active champion certified by `alpha_strategy_factory_v1`. Strategies awaiting more samples are automatically reconsidered when replay evidence grows.

Approved intraday candidates now enter a separate persisted order lifecycle. Signals create `paper_execution_orders`; only later stored market bars can create `paper_execution_fills`. The execution model preserves theoretical and executed prices separately and records spread, liquidity-sensitive dynamic slippage, commission, volume participation, latency, FX conversion cost, short borrow cost and gap-through-stop loss. It supports partial fills, expires unfilled orders, opens a partial position when an executed remainder is cancelled at expiry, and never invents a same-timestamp fill.

Market sessions and provider halt metadata are execution gates. Regular-session orders cannot fill from opening/closing-auction bars unless the frozen order explicitly permits that session. Halted bars never fill. Intraday positions close at the next session by default; overnight carrying is an explicit opt-in. Cross-currency orders use only a stored point-in-time FX bar at or before the decision timestamp and are rejected with `FX_RATE_UNAVAILABLE` when that evidence is absent. Short orders similarly require a borrow-rate observation instead of assuming free borrow.

No-trade decisions with an observable reference price are persisted in `intraday_no_trade_decisions` and evaluated only after their configured future horizon. The resulting evidence distinguishes `CORRECT_NO_TRADE`, `MISSED_OPPORTUNITY`, `EDGE_DESTROYED_BY_COSTS` and `SIGNAL_DECAY_BEFORE_ENTRY`; expired executable orders remain separately classified as `ORDER_NOT_FILLED`. These outcomes update strategy memory and learning evidence without pretending that an unfilled order was a trade.

Runtime and UI boundaries:

- `hyperbolic_replay_training` produces historical evidence in bounded background slices.
- `alpha_strategy_factory` certifies or rejects strategies every configured interval.
- `intraday_paper_trading` discovers new paper candidates.
- `paper_execution_lifecycle` advances persisted orders and open positions independently.
- Training and Paper Forward snapshots expose compact `strategy_factory` and `execution_reality` summaries; GET requests do not run research or execution.

Relevant controls are `BLUM_STRATEGY_FACTORY_ENABLED`, `BLUM_STRATEGY_FACTORY_MINUTES`, `BLUM_STRATEGY_FACTORY_MAX_VARIANTS_PER_FAMILY`, `BLUM_STRATEGY_FACTORY_SEED`, `BLUM_PAPER_EXECUTION_LIFECYCLE_MINUTES`, `BLUM_PAPER_EXECUTION_ACCOUNT_CURRENCY`, `BLUM_PAPER_EXECUTION_FX_SPREAD_BPS`, `BLUM_INTRADAY_ALLOW_OVERNIGHT` and `BLUM_INTRADAY_NO_TRADE_EVALUATION_MINUTES`.

This architecture accelerates evidence production, not promotion. A high rejection rate is expected. Replay evidence remains distinct from paper-forward evidence, all fills are simulated research records, and no broker or real-money path exists.

### Decision execution parity and promotion frontier

Intraday research variants are now immutable executable contracts rather than descriptive labels. Each contract freezes its entry rule, lookback, relative-volume threshold, multi-timeframe requirements, market/regime filters, ATR stop, target R multiple, trailing rule and maximum holding period under a deterministic strategy fingerprint.

The same point-in-time evaluator is used in historical replay and paper-forward scouting. Replay evidence is unique by asset, strategy fingerprint, timeframe and decision timestamp, so two genuine variants can study the same market window without sharing outcomes. Strategy Factory validation reads only evidence generated by the exact fingerprint; a profitable canonical setup can no longer validate an unexecuted metadata variant.

The adaptive replay worker reads a lightweight promotion frontier before each bounded cycle. It allocates most experiment capacity to executable challengers closest to the existing 300-trade and robustness gates while preserving broad exploration. The selected fingerprints, sample gaps and research reasons are persisted in replay and Training snapshots. This changes research allocation only: it does not lower sample, cost, multiple-testing, stability, drawdown, benchmark or forward-evidence requirements.

When a certified or reduced-risk experimental strategy reaches paper-forward scouting, BLUM freezes the exact executable contract in the candidate and order evidence. Entry state, stop, target, trailing multiple and holding budget therefore match the rules measured in replay. Session, data freshness, liquidity, cost, concentration and later-fill checks remain independent execution gates.

This is still autonomous paper research, not broker-connected copy trading. A strategy can remain unpromoted indefinitely, a valid signal can remain a no-trade, and no position or positive alpha is claimed without stored forward outcomes.

## Evidence, Trust and Copy Readiness Engine

BLUM measures whether a strategy has enough reproducible evidence to be copied in paper research. The engine keeps four evidence classes strictly separate: `REPLAY_EVIDENCE`, `WALK_FORWARD_EVIDENCE`, `PAPER_FORWARD_EVIDENCE` and `INTRADAY_FORWARD_EVIDENCE`. Replay results can support research, but cannot by themselves promote a strategy to copy-ready status.

The background/command path appends immutable evidence cards, readiness history and lifecycle events. Read paths never recalculate:

- `GET /api/copy-readiness/strategies` returns a paginated latest-state projection.
- `GET /api/copy-readiness/strategies/{strategy_id}` returns readiness plus separated evidence cards.
- `GET /api/copy-readiness/strategies/{strategy_id}/timeline` returns a bounded audit timeline.
- `POST /api/copy-readiness/recalculate` is the explicit, bounded projection command and refreshes compact Paper Forward and Alpha snapshots.
- `GET /api/alpha/snapshot` and `GET /api/paper-forward/snapshot` consume stored readiness projections; neither starts learning, lifecycle work or recalculation.

Default paper-copy promotion requires at least 100 global terminal forward trades, 30 terminal trades for the strategy, 90 observation days, positive net expectancy and benchmark excess, drawdown at or below 15%, replay-to-forward decay at or below 35%, five tickers, two regimes and controlled concentration. High-confidence and limited-external-validation classifications use stricter thresholds (300/100/180 and 500/150/270 respectively). Every threshold is configurable with the `COPY_READINESS_*`, `COPY_READINESS_HIGH_CONFIDENCE_*` and `LIMITED_EXTERNAL_VALIDATION_*` environment variables.

Trade snapshots expose the evidence status, forward sample, net edge after measured costs, benchmark context, concentration, invalidation and paper-risk ceiling. Missing benchmark, cost or data-quality evidence remains `null` and blocks promotion where required; it is never converted to a favorable zero.

`ELIGIBLE_FOR_LIMITED_EXTERNAL_VALIDATION` is an autonomous research classification only. The engine has no broker adapter, order submission path or real-money execution. It does not promise alpha, does not blend replay with forward results and does not modify a trade's frozen decision payload.

## Brain Learning Proof

The Brain page measures whether BLUM is learning and whether stored paper decisions are improving. It still performs one read-only call to `GET /api/brain/snapshot`; no training, lifecycle work or benchmark recalculation runs during page render.

The snapshot and UI expose four compact evidence views:

- **Brain Improvement**: Brain Score, Decision Quality and Learning Velocity over timestamped stored snapshots.
- **P/L vs Benchmark**: cumulative paper-forward net P/L, matched holding-period benchmark contribution, wins, losses, expectancy R and drawdown.
- **Learning Throughput**: predictions, evaluated outcomes and persistent memory updates per bounded learning cycle.
- **Copy Trading Gate**: forward sample, observation time, maturity, readiness, capital eligibility, blockers and the next evidence milestone.

Missing values remain unavailable and short samples are marked `Insufficient evidence`. Charts never synthesize an improving line from one observation. Historical replay, walk-forward and paper-forward evidence remain separate.

### Evidence acceleration

BLUM projects a new Brain Score snapshot only when the stored learning or trading evidence changes. A stable evidence fingerprint prevents scheduler retries from creating duplicate history, while productive professional and replay cycles publish their result in the background. The five-snapshot directional threshold is unchanged: the chart becomes populated faster through real learning events, not synthetic points.

The scheduled paper-forward worker now performs two bounded phases in order: candidate scouting with frozen point-in-time evidence, followed by lifecycle advancement. Every opened position receives a deterministic time stop derived from the frozen trade plan and capped by `PAPER_FORWARD_MAX_HOLDING_DAYS` (10 days by default). Existing open positions without an expiration are backfilled from their original open timestamp, so they cannot remain unresolved indefinitely.

These changes do not lower the 30 closed-trade copy-readiness threshold and do not turn replay outcomes into forward evidence. Stops, targets, invalidations and time exits still require stored market prices after the frozen decision timestamp.

BLUM does not target an impossible 100% winning-trade rate. A robust trading-research system can have controlled losing trades; professional evidence requires positive net expectancy after costs, acceptable drawdown, benchmark-relative performance, calibration, reproducibility and enough forward observations. Copy readiness is an evidence-maturity status, not a guarantee of future profit or permission to deploy real capital.

### Institutional pilot readiness

The Brain snapshot includes a fail-closed `institutional_pilot` projection. It does not execute orders or declare BLUM profitable. It answers whether stored, exact-strategy evidence is mature enough for a future controlled pilot.

The gate requires a promoted strategy, exact replay/forward fingerprint parity, valid benchmark methodology, fresh execution evidence, measured costs and slippage, positive net expectancy and benchmark excess, controlled drawdown and concentration, sufficient market/regime coverage, and the existing strict forward sample thresholds. Missing or zero evidence is never replaced by a favorable fallback.

When eligible, the projected envelope remains bounded to 5% of designated capital, 0.25% risk per trade, 1% aggregate open risk, 0.5% correlated-theme risk and five simultaneous positions. Stale evidence, methodology failure, persistence/runtime degradation, non-positive edge, excessive drawdown, excessive open risk, fingerprint mismatch or strategy degradation activates the kill switch. This is an auditable research gate only; BLUM still has no broker execution path.

Evidence production is accelerated without lowering gates. The adaptive replay controller allocates bounded experiment slots across promotion-frontier candidates, failure replay, coverage gaps and broad exploration. Unchanged candidates rotate after repeated stalled slices, while random coverage is preserved to reduce selection bias.

## Limitations

- Public RSS, Google News RSS search, Yahoo and Stooq are demo-grade public data sources, not licensed institutional feeds.
- SEC EDGAR current feeds are public filing evidence. They do not cover private-company rumor, expected listings without filings or licensed IPO calendars.
- The system does not generate synthetic prices. If public providers fail or rate-limit, the affected assets are reported as missing instead of being filled with fake data.
- FinBERT, embeddings and LLM model loading depend on runtime memory and Hugging Face model availability.
- Qwen3-VL and InternVL3 chart vision are optional because multimodal models can exceed CPU Space resources. Deterministic OHLCV technical analysis remains active without them.
- The reasoning layer must not invent data; it is constrained to retrieved evidence.
- Signal classifications are research triage outputs, not investment recommendations.
- PostgreSQL is the database layer; the Docker demo can start an embedded PostgreSQL instance for Hugging Face convenience.

## Financial Disclaimer

This project is for educational, research and technical case-study purposes only. It does not constitute financial advice, investment advice, a recommendation, a trading signal, portfolio guidance or an offer to buy or sell any security. Always perform independent research and consult qualified professionals before making financial decisions.

## Roadmap

The execution roadmap is tracked in [`ROADMAP.md`](../../ROADMAP.md). It covers Docker Space stabilization, data ingestion reliability, AI model productionization, semantic intelligence, signal engine upgrades, ETF intelligence, backtesting, frontend UX, provider architecture, testing and open-source polish.

## Engineering Standards

Development standards are tracked in [`ENGINEERING_STANDARDS.md`](../engineering/standards.md). The project explicitly rejects placeholders, fabricated data and synthetic market-data fallbacks. Every shipped increment should be evidence-bound, efficient, explainable and verified.

## Contributing

Contributions should preserve the project philosophy: transparent evidence,
modular models, explainable scoring, no fabricated data and no investment
recommendations. See [CONTRIBUTING.md](../../CONTRIBUTING.md) for the development and
data-contribution workflow, [GOVERNANCE.md](../../GOVERNANCE.md) for change control and
[SECURITY.md](../../SECURITY.md) for private vulnerability reporting.
## Autonomous Forex Alpha Trader

BLUM includes a paper-only Forex decision core for selective scalping and short
intraday research. `BlumForexTraderCore` is the sole path from a Forex proposal
to a new paper order. It requires point-in-time `1h/15m/5m/1m` evidence, a
paper-eligible strategy, positive net edge, an eligible session, a completed
contrarian review and portfolio-risk approval.

The supported universe is limited to EUR/USD, GBP/USD, USD/JPY, USD/CHF,
AUD/USD, USD/CAD, NZD/USD, EUR/GBP, EUR/JPY, GBP/JPY, AUD/JPY and EUR/CHF.
The execution simulator uses directional bid/ask fills, spread, slippage,
commission, latency, margin, partial fills, gap-through stops and overnight
swap. It never connects to a broker and never sends real orders.

The isolated scheduler runs one bounded cycle per minute. It refreshes the
stalest pairs first and dynamically covers at least the configured freshness
window (four of twelve pairs per minute with the default three-minute budget),
hydrating each selected pair's complete `1h/15m/5m/1m` stack. Replay workers
continue deeper research independently. The scheduler manages open positions
even while paused and persists a heartbeat and idempotent cycle key.
Historical replay, walk-forward validation and paper-forward Forex evidence are
kept logically and physically separate.

Read-only status is available at `GET /api/forex-trader/snapshot`. It reads the
latest persisted `forex_trader_summary` snapshot and never triggers market data,
learning or execution. Explicit controls are POST-only:

- `POST /api/forex-trader/run-cycle`
- `POST /api/forex-trader/start`
- `POST /api/forex-trader/pause`
- `POST /api/forex-trader/resume`
- `POST /api/forex-trader/emergency-stop`

Important settings include `BLUM_FOREX_TRADER_ENABLED`,
`BLUM_FOREX_TRADER_MINUTES`, `BLUM_FOREX_TRADER_MAX_PAIRS_PER_CYCLE`,
`BLUM_FOREX_TRADER_REFRESH_PAIRS_PER_CYCLE`,
`BLUM_FOREX_TRADER_FRESHNESS_BUDGET_MINUTES`,
`BLUM_FOREX_RISK_PER_TRADE_PERCENT`, `BLUM_FOREX_DAILY_LOSS_LIMIT_PERCENT`,
`BLUM_FOREX_MAX_OPEN_POSITIONS`, `BLUM_FOREX_ALPHA_MIN_FORWARD_TRADES`,
`BLUM_FOREX_NEWS_BLOCK_BEFORE_MINUTES` and
`BLUM_FOREX_NEWS_BLOCK_AFTER_MINUTES`.
Risk is capped at 0.5% per trade, daily paper loss at 2%, and four concurrent
Forex positions. Alpha eligibility requires at least 100 closed forward Forex
trades plus positive net expectancy, positive benchmark-relative evidence,
coverage, replay-forward decay, currency concentration and confidence gates.
Eligibility is evidence maturity, not a profit guarantee.

Forex confidence is a sample-aware analytical score, not an execution bypass.
The frozen proposal records setup, timeframe, data, strategy and execution
confidence separately. A hard blocker such as stale data, strategy immaturity
or non-positive net edge can reject an order without erasing the useful
analytical components. The Alpha Strategy Factory always reserves bounded
research capacity for a Forex `1h/15m/5m/1m` hypothesis, but the existing
50-sample experimental and 300-sample certification gates remain unchanged.

### Forex Evidence Academy

The Forex trader has an evidence-bound research curriculum. A bounded academy
slice runs with adaptive replay and maintains three separate layers:

- a provenance and usage catalog for ECB/FRED macro data, CFTC positioning,
  historical one-minute replay candidates and human-annotated Forex sentiment;
- research assignments across pairs, sessions, regimes and setup families;
- contextual memory compiled from persisted Forex replay and paper outcomes.

External knowledge does not increase trading confidence by itself. Text and
macro datasets can improve context, feature extraction and evaluation, while
only point-in-time outcomes with costs and benchmark comparison can become
`CONTEXT_ELIGIBLE`. At least 30 consistent outcomes are required for a context
to influence confidence, and the adjustment is capped at eight percentage
points. The adjustment cannot bypass stale-data, event-risk, execution-cost,
portfolio-risk or strategy-readiness vetoes.

The curriculum preserves broad exploration while prioritizing missing Forex
samples. Replay remains timestamp-bound, and experimental paper strategies
retain reduced risk. Dataset validation and large backfills are background or
manual operations; no GET route downloads data or starts training.

### Forex reinforcement policy and financial model council

Completed Forex paper episodes update an auditable contextual-bandit policy
identified by strategy, session, regime, setup family and direction. Its reward
uses realized net R after execution costs plus a bounded benchmark-relative
component. Stored terminal evidence is replayed incrementally in the background,
so previously persisted outcomes can become operational memory without running
new simulations during a request.

Every policy update stores the previous value, reward, learning rate, resulting
value, evidence identifier and policy version. A context needs at least 30
outcomes and a 95% confidence interval that excludes zero before it may adjust a
future decision. Adjustments are capped at eight percentage points and cannot
bypass data, cost, event, risk or readiness vetoes. This is contextual
reinforcement learning over completed paper episodes, not a claim that a generic
deep-RL agent has learned a profitable market policy.

The Financial Model Council provides explicit, resource-aware integration
boundaries:

- **FinBERT** remains the local financial-sentiment classifier, with its labeled
  VADER fallback when model loading is unavailable.
- **FinGPT** is registered as an optional financial-language adapter. Its 13B
  LoRA is not loaded on the CPU request path.
- **FinRobot** supplies a local structured multi-agent evidence and risk review.
- **FinLlama** is registered as a GPU/remote-only reasoning advisor because the
  selected model is 33B.
- **InvestLM** remains remote-optional and disabled until a reviewed model
  endpoint and license are configured.

Advisor votes are immutable decision evidence. They have no direct trading
authority, are evaluated against the later reward and cannot open or close a
position. `GET /api/ai/models/status` exposes the registered execution mode,
runtime status, license status, resource profile and vote count without loading
a model or changing state.

### Unified paper-trading evidence

The Paper Trading product surface reads one background-produced
`unified_paper_trading_summary` snapshot. It combines standard, intraday and
Forex paper records into one journal while retaining `source_engine`,
`market_group` and the native source identifier for every row. Source tables
remain authoritative: Forex records are not copied into generic paper tables.

Aggregate P/L, win rate, expectancy R, drawdown and benchmark excess include
eligible closed evidence from every paper engine exactly once. Open positions
contribute only observed unrealized P/L; rejected and no-trade decisions never
contribute profit. The snapshot also exposes separate per-market metrics so a
strong or weak Forex result cannot be hidden inside an aggregate.

`GET /api/paper-trading/snapshot` is snapshot-only. Trade replay is lazy and
source-aware through
`GET /api/paper-trading/trades/{source_engine}/{source_trade_id}`. The generic
paper worker and Forex worker refresh the projection after their own background
updates. Brain exposes the same aggregate evidence, while Alpha keeps Forex in
its own `forex_paper_forward` evidence split. None of these GET paths starts a
scan, lifecycle transition, learning cycle or recalculation.

The Paper Trading page defaults to an `Azioni / ETF` tab and exposes Forex in a
separate tab. Both views are derived client-side from the same snapshot. The
projection reserves bounded capacity for each active market group so frequent
Forex decisions cannot evict all equity rows from the visible journal.

Terminal outcomes without a fill keep `net_pnl_eur=null` and are displayed as
`not realized`; they are never presented as zero-profit trades. Small measured
P/L remains visible with additional decimal precision. Intraday Forex uses a
separate margin-accounting contract: position size is expressed in base
currency units, risk and P/L are converted to EUR using point-in-time FX data,
and only simulated margin is reserved. Missing conversion data blocks the
order rather than assuming an exchange rate.

## Trading ML Champion/Challenger

BLUM now has a supervised trading-learning lane for equities and Forex. It uses
scikit-learn because the available audited evidence does not justify a deep
reinforcement-learning policy with trading authority. The design has two
speeds:

- an `SGDClassifier` updates rapidly from new terminal outcomes but remains
  permanently shadow-only;
- deterministic `HistGradientBoostingClassifier` and regressor challengers are
  evaluated on purged expanding walk-forward folds before they can advise.

Point-in-time, cost-adjusted labels remain in SQL as the source of truth.
Bounded Polars scans and immutable partitioned Parquet files accelerate
training reads without changing evidence. Hyperparameter search is limited to
12 Optuna trials and 90 seconds. No GET endpoint starts projection, training,
search or promotion.

Promotion requires at least 300 replay outcomes, three purged folds, six
assets/pairs, positive net expectancy after costs, benchmark-aware calibration
improvement and non-concentrated positive P/L. Artifacts are loaded only from
the configured trusted directory after SHA-256 and feature-schema validation.
Drift, negative forward expectancy or artifact failure degrades the model and
supports rollback to a verified prior champion; otherwise deterministic BLUM
retains full authority.

An active model may adjust confidence by at most five points. Combined learned
influence is capped at ten points. It cannot remove stale-data, liquidity,
event, execution, portfolio or deterministic no-trade blockers. A validated
negative Forex forecast may add a veto. Every write-oriented decision records
the model, feature hash, probability, predicted net R, baseline, adjustment and
guardrails in `trading_ml_predictions`.

The bounded background worker runs every 15 minutes and publishes
`trading_ml_status`. Each cursor-backed slice accepts at most 500 new examples
per market family, preventing an initial backlog from becoming a monolithic
CPU job. `GET /api/trading-ml/status` reads that snapshot only;
`POST /api/trading-ml/run` is the explicit manual bounded trigger. These models
do not claim guaranteed profitability or copy readiness. Forex forward evidence
was still limited to 38 outcomes at design time, so the evidence gates, not
training speed, determine when a model may become active.

### FinRL-X Quant Challenger

BLUM includes a paper-only quantitative challenger built against the actual
[`AI4Finance-Foundation/FinRL-Trading`](https://github.com/AI4Finance-Foundation/FinRL-Trading)
weight-centric strategy contract. The Apache-2.0 upstream package is installed
from immutable revision
`e65d6f0483ead7d2ef4a5fc940cdf960392a25c1`; BLUM's runner imports
`BaseStrategy`, `StrategyConfig`, and `StrategyResult` from that pinned source.
It does not import FinRL-X in the API process.

The bundled runner consumes BLUM's immutable point-in-time Parquet feature
store, uses a chronological holdout, and writes a deterministic classification
and net-R policy as safe JSON. It never loads pickle artifacts. The runner is
invoked as a bounded subprocess by the existing background Trading ML worker,
so GET endpoints and page rendering cannot start training. A newly started
process auto-discovers a previously validated market-specific manifest under
`BLUM_FINRLX_ARTIFACT_ROOT`.

Every external artifact is rejected before use unless its manifest has the
expected provider, pinned upstream revision, supported algorithm, exact feature
schema, compatible market/action schema, SHA-256 digest and `paper_only=true`.
The accepted algorithms are PPO, SAC, TD3, DDPG, A2C and deterministic
baselines. The worker publishes FinRL-X availability and validation state in
the existing `trading_ml_status` snapshot.

For Forex and strict intraday candidates, policy output is stored under
`finrlx_quant` together with a `finrlx_overlay` audit. It may return only a
bounded directional score or target-weight proposal. The overlay remains
frozen until a chronological holdout has at least 100 samples, directional
accuracy is at least 52%, mean policy net R is positive, and the Ridge return
forecast beats its constant baseline. Only then can alignment move confidence
by at most five points; disagreement requires another confirmation. BLUM
continues to own data freshness, macro-event vetoes, costs, risk, units/lots,
margin, stops, targets and simulated execution. Existing blockers force the
external proposal to `HOLD`; no external proposal can open an order or remove
a blocker.

The Python configuration remains fail-closed by default. The production Docker
image explicitly enables the bundled runner:

```dotenv
BLUM_FINRLX_ENABLED=true
BLUM_FINRLX_RUNNER_COMMAND=/app/scripts/finrlx_runner.py
BLUM_FINRLX_ARTIFACT_ROOT=/data/trading_ml/finrlx
BLUM_FINRLX_MANIFEST_PATH=
BLUM_FINRLX_FEATURE_SCHEMA_HASH=
BLUM_FINRLX_TIMEOUT_SECONDS=90
```

Leaving `BLUM_FINRLX_FEATURE_SCHEMA_HASH` empty binds validation to BLUM's
current Trading ML feature schema. Training remains background-only and
bounded. Insufficient outcomes produce `INSUFFICIENT_EVIDENCE` and no artifact,
rather than a synthetic policy.

This integration operationalizes FinRL-X's strategy boundary; it does not
enable the upstream Alpaca deployment path or claim to run PPO/SAC/TD3 merely
because those names exist upstream. The first bundled challenger is a
deterministic, auditable policy because BLUM's current evidence volume does not
justify giving a deep RL policy influence. It adds no broker connectivity,
real-money execution, automatic promotion, or claim of alpha.

## BLUM Finance Model Release

BLUM now has a standalone, reproducible model-release boundary. BLUM Engine
remains the source of market truth; BLUM Finance is trained only to reproduce
evidence-bound financial reasoning, contradiction handling, risk disclosure,
technical invalidation and conservative abstention.

The release pipeline:

1. selects only SFT-approved examples above a configured quality threshold;
2. removes secrets, personal identifiers, broker identifiers and unlicensed
   verbatim source material;
3. deduplicates examples and applies grouped temporal splits so one thesis
   lineage cannot cross train, validation and test;
4. records source revision, row counts, split periods and content SHA-256;
5. trains a Qwen3-4B LoRA against an immutable dataset revision;
6. compares the candidate with the exact immutable base revision;
7. rejects candidates with insufficient samples, no target improvement,
   absolute or relative no-fabrication failure, weak structured validity,
   incomplete risk or invalidation logic, or degraded measured calibration;
8. requires runtime-specific smoke tests before replacing `Italianhype/Blum`.

The first audited dataset is published at
[`Italianhype/Blum-Finance-Reasoning`](https://huggingface.co/datasets/Italianhype/Blum-Finance-Reasoning).
It contains 521 real BLUM reasoning examples with a 416/52/53 grouped temporal
split. The immutable dataset revision and hashes are recorded in
`BLUM_FINANCE_MODEL_RELEASE_REPORT.md`.

The first downloadable model is published at
[`Italianhype/Blum`](https://huggingface.co/Italianhype/Blum) as **BLUM Finance
4B**, an MLX QLoRA derivative of the immutable
`mlx-community/Qwen3-4B-4bit` revision. Training uses assistant-only loss and
early stopping. A reproducible preprocessing derivative removes output numbers
that were absent from the point-in-time input and caps unvalidated confidence
at 70 without changing input evidence or split membership.

On the 53-example temporal test, the released candidate produced 100% valid
BLUM JSON, 100% numerical consistency, 92.86% no-fabrication score and a
96.26% aggregate reasoning score. The exact base produced readable prose but
zero schema-valid BLUM responses, so the aggregate delta measures task
adherence rather than general intelligence. The test has no labeled market
outcomes; confidence calibration is therefore **not measured**, and these
results do not establish trading alpha.

Inference and installation do not send telemetry. `blum-contribute` creates a
local redacted bundle only after explicit consent; network upload requires the
additional `--push` flag. Contributions enter
[`Italianhype/Blum-Finance-Memory`](https://huggingface.co/datasets/Italianhype/Blum-Finance-Memory)
in quarantine and never modify active weights automatically. Accepted examples
can enter an immutable future training snapshot; each incremental cycle creates
a versioned challenger and promotes it only after the same held-out gates.
Training never runs inside an inference request or on a frontend page.

### Outcome-aware continual model learning

The Space now persists an immutable local Analyst snapshot even when Hugging
Face training credentials or GPU jobs are unavailable. Every snapshot preserves
the original point-in-time thesis and, only when an outcome is mature, appends a
separate post-outcome critique. This ordering prevents future outcomes from
leaking into the original decision while teaching the next challenger why a
thesis held or failed.

The default supervisor checks for new mature evidence hourly and performs its
first check five minutes after startup. Identical evidence is content-addressed,
so unchanged snapshots are reused instead of rewritten.

Snapshot creation is background-first and can also be requested explicitly with
`POST /api/analyst/hf-training/snapshot?persist_local=true`. Read-only status and
archive endpoints are available at
`GET /api/analyst/hf-training/local-snapshot` and
`GET /api/analyst/hf-training/local-snapshot/archive`. No GET request trains,
publishes, or recalculates a model.

Downloaded installations can use `BlumFinanceMemoryStore` as an auditable local
memory. Only mature, source-verified, high-quality records observable before the
new request timestamp are retrieved, and they are explicitly labeled historical
analogies. `blum-memory-add` imports a validated contribution bundle. Community
submission remains opt-in through a pull request to quarantine; untrusted input
cannot directly modify shared memory or released weights.

The current model release requires Apple Silicon and MLX. A portable
Transformers/GGUF release remains a separate validation target. Language-model
reasoning scores do not demonstrate trading alpha, future profitability or
suitability for unattended capital execution.

# Historical Forex Knowledge Bootstrap

BLUM imports the licensed Kaggle
[Forex Trading Dataset with EMA, RSI & ATR (2025)](https://www.kaggle.com/datasets/jeleeladekunlefijabi/forex-trading-dataset-with-ema-rsi-and-atr)
inside the background Trading ML worker. The Learning and Paper Trading pages
never download or process the dataset.

The source is treated as external research evidence:

- source indicators and labels are ignored and recalculated from OHLC;
- duplicate date-only observations are consolidated into daily bars, never
  represented as intraday ticks;
- every feature uses information available at or before the decision timestamp;
- every label uses a later bar and includes a conservative estimated round-trip
  cost;
- examples use the `external_historical_replay` lane with `0.25` sample weight;
- source URL, license, version, SHA-256, pair coverage, and transformation policy
  are persisted in the feature-store manifest;
- historical confidence influence is capped at +/-3 percentage points and
  cannot bypass data, execution, risk, or no-edge vetoes;
- FinRL-X consumes the examples as a paper-only challenger. Poor holdout results
  remain shadow/frozen and cannot authorize paper trades.

The bundled source is daily and covers only EUR/USD, GBP/USD, and USD/JPY. It
improves historical regime and cross-pair context, but it is not evidence for
one-minute scalping and does not prove future profitability. Intraday decisions
still require fresh BLUM `1h/15m/5m/1m` market evidence and forward outcomes.
# BLUM Deterministic Execution Core

BLUM uses NautilusTrader 1.230.0 as an optional Rust-native deterministic execution kernel for equity, ETF and fiat-Forex research. BLUM remains the source of decisions, risk policy and learning evidence; Nautilus supplies event ordering, order-state transitions, simulated matching and portfolio accounting.

- Frozen BLUM decisions are replayed by an independent bounded background worker.
- Point-in-time bars are incrementally projected into a Nautilus Parquet catalog. Future or not-yet-acquired observations are rejected.
- Existing paper execution remains authoritative while the new kernel runs in `SHADOW` mode.
- Promotion is reversible and limited to paper execution. It requires at least 100 terminal comparisons, equity/Forex and regime coverage, and at least 99% state agreement.
- Divergence, duplicate fills, accounting failures or look-ahead evidence force rollback to shadow.
- `GET /api/runtime/execution-kernel` reads the latest compact snapshot and never runs execution or recalculation.
- Crypto, broker adapters and real-money execution are explicitly excluded.

Configuration uses `BLUM_NAUTILUS_*` environment variables. If the optional native wheel cannot load, BLUM starts normally and reports the kernel as unavailable. NautilusTrader is distributed under LGPL-3.0; BLUM uses its project name only for dependency attribution and calls this component the BLUM Deterministic Execution Core.

# Evidence-Bound Decision Council

BLUM now subjects stored intelligence to a persistent multi-agent decision
council before treating it as an actionable conclusion. Independent technical,
fundamental, sentiment, narrative and regime votes are weighted by their stored
reliability, challenged by bull and bear researchers, reviewed by aggressive,
neutral and conservative risk personas, and resolved by a portfolio manager.

The design was informed by the public
[TradingAgents](https://github.com/TauricResearch/TradingAgents) architecture,
but is implemented natively against BLUM contracts. It adds no mandatory LLM
provider or LangGraph dependency. The council only consumes point-in-time BLUM
evidence and cannot fetch data during deliberation.

- every turn, evidence reference, checkpoint and verdict is persisted;
- missing invalidation, reward/risk, independent evidence or consensus forces
  `WAIT`;
- mature outcomes create benchmark-relative reflections;
- historical outcomes known before a verdict cannot enter its reflection or
  confidence memory;
- outcome memory affects later confidence only after a minimum sample gate;
- processing runs in a bounded autonomous worker;
- dashboard/API reads use the asynchronous `decision_council_summary` snapshot;
- detailed replay is read-only and bounded.

Use `GET /api/engine/decision-council` for the compact snapshot and
`GET /api/engine/decision-council/runs/{run_id}` for an audit replay. This layer
improves decision discipline and traceability; it does not prove alpha, promise
profit, or bypass execution and portfolio risk controls. See
`EVIDENCE_DECISION_COUNCIL_REPORT.md` for the architecture and limitations.
