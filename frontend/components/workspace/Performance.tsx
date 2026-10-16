"use client";

import { useState } from "react";
import {
  operatingMarket,
  engineEvidence,
  finiteMetric,
} from "@/lib/operatingView.mjs";
import { useSnapshots, performanceReaders } from "./useSnapshots";
import {
  Empty,
  Freshness,
  MarketTabs,
  Metric,
  PageHeader,
  Panel,
  human,
  number,
} from "./Primitives";
const percent = (value: unknown) =>
  finiteMetric(value) === null ? "—" : `${number(value, 4)}%`;

export function Performance() {
  const { data, errors, pending, refresh } = useSnapshots(performanceReaders);
  const [market, setMarket] = useState("equity");
  const view = operatingMarket(data, market);
  const evidence = engineEvidence(data, market);
  const sample = data.desk?.markets?.[market];
  const interval = sample?.paired_interval;
  const history =
    data.paper?.metrics?.by_market?.[market === "forex" ? "forex" : "equities"];
  return (
    <div className="op-page">
      <PageHeader
        eyebrow="Results & evidence"
        title="Is BLUM earning its edge?"
        description="A qualified outcome, a cost-aware result and an aligned benchmark. Evaluate each market on its own evidence."
        pending={pending}
        onRefresh={refresh}
      />
      <div className="op-context">
        <MarketTabs market={market} onChange={setMarket} />
        <Freshness
          at={data.desk?.generated_at}
          error={errors.desk}
          status={data.desk?.snapshot_status}
        />
      </div>
      <section className="op-verdict">
        <span className="op-eyebrow">PROSPECTIVE EVIDENCE</span>
        <h2>{human(view.verdict)}</h2>
        <p>
          {!sample
            ? "Qualified benchmark evidence is unavailable in the current response."
            : view.paired
              ? "Inspect the paired sample and uncertainty below. A positive sample alone does not establish a durable, deployable edge."
              : "There are no qualified benchmark-paired outcomes in this sample. Market outperformance has not been established."}
        </p>
        <span className="op-status">{human(evidence.level)}</span>
      </section>
      <div className="op-metrics">
        <Metric
          label="Qualified closures"
          value={number(view.qualifiedClosed)}
          detail="After provenance, execution and cost checks."
        />
        <Metric
          label="Benchmark-paired sample"
          value={number(view.paired)}
          detail="Outcomes with an aligned benchmark period."
        />
        <Metric
          label="Benchmark-paired assets"
          value={number(sample?.closed_coverage?.assets)}
          detail="Asset coverage of the benchmark-paired sample."
        />
        <Metric
          label="Benchmark-paired dates"
          value={number(sample?.closed_coverage?.dates)}
          detail="Repeated same-day observations are not independent."
        />
      </div>
      <div className="op-two-column">
        <Panel
          title="Net outcome"
          description="Qualified amounts remain grouped by account currency."
        >
          {Object.entries(view.pnlByCurrency).length ? (
            Object.entries(view.pnlByCurrency).map(([currency, value]) => (
              <div className="op-large-result" key={currency}>
                <span>{currency} · net paper P/L</span>
                <strong className={value < 0 ? "op-loss" : ""}>
                  {number(value, 6)}
                </strong>
              </div>
            ))
          ) : (
            <Empty title="Qualified monetary P/L is unavailable">
              No qualified sample is different from a zero return. Legacy
              history remains below.
            </Empty>
          )}
          <div className="op-evidence-line">
            <span>Mean net return per outcome</span>
            <strong>{percent(sample?.mean_net_return_percent)}</strong>
          </div>
        </Panel>
        <Panel
          title="Against the benchmark"
          description="Pairing and uncertainty must accompany any alpha claim."
        >
          <div className="op-evidence-line">
            <span>Mean paired excess</span>
            <strong>{percent(sample?.mean_paired_excess_percent)}</strong>
          </div>
          <div className="op-evidence-line">
            <span>95% sample interval</span>
            <strong>
              {percent(interval?.lower_95)} to {percent(interval?.upper_95)}
            </strong>
          </div>
          <p className="op-body-copy">
            {interval?.method ?? "Benchmark methodology is unavailable."}
          </p>
          <p className="op-footnote">
            Sample uncertainty does not account for every source of bias. No
            multiple-testing correction is reported by this contract.
          </p>
        </Panel>
      </div>
      <Panel
        title="What is excluded?"
        description="An incomplete record cannot support a stronger performance claim."
      >
        {Object.keys(view.exclusions).length ? (
          <div className="op-reason-list">
            {Object.entries(view.exclusions)
              .sort((a, b) => b[1] - a[1])
              .map(([key, count]) => (
                <div key={key}>
                  <span>{human(key)}</span>
                  <strong>{number(count)}</strong>
                </div>
              ))}
          </div>
        ) : (
          <Empty
            title={
              sample
                ? "No exclusions reported"
                : "Qualification evidence unavailable"
            }
          >
            A decision may have several exclusion reasons. These counts are not
            a count of lost trades.
          </Empty>
        )}
      </Panel>
      <Panel
        title="Legacy paper history"
        description="Descriptive source history, separate from the qualified prospective sample."
      >
        <details className="op-disclosure">
          <summary>
            Inspect legacy metrics for{" "}
            {market === "forex" ? "Forex" : "equities & ETFs"}
          </summary>
          <div className="op-metrics op-three">
            <Metric
              label="Source closed sample"
              value={number(history?.sample_size)}
              detail="Historical accounting eligibility differs from qualification above."
            />
            <Metric
              label="Win rate"
              value={
                finiteMetric(history?.win_rate) === null
                  ? "—"
                  : percent(history.win_rate * 100)
              }
              detail="Within the source-reported closed sample."
            />
            <Metric
              label="Expectancy"
              value={`${number(history?.expectancy_r, 4)} R`}
              detail="Legacy average return relative to risk."
            />
          </div>
          <p className="op-body-copy">
            Profit factor{" "}
            {typeof history?.pnl_currency === "string" &&
            /^[A-Z]{3}$/.test(history.pnl_currency)
              ? number(history?.profit_factor, 3)
              : "unavailable without one declared account currency"}
            . Amounts and benchmark series are not pooled across markets. A
            legacy result cannot validate a new strategy.
          </p>
          <Freshness
            at={data.paper?.snapshot_created_at ?? data.paper?.generated_at}
            error={errors.paper}
          />
        </details>
      </Panel>
      <p className="op-page-footer">
        {data.desk?.window?.scope ??
          "Performance describes the evaluated research sample, not an all-history total."}
      </p>
      {Object.keys(errors).length > 0 && (
        <div role="alert" className="op-error-note">
          Some performance evidence could not refresh:{" "}
          {Object.keys(errors).join(", ")}. Inspect the available timestamps and
          retry.
        </div>
      )}
    </div>
  );
}
