export function alphaMetric(value: unknown, unit?: string): string;
export function alphaMarketView(data: any, market: string): {
  registered: number; qualifiedClosed: number; paired: number; alpha: number | null;
  pnl: number | null; interval: any; verdict: string; active: any[]; exclusions: Record<string, number>;
};
