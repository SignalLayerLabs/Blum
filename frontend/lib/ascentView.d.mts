export function metricValue(value: number | null | undefined): string;
export function evidencePresentation(lane: string): { label: string; tone: string };
export function validationLabel(status: string): string;

export type AscentMetrics = Record<string, number | null | undefined>;
export type AscentExperiment = {
  experiment_uid: string; generation_uid: string; status: string; source_sha256: string; source_text: string;
  development: { candidate?: AscentMetrics; champion?: AscentMetrics; brier_improvement?: number };
  validation: {
    candidate?: AscentMetrics; champion?: AscentMetrics; climatology?: AscentMetrics;
    blockers?: string[]; warnings?: string[]; research_eligible?: boolean; independent_recheck?: boolean;
    uncertainty?: { method: string; blocks: number; alpha: number; gain_lower_bound: number | null; assumption: string };
    slices?: Array<{ dimension: string; key: string; sample_size: number; brier_gain: number }>;
  };
};
export type AscentGeneration = {
  generation_uid: string; parent_uid: string | null; market_family: string; evidence_lane: string; status: string;
  source_revision: string; hypothesis: string; selected_experiment_uid: string | null;
  started_at: string; completed_at: string | null; blockers?: string[]; duration_seconds?: number;
  manifest: { dataset_hash?: string; trusted_code_hash?: string; seed?: number; training_samples?: number;
    development_samples?: number; holdout_samples?: number; purged_rows?: number; embargo_days?: number;
    budgets?: { max_rows: number; max_candidates: number; max_seconds: number; gpu_seconds: number; external_inference_calls: number } };
};
export type AscentSnapshot = {
  status: string; enabled: boolean; scheduler_enabled: boolean; generations: AscentGeneration[];
  experiments: AscentExperiment[]; research_champions: Array<{ experiment_uid: string; source_sha256: string }>;
  production_champions: Array<{ model_uid: string; market_family: string }>;
  strategy_champions: Array<{ fingerprint: string; family: string }>;
  policy: string; level_2: { status: string; training_launched: boolean; champion_repository: string };
};
