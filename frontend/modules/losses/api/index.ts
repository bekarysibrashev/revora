import { api } from "@/shared/api-client";
import type { LossMap, LossOpportunity } from "../schemas";

export function getLossMap(query: string) {
  return api<LossMap>(`/losses/map?${query}`);
}

export function refreshLossMap(query: string) {
  return api<LossMap & { detected: number }>(`/losses/refresh?${query}`, {
    method: "POST",
  });
}

export function updateLoss(
  id: string,
  payload: {
    status: string;
    recovered_amount?: number;
    assigned_user_id?: string | null;
  },
) {
  return api<LossOpportunity>(`/losses/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}
