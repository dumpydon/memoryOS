"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Filter,
  LoaderCircle,
  Search,
  SlidersHorizontal,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "@/components/status-state";
import { StatusBadge, TypeBadge } from "@/components/type-badge";
import { useWorkspace } from "@/components/workspace-context";
import { getMemories } from "@/lib/api/queries";
import type { MemoryStatus, MemoryType } from "@/lib/api/types";

const memoryTypes: MemoryType[] = [
  "preference",
  "semantic",
  "episodic",
  "procedural",
];
const statuses: MemoryStatus[] = [
  "active",
  "disputed",
  "superseded",
  "forgotten",
];

export function MemoryExplorer() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { scopeId, token } = useWorkspace();
  const [draftSearch, setDraftSearch] = useState(
    searchParams.get("search") || "",
  );
  const types = searchParams.getAll("type") as MemoryType[];
  const selectedStatuses = searchParams.getAll("status") as MemoryStatus[];
  const cursor = searchParams.get("cursor");
  const query = useMemo(
    () => ({
      scopeId,
      cursor,
      limit: 25,
      memoryTypes: types,
      statuses: selectedStatuses,
      search: searchParams.get("search") || undefined,
    }),
    [cursor, scopeId, searchParams, selectedStatuses, types],
  );
  const memories = useQuery({
    queryKey: ["memories", query],
    queryFn: () => getMemories(query, token),
  });

  function updateUrl(
    changes: Record<string, string | string[] | null | undefined>,
  ) {
    const next = new URLSearchParams(searchParams.toString());
    Object.entries(changes).forEach(([key, value]) => {
      next.delete(key);
      if (Array.isArray(value)) value.forEach((item) => next.append(key, item));
      else if (value) next.set(key, value);
    });
    router.replace(
      `${pathname}${next.toString() ? `?${next.toString()}` : ""}`,
      { scroll: false },
    );
  }

  function toggleFilter(key: "type" | "status", value: string) {
    const current = key === "type" ? types : selectedStatuses;
    const next = current.includes(value as never)
      ? current.filter((item) => item !== value)
      : [...current, value];
    updateUrl({ [key]: next, cursor: null });
  }

  function submitSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    updateUrl({ search: draftSearch.trim() || null, cursor: null });
  }

  const hasFilters =
    types.length > 0 ||
    selectedStatuses.length > 0 ||
    Boolean(searchParams.get("search"));

  return (
    <div className="page-wrap explorer-page">
      <header className="page-header">
        <div>
          <div className="breadcrumb">
            <span>Workspace</span>
            <span>/</span>
            <strong>Memory explorer</strong>
          </div>
          <h1>Memory explorer</h1>
          <p className="page-subtitle">
            Inspect active memories, provenance, confidence, and the history
            behind each version.
          </p>
        </div>
        <div className="header-actions">
          {memories.isFetching && memories.data ? (
            <span className="refreshing-pill" role="status">
              <LoaderCircle className="spin" size={13} aria-hidden="true" />
              Refreshing
            </span>
          ) : null}
          <span className="count-pill">
            {memories.data?.total ?? "—"} memories
          </span>
          <Link className="primary-button" href="/ingestion">
            Ingest interaction
          </Link>
        </div>
      </header>

      <section className="explorer-toolbar panel">
        <form className="search-field" onSubmit={submitSearch} role="search">
          <Search size={16} aria-hidden="true" />
          <input
            value={draftSearch}
            onChange={(event) => setDraftSearch(event.target.value)}
            placeholder="Search memory content or subject"
            aria-label="Search memories"
          />
          <button type="submit" className="search-submit">
            Search
          </button>
        </form>
        <div className="toolbar-separator" />
        <div className="filter-group">
          <Filter size={14} aria-hidden="true" />
          <span className="toolbar-label">Type</span>
          {memoryTypes.map((type) => (
            <button
              className={`filter-chip ${types.includes(type) ? "selected" : ""}`}
              type="button"
              key={type}
              onClick={() => toggleFilter("type", type)}
              aria-pressed={types.includes(type)}
            >
              {type}
            </button>
          ))}
        </div>
        <div className="filter-group">
          <SlidersHorizontal size={14} aria-hidden="true" />
          <span className="toolbar-label">Status</span>
          {statuses.slice(0, 2).map((status) => (
            <button
              className={`filter-chip ${selectedStatuses.includes(status) ? "selected" : ""}`}
              type="button"
              key={status}
              onClick={() => toggleFilter("status", status)}
              aria-pressed={selectedStatuses.includes(status)}
            >
              {status}
            </button>
          ))}
        </div>
        {hasFilters ? (
          <button
            className="clear-filters"
            type="button"
            onClick={() => {
              setDraftSearch("");
              updateUrl({ search: null, type: [], status: [], cursor: null });
            }}
          >
            Clear
          </button>
        ) : null}
      </section>

      {memories.isPending ? <LoadingState label="Loading memories" /> : null}
      {memories.isError ? (
        <ErrorState
          error={memories.error}
          onRetry={() => void memories.refetch()}
        />
      ) : null}
      {memories.data ? <MemoryTable items={memories.data.items} /> : null}
      {memories.data && memories.data.items.length === 0 ? (
        <EmptyState
          title="No memories match these filters"
          detail="Try a broader search or clear the active filters."
        />
      ) : null}
      {memories.data && memories.data.items.length > 0 ? (
        <div className="pagination-row">
          <button
            className="secondary-button"
            type="button"
            disabled={!cursor}
            onClick={() => updateUrl({ cursor: null })}
          >
            <ChevronLeft size={14} />
            Previous
          </button>
          <span>
            Showing {memories.data.items.length} of {memories.data.total}
          </span>
          <button
            className="secondary-button"
            type="button"
            disabled={!memories.data.page.next_cursor}
            onClick={() =>
              updateUrl({ cursor: memories.data.page.next_cursor })
            }
          >
            Next
            <ChevronRight size={14} />
          </button>
        </div>
      ) : null}
    </div>
  );
}

function MemoryTable({
  items,
}: {
  items: Awaited<ReturnType<typeof getMemories>>["items"];
}) {
  return (
    <div className="panel memory-table-panel">
      <div className="memory-table-wrap">
        <table className="memory-table">
          <thead>
            <tr>
              <th>Memory</th>
              <th>Type</th>
              <th>State</th>
              <th>Importance</th>
              <th>Confidence</th>
              <th>Confirmed</th>
              <th>Reinforced</th>
            </tr>
          </thead>
          <tbody>
            {items.map((memory) => (
              <tr key={memory.id}>
                <td>
                  <Link
                    className="memory-title-link"
                    href={`/memories/${memory.id}`}
                  >
                    <strong>{memory.content}</strong>
                    <span>
                      {memory.subject || memory.context_key || "Unscoped fact"}
                    </span>
                  </Link>
                </td>
                <td>
                  <TypeBadge type={memory.memory_type} />
                </td>
                <td>
                  <StatusBadge status={memory.status} />
                </td>
                <td>
                  <ScoreMeter value={memory.importance} />
                </td>
                <td>
                  <ScoreMeter value={memory.confidence} />
                </td>
                <td>{formatDate(memory.last_confirmed_at)}</td>
                <td>{memory.reinforcement_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ScoreMeter({ value }: { value: number }) {
  return (
    <span className="mini-score">
      <span>
        <i style={{ width: `${Math.round(value * 100)}%` }} />
      </span>
      <b>{value.toFixed(2)}</b>
    </span>
  );
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
  }).format(new Date(value));
}
