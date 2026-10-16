import test from "node:test";
import assert from "node:assert/strict";
import {
  operatingMarket,
  finiteMetric,
  callState,
  engineEvidence,
} from "../lib/operatingView.mjs";

test("missing numeric evidence stays unavailable, including empty strings and booleans", () => {
  for (const input of [null, undefined, "", " ", false, true, NaN, Infinity])
    assert.equal(finiteMetric(input), null);
  assert.equal(finiteMetric(0), 0);
  assert.equal(finiteMetric(-2.5), -2.5);
});
test("absent market payload is not a zero-trade success state", () => {
  const view = operatingMarket({}, "forex");
  assert.equal(view.available, false);
  assert.equal(view.closed, null);
  assert.equal(view.realized, null);
});
test("market outcomes use their own sample and never pooled aggregate returns", () => {
  const paper = {
    counts: {
      aggregate: { closed: 999 },
      by_market: { forex: { closed: 4, open: 1, no_fill_outcomes: 8 } },
    },
    metrics: {
      aggregate: { realized_pnl: 2000 },
      by_market: {
        forex: { sample_size: 4, expectancy_r: -0.2, win_rate: 0.25 },
      },
    },
  };
  const view = operatingMarket({ paper }, "forex");
  assert.equal(view.closed, 4);
  assert.equal(view.open, 1);
  assert.equal(view.noFill, 8);
  assert.equal(view.expectancyR, -0.2);
  assert.equal(view.realized, null);
});
test("qualified money remains grouped by account currency and is never silently summed", () => {
  const desk = {
    markets: {
      forex: {
        registered: 30,
        qualified_closed: 4,
        paired_sample: 0,
        observed_net_pnl_by_currency: { USD: 12, EUR: -3 },
        observed_net_pnl: null,
        pnl_currency: null,
      },
    },
  };
  const view = operatingMarket({ desk }, "forex");
  assert.deepEqual(view.pnlByCurrency, { USD: 12, EUR: -3 });
  assert.equal(view.realized, null);
  assert.equal(view.currency, null);
});
test("a recorded old plan is not an upcoming copy opportunity", () => {
  const desk = {
    markets: { equity: { active_calls: [] } },
    journal: [{ market: "equity", status: "CLOSED", entry: 100, target: 120 }],
  };
  assert.deepEqual(callState(desk, "equity").active, []);
  assert.equal(callState(desk, "equity").status, "NO_ACTIVE_CALL");
});
test("brain scores and activity counts do not turn into measured intelligence or alpha", () => {
  const result = engineEvidence(
    {
      brain: {
        brain_score: 99,
        learning_proof: { cycles_observed: 20, predictions_created: 1000 },
      },
      desk: { markets: { equity: { paired_sample: 0, qualified_closed: 0 } } },
    },
    "equity",
  );
  assert.equal(result.level, "COLLECTING_EVIDENCE");
  assert.equal(result.paired, 0);
  assert.equal(result.cycles, 20);
  assert.equal(result.calibratedProbability, null);
});

test("UTC-naive backend timestamps retain their UTC meaning", async () => {
  const { utcTimestamp } = await import("../lib/operatingView.mjs");
  assert.equal(
    utcTimestamp("2026-10-15T10:03:33"),
    Date.parse("2026-10-15T10:03:33Z"),
  );
});
test("future and stale snapshots cannot be advertised as recent", async () => {
  const { snapshotAge } = await import("../lib/operatingView.mjs");
  const now = Date.parse("2026-10-15T10:05:00Z");
  assert.equal(snapshotAge("2026-10-15T10:06:00", now).state, "future");
  assert.equal(snapshotAge("2026-10-15T09:00:00", now).state, "stale");
});

test("an expired unfilled order is not an executed or breakeven trade", async () => {
  const { tradeLifecycle } = await import("../lib/operatingView.mjs");
  assert.equal(
    tradeLifecycle({
      status: "EXPIRED",
      opened_at: null,
      entry_price: null,
      position_size: 0,
      net_pnl: 0,
    }),
    "unfilled",
  );
  assert.equal(
    tradeLifecycle({
      status: "CLOSED",
      opened_at: "2026-10-15T10:00:00",
      entry_price: 100,
      position_size: 2,
      net_pnl: 0,
    }),
    "closed",
  );
  assert.equal(
    tradeLifecycle({
      status: "OPEN",
      opened_at: "2026-10-15T10:00:00",
      entry_price: 100,
      position_size: 2,
    }),
    "open",
  );
});

test("native Forex money needs its frozen account currency; legacy EUR alias is insufficient", async () => {
  const { tradeMoney } = await import("../lib/operatingView.mjs");
  assert.deepEqual(
    tradeMoney({ source_engine: "forex_trader", net_pnl: 12, net_pnl_eur: 12 }),
    { net: null, gross: null, currency: null },
  );
  assert.deepEqual(
    tradeMoney({
      source_engine: "forex_trader",
      net_pnl: 12,
      gross_pnl: 14,
      pnl_currency: "USD",
    }),
    { net: 12, gross: 14, currency: "USD" },
  );
  assert.deepEqual(
    tradeMoney({
      source_engine: "paper_forward",
      net_pnl_eur: 0,
      gross_pnl_eur: 1,
    }),
    { net: 0, gross: 1, currency: "EUR" },
  );
});

test("cost presentation never labels order IDs, basis points or fill counts as cash charges", async () => {
  const { tradeCostLines } = await import("../lib/operatingView.mjs");
  const lines = tradeCostLines({
    source_engine: "paper_forward",
    costs: {
      order_id: 33,
      fill_count: 2,
      spread_bps: 1,
      spread_cost: 0.02,
      slippage_cost: 0,
      commission_cost: 0.03,
      total: 0.05,
    },
  });
  assert.deepEqual(
    lines.map((row) => row.label),
    ["Spread", "Slippage", "Commission", "Reported net execution cost"],
  );
  assert.deepEqual(
    lines.map((row) => row.amount),
    [0.02, 0, 0.03, 0.05],
  );
  assert.ok(lines.every((row) => row.currency === "EUR"));
});

test("cash-accounting detail shows explicit charges without subtracting embedded fill costs twice", async () => {
  const { tradeCostLines } = await import("../lib/operatingView.mjs");
  const lines = tradeCostLines({
    pnl_currency: "USD",
    costs: {
      spread_cost: 0.2,
      slippage_cost: 0.1,
      accounting: {
        entry_commission: 1,
        entry_fx_cost: 0,
        exit_commission: 1,
        exit_fx_cost: 0,
        explicit_costs: 2,
      },
    },
  });
  assert.equal(lines.length, 5);
  assert.equal(lines.at(-1).label, "Explicit cash charges");
  assert.equal(lines.at(-1).amount, 2);
  assert.ok(lines.every((row) => row.currency === "USD"));
});

test("a genuine partial fill is an open exposure, never a research-only candidate", async () => {
  const { tradeLifecycle } = await import("../lib/operatingView.mjs");
  assert.equal(
    tradeLifecycle({
      status: "PARTIALLY_FILLED",
      opened_at: "2026-10-15T10:00:00",
      entry_price: 100,
      position_size: 0.25,
    }),
    "open",
  );
  assert.equal(
    tradeLifecycle({
      status: "PARTIALLY_FILLED",
      opened_at: null,
      entry_price: null,
      position_size: 0,
    }),
    "unverified",
  );
});

test("an explicitly unverified currency cannot fall back to a legacy EUR alias", async () => {
  const { tradeMoney } = await import("../lib/operatingView.mjs");
  assert.deepEqual(
    tradeMoney({
      source_engine: "paper_forward",
      pnl_currency: null,
      net_pnl: 2,
      net_pnl_eur: 2,
    }),
    { net: null, gross: null, currency: null },
  );
});

test("a cached research evaluation cannot become a current call", () => {
  const value = callState(
    {
      markets: {
        equity: {
          active_calls_current: false,
          active_calls: [{ active_eligible: true, status: "OPEN" }],
        },
      },
    },
    "equity",
  );
  assert.equal(value.current, false);
  assert.deepEqual(value.active, []);
});
