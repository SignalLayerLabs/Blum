import assert from "node:assert/strict";
import test from "node:test";
import { metricValue, evidencePresentation, validationLabel } from "../lib/ascentView.mjs";

test("missing metrics never appear as zero or improvement", () => {
  assert.equal(metricValue(undefined), "—");
  assert.equal(metricValue(null), "—");
  assert.equal(metricValue(NaN), "—");
  assert.equal(metricValue(0), "0.0000");
  assert.equal(metricValue(0.25), "0.2500");
});

test("historical evidence is visually and explicitly distinct from forward evidence", () => {
  assert.deepEqual(evidencePresentation("REPLAY_EVIDENCE"), { label: "Historical replay", tone: "warning" });
  assert.deepEqual(evidencePresentation("PAPER_FORWARD_FOREX"), { label: "Paper forward · Forex", tone: "neutral" });
  assert.deepEqual(evidencePresentation("unknown"), { label: "Unclassified evidence", tone: "negative" });
});

test("retained research does not imply production promotion", () => {
  assert.equal(validationLabel("RETAINED_RESEARCH"), "Retained for research");
  assert.equal(validationLabel("NOT_SELECTED"), "Not selected · holdout unopened");
  assert.equal(validationLabel("REJECTED"), "Rejected by validation");
});
