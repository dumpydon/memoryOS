import type { MemoryStatus, MemoryType } from "@/lib/api/types";

export function TypeBadge({ type }: { type: MemoryType }) {
  return <span className={`type-badge ${type}`}>{type}</span>;
}

export function StatusBadge({ status }: { status: MemoryStatus }) {
  return <span className={`status-badge ${status}`}>{status}</span>;
}
