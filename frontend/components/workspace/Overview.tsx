"use client";
import Link from "next/link";
import { useState } from "react";
import {
  ArrowRight,
  Activity,
  Check,
  Database,
  ShieldCheck,
} from "lucide-react";
import {
  operatingMarket,
  callState,
  engineEvidence,
} from "@/lib/operatingView.mjs";
import { useSnapshots, overviewReaders } from "./useSnapshots";
import { OperatingState } from "./OperatingState";
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
export function Overview() {
  const { data, errors, pending, refresh } = useSnapshots(overviewReaders);
  const [market, setMarket] = useState("equity");
  const view = operatingMarket(data, market);
  const calls = callState(data.desk, market);
  const evidence = engineEvidence(data, market);
  const focus = data.brain?.current_learning_objective;
  const blockers = Object.entries(view.exclusions)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3);
  return (
    <div className="op-page">
      <PageHeader
        eyebrow="Your research workspace"
        title="Your trading desk"
        description="What BLUM is doing, what it could trade next, and what its paper results actually support."
        pending={pending}
        onRefresh={refresh}
      />
      <div className="op-context">
        <MarketTabs market={market} onChange={setMarket} />
        <span className="op-context-note">
          Separate markets. Separate results.
        </span>
      </div>
      <OperatingState
        data={data.runtime}
        error={errors.runtime}
        market={market}
      />
      <section className="op-hero">
        <div className="op-hero-copy">
          <span className="op-eyebrow">CURRENT POSITION</span>
          <h2>
            {!data.desk
              ? "Checking the research record"
              : !calls.current
                ? "Current call state is not established"
                : calls.active.length
                  ? "Research calls available for inspection"
                  : "No qualified call is available."}
          </h2>
          <p>
            {!data.desk
              ? "Loading the actual stored evidence. Availability and missing data stay visible."
              : "Decision activity is different from trade execution. An idea enters the qualified record only after its inputs, fill and costs pass the required checks."}
          </p>
          <Link href="/calls" className="op-button op-primary">
            Inspect research calls <ArrowRight size={16} />
          </Link>
        </div>
        <div className="op-hero-fact">
          <span>Qualified closed calls</span>
          <strong>{number(view.qualifiedClosed)}</strong>
          <p>{human(view.verdict)}</p>
          <Freshness
            at={data.desk?.generated_at}
            error={errors.desk}
            status={data.desk?.snapshot_status}
          />
        </div>
      </section>
      <div className="op-metrics">
        <Metric
          label="Recorded decisions"
          value={number(view.registered)}
          detail="A research decision is not an executed trade."
        />
        <Metric
          label="Open paper positions"
          value={number(view.open)}
          detail="Source-reported positions in this market."
        />
        <Metric
          label="Recorded paper closures"
          value={number(view.closed)}
          detail="Legacy history; qualification is evaluated separately."
        />
        <Metric
          label="Paired benchmark outcomes"
          value={number(view.paired)}
          detail="Only aligned, qualified observations enter this sample."
        />
      </div>
      <div className="op-two-column">
        <Panel
          title="Can I follow a move yet?"
          description="Upcoming plans must be visible before their entry."
          href="/calls"
        >
          <Empty
            title={
              !calls.current
                ? "Current call state is unverified"
                : calls.active.length
                  ? "Inspect the current research calls"
                  : "No advance plan to follow"
            }
          >
            {calls.active.length
              ? "Inspect the plan, source time and eligibility. Advance publication has not yet been established by the current registry."
              : "The current registry records research decisions. It does not establish a copyable lead time; do not treat historical entries as upcoming opportunities."}
          </Empty>
          <div className="op-flow">
            <span>
              <Database size={14} /> Evidence
            </span>
            <ArrowRight size={12} />
            <span>
              <ShieldCheck size={14} /> Risk & costs
            </span>
            <ArrowRight size={12} />
            <span>
              <Check size={14} /> Paper outcome
            </span>
          </div>
        </Panel>
        <Panel
          title="What is stopping a qualified result?"
          description="The most frequent exclusions in the prospective record."
        >
          <div className="op-reason-list">
            {blockers.length ? (
              blockers.map(([key, count]) => (
                <div key={key}>
                  <span>{human(key)}</span>
                  <strong>{number(count)}</strong>
                </div>
              ))
            ) : (
              <Empty
                title={
                  data.desk?.markets?.[market]
                    ? "No exclusions reported"
                    : "Waiting for the call record"
                }
              >
                Missing evidence is not counted as a successful result.
              </Empty>
            )}
          </div>
          <p className="op-footnote">
            A decision may have more than one exclusion.
          </p>
        </Panel>
      </div>
      <div className="op-two-column">
        <Panel
          title="Trading intelligence"
          description="Measured evidence, rather than a synthetic intelligence score."
          href="/alpha"
        >
          <div className="op-evidence-level">
            <span className="op-status">
              <Activity size={13} />
              {human(evidence.level)}
            </span>
            <p>
              A validated edge needs mature, cost-aware outcomes and a relevant
              benchmark. Activity and model explanations alone do not establish
              it.
            </p>
          </div>
          <div className="op-evidence-line">
            <span>Qualified outcomes</span>
            <strong>{number(evidence.qualified)}</strong>
          </div>
          <div className="op-evidence-line">
            <span>Benchmark-paired observations</span>
            <strong>{number(evidence.paired)}</strong>
          </div>
        </Panel>
        <Panel
          title="What is BLUM learning?"
          description="The current stored research focus."
          href="/training-ground"
        >
          <h3 className="op-focus-title">
            {focus?.target
              ? human(focus.target)
              : pending
                ? "Reading research state…"
                : "No current focus is available"}
          </h3>
          <p className="op-body-copy">
            {focus?.reason ??
              "The workspace will show the actual stored objective when it is available."}
          </p>
          <div className="op-evidence-line">
            <span>Observed learning cycles</span>
            <strong>{number(evidence.cycles)}</strong>
          </div>
          <p className="op-footnote">
            A cycle count measures activity, not improved trading performance.
          </p>
          <Freshness at={data.brain?.generated_at} error={errors.brain} />
        </Panel>
      </div>
      <Panel
        title="The paper result, with the right context"
        description="Qualified monetary results are grouped by account currency."
      >
        <div className="op-result-grid">
          {Object.entries(view.pnlByCurrency).length ? (
            Object.entries(view.pnlByCurrency).map(([currency, value]) => (
              <Metric
                key={currency}
                label={`Qualified net P/L · ${currency}`}
                value={number(value, 6)}
                detail="After the recorded execution costs; a paper result."
                tone={value < 0 ? "negative" : "neutral"}
              />
            ))
          ) : (
            <Empty title="No qualified monetary P/L available">
              This is unavailable evidence, not a zero return. The Trades view
              retains the separate source history and its cost details.
            </Empty>
          )}
          <div className="op-result-context">
            <span>Legacy expectancy</span>
            <strong>{number(view.expectancyR, 3)} R</strong>
            <p>
              Descriptive source history. It is not a verified prospective track
              record.
            </p>
            <Link href="/paper-trading">
              Inspect trades and costs <ArrowRight size={14} />
            </Link>
          </div>
        </div>
        <Freshness
          at={data.paper?.snapshot_created_at ?? data.paper?.generated_at}
          error={errors.paper}
        />
      </Panel>
      {Object.keys(errors).length > 0 && (
        <div className="op-error-note" role="alert">
          <strong>Some research views could not refresh.</strong>
          <p>
            {Object.keys(errors).join(", ")}. Available sections remain visible;
            check their own timestamps. Use Refresh to retry.
          </p>
        </div>
      )}
      <p className="op-page-footer">
        Paper research only. No market-outperformance claim is established by
        this workspace.
      </p>
    </div>
  );
}
