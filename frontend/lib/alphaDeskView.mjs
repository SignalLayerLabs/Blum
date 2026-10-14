export function alphaMetric(value, unit = '') {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(3)}${unit}` : '—';
}

export function alphaMarketView(data, market) {
  const source = data?.markets?.[market] ?? {};
  return {
    registered: source.registered ?? 0,
    qualifiedClosed: source.qualified_closed ?? 0,
    paired: source.paired_sample ?? 0,
    alpha: source.mean_paired_excess_percent ?? null,
    pnl: source.observed_net_pnl ?? null,
    interval: source.paired_interval ?? {},
    verdict: source.verdict ?? 'INSUFFICIENT_EVIDENCE',
    active: source.active_calls ?? [],
    exclusions: source.exclusions ?? {},
  };
}
