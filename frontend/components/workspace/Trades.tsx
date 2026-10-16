"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  filterPaperMarket,
  mergePaperTrades,
} from "@/lib/paperTradingView.mjs";
import {
  operatingMarket,
  tradeLifecycle,
  tradeMoney,
  tradeCostLines,
} from "@/lib/operatingView.mjs";
import { useSnapshots, tradeReaders } from "./useSnapshots";
import {
  Empty,
  Freshness,
  MarketTabs,
  Metric,
  PageHeader,
  Panel,
  human,
  number,
  stamp,
} from "./Primitives";

import { TradeRow, money } from "./TradeRow";

const lifecycles = [
  ["open", "Open positions"],
  ["closed", "Executed closures"],
  ["unfilled", "Unfilled orders"],
  ["decisions", "Research decisions"],
  ["unverified", "Unverified records"],
];

export function Trades() {
  const { data, errors, pending, refresh } = useSnapshots(tradeReaders);
  const [market, setMarket] = useState("equity");
  const [lifecycle, setLifecycle] = useState("open");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<any>(null);
  const [detail, setDetail] = useState<any>(null);
  const [detailError, setDetailError] = useState("");
  const view = operatingMarket(data, market);
  const all = filterPaperMarket(
    mergePaperTrades(data.paper),
    market === "forex" ? "forex" : "equities",
  );
  const rows = all.filter(
    (row: any) =>
      tradeLifecycle(row) === lifecycle &&
      String(row.ticker ?? "")
        .toUpperCase()
        .includes(search.trim().toUpperCase()),
  );
  useEffect(() => {
    let active = true;
    setDetail(null);
    setDetailError("");
    if (selected)
      api
        .unifiedPaperTradingDetail(
          selected.source_engine,
          selected.source_trade_id,
        )
        .then((value) => {
          if (active) {
            if (value?.status === "NOT_FOUND")
              setDetailError("The source record was not found");
            else setDetail(value);
          }
        })
        .catch((error) => {
          if (active) setDetailError(String(error.message ?? error));
        });
    return () => {
      active = false;
    };
  }, [selected]);
  useEffect(() => {
    if (!selected) return;
    const panel = document.getElementById("trade-detail");
    panel?.focus({ preventScroll: true });
    panel?.scrollIntoView({ block: "start", behavior: "auto" });
  }, [selected]);
  const trade = detail?.trade ?? selected;
  const pnl = tradeMoney(trade);
  return (
    <div className="op-page">
      <PageHeader
        eyebrow="Execution & accounting"
        title="Every trade has a record."
        description="Inspect real paper positions, unfilled orders and recorded costs. A skipped idea is not a trade."
        pending={pending}
        onRefresh={refresh}
      />
      <div className="op-context">
        <MarketTabs
          market={market}
          onChange={(value) => {
            setMarket(value);
            setSelected(null);
          }}
        />
        <Freshness
          at={data.paper?.snapshot_created_at ?? data.paper?.generated_at}
          error={errors.paper}
        />
      </div>
      <div className="op-metrics op-three">
        <Metric
          label="Open positions"
          value={number(view.open)}
          detail="Source-reported positions; separate from candidates."
        />
        <Metric
          label="Executed closures"
          value={number(view.closed)}
          detail="Source history, including legacy paper execution."
        />
        <Metric
          label="Terminal orders without P/L"
          value={number(view.noFill)}
          detail="These are excluded from the realized-result sample."
        />
      </div>
      <Panel
        title="Trade journal"
        description="A bounded snapshot of recent records; filters apply to the visible sample."
      >
        <div className="op-filterbar">
          <div className="op-filter-tabs" aria-label="Trade lifecycle">
            {lifecycles.map(([key, label]) => (
              <button
                type="button"
                key={key}
                aria-pressed={lifecycle === key}
                onClick={() => {
                  setLifecycle(key);
                  setSelected(null);
                }}
              >
                {label}
              </button>
            ))}
          </div>
          <label className="op-search">
            Asset
            <input
              type="search"
              placeholder="Search ticker"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
        </div>
        {rows.length ? (
          <div className="op-table-wrap">
            <table className="op-table">
              <thead>
                <tr>
                  <th>Asset / side</th>
                  <th>Status / timing</th>
                  <th>Entry / mark / exit</th>
                  <th>P/L</th>
                  <th>Inspect</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row: any) => (
                  <TradeRow
                    key={row.trade_id}
                    row={row}
                    expanded={selected?.trade_id === row.trade_id}
                    onInspect={() => setSelected(row)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title={
              pending && !data.paper
                ? "Reading the paper record"
                : `No ${lifecycles.find(([key]) => key === lifecycle)?.[1].toLowerCase()} in this view`
            }
          >
            This filter covers the visible snapshot. It does not infer an empty
            database or successful trading.
          </Empty>
        )}
        <p className="op-footnote">
          {number(all.length)} visible records for this market. No-fill and
          unverified records do not enter this view’s executed-closure list.
        </p>
      </Panel>
      {selected && (
        <Panel
          id="trade-detail"
          title={`${selected.ticker} · execution detail`}
          description={`${human(selected.source_engine)} · source #${selected.source_trade_id}`}
        >
          <div className="op-detail-actions">
            <button
              type="button"
              className="op-button"
              onClick={() => setSelected(null)}
            >
              Close detail
            </button>
            <span>
              {detailError
                ? "Detail unavailable"
                : detail
                  ? "Source detail loaded"
                  : "Reading source detail…"}
            </span>
          </div>
          {detailError && (
            <p className="op-error-note" role="alert">
              {detailError}. Snapshot fields below retain their original
              timestamp.
            </p>
          )}
          <div className="op-metrics op-three">
            <Metric
              label="Gross result"
              value={money(pnl.gross, pnl.currency)}
              detail="Recorded gross amount; currency must be declared."
            />
            <Metric
              label={
                tradeLifecycle(trade) === "open"
                  ? "Unrealized result"
                  : "Net result"
              }
              value={money(
                tradeLifecycle(trade) === "open"
                  ? trade?.unrealized_pnl
                  : pnl.net,
                pnl.currency,
              )}
              detail="Recorded net amount. Missing does not mean zero."
            />
            <Metric
              label={
                tradeLifecycle(trade) === "open"
                  ? "Current R (source)"
                  : "Realized R"
              }
              value={number(trade?.r_multiple, 3)}
              detail="Result relative to the declared risk amount."
            />
          </div>
          <div className="op-two-column">
            <div>
              <h3 className="op-subheading">Costs in the source record</h3>
              {tradeCostLines(trade).map((line) => (
                <div key={line.label} className="op-evidence-line">
                  <span>{line.label}</span>
                  <strong>
                    {number(line.amount, 6)}{" "}
                    {line.currency ?? "· unit unavailable"}
                  </strong>
                </div>
              ))}
              <p className="op-footnote">
                Recorded model assumptions are available in the event details.
                Embedded execution costs must not be subtracted twice.
              </p>
            </div>
            <div>
              <h3 className="op-subheading">Plan & outcome</h3>
              <div className="op-evidence-line">
                <span>Recorded mark</span>
                <strong>{number(trade?.current_price, 5)}</strong>
              </div>
              <div className="op-evidence-line">
                <span>Stop</span>
                <strong>{number(trade?.stop_loss, 5)}</strong>
              </div>
              <div className="op-evidence-line">
                <span>Target</span>
                <strong>{number(trade?.target_1, 5)}</strong>
              </div>
              <p className="op-body-copy">
                {human(trade?.close_reason ?? trade?.outcome_label)}
              </p>
              <p className="op-body-copy">
                {trade?.lesson_learned ?? "No stored lesson."}
              </p>
            </div>
          </div>
          <details className="op-disclosure">
            <summary>
              Source events & assumptions ({number(detail?.events?.length)})
            </summary>
            <pre>
              {JSON.stringify(
                {
                  cost_model: trade?.costs ?? {},
                  events: detail?.events ?? [],
                },
                null,
                2,
              )}
            </pre>
          </details>
        </Panel>
      )}
      {errors.paper && (
        <div className="op-error-note" role="alert">
          The trade snapshot could not refresh. {errors.paper}
        </div>
      )}
    </div>
  );
}
