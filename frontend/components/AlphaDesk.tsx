"use client";

import { BloombergPanel } from "@/components/FinancialTerminal";
import { StatusBadge } from "@/components/StatusBadge";
import { alphaMarketView, alphaMetric } from "@/lib/alphaDeskView.mjs";

export function AlphaDesk({ data }: { data: any }) {
  if (!data) return <BloombergPanel title="Prospective Alpha Desk" value="unavailable"><p>The call registry is unavailable. Performance is not inferred from legacy records.</p></BloombergPanel>;
  return (
    <section aria-label="Prospective Alpha Desk" style={{ marginBottom: 16 }}>
      <BloombergPanel title="Prospective Alpha Desk" value={`${data.registered_count ?? 0} registered`} subtitle="Calls recorded before outcomes. Equities and Forex are evaluated separately.">
        <p style={{ color: "var(--text-secondary)", marginBottom: 12 }}>Only registered calls with causal inputs, valid fills and reconciled costs qualify. Imported history cannot create a forward track record. Confidence remains a heuristic.</p>
        <div className="grid-2">
          <Market data={data} market="equity" title="Equities / ETFs" />
          <Market data={data} market="forex" title="Forex" />
        </div>
        <p style={{ color: "var(--text-secondary)", marginTop: 12 }}>Window: {data.window?.evaluated ?? 0} of {data.registered_count ?? 0} registrations, maximum {data.window?.limit ?? "—"}. {data.window?.truncated ? "Earlier registrations are outside this bounded read." : "All current registrations are included."} A positive paired sample requires 100 observations, 30 closure dates and three assets. The interval does not certify strategy promotion or competitor superiority.</p>
        <p style={{ color: "var(--text-secondary)" }}>Recovery: {data.durability?.mode === "embedded_postgres" ? "periodic backups; the latest updates may be absent after a restart" : "external database; guarantees depend on its recovery configuration"}.</p>
      </BloombergPanel>
      <BloombergPanel title="Registered Call Journal" value={`${data.journal?.length ?? 0} shown`} subtitle="Original decisions, source integrity and explicit exclusions." dense>
        <div style={{ overflowX: "auto" }}>
          <table className="terminal-table" aria-label="Registered alpha calls">
            <thead><tr><th>Asset / market</th><th>Recorded UTC</th><th>Direction / state</th><th>Source</th><th>Net account P/L</th><th>Paired excess</th><th>Qualification</th></tr></thead>
            <tbody>{(data.journal ?? []).map((call: any) => <tr key={call.source_uid}>
              <td>{call.asset}<br /><small>{call.market}</small></td>
              <td>{call.registered_at?.replace("T", " ")}<br /><small title={call.input_sha256}>Input {call.input_sha256?.slice(0, 12)}</small></td>
              <td>{call.direction ?? "unknown"}<br /><small>{call.status}</small></td>
              <td>{call.provider ?? "unattributed"}<br /><small>{call.quote_at?.replace("T", " ") ?? "timestamp missing"}</small></td>
              <td>{alphaMetric(call.net_pnl)}</td><td>{alphaMetric(call.paired_excess_percent, "%")}</td>
              <td>{call.qualified_closed ? "Cost-qualified close" : call.outcome_status}<br /><small>{call.blockers?.join(" · ") || "No current blocker"}</small></td>
            </tr>)}</tbody>
          </table>
          {!data.journal?.length && <p className="terminal-empty">No prospective calls registered yet. Existing historical and paper records remain descriptive evidence below.</p>}
        </div>
      </BloombergPanel>
    </section>
  );
}

function Market({ data, market, title }: { data: any; market: string; title: string }) {
  const view = alphaMarketView(data, market);
  return <BloombergPanel title={title} value={view.verdict.replaceAll("_", " ")} subtitle="No samples or performance pooled across markets.">
    <StatusBadge label={view.verdict} />
    <div className="brain-list dense" style={{ marginTop: 10 }}>
      <div><span>Registered / cost-qualified / paired</span><strong>{view.registered} / {view.qualifiedClosed} / {view.paired}</strong></div>
      <div><span>Mean paired excess</span><strong>{alphaMetric(view.alpha, "%")}</strong></div>
      <div><span>95% closure-date interval</span><strong>{alphaMetric(view.interval.lower_95, "%")} to {alphaMetric(view.interval.upper_95, "%")}</strong></div>
      <div><span>Closure dates / assets</span><strong>{view.interval.dates ?? 0} / {view.interval.assets ?? 0}</strong></div>
      <div><span>Observed net account P/L</span><strong>{alphaMetric(view.pnl)}</strong></div>
    </div>
    <h3 style={{ marginTop: 14 }}>Current qualified calls</h3>
    {view.active.map((call: any) => <div className="brain-list dense" key={call.source_uid}>
      <div><strong>{call.asset} · {call.direction}</strong><p>Entry {alphaMetric(call.entry)} · Stop {alphaMetric(call.stop)} · Target {alphaMetric(call.target)}</p><span>Stored expected net edge: {alphaMetric(call.expected_net_edge)} {call.edge_units}. {call.model}</span></div>
    </div>)}
    {!view.active.length && <p>No current call passes the source, freshness and stored-edge gates.</p>}
    <details style={{ marginTop: 10 }}><summary>Excluded evidence</summary>{Object.entries(view.exclusions).map(([reason, count]) => <p key={reason}>{reason.replaceAll("_", " ")}: {count}</p>)}{!Object.keys(view.exclusions).length && <p>No recorded exclusions in this window.</p>}</details>
  </BloombergPanel>;
}
