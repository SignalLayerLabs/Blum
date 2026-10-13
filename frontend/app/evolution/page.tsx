"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { evidencePresentation, metricValue, validationLabel, type AscentSnapshot, type AscentExperiment } from "@/lib/ascentView.mjs";

const comparisonMetrics = [
  ["brier_score", "Brier loss ↓"], ["log_loss", "Log loss ↓"], ["calibration_error", "Calibration error ↓"],
  ["sample_size", "Holdout observations"], ["net_expectancy", "Stored net R / trade"],
  ["benchmark_excess", "Stored benchmark excess"], ["max_drawdown", "Trade R drawdown"],
] as const;

export default function EvolutionPage() {
  const [data, setData] = useState<AscentSnapshot | null>(null);
  const [selectedUid, setSelectedUid] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    setError(null);
    try { setData(await api.ascentStatus()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Research history is unavailable."); }
    finally { setLoading(false); }
  }
  useEffect(() => { void refresh(); }, []);

  const selected = data?.generations.find(row => row.generation_uid === selectedUid) ?? data?.generations[0];
  const candidates = data?.experiments.filter(row => row.generation_uid === selected?.generation_uid) ?? [];
  const evaluated = candidates.find(row => row.experiment_uid === selected?.selected_experiment_uid);
  const evidence = evidencePresentation(selected?.evidence_lane ?? "unknown");

  return <>
    <div className="page-header">
      <div><div className="kicker">ASCENT · Research observatory</div><h1>Evolution through evidence.</h1>
        <p>Observe → diagnose → hypothesize → modify → test → compete → validate → retain or reject.</p></div>
      <button onClick={() => void refresh()} disabled={loading}>{loading ? "Loading…" : "Refresh history"}</button>
    </div>
    {error && <div className="panel ascent-alert" role="alert">{error}</div>}
    {!data && loading && <div className="empty-state">Loading recorded experiments…</div>}
    {data && <>
      <div className="ascent-policy"><span className={`status-badge ${data.enabled ? "neutral" : "warning"}`}>
        {data.enabled ? "Research enabled" : "Research disabled"}</span><p>{data.policy}</p>
        <span>Scheduler {data.scheduler_enabled ? "configured" : "off"} · Software evolution · Paper only</span></div>
      <section className="grid-3 ascent-overview">
        <article className="panel"><div className="panel-head"><span>Current production Champions</span></div>
          {!data.production_champions.length && <p className="ascent-muted">No active trading ML Champion recorded.</p>}
          {data.production_champions.map(row => <p key={row.model_uid}><strong>{row.market_family}</strong><br /><code>{row.model_uid}</code></p>)}
          {data.strategy_champions.map(row => <p key={row.fingerprint}>{row.family} · <code>{short(row.fingerprint)}</code></p>)}
        </article>
        <article className="panel"><div className="panel-head"><span>Research calibration Champions</span></div>
          {!data.research_champions.length && <p className="ascent-muted">Frozen confidence is the initial baseline. No retained calibration artifact yet.</p>}
          {data.research_champions.map(row => <p key={row.experiment_uid}><code>{short(row.experiment_uid)}</code><br />Retained for research; production approval required.</p>)}
        </article>
        <article className="panel"><div className="panel-head"><span>Model-weight evolution</span></div>
          <p>Existing Hugging Face Champion/Challenger pipeline</p><code>{data.level_2.champion_repository}</code>
          <p className="ascent-muted">ASCENT has not launched weight training. Calibration results measure software behavior.</p>
        </article>
      </section>
      {!data.generations.length && <section className="panel ascent-empty"><h2>No experiments recorded.</h2>
        <p>Completed research cycles will appear here with their source changes, evaluation evidence, lineage and rejection reasons.</p>
        <p className="ascent-muted">This page reads stored evidence. Opening it does not start research.</p></section>}
      {!!data.generations.length && <div className="ascent-workbench">
        <section className="panel"><div className="panel-head"><span>Recent generations</span><strong>{data.generations.length} shown</strong></div>
          <div className="ascent-history">{data.generations.map(row => {
            const lane = evidencePresentation(row.evidence_lane);
            return <button key={row.generation_uid} className={`ascent-generation ${row === selected ? "selected" : ""}`}
              onClick={() => setSelectedUid(row.generation_uid)} aria-pressed={row === selected}>
              <span className={`status-badge ${lane.tone}`}>{lane.label}</span>
              <strong>{row.market_family} · {validationLabel(row.status)}</strong>
              <time>{row.started_at.replace("T", " ").slice(0, 19)} UTC</time>
              <code>{short(row.generation_uid)}</code>
              <span>Parent {row.parent_uid ? short(row.parent_uid) : "initial generation"}</span>
            </button>;
          })}</div>
        </section>
        {selected && <section className="panel ascent-detail">
          <div className="panel-head"><span>Frozen research hypothesis</span><span className={`status-badge ${evidence.tone}`}>{evidence.label}</span></div>
          <h2>{selected.hypothesis}</h2>
          <div className="ascent-facts"><div><span>Development</span><strong>{selected.manifest.development_samples ?? "—"}</strong></div>
            <div><span>Holdout</span><strong>{selected.manifest.holdout_samples ?? "—"}</strong></div>
            <div><span>Purged rows</span><strong>{selected.manifest.purged_rows ?? "—"}</strong></div>
            <div><span>Embargo</span><strong>{selected.manifest.embargo_days === undefined ? "—" : `${selected.manifest.embargo_days} days`}</strong></div></div>
          {!!selected.blockers?.length && <div className="ascent-alert"><strong>Validation blockers</strong>
            <ul>{selected.blockers.map(blocker => <li key={blocker}>{blocker.replaceAll("_", " ").toLowerCase()}</li>)}</ul></div>}
          <div className="panel-head"><span>Competing implementations</span><strong>{candidates.length} candidates</strong></div>
          {candidates.map(candidate => <details className="ascent-candidate" key={candidate.experiment_uid} open={candidate === evaluated}>
            <summary>{short(candidate.experiment_uid)} · {validationLabel(candidate.status)}
              <span>Development Brier {metricValue(candidate.development.candidate?.brier_score)}</span></summary>
            <pre>{candidate.source_text}</pre><p className="ascent-muted">Source SHA-256 <code>{candidate.source_sha256}</code></p>
          </details>)}
          <HoldoutComparison experiment={evaluated} />
          <div className="panel-head"><span>Traceability and resources</span></div>
          <dl className="ascent-trace"><dt>Dataset hash</dt><dd>{selected.manifest.dataset_hash ?? "Not frozen"}</dd>
            <dt>Code revision</dt><dd>{selected.source_revision}</dd><dt>Trusted evaluator hash</dt><dd>{selected.manifest.trusted_code_hash ?? "—"}</dd>
            <dt>Seed</dt><dd>{selected.manifest.seed ?? "—"}</dd><dt>Recorded cycle duration</dt><dd>{selected.duration_seconds === undefined ? "—" : `${selected.duration_seconds}s`}</dd>
            <dt>Per-cycle ceiling</dt><dd>{selected.manifest.budgets ? `${selected.manifest.budgets.max_rows} rows · ${selected.manifest.budgets.max_candidates} candidates · ${selected.manifest.budgets.max_seconds}s` : "No snapshot"}</dd>
            <dt>GPU / external inference budget</dt><dd>{selected.manifest.budgets ? "0 / 0" : "—"}</dd></dl>
        </section>}
      </div>}
    </>}
  </>;
}

function HoldoutComparison({ experiment }: { experiment?: AscentExperiment }) {
  const validation = experiment?.validation;
  if (!validation?.candidate) return <div className="empty-state">No completed independent holdout evaluation for this generation.</div>;
  return <>
    <div className="panel-head"><span>Independent holdout comparison</span><strong>{validation.independent_recheck ? "Rechecked" : "Unverified"}</strong></div>
    <div className="table-shell"><table className="ascent-comparison"><thead><tr><th>Measure</th><th>Candidate</th><th>Research Champion</th><th>Training climatology</th></tr></thead>
      <tbody>{comparisonMetrics.map(([key, label]) => <tr key={key}><th>{label}</th><td>{metricValue(validation.candidate?.[key])}</td>
        <td>{metricValue(validation.champion?.[key])}</td><td>{metricValue(validation.climatology?.[key])}</td></tr>)}</tbody></table></div>
    {validation.uncertainty && <p className="ascent-muted">Brier gain lower bound {metricValue(validation.uncertainty.gain_lower_bound)} · {validation.uncertainty.blocks} horizon-aware blocks · adjusted α {validation.uncertainty.alpha.toPrecision(3)}.<br />{validation.uncertainty.assumption}</p>}
    {!!validation.slices?.length && <details className="ascent-candidate"><summary>Asset and regime robustness</summary>
      {validation.slices.map(slice => <p key={`${slice.dimension}:${slice.key}`}>{slice.key} · {slice.sample_size} observations · Brier gain {metricValue(slice.brier_gain)}</p>)}</details>}
    {validation.warnings?.map(warning => <p className="ascent-muted" key={warning}>{warning}</p>)}
    <p>Financial metrics describe identical stored decisions. Calibration has not changed trading returns or production authority.</p>
  </>;
}

function short(value: string) { return value.length > 24 ? `${value.slice(0, 16)}…${value.slice(-6)}` : value; }
