export type CurriculumMetrics = {
  trade_count: number;
  win_rate: number | null;
  win_rate_interval: [number, number] | null;
  net_return: number | null;
  max_closed_trade_drawdown: number;
  profit_factor: number | null;
  expectancy_r: number | null;
};

export type CurriculumLane = {
  lane: string;
  market: string;
  timeframe: string;
  ticker: string;
  checkpoint: string;
  training_episodes: number;
  learned_outcomes: number;
  training_status: "TRAINING" | "PACK_EXHAUSTED";
  source_hash: string;
  source_rows: number;
  benchmark?: {
    window_hash: string;
    previous_net_return?: number | null;
    return_change_from_previous?: number | null;
    confirmation_opened: boolean;
    policy: CurriculumMetrics;
    fixed_expert: CurriculumMetrics;
    cash_return: number;
    buy_hold_price_return: number;
  } | null;
  forward?: {
    status: "PENDING" | "OPEN" | "CLOSED" | "STALE_CONTEXT" | "WAITING_SIGNAL" | "UNFILLED" | "BLOCKED";
    decision_at?: string;
    updated_at?: string;
    learned_outcomes?: number;
    closed_count: number;
    cash_quote_units: number;
    last_outcome?: { status?: string; net_r?: number; reason?: string };
  } | null;
};

export type CurriculumSnapshot = {
  version: "curriculum-v1";
  status: "EXPERIMENTAL";
  updated_at: string | null;
  lanes: CurriculumLane[];
  limitations: string[];
};
