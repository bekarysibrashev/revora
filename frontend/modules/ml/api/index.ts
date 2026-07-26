import { api } from "@/shared/api-client";
import type {
  MLDatasetSnapshot,
  MLRegistry,
  NoShowReadiness,
} from "../schemas";

export function getNoShowReadiness(query: string) {
  return api<NoShowReadiness>(`/ml/no-show/readiness?${query}`);
}

export function createNoShowSnapshot(query: string) {
  return api<MLDatasetSnapshot>(`/ml/no-show/snapshots?${query}`, {
    method: "POST",
  });
}

export function getMLSnapshots() {
  return api<{ items: MLDatasetSnapshot[]; total: number }>("/ml/snapshots");
}

export function getMLRegistry() {
  return api<MLRegistry>("/ml/registry");
}
