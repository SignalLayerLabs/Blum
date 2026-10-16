export const CLOSED_PAPER_STATUSES = new Set(["CLOSED", "EXPIRED", "INVALIDATED"]);
export const OPEN_PAPER_STATUSES = new Set(["OPEN", "MANAGED", "PARTIALLY_FILLED"]);
export const CANDIDATE_PAPER_STATUSES = new Set(["CANDIDATE", "WAITING_FOR_TRIGGER", "SKIPPED", "DATA_BLOCKED", "ERROR"]);

export function normalizePaperStatus(value) {
  return String(value ?? "UNKNOWN").toUpperCase();
}

export function paperTradeKey(row) {
  return String(
    row.trade_id
      ?? row.trade_uid
      ?? `${row.source_engine ?? "paper"}-${row.source_trade_id ?? "unknown"}-${row.ticker ?? "unknown"}`,
  );
}

export function mergePaperTrades(snapshot) {
  const rows = [
    ...(snapshot?.trades ?? []),
    ...(snapshot?.latest_candidates ?? snapshot?.candidates ?? []),
    ...(snapshot?.open_positions ?? []),
    ...(snapshot?.recently_closed_trades ?? snapshot?.recently_closed ?? []),
    ...(snapshot?.executed_closures ?? []),
    ...(snapshot?.unfilled_orders ?? []),
  ];
  const byTrade = new Map();

  for (const row of rows) {
    const key = paperTradeKey(row);
    const previous = byTrade.get(key);
    if (!previous) {
      byTrade.set(key, row);
      continue;
    }

    const previousTerminal = CLOSED_PAPER_STATUSES.has(normalizePaperStatus(previous.status));
    const currentTerminal = CLOSED_PAPER_STATUSES.has(normalizePaperStatus(row.status));
    if (currentTerminal || !previousTerminal) {
      byTrade.set(key, { ...previous, ...row });
    }
  }

  return Array.from(byTrade.values());
}

export function isForexPaperTrade(row) {
  const ticker = String(row?.ticker ?? "").trim().toUpperCase();
  const market = String(row?.market ?? "").trim().toUpperCase();
  const assetType = String(row?.asset_type ?? "").trim().toUpperCase();
  return row?.market_group === "forex"
    || ticker.endsWith("=X")
    || market.includes("FOREX")
    || ["FX", "CURRENCY"].includes(market)
    || assetType.includes("FOREX")
    || ["FX", "CURRENCY", "CURRENCY_PAIR"].includes(assetType);
}

export function filterPaperMarket(rows, market) {
  return rows.filter((row) => market === "forex" ? isForexPaperTrade(row) : !isForexPaperTrade(row));
}

export function filterPaperLifecycle(rows, lifecycle) {
  const statuses = lifecycle === "closed"
    ? CLOSED_PAPER_STATUSES
    : lifecycle === "open"
      ? OPEN_PAPER_STATUSES
      : CANDIDATE_PAPER_STATUSES;
  return rows.filter((row) => statuses.has(normalizePaperStatus(row.status)));
}

export function formatPaperCurrency(value) {
  if (value === null || value === undefined || value === "") return "not realized";
  const number = Number(value);
  if (!Number.isFinite(number)) return "not realized";
  const absolute = Math.abs(number);
  const digits = absolute > 0 && absolute < 0.01 ? 6 : 2;
  const prefix = number > 0 ? "+" : "";
  return `${prefix}${number.toFixed(digits)} EUR`;
}

export function paperPnlTone(value) {
  if (value === null || value === undefined || value === "") return "neutral";
  const number = Number(value);
  if (!Number.isFinite(number) || number === 0) return "neutral";
  return number > 0 ? "positive" : "negative";
}
