export function metricValue(value) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(4) : "—";
}

export function evidencePresentation(lane) {
  if (lane === "REPLAY_EVIDENCE") return { label: "Historical replay", tone: "warning" };
  if (lane === "PAPER_FORWARD_FOREX") return { label: "Paper forward · Forex", tone: "neutral" };
  return { label: "Unclassified evidence", tone: "negative" };
}

export function validationLabel(status) {
  if (status === "RETAINED_RESEARCH") return "Retained for research";
  if (status === "NOT_SELECTED") return "Not selected · holdout unopened";
  if (status === "REJECTED") return "Rejected by validation";
  return status.toLowerCase().replaceAll("_", " ");
}
