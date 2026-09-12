"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Check,
  Clock3,
  Copy,
  GitBranch,
  LockKeyhole,
  ShieldAlert,
  Sparkles,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import {
  ErrorState,
  InlineNotice,
  LoadingState,
} from "@/components/status-state";
import { StatusBadge, TypeBadge } from "@/components/type-badge";
import { useWorkspace } from "@/components/workspace-context";
import {
  forgetMemory,
  getMemory,
  getMemoryHistory,
  resolveMemory,
} from "@/lib/api/queries";
import type { MemoryEvent, MemoryRecord } from "@/lib/api/types";

export function MemoryDetail({ memoryId }: { memoryId: string }) {
  const { scopeId, token, isOwner } = useWorkspace();
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState<string | null>(null);
  const memory = useQuery({
    queryKey: ["memory", scopeId, memoryId],
    queryFn: () => getMemory(scopeId, memoryId, token),
    enabled: Boolean(memoryId),
  });
  const history = useQuery({
    queryKey: ["memory-history", scopeId, memoryId],
    queryFn: () => getMemoryHistory(scopeId, memoryId, token),
    enabled: Boolean(memoryId),
  });
  const forget = useMutation({
    mutationFn: (reason: string) =>
      forgetMemory(scopeId, memoryId, reason, token),
    onSuccess: () => {
      setNotice(
        "This memory lineage is now forgotten and excluded from recall.",
      );
      void queryClient.invalidateQueries({
        queryKey: ["memory", scopeId, memoryId],
      });
      void queryClient.invalidateQueries({
        queryKey: ["memory-history", scopeId, memoryId],
      });
      void queryClient.invalidateQueries({ queryKey: ["memories"] });
    },
  });
  const resolve = useMutation({
    mutationFn: ({
      selectedMemoryId,
      reason,
    }: {
      selectedMemoryId: string;
      reason: string;
    }) => resolveMemory(scopeId, memoryId, selectedMemoryId, reason, token),
    onSuccess: () => {
      setNotice("The dispute was resolved and the selected version is active.");
      void queryClient.invalidateQueries({
        queryKey: ["memory", scopeId, memoryId],
      });
      void queryClient.invalidateQueries({
        queryKey: ["memory-history", scopeId, memoryId],
      });
      void queryClient.invalidateQueries({ queryKey: ["memories"] });
    },
  });

  if (memory.isPending || history.isPending)
    return (
      <div className="page-wrap">
        <LoadingState label="Loading memory detail" />
      </div>
    );
  if (memory.isError)
    return (
      <div className="page-wrap">
        <ErrorState
          error={memory.error}
          onRetry={() => void memory.refetch()}
        />
      </div>
    );
  if (history.isError)
    return (
      <div className="page-wrap">
        <ErrorState
          error={history.error}
          onRetry={() => void history.refetch()}
        />
      </div>
    );
  if (!memory.data || !history.data) return null;

  return (
    <MemoryDetailContent
      memory={memory.data}
      history={history.data}
      isOwner={isOwner}
      notice={notice}
      onForget={(reason) => forget.mutate(reason)}
      forgetPending={forget.isPending}
      onResolve={(selectedMemoryId, reason) =>
        resolve.mutate({ selectedMemoryId, reason })
      }
      resolvePending={resolve.isPending}
    />
  );
}

function MemoryDetailContent({
  memory,
  history,
  isOwner,
  notice,
  onForget,
  forgetPending,
  onResolve,
  resolvePending,
}: {
  memory: MemoryRecord;
  history: Awaited<ReturnType<typeof getMemoryHistory>>;
  isOwner: boolean;
  notice: string | null;
  onForget: (reason: string) => void;
  forgetPending: boolean;
  onResolve: (selectedMemoryId: string, reason: string) => void;
  resolvePending: boolean;
}) {
  const [selectedVersion, setSelectedVersion] = useState(memory.id);
  const [reason, setReason] = useState("");
  const currentVersion = history.versions.find(
    (version) => version.memory.id === selectedVersion,
  )?.memory;
  const displayMemory = currentVersion || memory;
  const why = displayMemory.why.length
    ? displayMemory.why
    : deriveWhy(displayMemory, history.events);
  return (
    <div className="page-wrap detail-page">
      <Link className="back-link" href="/memories">
        <ArrowLeft size={15} />
        Back to explorer
      </Link>
      <header className="detail-header">
        <div>
          <div className="breadcrumb">
            <span>Memory explorer</span>
            <span>/</span>
            <strong>Memory detail</strong>
          </div>
          <div className="detail-title-row">
            <TypeBadge type={displayMemory.memory_type} />
            <StatusBadge status={displayMemory.status} />
            <span className="version-label">
              Version {displayMemory.version}
            </span>
          </div>
          <h1>{displayMemory.content}</h1>
          <p className="page-subtitle">
            Lineage {displayMemory.lineage_id.slice(0, 8)} · Created{" "}
            {formatDate(displayMemory.created_at)}
          </p>
        </div>
        <div className="detail-actions">
          {isOwner ? (
            <button
              className="danger-button"
              type="button"
              disabled={forgetPending || displayMemory.status === "forgotten"}
              onClick={() => onForget(reason || "Forgotten by owner")}
            >
              <Trash2 size={14} />
              {forgetPending ? "Forgetting…" : "Forget lineage"}
            </button>
          ) : (
            <span className="owner-required">
              <LockKeyhole size={14} />
              Owner token required for actions
            </span>
          )}
        </div>
      </header>
      {notice ? (
        <InlineNotice tone="success">
          <Check size={15} />
          {notice}
        </InlineNotice>
      ) : null}

      <section className="detail-grid">
        <article className="panel detail-main-card">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Memory signal</span>
              <h2>Why this memory matters</h2>
            </div>
          </div>
          <div className="detail-metrics">
            <DetailMetric label="Importance" value={displayMemory.importance} />
            <DetailMetric label="Confidence" value={displayMemory.confidence} />
            <div className="detail-metric">
              <span>Reinforcements</span>
              <strong>{displayMemory.reinforcement_count}</strong>
              <small>distinct interactions</small>
            </div>
            <div className="detail-metric">
              <span>Last confirmed</span>
              <strong>{formatDate(displayMemory.last_confirmed_at)}</strong>
              <small>{relativeDays(displayMemory.last_confirmed_at)}</small>
            </div>
          </div>
          <div className="metadata-grid">
            <MetaItem label="Subject" value={displayMemory.subject || "—"} />
            <MetaItem
              label="Context"
              value={displayMemory.context_key || "—"}
            />
            <MetaItem
              label="Attribute"
              value={displayMemory.attribute_key || "—"}
            />
            <MetaItem
              label="Embedding space"
              value={`${displayMemory.embedding_model} · ${displayMemory.embedding_dimensions}d`}
            />
          </div>
          <div className="why-memory-box">
            <div className="why-memory-heading">
              <span className="why-memory-icon">
                <Sparkles size={13} aria-hidden="true" />
              </span>
              <div>
                <span className="review-section-label">Explainability</span>
                <h3>Remembered because</h3>
              </div>
            </div>
            <ul>
              {why.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </div>
        </article>
        <article className="panel provenance-card">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Lineage</span>
              <h2>Version history</h2>
            </div>
            <GitBranch
              size={16}
              className="panel-heading-icon"
              aria-hidden="true"
            />
          </div>
          <div className="version-list">
            {history.versions.map((version) => (
              <label
                className={`version-row ${selectedVersion === version.memory.id ? "selected" : ""}`}
                key={version.memory.id}
              >
                <input
                  type="radio"
                  name="version"
                  value={version.memory.id}
                  checked={selectedVersion === version.memory.id}
                  onChange={() => setSelectedVersion(version.memory.id)}
                />
                <span className="version-copy">
                  <strong>
                    v{version.memory.version} · {version.memory.status}
                  </strong>
                  <span>{version.memory.content}</span>
                  <small>{formatDate(version.memory.created_at)}</small>
                </span>
                {version.is_current ? (
                  <span className="current-label">current</span>
                ) : null}
              </label>
            ))}
          </div>
          {memory.status === "disputed" && isOwner ? (
            <div className="resolve-box">
              <label className="field-label" htmlFor="resolve-reason">
                Resolution note
              </label>
              <input
                id="resolve-reason"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="Why is this version active?"
              />
              <button
                className="primary-button"
                type="button"
                disabled={resolvePending}
                onClick={() =>
                  onResolve(selectedVersion, reason || "Resolved by owner")
                }
              >
                {resolvePending ? "Resolving…" : "Resolve dispute"}
              </button>
            </div>
          ) : null}
        </article>
      </section>

      <section className="panel timeline-panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Audit trail</span>
            <h2>What happened over time</h2>
          </div>
          <span className="timeline-count">{history.events.length} events</span>
        </div>
        {history.events.length ? (
          <div className="timeline-list">
            {history.events.map((event) => (
              <TimelineRow event={event} key={event.id} />
            ))}
          </div>
        ) : (
          <div className="empty-panel">
            No events have been recorded for this lineage yet.
          </div>
        )}
      </section>
      {!isOwner ? (
        <div className="detail-footnote">
          <ShieldAlert size={15} />
          Viewing is public in demo mode. Add an owner token in{" "}
          <Link href="/settings">Settings</Link> to forget or resolve memories.
        </div>
      ) : null}
    </div>
  );
}

function DetailMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="detail-metric">
      <span>{label}</span>
      <strong>{value.toFixed(2)}</strong>
      <span className="metric-line">
        <i style={{ width: `${Math.round(value * 100)}%` }} />
      </span>
    </div>
  );
}
function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="meta-item">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
function TimelineRow({ event }: { event: MemoryEvent }) {
  return (
    <div className="timeline-row">
      <span className={`timeline-dot ${event.event_type}`} />
      <div>
        <div className="timeline-event-title">
          <strong>{event.event_type}</strong>
          <span>{formatDate(event.created_at)}</span>
        </div>
        <p>{event.reason_summary}</p>
        {event.evidence_excerpt ? (
          <blockquote>“{event.evidence_excerpt}”</blockquote>
        ) : null}
      </div>
    </div>
  );
}
function formatDate(value: string) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}
function relativeDays(value: string) {
  const days = Math.round(
    (Date.now() - new Date(value).getTime()) / 86_400_000,
  );
  return days <= 0 ? "today" : `${days}d ago`;
}

function deriveWhy(memory: MemoryRecord, events: MemoryEvent[]) {
  const memoryEvents = events.filter((event) => event.memory_id === memory.id);
  if (memory.reinforcement_count > 0) {
    return [
      "the same subject and context appeared again",
      `confirmed by ${memory.reinforcement_count} separate interaction${memory.reinforcement_count === 1 ? "" : "s"}`,
      `confidence ${memory.confidence.toFixed(2)}`,
    ];
  }
  if (memoryEvents.some((event) => event.event_type === "superseded")) {
    return [
      "newer evidence described the same attribute",
      "the previous version remains available in this lineage",
      `confidence ${memory.confidence.toFixed(2)}`,
    ];
  }
  if (memoryEvents.some((event) => event.event_type === "disputed")) {
    return [
      "the evidence was worth preserving",
      "MemoryOS could not resolve the conflict safely",
      "the decision is waiting in Memory review",
    ];
  }
  return [
    "an explicit signal was found in the interaction",
    `high expected future usefulness (${memory.importance.toFixed(2)} importance)`,
    `confidence ${memory.confidence.toFixed(2)}`,
  ];
}
