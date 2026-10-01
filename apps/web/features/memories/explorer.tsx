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
import { useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";

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
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { scopeId, token } = useWorkspace();
  const [asOf] = useState(() => Date.now());
  const [searchResetKey, setSearchResetKey] = useState(0);
  const appliedSearch = searchParams.get("search") || "";
  const [cursorTrail, setCursorTrail] = useState<string[]>([]);
  const types = searchParams.getAll("type") as MemoryType[];
  const rawStatuses = searchParams.getAll("status");
  const allStatuses = rawStatuses.includes("all");
  const explicitStatuses = rawStatuses.filter(
    (status): status is MemoryStatus =>
      statuses.includes(status as MemoryStatus),
  );
  const selectedStatuses: MemoryStatus[] = allStatuses
    ? []
    : explicitStatuses.length
      ? explicitStatuses
      : ["active"];
  const cursor = searchParams.get("cursor");
  const query = {
    scopeId,
    cursor,
    limit: 25,
    memoryTypes: types,
    statuses: selectedStatuses,
    search: appliedSearch || undefined,
  };
  const memories = useQuery({
    queryKey: ["memories", query],
    queryFn: () => getMemories(query, token),
  });

  function updateUrl(
    changes: Record<string, string | string[] | null | undefined>,
  ) {
    if (["search", "type", "status"].some((key) => key in changes)) {
      setCursorTrail([]);
    }
    // Client-only filters must compose against the latest URL, even between renders.
    const next = new URLSearchParams(window.location.search);
    Object.entries(changes).forEach(([key, value]) => {
      next.delete(key);
      if (Array.isArray(value)) value.forEach((item) => next.append(key, item));
      else if (value) next.set(key, value);
    });
    window.history.replaceState(
      null,
      "",
      `${pathname}${next.toString() ? `?${next.toString()}` : ""}`,
    );
  }

  function toggleType(type: MemoryType) {
    const currentTypes = new URLSearchParams(window.location.search).getAll(
      "type",
    );
    updateUrl({
      type: currentTypes.includes(type)
        ? currentTypes.filter((item) => item !== type)
        : [...currentTypes, type],
      cursor: null,
    });
  }

  function toggleStatus(status: MemoryStatus) {
    const currentStatuses = new URLSearchParams(window.location.search).getAll(
      "status",
    );
    const current =
      currentStatuses.includes("all") ||
      (!currentStatuses.length && status !== "active")
        ? []
        : currentStatuses.length
          ? currentStatuses.filter((item) =>
              statuses.includes(item as MemoryStatus),
            )
          : ["active"];
    const next = current.includes(status)
      ? current.filter((item) => item !== status)
      : [...current, status];
    updateUrl({ status: next.length ? next : ["all"], cursor: null });
  }

  const hasFilters =
    types.length > 0 || rawStatuses.length > 0 || Boolean(appliedSearch);

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
            Browse current knowledge and follow each memory back to its
            evidence.
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
            {memories.data?.total ?? "—"}{" "}
            {allStatuses ||
            selectedStatuses.length !== 1 ||
            selectedStatuses[0] !== "active"
              ? "matching"
              : "active"}{" "}
            {memories.data?.total === 1 ? "memory" : "memories"}
          </span>
          <Link className="primary-button" href="/ingestion">
            Ingest interaction
          </Link>
        </div>
      </header>

      <section className="explorer-toolbar panel">
        <MemorySearch
          key={`${appliedSearch}:${searchResetKey}`}
          appliedSearch={appliedSearch}
          onSearch={(search) =>
            updateUrl({ search: search || null, cursor: null })
          }
        />
        <div className="toolbar-separator" />
        <div className="filter-group">
          <Filter size={14} aria-hidden="true" />
          <span className="toolbar-label">Type</span>
          {memoryTypes.map((type) => (
            <button
              className={`filter-chip ${types.includes(type) ? "selected" : ""}`}
              type="button"
              key={type}
              onClick={() => toggleType(type)}
              aria-pressed={types.includes(type)}
            >
              {type}
            </button>
          ))}
        </div>
        <div className="filter-group">
          <SlidersHorizontal size={14} aria-hidden="true" />
          <span className="toolbar-label">Status</span>
          <button
            className={`filter-chip ${allStatuses ? "selected" : ""}`}
            type="button"
            onClick={() => updateUrl({ status: ["all"], cursor: null })}
            aria-pressed={allStatuses}
          >
            All
          </button>
          {statuses.map((status) => (
            <button
              className={`filter-chip ${selectedStatuses.includes(status) ? "selected" : ""}`}
              type="button"
              key={status}
              onClick={() => toggleStatus(status)}
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
              setSearchResetKey((key) => key + 1);
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
      {memories.data ? (
        <MemoryList
          items={memories.data.items}
          asOf={asOf}
          label={
            selectedStatuses.length === 1 && selectedStatuses[0] === "active"
              ? "Active memories"
              : "Matching memories"
          }
        />
      ) : null}
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
            onClick={() => {
              updateUrl({ cursor: cursorTrail.at(-1) || null });
              setCursorTrail((trail) => trail.slice(0, -1));
            }}
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
            onClick={() => {
              setCursorTrail((trail) => [...trail, cursor || ""]);
              updateUrl({ cursor: memories.data.page.next_cursor });
            }}
          >
            Next
            <ChevronRight size={14} />
          </button>
        </div>
      ) : null}
    </div>
  );
}

function MemorySearch({
  appliedSearch,
  onSearch,
}: {
  appliedSearch: string;
  onSearch: (search: string) => void;
}) {
  const [draftSearch, setDraftSearch] = useState(appliedSearch);
  return (
    <form
      className="search-field"
      role="search"
      onSubmit={(event) => {
        event.preventDefault();
        const search = draftSearch.trim();
        setDraftSearch(search);
        onSearch(search);
      }}
    >
      <Search size={16} aria-hidden="true" />
      <input
        value={draftSearch}
        onChange={(event) => setDraftSearch(event.target.value)}
        placeholder="Search text, subject, or context"
        aria-label="Search memories"
      />
      <button type="submit" className="search-submit">
        Search
      </button>
    </form>
  );
}

function MemoryList({
  items,
  asOf,
  label,
}: {
  items: Awaited<ReturnType<typeof getMemories>>["items"];
  asOf: number;
  label: string;
}) {
  return (
    <section className="panel memory-list-panel" aria-label={label}>
      <div className="memory-list-heading">{label}</div>
      <ul className="memory-list">
        {items.map((memory) => {
          const expired =
            memory.status === "active" &&
            memory.expires_at &&
            Date.parse(memory.expires_at) <= asOf;
          return (
            <li
              key={memory.id}
              className="memory-list-item"
              data-status={memory.status}
            >
              <Link
                className="memory-list-link"
                href={`/memories/${memory.id}`}
              >
                <div className="memory-list-copy">
                  <strong>{memory.content}</strong>
                  <span>
                    {[memory.subject, memory.context_key]
                      .filter(Boolean)
                      .join(" · ") || "General context"}
                  </span>
                </div>
                <div className="memory-list-signals">
                  <div className="memory-list-badges">
                    <TypeBadge type={memory.memory_type} />
                    <span
                      title={statusDescription(memory.status, Boolean(expired))}
                    >
                      <StatusBadge status={memory.status} />
                    </span>
                    {expired ? (
                      <span className="memory-expired-note">
                        Expired for recall
                      </span>
                    ) : null}
                  </div>
                  <div className="memory-list-facts">
                    <span>
                      <b>{Math.round(memory.confidence * 100)}%</b> confidence
                    </span>
                    <span>
                      <b>{Math.round(memory.importance * 100)}%</b> importance
                    </span>
                    {memory.reinforcement_count > 0 ? (
                      <span>
                        {memory.reinforcement_count} reinforcement
                        {memory.reinforcement_count === 1 ? "" : "s"}
                      </span>
                    ) : null}
                    <time dateTime={memory.last_confirmed_at}>
                      Confirmed {formatDate(memory.last_confirmed_at)}
                    </time>
                  </div>
                </div>
                <ChevronRight
                  className="memory-list-chevron"
                  size={16}
                  aria-hidden="true"
                />
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function statusDescription(status: MemoryStatus, expired: boolean) {
  if (expired) return "Validity ended; excluded from normal recall.";
  return {
    active: "Current memory available to normal recall.",
    disputed: "Conflicting evidence needs review.",
    superseded: "Historical memory replaced by the current memory.",
    forgotten: "Excluded from normal recall.",
  }[status];
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}
