export type NoShowReadiness = {
  status: "empty" | "insufficient" | "exploratory" | "ready";
  status_reason: string;
  row_count: number;
  positive_count: number;
  positive_rate: string;
  date_min: string | null;
  date_max: string | null;
  source_max_updated_at: string | null;
  recommended_train_rows: number;
  recommended_positive_rows: number;
  feature_coverage: {
    name: string;
    description: string;
    available_count: number;
    coverage_rate: string;
    usable: boolean;
  }[];
  cohorts: {
    dimension: string;
    value: string;
    label: string;
    appointments: number;
    no_shows: number;
    no_show_rate: string;
    lift_vs_baseline: string | null;
    confidence_low: string;
    confidence_high: string;
    reliable: boolean;
  }[];
  generated_at: string;
};

export type MLDatasetSnapshot = {
  id: string;
  purpose: string;
  snapshot_key: string;
  branch_id: string | null;
  date_from: string;
  date_to: string;
  row_count: number;
  positive_count: number;
  feature_schema: Record<string, unknown>;
  quality_report: Record<string, unknown>;
  source_max_updated_at: string | null;
  created_at: string;
};

export type MLRegistry = {
  dataset_snapshots: number;
  experiments: number;
  model_versions: number;
  predictions: number;
  active_model: boolean;
};
