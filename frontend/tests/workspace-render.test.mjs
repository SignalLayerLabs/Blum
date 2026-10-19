import "./helpers/tsx-loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { PathnameContext } from "next/dist/shared/lib/hooks-client-context.shared-runtime.js";
const { AppShell } = await import("../components/AppShell.tsx");

const routes = [
  ["/brain", "Overview"],
  ["/calls", "Calls"],
  ["/paper-trading", "Trades"],
  ["/alpha", "Performance"],
  ["/training-ground", "Research"],
];

test("five workspace destinations render and trailing-slash URLs select the right navigation", () => {
  for (const [path, label] of [
    ...routes,
    ["/dashboard", "Overview"],
    ["/copy-trading", "Trades"],
    ["/learning", "Research"],
  ]) {
    for (const pathname of [path, path + "/"]) {
      const markup = renderToStaticMarkup(
        React.createElement(
          PathnameContext.Provider,
          { value: pathname },
          React.createElement(
            AppShell,
            null,
            React.createElement("h1", null, "Workspace content"),
          ),
        ),
      );
      const current =
        markup.match(/<a\b[^>]*aria-current="page"[^>]*>[\s\S]*?<\/a>/g) ?? [];
      assert.equal(current.length, 1, pathname);
      assert.match(current[0], new RegExp(`>${label}</a>`));
      assert.equal((markup.match(/class="blum-nav-link/g) ?? []).length, 5);
      assert.ok(!markup.includes("blum-legacy-surface"), pathname);
      assert.match(markup, /Paper environment/);
    }
  }
});

test("primary pages render useful unavailable/loading evidence without invented results", async () => {
  const modules = [
    ["brain", "Your trading desk"],
    ["calls", "Calls, with their context."],
    ["paper-trading", "Every trade has a record."],
    ["alpha", "Is BLUM earning its edge?"],
    ["training-ground", "Follow the reasoning."],
  ];
  for (const [path, heading] of modules) {
    const { default: Page } = await import(`../app/${path}/page.tsx`);
    const markup = renderToStaticMarkup(React.createElement(Page));
    assert.ok(markup.includes(heading), path);
    assert.match(markup, /Checking/);
    assert.doesNotMatch(markup, /99%|100%|COPY_READY|No completed trades/);
  }
});

test("workspace data readers issue only the vetted GET requests", async () => {
  const {
    overviewReaders,
    callReaders,
    tradeReaders,
    performanceReaders,
    researchReaders,
  } = await import("../components/workspace/useSnapshots.ts");
  const requests = [];
  const previous = globalThis.fetch;
  const previousLocation = globalThis.location;
  globalThis.location = { pathname: "/calls/", search: "" };
  globalThis.fetch = async (path, options) => {
    requests.push({ path, options });
    return new Response(JSON.stringify({ status: "NO_SNAPSHOTS" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  try {
    for (const pathname of ["/", ...routes.map(([path]) => path + "/")]) {
      globalThis.location = { pathname, search: "" };
      for (const group of [
        overviewReaders,
        callReaders,
        tradeReaders,
        performanceReaders,
        researchReaders,
      ])
        for (const reader of Object.values(group)) await reader();
    }
    assert.deepEqual(
      new Set(requests.map((row) => row.path)),
      new Set([
        "/api/runtime/operating-state",
        "/api/brain/snapshot",
        "/api/paper-trading/snapshot?limit=20",
        "/api/paper-trading/snapshot?limit=50",
        "/api/alpha/desk",
        "/api/training/snapshot",
        "/api/training/curriculum",
      ]),
    );
    assert.ok(requests.every((row) => row.options.method === "GET"));
    assert.ok(
      requests.every(
        (row) =>
          !Object.keys(row.options.headers).some((key) =>
            /admin|authorization/i.test(key),
          ),
      ),
    );
  } finally {
    globalThis.fetch = previous;
    if (previousLocation === undefined) delete globalThis.location;
    else globalThis.location = previousLocation;
  }
});

const curriculumSnapshot = {
  version: "curriculum-v1",
  status: "EXPERIMENTAL",
  updated_at: "2026-10-19T12:00:00Z",
  limitations: ["Development windows are reused; confirmation is reserved."],
  lanes: [{
    lane: "USA:1d:SPY", market: "USA", timeframe: "1d", ticker: "SPY",
    checkpoint: "checkpoint1234567890", source_hash: "source1234567890", source_rows: 2500,
    training_episodes: 12, learned_outcomes: 73, training_status: "PACK_EXHAUSTED",
    benchmark: {
      window_hash: "window1234567890", confirmation_opened: false,
      policy: { trade_count: 10, win_rate: 0.6, win_rate_interval: [0.4, 0.76], net_return: 0.05, max_closed_trade_drawdown: 0.03, profit_factor: 1.4, expectancy_r: 0.25 },
      fixed_expert: { trade_count: 8, win_rate: 0.5, win_rate_interval: [0.22, 0.78], net_return: -0.02, max_closed_trade_drawdown: 0.07, profit_factor: 0.8, expectancy_r: -0.1 },
      cash_return: 0, buy_hold_price_return: 0.08,
    },
    forward: { status: "PENDING", decision_at: "2026-10-19T11:00:00Z", updated_at: "2026-10-19T12:00:00Z", closed_count: 2, cash_quote_units: 10025 },
  }],
};

test("curriculum compares modeled outcomes on the stored window without upgrading forward evidence", async () => {
  const { CurriculumPanel } = await import("../components/workspace/Research.tsx");
  assert.equal(typeof CurriculumPanel, "function");
  const markup = renderToStaticMarkup(React.createElement(CurriculumPanel, { snapshot: curriculumSnapshot, pending: false }));

  for (const text of ["Outcome-driven curriculum", "SPY", "Selected policy", "Fixed expert", "Cash", "Price-only hold", "5%", "-2%", "8%", "60%", "40%", "76%", "0.25R", "Learned outcomes", "73", "checkpoint1234567890", "window1234567890", "Source pack exhausted", "Reserved confirmation unopened", "Prospective research paper", "Closed prospective outcomes", "quote units"])
    assert.ok(markup.includes(text), text);
  assert.match(markup, /separate from native paper orders/i);
  assert.match(markup, /excludes dividends and costs/i);
  assert.doesNotMatch(markup, /<pre|COPY_READY|guaranteed|certified/i);
});

test("curriculum distinguishes checking, missing snapshots and failed refreshes", async () => {
  const { CurriculumPanel } = await import("../components/workspace/Research.tsx");
  assert.equal(typeof CurriculumPanel, "function");
  const checking = renderToStaticMarkup(React.createElement(CurriculumPanel, { pending: true }));
  const empty = renderToStaticMarkup(React.createElement(CurriculumPanel, { snapshot: { ...curriculumSnapshot, lanes: [], updated_at: null }, pending: false }));
  const failed = renderToStaticMarkup(React.createElement(CurriculumPanel, { pending: false, error: "503" }));
  const cached = renderToStaticMarkup(React.createElement(CurriculumPanel, { snapshot: curriculumSnapshot, pending: false, error: "503" }));

  assert.match(checking, /Checking curriculum snapshot/);
  assert.match(empty, /No curriculum lanes stored/);
  assert.match(failed, /Curriculum snapshot unavailable/);
  assert.match(cached, /Showing the last stored curriculum/);
  assert.match(cached, /checkpoint1234567890/);
  for (const markup of [checking, empty, failed]) assert.doesNotMatch(markup, /0%|0 episodes|0 outcomes/);
});

test("curriculum keeps prospective outcomes distinct through every stored forward state", async () => {
  const { CurriculumPanel } = await import("../components/workspace/Research.tsx");
  assert.equal(typeof CurriculumPanel, "function");
  for (const [status, label] of [
    ["PENDING", "Pending later market bars"], ["CLOSED", "Research paper outcome closed"],
    ["STALE_CONTEXT", "Waiting for fresh context"], ["WAITING_SIGNAL", "Waiting for a signal"],
    ["UNFILLED", "Research order unfilled"],
  ]) {
    const lane = curriculumSnapshot.lanes[0];
    const snapshot = { ...curriculumSnapshot, lanes: [{ ...lane, forward: { ...lane.forward, status } }] };
    const markup = renderToStaticMarkup(React.createElement(CurriculumPanel, { snapshot, pending: false }));
    assert.ok(markup.includes(label), status);
    assert.match(markup, /separate from native paper orders/i);
  }
});

test("populated open and partial trade rows expose their mark and unrealized amount", async () => {
  const { TradeRow } = await import("../components/workspace/TradeRow.tsx");
  for (const status of ["OPEN", "PARTIALLY_FILLED"]) {
    const markup = renderToStaticMarkup(
      React.createElement(
        "table",
        null,
        React.createElement(
          "tbody",
          null,
          React.createElement(TradeRow, {
            row: {
              status,
              ticker: "EURUSD=X",
              direction: "LONG",
              opened_at: "2026-10-15T12:00:00Z",
              entry_price: 1.1,
              current_price: 1.1015,
              position_size: 0.01,
              pnl_currency: "EUR",
              unrealized_pnl: -0.0025,
            },
            expanded: false,
            onInspect: () => {},
          }),
        ),
      ),
    );
    assert.match(markup, /1\.1015/);
    assert.match(markup, /-0\.0025 EUR · unrealized/);
    assert.match(markup, /op-loss/);
    assert.doesNotMatch(markup, /Not realized/);
  }
});

test("snapshot source status overrides a recent timestamp", async () => {
  const { Freshness } = await import("../components/workspace/Primitives.tsx");
  for (const [status, message] of [
    ["stale", /marked stale/],
    ["missing", /unavailable/],
    ["invalid_clock", /invalid evaluation clock/],
  ]) {
    const markup = renderToStaticMarkup(
      React.createElement(Freshness, {
        at: new Date().toISOString(),
        status,
      }),
    );
    assert.match(markup, /op-warning/);
    assert.match(markup, message);
  }
});
