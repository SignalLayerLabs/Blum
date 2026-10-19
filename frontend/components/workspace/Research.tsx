"use client";

import Link from "next/link";
import type { CurriculumLane, CurriculumMetrics, CurriculumSnapshot } from "@/lib/curriculum";
import { useSnapshots, researchReaders } from "./useSnapshots";
import {
  Empty,
  Freshness,
  Metric,
  PageHeader,
  Panel,
  human,
  number,
  stamp,
} from "./Primitives";

function percent(value: unknown) {
  return typeof value === "number" && Number.isFinite(value)
    ? `${number(value * 100, 2)}%`
    : "—";
}

function riskMultiple(value: unknown) {
  return typeof value === "number" && Number.isFinite(value)
    ? `${number(value, 2)}R`
    : "—";
}

function BenchmarkRow({ label, detail, metrics, returnValue }: {
  label: string; detail: string; metrics?: CurriculumMetrics; returnValue?: number;
}) {
  const interval = metrics?.win_rate_interval;
  return (
    <tr>
      <td><strong>{label}</strong><span>{detail}</span></td>
      <td>{percent(returnValue ?? metrics?.net_return)}</td>
      <td>{number(metrics?.trade_count)}</td>
      <td>
        {percent(metrics?.win_rate)}
        {interval && <span>{percent(interval[0])} – {percent(interval[1])}</span>}
      </td>
      <td>{riskMultiple(metrics?.expectancy_r)}</td>
      <td>{percent(metrics?.max_closed_trade_drawdown)}</td>
      <td>{number(metrics?.profit_factor, 2)}</td>
    </tr>
  );
}

const forwardLabels: Record<string, string> = {
  PENDING: "Pending later market bars",
  OPEN: "Research paper position open",
  CLOSED: "Research paper outcome closed",
  STALE_CONTEXT: "Waiting for fresh context",
  WAITING_SIGNAL: "Waiting for a signal",
  UNFILLED: "Research order unfilled",
  BLOCKED: "Research execution blocked",
};

function CurriculumLaneCard({ lane }: { lane: CurriculumLane }) {
  const benchmark = lane.benchmark;
  const forward = lane.forward;
  return (
    <article className="op-call-card">
      <div className="op-context">
        <h3>{lane.ticker} · {lane.market} · {lane.timeframe}</h3>
        <span className="op-status">
          {lane.training_status === "PACK_EXHAUSTED" ? "Source pack exhausted" : lane.training_status === "TRAINING" ? "Training" : "Training state unavailable"}
        </span>
      </div>
      <div className="op-metrics op-three">
        <Metric label="Training episodes" value={number(lane.training_episodes)} detail="Unique completed training blocks." />
        <Metric label="Learned outcomes" value={number(lane.learned_outcomes)} detail="Dependent expert outcomes; not independent forward evidence." />
        <Metric label="Source rows" value={number(lane.source_rows)} detail="Rows in this frozen source pack." />
      </div>
      <div className="op-evidence-line">
        <span>Policy checkpoint</span>
        <code title={lane.checkpoint}>{lane.checkpoint?.slice(0, 12) ?? "Unavailable"}</code>
      </div>
      {benchmark ? (
        <>
          <p className="op-footnote">
            Development monitoring on the same stored window. {benchmark.confirmation_opened === false ? "Reserved confirmation unopened." : "Confirmation status requires review."}
          </p>
          {typeof benchmark.return_change_from_previous === "number" && (
            <p className="op-footnote">Return change from previous checkpoint: {number(benchmark.return_change_from_previous * 100, 2)} percentage points · same development window.</p>
          )}
          <div className="op-table-wrap">
            <table className="op-table" aria-label={`${lane.ticker} curriculum benchmark comparison`}>
              <thead><tr>
                <th>Reference</th><th>Return</th><th>Closed trades</th>
                <th>Win rate / interval</th><th>Expectancy</th>
                <th>Closed-trade drawdown</th><th>Profit factor</th>
              </tr></thead>
              <tbody>
                <BenchmarkRow label="Selected policy" detail="Modeled after execution costs" metrics={benchmark.policy} />
                <BenchmarkRow label="Fixed expert" detail="Unchanged expert on the same window" metrics={benchmark.fixed_expert} />
                <BenchmarkRow label="Cash" detail="No-trade reference" returnValue={benchmark.cash_return} />
                <BenchmarkRow label="Price-only hold" detail="Same asset; excludes dividends and costs" returnValue={benchmark.buy_hold_price_return} />
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <Empty title="No stored benchmark yet">This lane has no completed development comparison to display.</Empty>
      )}
      <h3>Prospective research paper</h3>
      <div className="op-evidence-line">
        <span>Observation status</span>
        <strong>{forwardLabels[forward?.status ?? ""] ?? "Prospective observation unavailable"}</strong>
      </div>
      <div className="op-evidence-line"><span>Live outcome learning updates</span><strong>{number(forward?.learned_outcomes)}</strong></div>
      <div className="op-evidence-line"><span>Closed prospective outcomes</span><strong>{number(forward?.closed_count)}</strong></div>
      <div className="op-evidence-line"><span>Lane balance · quote units</span><strong>{number(forward?.cash_quote_units, 2)}</strong></div>
      {forward?.decision_at && <p className="op-footnote">Decision {stamp(forward.decision_at)} · observation updated {stamp(forward.updated_at)}</p>}
      {forward?.last_outcome?.net_r !== undefined && (
        <p className="op-footnote">Last stored outcome: {riskMultiple(forward.last_outcome.net_r)} · {human(forward.last_outcome.reason)}</p>
      )}
      <p className="op-footnote">These observations are separate from native paper orders and filled-order counts. The lane balance is realized cash before any open-position reservation; it is not a consolidated portfolio return.</p>
      <details className="op-disclosure">
        <summary>Checkpoint and source identity</summary>
        <p className="op-footnote" style={{ overflowWrap: "anywhere" }}>Checkpoint: <code>{lane.checkpoint ?? "Unavailable"}</code></p>
        <p className="op-footnote" style={{ overflowWrap: "anywhere" }}>Source hash: <code>{lane.source_hash ?? "Unavailable"}</code></p>
        <p className="op-footnote" style={{ overflowWrap: "anywhere" }}>Benchmark window: <code>{benchmark?.window_hash ?? "Unavailable"}</code></p>
      </details>
    </article>
  );
}

export function CurriculumPanel({ snapshot, pending, error }: {
  snapshot?: CurriculumSnapshot; pending: boolean; error?: string;
}) {
  const lanes = Array.isArray(snapshot?.lanes) ? snapshot.lanes : [];
  return (
    <Panel title="Outcome-driven curriculum" description="Experimental historical strategy selection, compared against declared baselines.">
      {snapshot && (
        <div className="op-context">
          <span className="op-status">Experimental research</span>
          <Freshness at={snapshot.updated_at ?? undefined} error={error} />
        </div>
      )}
      {error && lanes.length > 0 && <p className="op-error-note" role="alert">Showing the last stored curriculum; its refresh failed.</p>}
      {lanes.length > 0 ? (
        <div className="op-call-list">{lanes.map((lane) => <CurriculumLaneCard key={lane.lane} lane={lane} />)}</div>
      ) : (
        <Empty title={error ? "Curriculum snapshot unavailable" : pending ? "Checking curriculum snapshot" : "No curriculum lanes stored"}>
          {error ? "The curriculum could not be read. Refresh to try again." : pending ? "Reading the stored curriculum; this does not start training." : "No eligible source pack or completed curriculum snapshot is visible yet."}
        </Empty>
      )}
      {(snapshot?.limitations ?? []).length > 0 && (
        <details className="op-disclosure">
          <summary>Curriculum limits</summary>
          <ul className="op-footnote">{snapshot!.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
        </details>
      )}
    </Panel>
  );
}

function PatternList({ rows, empty }: { rows: any[]; empty: string }) {
  return rows.length ? (
    <div className="op-research-list">
      {rows.slice(0, 6).map((row, index) => (
        <article key={row.id ?? index}>
          <h3>
            {human(
              row.pattern ??
                row.setup_type ??
                row.title ??
                row.name ??
                row.factor ??
                "Recorded pattern",
            )}
          </h3>
          <p>
            {row.observation ??
              row.reason ??
              row.summary ??
              row.description ??
              row.lesson ??
              "Inspect the source detail for this observation."}
          </p>
          <details className="op-disclosure">
            <summary>Evidence detail</summary>
            <pre>{JSON.stringify(row, null, 2)}</pre>
          </details>
        </article>
      ))}
    </div>
  ) : (
    <Empty title={empty}>
      The workspace does not substitute generated explanations for measured
      results.
    </Empty>
  );
}
export function Research() {
  const { data, errors, pending, refresh } = useSnapshots(researchReaders);
  const training = data.training;
  const planner = training?.research_planner;
  const validation = training?.current_validation;
  const totals = validation?.evidence_total;
  const queue = planner?.queued_experiments ?? [];
  const focus =
    planner?.current_research_objective ??
    queue[0] ??
    training?.current_experiment;
  return (
    <div className="op-page">
      <PageHeader
        eyebrow="Hypotheses & learning"
        title="Follow the reasoning."
        description="What BLUM is investigating, what changed, and which claims still need an outcome."
        pending={pending}
        onRefresh={refresh}
      />
      <div className="op-context">
        <span className="op-status">
          {human(validation?.display_status ?? training?.status)}
        </span>
        <Freshness
          at={training?.snapshot_created_at ?? training?.generated_at}
          error={errors.training}
        />
      </div>
      <CurriculumPanel snapshot={data.curriculum} pending={pending} error={errors.curriculum} />
      <Panel
        title="Current investigation"
        description="The latest stored research objective."
      >
        <h3 className="op-focus-title">
          {human(focus?.target ?? focus?.name)}
        </h3>
        <p className="op-body-copy">
          {planner?.why_selected ??
            focus?.reason ??
            "No current research rationale is available."}
        </p>
        <div className="op-hypothesis">
          <span className="op-eyebrow">HYPOTHESIS</span>
          <p>
            {planner?.next_hypothesis ??
              training?.current_hypothesis ??
              "No testable hypothesis is stored."}
          </p>
        </div>
        <p className="op-footnote">
          A hypothesis and a high confidence score are research inputs. Improved
          net outcomes against a declared baseline are the evidence of progress.
        </p>
      </Panel>
      <div className="op-metrics">
        <Metric
          label="Predictions generated"
          value={number(totals?.predictions_generated)}
          detail="Research activity; not a hit rate."
        />
        <Metric
          label="Outcomes evaluated"
          value={number(totals?.outcomes_evaluated)}
          detail="A prediction may have several evaluated horizons."
        />
        <Metric
          label="Mistakes analyzed"
          value={number(totals?.mistakes_analyzed)}
          detail="Stored analysis, not proof of a corrected model."
        />
        <Metric
          label="Memory updates"
          value={number(totals?.memory_updates)}
          detail="Changes still need independent validation."
        />
      </div>
      <div className="op-two-column">
        <Panel
          title="Latest experiment result"
          description="Inspect what the source result actually supports."
        >
          <h3 className="op-focus-title">
            {human(planner?.experiment_result?.status)}
          </h3>
          <p className="op-body-copy">
            {planner?.experiment_result?.summary ??
              validation?.summary ??
              "No completed result is available."}
          </p>
          <div className="op-evidence-line">
            <span>Reported sample</span>
            <strong>{number(planner?.experiment_result?.sample_size)}</strong>
          </div>
          <Link className="op-text-link" href="/alpha">
            Inspect performance evidence →
          </Link>
        </Panel>
        <Panel
          title="Research limits"
          description="Constraints remain visible while the engine operates."
        >
          <p className="op-body-copy">
            {training?.paper_forward_learning_blocker?.summary ??
              "No current paper-forward blocker summary is stored."}
          </p>
          <div className="op-reason-list">
            {(planner?.known_limitations ?? []).map((item: string) => (
              <div key={item}>
                <span>{human(item)}</span>
              </div>
            ))}
          </div>
          <p className="op-footnote">
            {training?.reason_if_target_missed ??
              training?.budget_guard?.reason ??
              "No additional budget or throughput reason is reported."}
          </p>
        </Panel>
      </div>
      <Panel
        title="Next experiments"
        description="The visible stored queue; selection is separate from execution."
      >
        {queue.length ? (
          <div className="op-research-list">
            {queue.slice(0, 5).map((row: any, index: number) => (
              <article key={index}>
                <span className="op-status">{human(row.priority_type)}</span>
                <h3>{human(row.target)}</h3>
                <p>{row.experiment ?? row.reason}</p>
                <p className="op-footnote">{row.reason}</p>
              </article>
            ))}
          </div>
        ) : (
          <Empty title="No queued experiment is visible">
            The next research step has not been stored in this snapshot.
          </Empty>
        )}
      </Panel>
      <div className="op-two-column">
        <Panel
          title="Patterns under investigation"
          description="Source-reported findings still require prospective validation."
        >
          <PatternList
            rows={training?.patterns_discovered ?? []}
            empty="No positive pattern is stored"
          />
        </Panel>
        <Panel
          title="Rejected patterns"
          description="Negative evidence is part of the research record."
        >
          <PatternList
            rows={training?.patterns_rejected ?? []}
            empty="No rejected pattern is stored"
          />
        </Panel>
      </div>
      <Panel
        title="Recent learning runs"
        description="Activity timestamps are distinct from effectiveness."
      >
        {training?.learning_timeline?.length ? (
          <div className="op-table-wrap">
            <table className="op-table">
              <thead>
                <tr>
                  <th>Started</th>
                  <th>Status</th>
                  <th>Stored result</th>
                </tr>
              </thead>
              <tbody>
                {training.learning_timeline
                  .slice(0, 8)
                  .map((row: any, index: number) => (
                    <tr key={row.id ?? index}>
                      <td>{stamp(row.started_at)}</td>
                      <td>{human(row.status)}</td>
                      <td>
                        {row.display_detail ??
                          `${number(row.predictions_generated)} predictions · ${number(row.outcomes_evaluated)} outcomes · ${number(row.memory_updates)} memory updates`}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="No learning run is visible">
            A missing timeline does not establish that a worker is active.
          </Empty>
        )}
      </Panel>
      <details className="op-disclosure">
        <summary>Advanced research diagnostics</summary>
        <p className="op-body-copy">
          Inspect the existing experiment and generation evidence in{" "}
          <Link className="op-text-link" href="/evolution">
            Evolution
          </Link>
          .
        </p>
      </details>
      {errors.training && (
        <div className="op-error-note" role="alert">
          Research evidence could not refresh. {errors.training}
        </div>
      )}
    </div>
  );
}
