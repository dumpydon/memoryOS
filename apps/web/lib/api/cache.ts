import type { QueryClient } from "@tanstack/react-query";

import type { IngestInteractionResponse } from "./types";

// A lifecycle mutation can affect a lineage and several consolidation sources.
// Invalidate the complete inspection/recall views, including active observers.
export function refreshMemoryViews(queryClient: QueryClient) {
  return Promise.all(
    [
      "memories",
      "memory",
      "memory-history",
      "reviews",
      "review-memory-pool",
      "recall-compare",
      "overview",
    ].map((key) => queryClient.invalidateQueries({ queryKey: [key] })),
  );
}

export function refreshIngestionCaches(
  queryClient: QueryClient,
  response: IngestInteractionResponse,
) {
  const changed =
    response.status === "completed" &&
    response.decisions.some((decision) =>
      [
        "created",
        "reinforced",
        "superseded",
        "disputed",
        "consolidated",
      ].includes(decision.decision_type),
    );
  return changed ? refreshMemoryViews(queryClient) : Promise.resolve();
}
