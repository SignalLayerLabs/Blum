import { Empty, Panel, human, number, stamp } from "./Primitives";

const names: Record<string, string> = {
  intraday_paper_trading: "Intraday scanner",
  paper_execution_lifecycle: "Order & position manager",
  live_forward_paper_trading: "Paper-forward scanner",
};
export function OperatingState({
  data,
  error,
  market,
}: {
  data: any;
  error?: string;
  market: string;
}) {
  const source = data?.markets?.[market];
  return (
    <Panel
      title="Is the engine working?"
      description="Persisted worker observations; a running process is separate from an executed trade."
    >
      {!source ? (
        <Empty
          title={
            error
              ? "Worker status could not refresh"
              : "Reading worker observations"
          }
        >
          Worker activity has not been established by the available response.
          Trading results below are separate evidence.
        </Empty>
      ) : market === "forex" ? (
        <>
          <div className="op-operating-state">
            <span className="op-status">{human(source.status)}</span>
            <p>
              Control state: {human(source.desired_state)}.{" "}
              {source.worker_observed_alive
                ? "A recent worker heartbeat is recorded."
                : "No recent valid worker heartbeat is established."}
            </p>
          </div>
          <div className="op-runtime-grid">
            <div>
              <span>Worker heartbeat</span>
              <strong>{stamp(source.heartbeat_at)}</strong>
            </div>
            <div>
              <span>Last completed cycle</span>
              <strong>
                {stamp(source.last_completed_cycle?.completed_at)}
              </strong>
            </div>
            <div>
              <span>Orders / fills · last cycle</span>
              <strong>
                {number(source.last_completed_cycle?.orders)} /{" "}
                {number(source.last_completed_cycle?.fills)}
              </strong>
            </div>
          </div>
          <p className="op-body-copy">
            {source.active_blockers?.length
              ? `Current no-entry reasons: ${source.active_blockers.map(human).join(" · ")}`
              : "No completed-cycle blocker is reported. This does not establish a new trade."}
          </p>
        </>
      ) : (
        <div className="op-runtime-grid">
          {source.workers?.map((worker: any) => (
            <div key={worker.name}>
              <span>{names[worker.name] ?? human(worker.name)}</span>
              <strong>{human(worker.status)}</strong>
              <small>
                Started {stamp(worker.last_started_at)}
                <br />
                Completed {stamp(worker.last_completed_at)}
              </small>
            </div>
          ))}
        </div>
      )}
      {error && source && (
        <p role="alert" className="op-error-note">
          Worker status could not refresh. Inspect the recorded timestamps.
        </p>
      )}
      <p className="op-footnote">
        Heartbeat and job timestamps describe worker activity. They do not
        certify quote freshness or a profitable trading edge. Visible views
        refresh automatically after one minute.
      </p>
    </Panel>
  );
}
