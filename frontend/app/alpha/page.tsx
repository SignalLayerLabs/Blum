"use client";

import { useEffect, useMemo, useState } from "react";
import { BarChart3, CheckCircle2, Gauge, TrendingDown, TrendingUp } from "lucide-react";
import { api } from "@/lib/api";
import { BloombergPanel, MetricCard, MiniSparkline, TerminalHeader } from "@/components/FinancialTerminal";
import { LoadingState } from "@/components/LoadingState";
import { StatusBadge } from "@/components/StatusBadge";
import { AlphaDesk } from "@/components/AlphaDesk";

const EVIDENCE_GRADE_ORDER = ["NO_DATA", "INSUFFICIENT_EVIDENCE", "WEAK", "MIXED", "PROMISING", "STRONG"];

export default function AlphaPage() {
  const [data, setData] = useState<any | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;
    api.traderAlpha()
      .then((payload) => mounted && setData(payload))
      .catch((err) => mounted && setError(err instanceof Error ? err.message : String(err)));
    return () => {
      mounted = false;
    };
  }, []);

  const spark = useMemo(() => {
    if (!data) return [0, 0];
    const values = [
      data.historical_alpha,
      data.walk_forward_alpha,
      data.paper_forward_alpha,
      data.live_forward_alpha,
    ].map(Number).filter(Number.isFinite);
    return values.length > 1 ? values : [0, Number(data.alpha) || 0];
  }, [data]);

  if (error) {
    return (
      <div className="terminal-empty">
        Alpha snapshot unavailable: {error}. The page is read-only and did not trigger recalculation.
      </div>
    );
  }
  if (!data) return <LoadingState label="Loading Alpha Evidence" />;

  const grade = normalizeGrade(data.evidence_grade);
  const verdictTone = gradeTone(grade);
  const blockers = data.current_blockers ?? [];
  const lessons = data.latest_alpha_lessons ?? [];
  const primaryEvidence = data.primary_evidence ?? {};
  const displayedSampleSize = data.total_evidence_sample_size ?? data.sample_size ?? 0;
  const primaryReturn = primaryEvidence.blum_return ?? data.blum_return;
  const primaryBenchmark = primaryEvidence.benchmark_return ?? data.benchmark_return;
  const primaryAlpha = primaryEvidence.alpha ?? primaryEvidence.benchmark_excess ?? data.alpha;
  const primaryLabel = primaryEvidence.label ?? "Paper-Forward Evidence";
  const alphaTone = metricTone(primaryAlpha);

  return (
    <>
      <TerminalHeader
        eyebrow="BLUM Alpha"
        title="Alpha Evidence"
        subtitle="One question only: is BLUM generating benchmark-relative paper-forward alpha?"
        statusItems={[
          { label: "Verdict", value: grade.replaceAll("_", " "), tone: verdictTone },
          { label: "Sample", value: String(displayedSampleSize), tone: Number(displayedSampleSize) >= Number(data.min_required_sample_size ?? 30) ? "positive" : "attention" },
          { label: "Updated", value: compactDate(data.last_updated_at ?? data.generated_at), tone: "info" },
          { label: "Policy", value: "read only", tone: "info" },
        ]}
      />

      <AlphaDesk data={data.registered_alpha_desk} />
      <section className="alpha-verdict-panel">
        <div>
          <span>Alpha Verdict</span>
          <h2>{data.verdict ?? fallbackVerdict(grade)}</h2>
          <p>{data.evidence_reason ?? "Evidence reason unavailable."}</p>
        </div>
        <div className={`alpha-grade tone-${verdictTone}`}>
          <strong>{grade}</strong>
          <span>{formatNumber(data.confidence_in_evidence)}% evidence confidence</span>
        </div>
      </section>

      <section className="terminal-command-grid">
        <MetricCard label="BLUM Return" value={formatPct(primaryReturn)} subvalue={primaryLabel} icon={<TrendingUp size={15} />} tone={metricTone(primaryReturn)} />
        <MetricCard label="Benchmark Return" value={formatPct(primaryBenchmark)} subvalue="same evidence stream where available" icon={<BarChart3 size={15} />} tone={primaryBenchmark === null || primaryBenchmark === undefined ? "attention" : "info"} />
        <MetricCard label="Alpha" value={formatPct(primaryAlpha)} subvalue={`${primaryLabel} benchmark excess`} icon={Number(primaryAlpha) >= 0 ? <TrendingUp size={15} /> : <TrendingDown size={15} />} tone={metricTone(primaryAlpha)} />
        <MetricCard label="Sample Size" value={String(displayedSampleSize)} subvalue={`${data.forward_sample_size ?? data.sample_size ?? 0} paper-forward closed`} icon={<Gauge size={15} />} tone={Number(displayedSampleSize) >= Number(data.min_required_sample_size ?? 30) ? "positive" : "attention"} />
        <MetricCard label="Realized P/L" value={formatMoney(data.realized_pnl)} subvalue={`unrealized ${formatMoney(data.unrealized_pnl)}`} icon={<CheckCircle2 size={15} />} tone={metricTone(data.realized_pnl)} />
        <MetricCard label="Benchmark Excess" value={formatPct(data.benchmark_excess)} subvalue={data.benchmark_excess === null || data.benchmark_excess === undefined ? "Benchmark comparison unavailable." : "closed paper-forward trades"} icon={<BarChart3 size={15} />} tone={metricTone(data.benchmark_excess)} />
      </section>

      <section className="grid-2">
        <BloombergPanel title="Evidence Quality" value={grade} subtitle="Evidence strength is capped by sample size and benchmark coverage.">
          <div className="alpha-evidence-ladder">
            {EVIDENCE_GRADE_ORDER.map((item) => (
              <div key={item} className={item === grade ? "active" : ""}>
                <span>{item.replaceAll("_", " ")}</span>
              </div>
            ))}
          </div>
          <div className="brain-list dense" style={{ marginTop: 10 }}>
            <Fact label="Confidence in evidence" value={`${formatNumber(data.confidence_in_evidence)}%`} detail="Not a trading confidence score. It measures whether evidence is usable." />
            <Fact label="Latest update" value={compactDate(data.last_updated_at ?? data.generated_at)} />
            <Fact label="Main blocker" value={data.current_blocker ?? "No primary blocker stored."} />
          </div>
        </BloombergPanel>

        <BloombergPanel title="Performance vs Benchmark" value={formatPct(primaryAlpha)} subtitle="No benchmark means no alpha claim.">
          <MiniSparkline values={spark as number[]} tone={alphaTone} />
          <div className="brain-list dense" style={{ marginTop: 10 }}>
            <Fact label="Evidence stream" value={primaryLabel} />
            <Fact label="BLUM return" value={formatPct(primaryReturn)} />
            <Fact label="Benchmark return" value={formatPct(primaryBenchmark)} />
            <Fact label="Alpha" value={formatPct(primaryAlpha)} detail={primaryBenchmark === null || primaryBenchmark === undefined ? "Benchmark comparison unavailable." : "Measured against stored benchmark evidence."} />
          </div>
        </BloombergPanel>
      </section>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <BloombergPanel title="Risk & Drawdown" value={formatPct(data.max_drawdown)} subtitle="Risk is part of alpha evidence, not a footnote.">
          <div className="brain-list dense">
            <Fact label="Max drawdown" value={formatPct(data.max_drawdown)} detail={data.current_risk_warning ?? "No risk warning stored."} />
            <Fact label="Worst trade" value={tradeLabel(data.worst_trade)} detail={tradeDetail(data.worst_trade)} />
            <Fact label="Current risk warning" value={data.current_risk_warning ?? "None stored."} />
          </div>
        </BloombergPanel>

        <BloombergPanel title="Expectancy & Trade Quality" value={`${formatNumber(data.average_r)}R`} subtitle="A lucky single trade must not be confused with repeatable edge.">
          <div className="brain-list dense">
            <Fact label="Expectancy" value={`${formatNumber(data.expectancy)}R`} />
            <Fact label="Profit factor" value={formatNumber(data.profit_factor)} />
            <Fact label="Win rate" value={formatRatioPct(data.win_rate)} />
            <Fact label="Median R" value={`${formatNumber(data.median_r)}R`} />
            <Fact label="Best trade" value={tradeLabel(data.best_trade)} detail={tradeDetail(data.best_trade)} />
          </div>
        </BloombergPanel>
      </section>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <BloombergPanel title="Edge Map" value={data.best_edge?.entity ?? "not proven"} subtitle="Low-sample edges are marked as weak evidence.">
          <EdgeTable groups={data.edge_map?.by_setup ?? []} />
        </BloombergPanel>
        <BloombergPanel title="Weakness Map" value={data.biggest_weakness?.code ?? "pending"} subtitle="What is preventing stronger benchmark-relative alpha?">
          <BlockerList rows={data.weakness_map ?? blockers} />
        </BloombergPanel>
      </section>

      <BloombergPanel title="Evidence Split" value="separated" subtitle="Historical, walk-forward and paper-forward evidence are not blended into one fake score." dense>
        <div className="alpha-split-grid">
          <EvidenceSplit title="Historical Replay" payload={data.evidence_split?.historical_replay ?? data.historical} />
          <EvidenceSplit title="Walk-Forward Validation" payload={data.evidence_split?.walk_forward_validation ?? data.walk_forward} />
          <EvidenceSplit title="Paper-Forward Evidence" payload={data.evidence_split?.paper_forward ?? data.paper_forward} />
          <EvidenceSplit title="Intraday Paper-Forward" payload={data.evidence_split?.intraday_paper_forward ?? data.intraday_paper_forward} />
          <EvidenceSplit title="Forex Paper-Forward" payload={data.evidence_split?.forex_paper_forward ?? data.forex_paper_forward} />
          <EvidenceSplit title="Live-Forward Evidence" payload={data.evidence_split?.live_forward ?? data.live_forward} />
        </div>
      </BloombergPanel>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <BloombergPanel title="Current Blockers" value={blockers.length ? `${blockers.length} blockers` : "none"} subtitle="Missing data is shown directly, not hidden.">
          <BlockerList rows={blockers} />
        </BloombergPanel>
        <BloombergPanel title="Latest Alpha Lessons" value={lessons.length ? `${lessons.length} lessons` : "none"} subtitle="Lessons connect closed paper-forward outcomes to future alpha evidence.">
          <div className="brain-list dense">
            {lessons.slice(0, 6).map((lesson: any, index: number) => (
              <div key={`${lesson.linked_trade_id ?? index}-${lesson.ticker}`}>
                <StatusBadge label={lesson.outcome ?? "lesson"} />
                <strong>{lesson.ticker ?? "Unknown"} · {lesson.setup_type ?? "unknown setup"}</strong>
                <p>{lesson.what_should_change_next ?? lesson.what_was_correct ?? "Lesson text unavailable."}</p>
                <span>Alpha impact {formatPct(lesson.alpha_impact)} | Benchmark {formatPct(lesson.benchmark_impact)}</span>
              </div>
            ))}
            {!lessons.length && <Fact label="No lessons yet" value="Closed paper-forward lessons are not available yet." />}
          </div>
        </BloombergPanel>
      </section>

      <BloombergPanel title="Truth Layer" value="evidence first" subtitle="The page does not claim market outperformance without enough stored evidence." dense>
        <div className="brain-list dense">
          {(data.truth ?? []).slice(0, 5).map((line: string, index: number) => (
            <div key={`${index}-${line}`}>
              <StatusBadge label={index === 0 ? "verdict" : "truth"} />
              <strong>{line}</strong>
            </div>
          ))}
        </div>
      </BloombergPanel>
    </>
  );
}

function EvidenceSplit({ title, payload }: { title: string; payload: any }) {
  const grade = normalizeGrade(payload?.evidence_grade ?? payload?.status);
  const sampleSize = payload?.sample_size ?? 0;
  const reason = payload?.evidence_reason ?? "Evidence reason unavailable.";
  return (
    <div className={`alpha-split-card tone-${gradeTone(grade)}`}>
      <span>{title}</span>
      <strong>{grade}</strong>
      <p>{sampleSize ? `Sample ${sampleSize}` : reason}</p>
      <div>
        <b>Return</b><em>{formatPct(payload?.return ?? payload?.blum_return)}</em>
      </div>
      <div>
        <b>Benchmark</b><em>{formatPct(payload?.benchmark_return)}</em>
      </div>
      <div>
        <b>Alpha</b><em>{formatPct(payload?.alpha ?? payload?.benchmark_excess ?? payload?.average_excess_return)}</em>
      </div>
      <div>
        <b>Benchmark excess</b><em>{formatPct(payload?.benchmark_excess ?? payload?.average_excess_return)}</em>
      </div>
      {sampleSize ? <small>{reason}</small> : null}
    </div>
  );
}

function EdgeTable({ groups }: { groups: any[] }) {
  if (!groups.length) {
    return <div className="terminal-empty compact">No repeatable edge groups yet. Closed paper-forward trades are required.</div>;
  }
  return (
    <div className="alpha-table">
      <div className="alpha-table-row head">
        <span>Edge</span><span>Sample</span><span>Alpha</span><span>Avg R</span><span>Warning</span>
      </div>
      {groups.slice(0, 8).map((row) => (
        <div className="alpha-table-row" key={`${row.entity}-${row.sample_size}`}>
          <strong>{row.entity}</strong>
          <span>{row.sample_size ?? 0}</span>
          <span>{formatPct(row.alpha)}</span>
          <span>{formatNumber(row.average_r)}R</span>
          <span>{row.warning || row.evidence_grade || "tracked"}</span>
        </div>
      ))}
    </div>
  );
}

function BlockerList({ rows }: { rows: any[] }) {
  if (!rows.length) {
    return <div className="terminal-empty compact">No blocker stored in the current Alpha snapshot.</div>;
  }
  return (
    <div className="brain-list dense">
      {rows.slice(0, 8).map((item: any, index: number) => (
        <div key={`${item.code ?? index}-${item.title}`}>
          <StatusBadge label={item.code ?? "blocker"} />
          <strong>{item.title ?? String(item)}</strong>
          {item.remedy && <p>{item.remedy}</p>}
        </div>
      ))}
    </div>
  );
}

function Fact({ label, value, detail }: { label: string; value: any; detail?: any }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value ?? "n/a"}</strong>
      {detail && <p>{detail}</p>}
    </div>
  );
}

function normalizeGrade(value: any) {
  const text = String(value ?? "NO_DATA").toUpperCase();
  if (text.includes("STRONG")) return "STRONG";
  if (text.includes("PROMISING")) return "PROMISING";
  if (text.includes("MIXED")) return "MIXED";
  if (text.includes("WEAK")) return "WEAK";
  if (text.includes("INSUFFICIENT")) return "INSUFFICIENT_EVIDENCE";
  if (text.includes("NO_DATA") || text.includes("MISSING")) return "NO_DATA";
  return EVIDENCE_GRADE_ORDER.includes(text) ? text : "NO_DATA";
}

function gradeTone(grade: string): "positive" | "attention" | "negative" | "info" {
  if (grade === "STRONG" || grade === "PROMISING") return "positive";
  if (grade === "MIXED" || grade === "INSUFFICIENT_EVIDENCE") return "attention";
  if (grade === "WEAK" || grade === "NO_DATA") return "negative";
  return "info";
}

function metricTone(value: any): "positive" | "attention" | "negative" | "info" {
  const number = Number(value);
  if (!Number.isFinite(number)) return "attention";
  if (number > 0) return "positive";
  if (number < 0) return "negative";
  return "info";
}

function fallbackVerdict(grade: string) {
  if (grade === "NO_DATA") return "No alpha evidence yet.";
  if (grade === "INSUFFICIENT_EVIDENCE") return "Evidence insufficient.";
  if (grade === "WEAK") return "BLUM is not generating reliable alpha evidence.";
  if (grade === "PROMISING") return "BLUM shows promising but unproven alpha evidence.";
  if (grade === "STRONG") return "BLUM shows strong paper-forward alpha evidence.";
  return "Alpha evidence is mixed.";
}

function tradeLabel(trade: any) {
  if (!trade) return "n/a";
  return `${trade.ticker ?? "Unknown"} · ${trade.setup_type ?? "unknown setup"}`;
}

function tradeDetail(trade: any) {
  if (!trade) return undefined;
  return `R ${formatNumber(trade.r_multiple)} | P/L ${formatMoney(trade.pnl)} | benchmark excess ${formatPct(trade.benchmark_excess)}`;
}

function compactDate(value: any) {
  if (!value) return "n/a";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

function formatNumber(value: any) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(2) : "n/a";
}

function formatPct(value: any) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(2)}%` : "n/a";
}

function formatRatioPct(value: any) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "n/a";
  return `${(number * 100).toFixed(2)}%`;
}

function formatMoney(value: any) {
  const number = Number(value);
  return Number.isFinite(number) ? `€${number.toFixed(2)}` : "n/a";
}
