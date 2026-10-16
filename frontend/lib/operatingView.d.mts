export function finiteMetric(value: unknown): number | null;
export function tradeLifecycle(row: any): string;
export function tradeMoney(row: any): {
  net: number | null;
  gross: number | null;
  currency: string | null;
};
export function tradeCostLines(
  row: any,
): { label: string; amount: number; currency: string | null }[];
export function operatingMarket(
  sources?: { paper?: any; desk?: any },
  market?: string,
): {
  available: boolean;
  registered: number | null;
  open: number | null;
  closed: number | null;
  noFill: number | null;
  rejected: number | null;
  winRate: number | null;
  expectancyR: number | null;
  qualifiedClosed: number | null;
  paired: number | null;
  realized: number | null;
  currency: string | null;
  pnlByCurrency: Record<string, number>;
  verdict: string;
  exclusions: Record<string, number>;
};
export function callState(
  desk: any,
  market?: string,
): { status: string; active: any[]; current: boolean };
export function engineEvidence(
  sources?: { brain?: any; desk?: any },
  market?: string,
): {
  level: string;
  paired: number | null;
  qualified: number | null;
  cycles: number | null;
  calibratedProbability: null;
};
export function utcTimestamp(value: unknown): number | null;
export function snapshotAge(
  value: unknown,
  now?: number,
): { state: string; seconds: number | null };
