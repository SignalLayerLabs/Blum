"use client";

import Link from "next/link";
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
