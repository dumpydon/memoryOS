import { apiFetch } from "./client";
import type {
  DemoCatalogResponse,
  ExecutionMode,
  IngestInteractionResponse,
  MemoryHistoryResponse,
  MemoryListResponse,
  MemoryRecord,
  OverviewResponse,
  RecallComparisonResponse,
} from "./types";

export type MemoryListQuery = {
  scopeId: string;
  cursor?: string | null;
  limit?: number;
  memoryTypes?: string[];
  statuses?: string[];
  search?: string;
};

function paramsFromObject(entries: Array<[string, string | null | undefined]>) {
  const params = new URLSearchParams();
  entries.forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  return params;
}

export function getOverview(scopeId: string, token?: string | null) {
  return apiFetch<OverviewResponse>(
    `/v1/overview?scope_id=${encodeURIComponent(scopeId)}`,
    { token },
  );
}

export function getDemoCatalog(token?: string | null) {
  return apiFetch<DemoCatalogResponse>("/v1/demo/scenarios", { token });
}

export function getMemories(query: MemoryListQuery, token?: string | null) {
  const params = paramsFromObject([
    ["scope_id", query.scopeId],
    ["cursor", query.cursor],
    ["limit", String(query.limit || 25)],
    ["search", query.search],
  ]);
  query.memoryTypes?.forEach((type) => params.append("memory_types", type));
  query.statuses?.forEach((status) => params.append("statuses", status));
  return apiFetch<MemoryListResponse>(`/v1/memories?${params.toString()}`, {
    token,
  });
}

export function getMemory(
  scopeId: string,
  memoryId: string,
  token?: string | null,
) {
  return apiFetch<MemoryRecord>(
    `/v1/memories/${encodeURIComponent(memoryId)}?scope_id=${encodeURIComponent(scopeId)}`,
    { token },
  );
}

export function getMemoryHistory(
  scopeId: string,
  memoryId: string,
  token?: string | null,
) {
  return apiFetch<MemoryHistoryResponse>(
    `/v1/memories/${encodeURIComponent(memoryId)}/history?scope_id=${encodeURIComponent(scopeId)}`,
    { token },
  );
}

export function postInteraction(
  input: {
    scope_id: string;
    text: string;
    source_ref?: string;
    idempotency_key?: string;
    mode: ExecutionMode;
    preview: boolean;
  },
  token?: string | null,
) {
  return apiFetch<IngestInteractionResponse>("/v1/interactions", {
    method: "POST",
    body: JSON.stringify(input),
    token,
  });
}

export function postRecallCompare(
  input: {
    scope_id: string;
    query: string;
    limit: number;
    mode: ExecutionMode;
  },
  token?: string | null,
) {
  return apiFetch<RecallComparisonResponse>("/v1/recall/compare", {
    method: "POST",
    body: JSON.stringify(input),
    token,
  });
}

export function forgetMemory(
  scopeId: string,
  memoryId: string,
  reason: string,
  token: string,
) {
  return apiFetch(
    `/v1/memories/${encodeURIComponent(memoryId)}/forget?scope_id=${encodeURIComponent(scopeId)}`,
    {
      method: "POST",
      body: JSON.stringify({ reason }),
      token,
    },
  );
}

export function resolveMemory(
  scopeId: string,
  memoryId: string,
  selectedMemoryId: string,
  reason: string,
  token: string,
) {
  return apiFetch(
    `/v1/memories/${encodeURIComponent(memoryId)}/resolve?scope_id=${encodeURIComponent(scopeId)}`,
    {
      method: "POST",
      body: JSON.stringify({ selected_memory_id: selectedMemoryId, reason }),
      token,
    },
  );
}
