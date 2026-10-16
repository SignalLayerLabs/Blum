/** Display evidence without upgrading its currency, provenance or strength. */
export function finiteMetric(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function tradeLifecycle(row) {
  const status = String(row?.status ?? "").toUpperCase();
  const filled =
    utcTimestamp(row?.opened_at) !== null &&
    finiteMetric(row?.entry_price) > 0 &&
    finiteMetric(row?.position_size) > 0;
  if (["OPEN", "MANAGED", "PARTIALLY_FILLED"].includes(status))
    return filled ? "open" : "unverified";
  if (["CLOSED", "EXPIRED", "INVALIDATED", "CANCELLED"].includes(status))
    return filled ? "closed" : status === "CLOSED" ? "unverified" : "unfilled";
  return "decisions";
}

export function tradeMoney(row) {
  const currency =
    typeof row?.pnl_currency === "string" && /^[A-Z]{3}$/.test(row.pnl_currency)
      ? row.pnl_currency
      : null;
  if (currency)
    return {
      net: finiteMetric(row.net_pnl),
      gross: finiteMetric(row.gross_pnl),
      currency,
    };
  if (
    row?.source_engine === "paper_forward" &&
    !Object.hasOwn(row, "pnl_currency")
  )
    return {
      net: finiteMetric(row.net_pnl_eur),
      gross: finiteMetric(row.gross_pnl_eur),
      currency: "EUR",
    };
  return { net: null, gross: null, currency: null };
}

export function tradeCostLines(row) {
  const costs = row?.costs ?? {};
  const cash = costs.accounting;
  const fields =
    cash && typeof cash === "object" && Object.keys(cash).length
      ? [
          ["Entry commission", cash.entry_commission],
          ["Entry FX charge", cash.entry_fx_cost],
          ["Exit commission", cash.exit_commission],
          ["Exit FX charge", cash.exit_fx_cost],
          ["Explicit cash charges", cash.explicit_costs],
        ]
      : [
          ["Spread", costs.spread_cost ?? costs.spread],
          ["Slippage", costs.slippage_cost ?? costs.slippage],
          ["Commission", costs.commission_cost ?? costs.commission],
          ["FX charge", costs.fx_cost],
          ["Borrow charge", costs.borrow_cost],
          ["Gap charge", costs.gap_cost],
          ["Swap credit (+) / charge (−)", costs.swap],
          ["Reported net execution cost", costs.total],
        ];
  const currency = tradeMoney(row).currency;
  return fields
    .filter(([, value]) => finiteMetric(value) !== null)
    .map(([label, amount]) => ({ label, amount, currency }));
}

export function operatingMarket({ paper, desk } = {}, market = "equity") {
  const key = market === "forex" ? "forex" : "equities";
  const counts = paper?.counts?.by_market?.[key];
  const metrics = paper?.metrics?.by_market?.[key];
  const qualified = desk?.markets?.[market];
  const currency =
    typeof qualified?.pnl_currency === "string" ? qualified.pnl_currency : null;
  const pnlByCurrency = Object.fromEntries(
    Object.entries(qualified?.observed_net_pnl_by_currency ?? {}).filter(
      ([, value]) => finiteMetric(value) !== null,
    ),
  );
  return {
    available: Boolean(counts || metrics || qualified),
    registered: finiteMetric(qualified?.registered),
    open: finiteMetric(counts?.open),
    closed: finiteMetric(counts?.closed),
    noFill: finiteMetric(counts?.no_fill_outcomes),
    rejected: finiteMetric(counts?.decisions_rejected),
    winRate: finiteMetric(metrics?.win_rate),
    expectancyR: finiteMetric(metrics?.expectancy_r),
    qualifiedClosed: finiteMetric(qualified?.qualified_closed),
    paired: finiteMetric(qualified?.paired_sample),
    realized: currency ? finiteMetric(qualified?.observed_net_pnl) : null,
    currency,
    pnlByCurrency,
    verdict: qualified?.verdict ?? "UNAVAILABLE",
    exclusions: qualified?.exclusions ?? {},
  };
}

export function callState(desk, market = "equity") {
  const source = desk?.markets?.[market];
  if (!source) return { status: "UNAVAILABLE", active: [] };
  const terminal = new Set(["CLOSED", "EXPIRED", "INVALIDATED", "CANCELLED"]);
  const active = (source.active_calls ?? []).filter(
    (row) =>
      row.active_eligible === true &&
      !terminal.has(String(row.status).toUpperCase()),
  );
  return {
    status: active.length ? "CURRENT_RESEARCH_CALLS" : "NO_ACTIVE_CALL",
    active,
  };
}

export function engineEvidence({ brain, desk } = {}, market = "equity") {
  const source = desk?.markets?.[market];
  const paired = finiteMetric(source?.paired_sample);
  const qualified = finiteMetric(source?.qualified_closed);
  const level = !source
    ? "UNAVAILABLE"
    : source.paired_interval?.positive_sample === true
      ? "POSITIVE_PAIRED_SAMPLE"
      : paired > 0
        ? "BENCHMARK_EVALUATION"
        : qualified > 0
          ? "OUTCOMES_ACCUMULATING"
          : "COLLECTING_EVIDENCE";
  return {
    level,
    paired,
    qualified,
    cycles: finiteMetric(brain?.learning_proof?.cycles_observed),
    calibratedProbability: null,
  };
}

export function utcTimestamp(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T/.test(value))
    return null;
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : value + "Z";
  const stamp = Date.parse(normalized);
  return Number.isFinite(stamp) ? stamp : null;
}

export function snapshotAge(value, now = Date.now()) {
  const stamp = utcTimestamp(value);
  if (stamp === null) return { state: "unknown", seconds: null };
  const seconds = (now - stamp) / 1000;
  if (seconds < -5) return { state: "future", seconds };
  return {
    state: seconds > 300 ? "stale" : "recent",
    seconds: Math.max(0, seconds),
  };
}
