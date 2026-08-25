export type DatasetHealth = {
  key: string;
  name: string;
  record_count: number;
  latest_at: string | null;
  status: "ready" | "stale" | "empty" | "unknown" | "not_connected";
  scope: "tenant" | "period" | "external";
};

export type QualityIssue = {
  code: string;
  name: string;
  description: string;
  severity: "critical" | "warning";
  affected_records: number;
  dataset: string;
};

export type DataQuality = {
  summary: {
    score: number;
    status: "good" | "warning" | "critical";
    ready_datasets: number;
    total_datasets: number;
    critical_issues: number;
    warning_issues: number;
  };
  datasets: DatasetHealth[];
  issues: QualityIssue[];
  connections: {
    id: string;
    provider: string;
    name: string;
    status: string;
    last_sync_at: string | null;
    last_sync_status: string | null;
  }[];
  generated_at: string;
};

export type MetricCatalog = {
  items: {
    key: string;
    name: string;
    group: string;
    description: string;
    formula: string;
    required_datasets: string[];
    available: boolean;
    missing_datasets: string[];
  }[];
  available: number;
  total: number;
  generated_at: string;
};
