"use client";
import { useState } from "react";
import { callState, operatingMarket } from "@/lib/operatingView.mjs";
import { useSnapshots, callReaders } from "./useSnapshots";
import {
  Empty,
  Freshness,
  MarketTabs,
  Metric,
  PageHeader,
  Panel,
  human,
  number,
  stamp,
} from "./Primitives";
export function Calls() {
  const { data, errors, pending, refresh } = useSnapshots(callReaders);
  const [market, setMarket] = useState("equity");
  const state = callState(data.desk, market);
  const view = operatingMarket(data, market);
  const rows = (data.desk?.journal ?? []).filter(
    (row: any) => row.market === market,
  );
  return (
    <div className="op-page">
      <PageHeader
        eyebrow="Decisions & timing"
        title="Calls, with their context."
        description="Separate a current research idea from a historical decision and an actual advance entry plan."
        pending={pending}
        onRefresh={refresh}
      />
      <div className="op-context">
        <MarketTabs market={market} onChange={setMarket} />
        <Freshness at={data.desk?.generated_at} error={errors.desk} />
      </div>
      <div className="op-metrics op-three">
        <Metric
          label="Recorded decisions"
          value={number(view.registered)}
          detail="Registered research, not a count of executed orders."
        />
        <Metric
          label="Current eligible research calls"
          value={data.desk ? number(state.active.length) : "—"}
          detail="Reported by the current qualification contract."
        />
        <Metric
          label="Qualified closed outcomes"
          value={number(view.qualifiedClosed)}
          detail="Only outcomes passing provenance and cost checks."
        />
      </div>
      <Panel
        title="Before the entry"
        description="An advance plan needs a publication time, earliest entry and expiry."
      >
        {state.active.length ? (
          <div className="op-call-list">
            {state.active.map((row: any) => (
              <article className="op-call-card" key={row.source_uid}>
                <span className="op-status">Research call</span>
                <h3>
                  {row.asset} · {human(row.direction)}
                </h3>
                <p>
                  Recorded {stamp(row.registered_at)}. Advance
                  publication-to-entry lead time is not established by this
                  registry.
                </p>
                <div className="op-call-levels">
                  <span>
                    Entry <strong>{number(row.entry, 5)}</strong>
                  </span>
                  <span>
                    Stop <strong>{number(row.stop, 5)}</strong>
                  </span>
                  <span>
                    Target <strong>{number(row.target, 5)}</strong>
                  </span>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <Empty
            title={
              state.status === "UNAVAILABLE"
                ? "Call evidence is unavailable"
                : "No advance plan is available"
            }
          >
            The current registry does not provide a verified
            publication-to-entry lead time. Past decisions below are not
            upcoming alerts. Availability of this view does not establish an
            actionable move.
          </Empty>
        )}
      </Panel>
      <Panel
        title="Decision journal"
        description="Recent visible records. The API exposes a bounded journal across both markets."
      >
        {rows.length ? (
          <div className="op-table-wrap">
            <table className="op-table">
              <thead>
                <tr>
                  <th>Asset</th>
                  <th>Decision</th>
                  <th>Registered</th>
                  <th>Qualification / reason</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row: any) => (
                  <tr key={row.source_uid}>
                    <td>
                      <strong>{row.asset}</strong>
                      <span>{row.provider ?? "Provider unavailable"}</span>
                    </td>
                    <td>
                      {human(row.status)}
                      <span>{human(row.direction)}</span>
                    </td>
                    <td>{stamp(row.registered_at)}</td>
                    <td>
                      <details>
                        <summary>
                          {row.active_eligible
                            ? "Current research call"
                            : human(row.blockers?.[0] ?? "Not qualified")}
                        </summary>
                        <p>
                          {(row.blockers ?? []).map(human).join(" · ") ||
                            "No exclusions reported."}
                        </p>
                        <p>
                          Source{" "}
                          {String(row.source_revision ?? "unavailable").slice(
                            0,
                            12,
                          )}{" "}
                          · input{" "}
                          {String(row.input_sha256 ?? "unavailable").slice(
                            0,
                            12,
                          )}
                        </p>
                        <p>
                          Confidence {number(row.confidence, 1)} — heuristic,
                          not a calibrated probability.
                        </p>
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title={
              data.desk
                ? "No records in the visible journal for this market"
                : "Loading the decision journal"
            }
          >
            A bounded empty journal does not prove that the full database
            contains no decisions.
          </Empty>
        )}
      </Panel>
      {errors.desk && (
        <div className="op-error-note" role="alert">
          <strong>The call record could not refresh.</strong>
          <p>
            {errors.desk} Use Refresh to retry; previous records retain their
            snapshot timestamp.
          </p>
        </div>
      )}
    </div>
  );
}
