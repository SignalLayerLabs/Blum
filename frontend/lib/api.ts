import { AccuracyOverview, AccuracyProfile, Asset, BrainAccuracy, BrainAssetMemory, BrainEvaluation, BrainStatus, ChartReport, CommunitySentimentPayload, DashboardOverview, DataCoverage, ExecutiveDashboardPayload, FinancialChatResponse, IPORadar, LiveNewsArticle, MacroOverview, MarketBrain, MarketBrainHistoryRow, MarketNarrativePayload, MarketSentiment, OpportunityRadarPayload, PipelineStatus, PortfolioScenarioPayload, RelatedNews, Signal, SignalValidationReport, StockRadar, SystemStatus, WatchlistPayload } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";
import type { AscentSnapshot } from "./ascentView.mjs";
import type { CurriculumSnapshot } from "./curriculum";
const inFlightRequests = new Map<string, Promise<any>>();
const memoryCache = new Map<string, { expiresAt: number; value: any }>();
const LEARNING_INITIAL_RENDER_GUARD_MS = 4000;
const heavyLearningPostFragments = [
  "/recalculate",
  "/run-cycle",
  "/pipeline/run",
  "/market/update",
  "/news/update",
  "/signals/run",
  "/data/repair",
  "/fundamentals/update",
  "/macro/update",
  "/stock-radar/update",
  "/ipo-radar/update",
  "/api/learning-intelligence/self-improvement/generate",
  "/api/capital-allocation/recalculate",
  "/api/alpha-recovery/recalculate",
  "/api/alpha-recovery/methodology/validate",
  "/api/alpha-recovery/attribution/calculate",
  "/api/alpha-recovery/missed-winners/detect",
  "/api/alpha-recovery/actions/generate",
  "/api/meta-cognition/recalculate",
  "/api/meta-cognition/factor-importance/recalculate",
  "/api/meta-cognition/evaluate",
  "/api/meta-cognition/capital-preservation/evaluate",
  "/api/meta-cognition/learning-focus/generate",
  "/api/meta-cognition/noise/detect",
  "/snapshots/produce"
];
const requestStats = {
  total: 0,
  duplicate: 0,
  cacheHits: 0,
  initialLearningPage: [] as Array<{ path: string; method: string; duration_ms: number; status: string; duplicate?: boolean; cache_hit?: boolean }>
};
let learningPagePath = "";
let learningPageStartedAt: number | null = null;

async function getJson<T>(path: string): Promise<T> {
  const response = await fetchBlum(path, { method: "GET", headers: { Accept: "application/json" }, cacheTtlMs: 2500, timeoutMs: 12000 });
  if (!response.ok) {
    throw new Error(await responseError(response));
  }
  return response.json() as Promise<T>;
}

async function postJson<T>(path: string, payload: unknown): Promise<T> {
  const response = await fetchBlum(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    timeoutMs: 20000
  });
  if (!response.ok) {
    throw new Error(await responseError(response));
  }
  return response.json() as Promise<T>;
}

async function fetchBlum(path: string, options: RequestInit & { timeoutMs?: number; cacheTtlMs?: number } = {}): Promise<Response> {
  const method = String(options.method ?? "GET").toUpperCase();
  const key = `${method}:${path}:${typeof options.body === "string" ? options.body : ""}`;
  const started = nowMs();
  requestStats.total += 1;

  if (method === "POST" && shouldBlockLearningHeavyPost(path)) {
    const duration = nowMs() - started;
    recordInitialLearningRequest(path, method, duration, "blocked_heavy_frontend_recalculation", false, false);
    reportFrontendTiming(path, method, duration, "blocked_heavy_frontend_recalculation", true);
    return new Response(JSON.stringify({
      detail: "blocked_heavy_frontend_recalculation",
      policy: "Learning page render is read-only. Heavy training/recalculation jobs must be explicit backend or user actions after initial load."
    }), { status: 409, headers: { "Content-Type": "application/json", "X-BLUM-BLOCKED-HEAVY-FRONTEND-RECALCULATION": "true" } });
  }

  if (method === "GET") {
    const cached = memoryCache.get(key);
    if (cached && cached.expiresAt > Date.now()) {
      requestStats.cacheHits += 1;
      recordInitialLearningRequest(path, method, nowMs() - started, "cache", false, true);
      reportFrontendTiming(path, method, nowMs() - started, "cache_hit", true);
      return new Response(JSON.stringify(cached.value), { status: 200, headers: { "Content-Type": "application/json", "X-BLUM-FRONTEND-CACHE": "true" } });
    }
    const existing = inFlightRequests.get(key);
    if (existing) {
      requestStats.duplicate += 1;
      recordInitialLearningRequest(path, method, nowMs() - started, "deduped", true, false);
      reportFrontendTiming(path, method, nowMs() - started, "deduped", true);
      return existing.then((value) => new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json", "X-BLUM-FRONTEND-DEDUPE": "true" } }));
    }
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs ?? 12000);
  const request = fetch(`${API_BASE}${path}`, {
    ...options,
    method,
    cache: "no-store",
    signal: controller.signal
  }).then(async (response) => {
    const duration = nowMs() - started;
    recordInitialLearningRequest(path, method, duration, response.ok ? "ok" : `http_${response.status}`, false, false);
    reportFrontendTiming(path, method, duration, response.ok ? "ok" : `http_${response.status}`);
    if (method === "GET" && response.ok && options.cacheTtlMs && !path.includes("/performance/")) {
      const clone = response.clone();
      try {
        memoryCache.set(key, { expiresAt: Date.now() + options.cacheTtlMs, value: await clone.json() });
      } catch {
        // Non-JSON GETs are not cached.
      }
    }
    return response;
  }).catch(async (error) => {
    const duration = nowMs() - started;
    recordInitialLearningRequest(path, method, duration, "error", false, false);
    reportFrontendTiming(path, method, duration, "error");
    if (method === "GET" && !String(error?.name).includes("Abort") && !path.includes("/performance/")) {
      return fetch(`${API_BASE}${path}`, { ...options, method, cache: "no-store" });
    }
    throw error;
  }).finally(() => {
    clearTimeout(timeout);
    inFlightRequests.delete(key);
  });

  if (method === "GET") {
    inFlightRequests.set(
      key,
      request.then((response) => response.clone().json()).catch(() => undefined)
    );
  }
  return request;
}

function reportFrontendTiming(path: string, method: string, duration_ms: number, status: string, force = false) {
  if (path.includes("/performance/frontend-widget") || path.includes("/api/performance/frontend-widget")) return;
  const onLearningPage = typeof location !== "undefined" && location.pathname.startsWith("/learning");
  const pathname = typeof location !== "undefined" ? location.pathname.replace(/\/+$/, "") || "/" : null;
  const onReadOnlyProductSurface = pathname !== null && ["/", "/dashboard", "/paper-trading", "/copy-trading", "/brain", "/calls", "/training-ground", "/learning", "/alpha", "/evolution"].includes(pathname);
  const route = typeof location !== "undefined" ? `${location.pathname}${location.search}` : "";
  const initialLearningWindow = onLearningPage && isWithinLearningInitialWindow();
  if (onReadOnlyProductSurface) return;
  if (!force && !onLearningPage && duration_ms < 400 && !path.includes("/learning")) return;
  fetch(`${API_BASE}/api/performance/frontend-widget`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: `frontend.api.${method}.${path}`, duration_ms, status, source: "fetchBlum", route, initial_learning_window: initialLearningWindow }),
    keepalive: true
  }).catch(() => undefined);
}

function recordInitialLearningRequest(path: string, method: string, duration_ms: number, status: string, duplicate: boolean, cache_hit: boolean) {
  if (!isWithinLearningInitialWindow()) return;
  requestStats.initialLearningPage.push({ path, method, duration_ms: Number(duration_ms.toFixed(2)), status, duplicate, cache_hit });
  if (requestStats.initialLearningPage.length > 160) requestStats.initialLearningPage.shift();
}

function shouldBlockLearningHeavyPost(path: string) {
  if (typeof location === "undefined" || !location.pathname.startsWith("/learning")) return false;
  if (!isWithinLearningInitialWindow()) return false;
  return heavyLearningPostFragments.some((fragment) => path.includes(fragment));
}

function isWithinLearningInitialWindow() {
  if (typeof location === "undefined" || !location.pathname.startsWith("/learning")) {
    learningPagePath = "";
    learningPageStartedAt = null;
    return false;
  }
  const currentPath = `${location.pathname}${location.search}`;
  const currentTime = nowMs();
  if (learningPagePath !== currentPath || learningPageStartedAt === null) {
    learningPagePath = currentPath;
    learningPageStartedAt = currentTime;
    requestStats.initialLearningPage = [];
  }
  return currentTime - learningPageStartedAt <= LEARNING_INITIAL_RENDER_GUARD_MS;
}

function nowMs() {
  return typeof performance === "undefined" ? Date.now() : performance.now();
}

async function responseError(response: Response) {
  try {
    const payload = await response.json();
    const detail = typeof payload?.detail === "string" ? payload.detail : JSON.stringify(payload?.detail ?? payload);
    return `${response.status} ${response.statusText}: ${detail}`;
  } catch {
    return `${response.status} ${response.statusText}`;
  }
}

export const api = {
  alphaDesk: () => getJson<any>("/api/alpha/desk"),
  ascentStatus: () => getJson<AscentSnapshot>("/api/ascent/status"),
  clientRequestStats: () => ({ ...requestStats, initialLearningPage: [...requestStats.initialLearningPage] }),
  performanceDiagnostics: () => getJson<any>("/performance/diagnostics"),
  recordPerformanceWidget: (payload: { name: string; duration_ms: number; status?: string; source?: string; detail?: string }) =>
    postJson<any>("/performance/frontend-widget", payload),
  systemStatus: () => getJson<SystemStatus>("/system/status"),
  operatingState: () => getJson<any>("/api/runtime/operating-state"),
  brainRuntimeState: () => getJson<any>("/brain/runtime-state"),
  brainCommandSummary: () => getJson<any>("/brain/command-summary"),
  brainCapabilities: () => getJson<any>("/brain/capabilities"),
  brainEvolution: () => getJson<any>("/brain/evolution"),
  traderBrain: () => getJson<any>("/api/brain/snapshot"),
  traderTrainingGround: () => getJson<any>("/api/training/snapshot"),
  tradingCurriculum: () => getJson<CurriculumSnapshot>("/api/training/curriculum"),
  traderPaperTrading: (limit = 20) => getJson<any>(`/api/paper-trading/snapshot?limit=${limit}`),
  unifiedPaperTradingDetail: (sourceEngine: string, sourceTradeId: number) =>
    getJson<any>(`/api/paper-trading/trades/${encodeURIComponent(sourceEngine)}/${sourceTradeId}`),
  paperForwardStatus: () => getJson<any>("/api/paper-forward/status"),
  paperForwardSnapshot: () => getJson<any>("/api/paper-forward/snapshot"),
  paperForwardTrades: (limit = 50, status?: string) =>
    getJson<any>(`/api/paper-forward/trades?limit=${limit}${status ? `&status=${encodeURIComponent(status)}` : ""}`),
  paperForwardTradeDetail: (tradeId: number) => getJson<any>(`/api/paper-forward/trades/${tradeId}`),
  paperForwardEvents: (tradeId: number) => getJson<any>(`/api/paper-forward/events/${tradeId}`),
  traderAlpha: () => getJson<any>("/api/alpha/snapshot"),
  snapshotsHealth: () => getJson<any>("/snapshots/health"),
  produceSnapshots: (snapshotType?: string, maxItems = 8) =>
    postJson<any>(`/snapshots/produce?max_items=${maxItems}${snapshotType ? `&snapshot_type=${encodeURIComponent(snapshotType)}` : ""}`, {}),
  learningHealth: () => getJson<any>("/learning/health"),
  brainStatus: () => getJson<BrainStatus>("/brain/status"),
  brainAccuracy: () => getJson<BrainAccuracy>("/brain/accuracy"),
  brainLearningEvents: (limit = 50) => getJson<any[]>(`/brain/learning-events?limit=${limit}`),
  brainSignalEvaluations: (limit = 120, ticker?: string) => getJson<BrainEvaluation[]>(`/brain/signal-evaluations?limit=${limit}${ticker ? `&ticker=${encodeURIComponent(ticker)}` : ""}`),
  brainAssetMemory: (ticker: string) => getJson<BrainAssetMemory>(`/brain/asset-memory/${encodeURIComponent(ticker)}`),
  brainConfidenceHistory: (ticker: string) => getJson<any>(`/brain/confidence-history/${encodeURIComponent(ticker)}`),
  evaluateBrainSignals: (limit = 240) => postJson<any>(`/brain/evaluate-signals?limit=${limit}`, {}),
  recalculateBrainWeights: () => postJson<any>("/brain/recalculate-weights", {}),
  runLearningCycle: (limit = 240) => postJson<any>(`/brain/run-learning-cycle?limit=${limit}`, {}),
  learningDashboard: () => getJson<any>("/learning/dashboard"),
  learningSummary: () => getJson<any>("/api/learning-intelligence/summary"),
  dashboardSnapshot: (snapshotType: string) => getJson<any>(`/api/dashboard-snapshots/${encodeURIComponent(snapshotType)}`),
  startupStatus: () => getJson<any>("/startup/status"),
  learningRuns: (limit = 50) => getJson<any[]>(`/learning/runs?limit=${limit}`),
  learningPredictions: (limit = 80, ticker?: string) => getJson<any[]>(`/learning/predictions?limit=${limit}${ticker ? `&ticker=${encodeURIComponent(ticker)}` : ""}`),
  learningMemory: (limit = 40) => getJson<any>(`/learning/memory?limit=${limit}`),
  runBlumLearningLoop: (batchSize = 25) => postJson<any>(`/learning/run-cycle?batch_size=${batchSize}`, {}),
  reasoningCoreStatus: () => getJson<any>("/model/reasoning-core/status"),
  reasoningCoreDiagnostics: () => getJson<any>("/model/reasoning-core/diagnostics"),
  thesisSurvival: (limit = 40) => getJson<any>(`/model/thesis-survival?limit=${limit}`),
  convictionDecay: (limit = 40) => getJson<any>(`/model/conviction-decay?limit=${limit}`),
  reliabilityByRegime: (limit = 40) => getJson<any>(`/model/reliability-by-regime?limit=${limit}`),
  thesisCompetitions: (limit = 30) => getJson<any>(`/model/thesis-competitions?limit=${limit}`),
  ensembleStatus: () => getJson<any>("/model/ensemble/status"),
  benchmarkRelative: (limit = 40) => getJson<any>(`/model/benchmark-relative?limit=${limit}`),
  trainingQuality: (limit = 40) => getJson<any>(`/model/training/quality?limit=${limit}`),
  sniperStatus: () => getJson<any>("/api/sniper/status"),
  sniperCandidates: (limit = 40, persist = false) => getJson<any>(`/api/sniper/candidates?limit=${limit}&persist=${persist ? "true" : "false"}`),
  sniperCandidate: (ticker: string, persist = false) => getJson<any>(`/api/sniper/candidates/${encodeURIComponent(ticker)}?persist=${persist ? "true" : "false"}`),
  sniperEvaluate: (limit = 40, tickers?: string) => postJson<any>(`/api/sniper/evaluate?limit=${limit}${tickers ? `&tickers=${encodeURIComponent(tickers)}` : ""}`, {}),
  sniperSimulate: (limit = 120, ticker?: string) => postJson<any>(`/api/sniper/simulate?limit=${limit}${ticker ? `&ticker=${encodeURIComponent(ticker)}` : ""}`, {}),
  sniperSetups: () => getJson<any[]>("/api/sniper/setups"),
  sniperRegimes: (limit = 80) => getJson<any[]>(`/api/sniper/regimes?limit=${limit}`),
  sniperMetrics: () => getJson<any>("/api/sniper/metrics"),
  sniperLessons: (limit = 40) => getJson<any[]>(`/api/sniper/lessons?limit=${limit}`),
  tradingGameStatus: () => getJson<any>("/api/trading-game/status"),
  tradingGameReadiness: () => getJson<any>("/api/trading-game/readiness"),
  copyTradingStatus: () => getJson<any>("/api/copy-trading/status"),
  copyTradingCandidates: (limit = 25) => getJson<any>(`/api/copy-trading/candidates?limit=${limit}`),
  copyTradingDashboard: (limit = 25) => getJson<any>(`/api/copy-trading/dashboard?limit=${limit}`),
  alphaReadiness: () => getJson<any>("/api/alpha/readiness"),
  alphaEdgeMap: (limit = 12) => getJson<any>(`/api/alpha/edge-map?limit=${limit}`),
  alphaGates: () => getJson<any>("/api/alpha/gates"),
  paperCopySummary: (limit = 12) => getJson<any>(`/api/paper-copy/summary?limit=${limit}`),
  paperCopyReadiness: () => getJson<any>("/api/paper-copy/readiness"),
  paperCopyStrategies: (limit = 40) => getJson<any>(`/api/paper-copy/strategies?limit=${limit}`),
  paperCopyPositions: (limit = 80) => getJson<any>(`/api/paper-copy/positions?limit=${limit}`),
  paperCopyPortfolio: (portfolioId: string) => getJson<any>(`/api/paper-copy/portfolio/${encodeURIComponent(portfolioId)}`),
  tradingGameRun: (batchSize = 60) => postJson<any>(`/api/trading-game/run?batch_size=${batchSize}`, {}),
  tradingGameReset: () => postJson<any>("/api/trading-game/reset", {}),
  tradingGameEquity: (limit = 500, gameId?: number) => getJson<any[]>(`/api/trading-game/equity?limit=${limit}${gameId ? `&game_id=${gameId}` : ""}`),
  tradingGameAnnotatedEquity: (limit = 800, gameId?: number) => getJson<any>(`/api/trading-game/equity/annotated?limit=${limit}${gameId ? `&game_id=${gameId}` : ""}`),
  tradingGameTrades: (limit = 200, gameId?: number) => getJson<any[]>(`/api/trading-game/trades?limit=${limit}${gameId ? `&game_id=${gameId}` : ""}`),
  tradingGameLedger: (limit = 200, gameId?: number) => getJson<any>(`/api/trading-game/ledger?limit=${limit}${gameId ? `&game_id=${gameId}` : ""}`),
  tradingGameLedgerSummary: (gameId?: number) => getJson<any>(`/api/trading-game/ledger/summary${gameId ? `?game_id=${gameId}` : ""}`),
  tradingGameLedgerByTicker: (ticker: string, limit = 200) => getJson<any>(`/api/trading-game/ledger/by-ticker/${encodeURIComponent(ticker)}?limit=${limit}`),
  tradingGameLedgerBySetup: (setupType: string, limit = 200) => getJson<any>(`/api/trading-game/ledger/by-setup/${encodeURIComponent(setupType)}?limit=${limit}`),
  tradingGameLedgerByOutcome: (outcomeLabel: string, limit = 200) => getJson<any>(`/api/trading-game/ledger/by-outcome/${encodeURIComponent(outcomeLabel)}?limit=${limit}`),
  tradingGameLedgerByCycle: (cycleId: number, limit = 500) => getJson<any>(`/api/trading-game/ledger/by-cycle/${cycleId}?limit=${limit}`),
  tradingGameTradeDetail: (tradeId: number) => getJson<any>(`/api/trading-game/trades/${tradeId}`),
  tradingGameTradeAttribution: (tradeId: number) => getJson<any[]>(`/api/trading-game/trades/${tradeId}/attribution`),
  tradingGameTradeQuality: (tradeId: number) => getJson<any>(`/api/trading-game/trades/${tradeId}/quality`),
  tradingGameTradePnlBreakdown: (tradeId: number) => getJson<any>(`/api/trading-game/trades/${tradeId}/pnl-breakdown`),
  tradingGameFailures: (limit = 80) => getJson<any[]>(`/api/trading-game/failures?limit=${limit}`),
  tradingGameLessons: (limit = 50) => getJson<any[]>(`/api/trading-game/lessons?limit=${limit}`),
  tradingGameBenchmark: (gameId?: number) => getJson<any>(`/api/trading-game/benchmark${gameId ? `?game_id=${gameId}` : ""}`),
  tradingGameReproducibility: (limit = 120) => getJson<any>(`/api/trading-game/reproducibility?limit=${limit}`),
  tradingGameLearningEvidence: (limit = 120) => getJson<any>(`/api/trading-game/learning-evidence?limit=${limit}`),
  tradingGameRealityCheck: (gameId?: number) => getJson<any>(`/api/trading-game/reality-check${gameId ? `?game_id=${gameId}` : ""}`),
  tradingGamePnlBreakdown: (gameId?: number) => getJson<any>(`/api/trading-game/pnl-breakdown${gameId ? `?game_id=${gameId}` : ""}`),
  tradingGameCycles: (limit = 100, gameId?: number) => getJson<any>(`/api/trading-game/cycles?limit=${limit}${gameId ? `&game_id=${gameId}` : ""}`),
  tradingGameCurrentCycle: (gameId?: number) => getJson<any>(`/api/trading-game/cycles/current${gameId ? `?game_id=${gameId}` : ""}`),
  tradingGameCycleStats: (gameId?: number) => getJson<any>(`/api/trading-game/cycles/stats${gameId ? `?game_id=${gameId}` : ""}`),
  tradingGameCycleDetail: (cycleId: number) => getJson<any>(`/api/trading-game/cycles/${cycleId}`),
  tradingGameCycleReset: (gameId?: number) => postJson<any>(`/api/trading-game/cycles/reset${gameId ? `?game_id=${gameId}` : ""}`, {}),
  tradingGameIntelligenceMetrics: (gameId?: number) => getJson<any>(`/api/trading-game/intelligence-metrics${gameId ? `?game_id=${gameId}` : ""}`),
  tradingGameIntelligenceRolling: (gameId?: number) => getJson<any>(`/api/trading-game/intelligence-metrics/rolling${gameId ? `?game_id=${gameId}` : ""}`),
  tradingGameIntelligenceBySetup: (gameId?: number) => getJson<any>(`/api/trading-game/intelligence-metrics/by-setup${gameId ? `?game_id=${gameId}` : ""}`),
  tradingGameIntelligenceByRegime: (gameId?: number) => getJson<any>(`/api/trading-game/intelligence-metrics/by-regime${gameId ? `?game_id=${gameId}` : ""}`),
  tradingGameIntelligenceBySector: (gameId?: number) => getJson<any>(`/api/trading-game/intelligence-metrics/by-sector${gameId ? `?game_id=${gameId}` : ""}`),
  tradingGameIntelligenceByCycle: (gameId?: number) => getJson<any>(`/api/trading-game/intelligence-metrics/by-cycle${gameId ? `?game_id=${gameId}` : ""}`),
  tradingGameHistoricalVsLive: () => getJson<any>("/api/trading-game/historical-vs-live"),
  liveTradingGameStatus: () => getJson<any>("/api/live-trading-game/status"),
  liveTradingGameRunCycle: () => postJson<any>("/api/live-trading-game/run-cycle", {}),
  liveTradingGamePositions: () => getJson<any>("/api/live-trading-game/positions"),
  liveTradingGameTrades: () => getJson<any>("/api/live-trading-game/trades"),
  liveTradingGameLedger: (limit = 200) => getJson<any>(`/api/live-trading-game/ledger?limit=${limit}`),
  liveTradingGameEquity: () => getJson<any>("/api/live-trading-game/equity"),
  liveTradingGameMetrics: () => getJson<any>("/api/live-trading-game/metrics"),
  liveTradingGameCompareHistorical: () => getJson<any>("/api/live-trading-game/compare-historical"),
  learningIntelligenceDashboard: () => getJson<any>("/api/learning-intelligence/dashboard"),
  learningTradingPower: () => getJson<any>("/api/learning-intelligence/trading-power"),
  recalculateLearningTradingPower: () => postJson<any>("/api/learning-intelligence/trading-power/recalculate", {}),
  learningBenchmarks: () => getJson<any>("/api/learning-intelligence/benchmarks"),
  learningBenchmark: (benchmarkName: string) => getJson<any>(`/api/learning-intelligence/benchmarks/${encodeURIComponent(benchmarkName)}`),
  recalculateLearningBenchmarks: () => postJson<any>("/api/learning-intelligence/benchmarks/recalculate", {}),
  learningProgress: () => getJson<any>("/api/learning-intelligence/progress"),
  learningProgressRolling: () => getJson<any>("/api/learning-intelligence/progress/rolling"),
  learningProgressBySetup: () => getJson<any>("/api/learning-intelligence/progress/by-setup"),
  learningProgressByRegime: () => getJson<any>("/api/learning-intelligence/progress/by-regime"),
  learningWeaknessMap: () => getJson<any>("/api/learning-intelligence/weakness-map"),
  learningWeaknessBySetup: () => getJson<any>("/api/learning-intelligence/weakness-map/by-setup"),
  learningWeaknessByRegime: () => getJson<any>("/api/learning-intelligence/weakness-map/by-regime"),
  learningWeaknessBySector: () => getJson<any>("/api/learning-intelligence/weakness-map/by-sector"),
  learningWeaknessByEngine: () => getJson<any>("/api/learning-intelligence/weakness-map/by-engine"),
  learningSelfImprovementActions: (limit = 80) => getJson<any>(`/api/learning-intelligence/self-improvement/actions?limit=${limit}`),
  generateLearningSelfImprovement: () => postJson<any>("/api/learning-intelligence/self-improvement/generate", {}),
  applyLearningSelfImprovement: (actionId: number) => postJson<any>(`/api/learning-intelligence/self-improvement/apply/${actionId}`, {}),
  evaluateLearningSelfImprovement: (actionId: number) => postJson<any>(`/api/learning-intelligence/self-improvement/evaluate/${actionId}`, {}),
  decisionIntelligenceDashboard: () => getJson<any>("/api/decision-intelligence/dashboard"),
  decisionSuperiority: () => getJson<any>("/api/decision-intelligence/superiority"),
  recalculateDecisionSuperiority: () => postJson<any>("/api/decision-intelligence/superiority/recalculate", {}),
  decisionUniverseSnapshots: () => getJson<any>("/api/decision-intelligence/universe-snapshots"),
  recalculateDecisionUniverseSnapshots: () => postJson<any>("/api/decision-intelligence/universe-snapshots/recalculate", {}),
  missedOpportunities: () => getJson<any>("/api/decision-intelligence/missed-opportunities"),
  businessQualityDashboard: () => getJson<any>("/api/business-quality/dashboard"),
  businessQualityScores: (limit = 80) => getJson<any>(`/api/business-quality/scores?limit=${limit}`),
  recalculateBusinessQuality: (limit = 80) => postJson<any>(`/api/business-quality/recalculate?limit=${limit}`, {}),
  portfolioIntelligenceDashboard: () => getJson<any>("/api/portfolio-intelligence/dashboard"),
  portfolioQuality: () => getJson<any>("/api/portfolio-intelligence/quality"),
  recalculatePortfolioIntelligence: () => postJson<any>("/api/portfolio-intelligence/recalculate", {}),
  capitalAllocationDashboard: () => getJson<any>("/api/capital-allocation/dashboard"),
  alphaRecoveryDashboard: () => getJson<any>("/api/alpha-recovery/dashboard"),
  recalculateAlphaRecovery: (benchmarkName?: string) => postJson<any>(`/api/alpha-recovery/recalculate${benchmarkName ? `?benchmark_name=${encodeURIComponent(benchmarkName)}` : ""}`, {}),
  alphaRecoveryMethodology: (limit = 40) => getJson<any>(`/api/alpha-recovery/methodology?limit=${limit}`),
  alphaRecoveryAttribution: (limit = 120) => getJson<any>(`/api/alpha-recovery/attribution?limit=${limit}`),
  alphaRecoveryMissedWinners: (limit = 80) => getJson<any>(`/api/alpha-recovery/missed-winners?limit=${limit}`),
  alphaRecoveryActions: (limit = 80) => getJson<any>(`/api/alpha-recovery/actions?limit=${limit}`),
  alphaRecoveryReplayPriorities: (limit = 30) => getJson<any>(`/api/alpha-recovery/replay-priorities?limit=${limit}`),
  metaCognitionSummary: () => getJson<any>("/api/meta-cognition/summary"),
  metaCognitionRecalculate: () => postJson<any>("/api/meta-cognition/recalculate", {}),
  metaFactorImportance: (limit = 120) => getJson<any>(`/api/meta-cognition/factor-importance?limit=${limit}`),
  recalculateMetaFactorImportance: () => postJson<any>("/api/meta-cognition/factor-importance/recalculate", {}),
  metaCognitionEvents: (limit = 120) => getJson<any>(`/api/meta-cognition/events?limit=${limit}`),
  evaluateMetaCognition: () => postJson<any>("/api/meta-cognition/evaluate", {}),
  metaCapitalPreservation: (limit = 120) => getJson<any>(`/api/meta-cognition/capital-preservation?limit=${limit}`),
  evaluateMetaCapitalPreservation: () => postJson<any>("/api/meta-cognition/capital-preservation/evaluate", {}),
  metaLearningFocus: (limit = 80) => getJson<any>(`/api/meta-cognition/learning-focus?limit=${limit}`),
  generateMetaLearningFocus: () => postJson<any>("/api/meta-cognition/learning-focus/generate", {}),
  metaReasoningNoise: (limit = 80) => getJson<any>(`/api/meta-cognition/noise?limit=${limit}`),
  detectMetaReasoningNoise: () => postJson<any>("/api/meta-cognition/noise/detect", {}),
  chartAnalyzeTicker: (ticker: string, timeframe = "6M", period = "1y", includeVisual = false) => getPostChart<ChartReport>(`/chart/analyze-ticker?ticker=${encodeURIComponent(ticker)}&timeframe=${encodeURIComponent(timeframe)}&period=${encodeURIComponent(period)}&include_visual=${includeVisual ? "true" : "false"}`),
  chartTechnicalReport: (ticker: string, timeframe = "6M") => getJson<ChartReport>(`/chart/technical-report/${encodeURIComponent(ticker)}?timeframe=${encodeURIComponent(timeframe)}`),
  chartLevels: (ticker: string, timeframe = "6M") => getJson<any>(`/chart/levels/${encodeURIComponent(ticker)}?timeframe=${encodeURIComponent(timeframe)}`),
  chartSignals: (ticker: string, timeframe = "6M") => getJson<any[]>(`/chart/signals/${encodeURIComponent(ticker)}?timeframe=${encodeURIComponent(timeframe)}`),
  chartHistory: (ticker: string, limit = 30) => getJson<any[]>(`/chart/history/${encodeURIComponent(ticker)}?limit=${limit}`),
  assets: () => getJson<Asset[]>("/assets"),
  asset: (ticker: string) => getJson<{ asset: Asset; market_snapshot: Asset["market_snapshot"]; prices: any[]; latest_signal: Signal | null; related_news: RelatedNews[] }>(`/assets/${encodeURIComponent(ticker)}`),
  overview: () => getJson<DashboardOverview>("/dashboard/overview"),
  liveNews: (limit = 60) => getJson<LiveNewsArticle[]>(`/news/live?limit=${limit}`),
  marketSentiment: (hours = 48) => getJson<MarketSentiment>(`/sentiment/market?hours=${hours}`),
  dataCoverage: () => getJson<DataCoverage>("/data/coverage"),
  repairData: (limit = 36) => postJson<any>(`/data/repair?limit=${limit}`, {}),
  accuracyOverview: () => getJson<AccuracyOverview>("/accuracy/overview"),
  runAccuracy: (limit = 80) => postJson<any>(`/accuracy/run?limit=${limit}`, {}),
  assetAccuracy: (ticker: string) => getJson<AccuracyProfile>(`/accuracy/${encodeURIComponent(ticker)}`),
  signalValidation: (limit = 240) => getJson<SignalValidationReport>(`/validation/signals?limit=${limit}`),
  macroOverview: () => getJson<MacroOverview>("/macro/overview"),
  updateMacro: () => postJson<any>("/macro/update", {}),
  updateFundamentals: (limit = 24) => postJson<any>(`/fundamentals/update?limit=${limit}`, {}),
  fundamentals: (ticker: string) => getJson<any>(`/fundamentals/${encodeURIComponent(ticker)}`),
  executiveDashboard: () => getJson<ExecutiveDashboardPayload>("/intelligence/executive"),
  opportunityRadar: (limit = 30) => getJson<OpportunityRadarPayload>(`/intelligence/opportunities?limit=${limit}`),
  marketNarrative: () => getJson<MarketNarrativePayload>("/intelligence/narrative"),
  communitySentiment: () => getJson<CommunitySentimentPayload>("/intelligence/community"),
  watchlist: () => getJson<WatchlistPayload>("/intelligence/watchlist"),
  addWatchlist: (ticker: string, thesis = "") => postJson<WatchlistPayload>(`/intelligence/watchlist/${encodeURIComponent(ticker)}?thesis=${encodeURIComponent(thesis)}`, {}),
  portfolioScenario: (riskProfile = "balanced") => getJson<PortfolioScenarioPayload>(`/intelligence/portfolio-scenario?risk_profile=${encodeURIComponent(riskProfile)}`),
  intelligenceReport: (ticker: string) => getJson<any>(`/intelligence/reports/${encodeURIComponent(ticker)}`),
  similarBacktest: (ticker: string) => getJson<any>(`/intelligence/backtest/${encodeURIComponent(ticker)}`),
  pipelineStatus: () => getJson<PipelineStatus>("/pipeline/status"),
  topSignals: (query = "") => getJson<Signal[]>(`/signals/top${query}`),
  signal: (ticker: string) => getJson<Signal>(`/signals/${ticker}`),
  sentiment: (ticker: string) => getJson<any[]>(`/sentiment/${ticker}`),
  explain: (ticker: string) => getJson<any>(`/ai/explain/${ticker}`),
  relatedNews: (ticker: string) => getJson<RelatedNews[]>(`/related-news?ticker=${ticker}`),
  themes: () => getJson<any[]>("/themes"),
  themeDetail: (label: string) => getJson<any>(`/themes/${encodeURIComponent(label)}`),
  etfTrends: () => getJson<any[]>("/etf-trends"),
  stockRadar: (limit = 80) => getJson<StockRadar>(`/stock-radar?limit=${limit}`),
  updateStockRadar: (limit = 36) => postJson<any>(`/stock-radar/update?limit=${limit}`, {}),
  ipoRadar: (limit = 80) => getJson<IPORadar>(`/ipo-radar?limit=${limit}`),
  updateIpoRadar: (limitPerForm = 50) => postJson<any>(`/ipo-radar/update?limit_per_form=${limitPerForm}`, {}),
  secSubmissions: (cik: string, persist = false) => getJson<any>(`/ipo-radar/sec-submissions/${cik}?persist=${persist ? "true" : "false"}`),
  marketBrain: () => getJson<MarketBrain>("/market-brain"),
  marketBrainHistory: (limit = 20) => getJson<MarketBrainHistoryRow[]>(`/market-brain/history?limit=${limit}`),
  runMarketBrain: (refreshPipeline = false) => postJson<MarketBrain>(`/market-brain/run?refresh_pipeline=${refreshPipeline ? "true" : "false"}&refresh_sec=true`, {}),
  modelStatus: () => getJson<any>("/ai/models/status"),
  semanticSearch: (query: string) => postJson<any[]>("/semantic-search", { query, limit: 12 }),
  financialChat: (payload: { message: string; tickers?: string[]; horizon?: string; risk_profile?: string; include_semantic_search?: boolean; language?: string; session_id?: string; mode?: string }) =>
    postJson<FinancialChatResponse>("/api/chat", payload),
  financialChatContext: () => getJson<any>("/api/chat/context"),
  financialChatHistory: (limit = 80) => getJson<any[]>(`/api/chat/history?limit=${limit}`),
  marketUpdate: () => postJson("/market/update", { period: "max", limit: 36 }),
  newsUpdate: () => postJson("/news/update", { lookback_hours: 72, limit_per_feed: 35 }),
  runSignals: () => postJson("/signals/run", { refresh_prices: false, limit: 36 }),
  runPipeline: () => postJson<any>("/pipeline/run", { refresh_prices: false, limit: 36 }),
  backtest: (ticker: string) => postJson<any>(`/backtest/${ticker}`, {})
};

function getPostChart<T>(path: string): Promise<T> {
  return postJson<T>(path, {});
}
