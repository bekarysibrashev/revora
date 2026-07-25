import { api } from "@/shared/api-client";
import type { DataQuality, MetricCatalog } from "../schemas";

export function getDataQuality(query: string) {
  return api<DataQuality>(`/analytics/quality?${query}`);
}

export function getMetricCatalog(query: string) {
  return api<MetricCatalog>(`/analytics/metrics?${query}`);
}
