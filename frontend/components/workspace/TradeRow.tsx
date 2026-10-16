import {
  finiteMetric,
  tradeLifecycle,
  tradeMoney,
} from "@/lib/operatingView.mjs";
import { human, number, stamp } from "./Primitives";

export function money(value: unknown, currency: string | null) {
  return currency ? `${number(value, 6)} ${currency}` : "Currency unavailable";
}

export function TradeRow({
  row,
  expanded,
  onInspect,
}: {
  row: any;
  expanded: boolean;
  onInspect: () => void;
}) {
  const values = tradeMoney(row);
  const lifecycle = tradeLifecycle(row);
  const result =
    lifecycle === "closed"
      ? values.net
      : lifecycle === "open"
        ? finiteMetric(row.unrealized_pnl)
        : null;
  return (
    <tr>
      <td>
        <strong>{row.ticker}</strong>
        <span>{human(row.direction)}</span>
      </td>
      <td>
        {human(row.status)}
        <span>
          {stamp(row.closed_at ?? row.opened_at ?? row.decision_timestamp)}
        </span>
      </td>
      <td>
        {number(row.entry_price, 5)} → {number(row.current_price, 5)}
        <span>Entry → recorded mark</span>
        <span>
          Exit {number(row.exit_price, 5)} · size {number(row.position_size, 6)}
        </span>
      </td>
      <td className={result !== null && result < 0 ? "op-loss" : ""}>
        {lifecycle === "closed"
          ? money(result, values.currency)
          : lifecycle === "open"
            ? `${money(result, values.currency)} · unrealized`
            : "Not realized"}
        <span>
          {number(row.r_multiple, 3)} R · {human(row.accounting_status)}
        </span>
      </td>
      <td>
        <button
          className="op-button"
          type="button"
          aria-expanded={expanded}
          onClick={onInspect}
        >
          View record
        </button>
      </td>
    </tr>
  );
}
