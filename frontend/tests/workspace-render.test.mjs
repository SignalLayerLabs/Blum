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
