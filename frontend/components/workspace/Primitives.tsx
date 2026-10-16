import Link from "next/link";
import { ArrowUpRight, RefreshCw } from "lucide-react";
import {
  finiteMetric,
  snapshotAge,
  utcTimestamp,
} from "@/lib/operatingView.mjs";
export function number(value: unknown, digits = 0) {
  const n = finiteMetric(value);
  return n === null
    ? "—"
    : n.toLocaleString("en-US", { maximumFractionDigits: digits });
}
export function stamp(value: unknown) {
  const n = utcTimestamp(value);
  return n === null
    ? "Timestamp unavailable"
    : new Date(n).toLocaleString(undefined, {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      });
}
export function human(value: unknown) {
  return typeof value === "string"
    ? value
        .toLowerCase()
        .replaceAll("_", " ")
        .replace(/^\w/, (char) => char.toUpperCase())
    : "Unavailable";
}
export function MarketTabs({
  market,
  onChange,
}: {
  market: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="op-tabs" aria-label="Market">
      <button
        type="button"
        aria-pressed={market === "equity"}
        onClick={() => onChange("equity")}
      >
        Equities & ETFs
      </button>
      <button
        type="button"
        aria-pressed={market === "forex"}
        onClick={() => onChange("forex")}
      >
        Forex
      </button>
    </div>
  );
}
export function PageHeader({
  eyebrow,
  title,
  description,
  pending,
  onRefresh,
}: {
  eyebrow: string;
  title: string;
  description: string;
  pending: boolean;
  onRefresh: () => void;
}) {
  return (
    <header className="op-page-heading">
      <div>
        <span className="op-eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <button
        className="op-button op-refresh"
        onClick={onRefresh}
        type="button"
        disabled={pending}
      >
        <RefreshCw size={15} className={pending ? "op-spin" : ""} />
        {pending ? "Checking…" : "Refresh"}
      </button>
    </header>
  );
}
export function Panel({
  id,
  title,
  description,
  href,
  children,
  className = "",
}: {
  id?: string;
  title: string;
  description?: string;
  href?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      id={id}
      tabIndex={id ? -1 : undefined}
      className={`op-panel ${className}`}
    >
      <div className="op-panel-heading">
        <div>
          <h2>{title}</h2>
          {description && <p>{description}</p>}
        </div>
        {href && (
          <Link href={href} aria-label={`Open ${title}`}>
            <ArrowUpRight size={19} />
          </Link>
        )}
      </div>
      {children}
    </section>
  );
}
export function Metric({
  label,
  value,
  detail,
  tone = "neutral",
}: {
  label: string;
  value: string;
  detail: string;
  tone?: string;
}) {
  return (
    <article className={`op-metric op-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <p>{detail}</p>
    </article>
  );
}
export function Freshness({ at, error }: { at?: string; error?: string }) {
  const age = snapshotAge(at);
  return (
    <div
      className={`op-freshness ${error || age.state === "future" || age.state === "stale" ? "op-warning" : ""}`}
    >
      <span className="op-dot" />
      {error
        ? "Refresh unavailable; inspect the snapshot timestamp"
        : age.state === "unknown"
          ? "Snapshot timestamp unavailable"
          : age.state === "future"
            ? "Snapshot timestamp is ahead of the clock"
            : `Snapshot ${stamp(at)}${age.state === "stale" ? " · older than 5 minutes" : ""}`}
    </div>
  );
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="op-empty">
      <strong>{title}</strong>
      <p>{children}</p>
    </div>
  );
}
