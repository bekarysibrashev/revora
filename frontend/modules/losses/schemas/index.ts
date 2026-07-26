export type LossOpportunity = {
  id: string;
  branch_id: string | null;
  assigned_user_id: string | null;
  loss_type: string;
  severity: "critical" | "warning";
  status: "open" | "in_progress" | "recovered" | "dismissed";
  title: string;
  description: string;
  recommended_action: string;
  entity_type: string | null;
  entity_id: string | null;
  estimated_amount: string;
  recovered_amount: string;
  currency: string;
  confidence: string;
  evidence: Record<string, unknown>;
  detected_at: string;
  last_detected_at: string;
};

export type LossMap = {
  summary: {
    estimated_total: string;
    recovered_total: string;
    open_count: number;
    in_progress_count: number;
    recovered_count: number;
    critical_count: number;
  };
  items: LossOpportunity[];
  total: number;
  generated_at: string;
};
