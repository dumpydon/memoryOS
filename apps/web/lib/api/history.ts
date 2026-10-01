import type { MemoryEvent } from "./types";

const lifecycleOrder: Record<MemoryEvent["event_type"], number> = {
  created: 0,
  reinforced: 1,
  disputed: 2,
  superseded: 3,
  resolved: 4,
  forgotten: 5,
  expired: 6,
};

export function compareLifecycleEvents(left: MemoryEvent, right: MemoryEvent) {
  // Source evidence can predate ingestion. Order the audit by when it was recorded.
  const timeDifference =
    Date.parse(left.created_at) - Date.parse(right.created_at);
  if (timeDifference) return timeDifference;
  const kindDifference =
    lifecycleOrder[left.event_type] - lifecycleOrder[right.event_type];
  if (kindDifference) return kindDifference;
  if (left.event_type === "reinforced" && right.event_type === "reinforced") {
    const leftCount = left.after?.reinforcement_count;
    const rightCount = right.after?.reinforcement_count;
    if (typeof leftCount === "number" && typeof rightCount === "number") {
      if (leftCount !== rightCount) return leftCount - rightCount;
    }
  }
  return left.id.localeCompare(right.id);
}

export function sourceEvidence(
  events: MemoryEvent[] | undefined,
  reviewCreatedAt: string,
) {
  const sources = events?.filter(
    (event) =>
      ["created", "reinforced", "disputed", "superseded"].includes(
        event.event_type,
      ) &&
      event.reason_code !== "consolidation_source_preserved" &&
      Date.parse(event.created_at) <= Date.parse(reviewCreatedAt),
  );
  return (
    sources?.filter((event) => event.evidence_excerpt).at(-1) || sources?.at(-1)
  );
}
