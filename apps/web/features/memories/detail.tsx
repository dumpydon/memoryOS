"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, GitBranch, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import {
  ErrorState,
  InlineNotice,
  LoadingState,
} from "@/components/status-state";
import { StatusBadge, TypeBadge } from "@/components/type-badge";
import { useWorkspace } from "@/components/workspace-context";
import { forgetMemory, getMemory, getMemoryHistory } from "@/lib/api/queries";
import { refreshMemoryViews } from "@/lib/api/cache";
import { compareLifecycleEvents } from "@/lib/api/history";
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
    onSuccess: async () => {
      setNotice(
        "This memory lineage is now forgotten and excluded from recall.",
      );
      await refreshMemoryViews(queryClient);
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
      key={memory.data.id}
      memory={memory.data}
      history={history.data}
      isOwner={isOwner}
      notice={notice}
      onForget={() => forget.mutate("Forgotten by owner")}
      forgetPending={forget.isPending}
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
}: {
  memory: MemoryRecord;
  history: Awaited<ReturnType<typeof getMemoryHistory>>;
  isOwner: boolean;
  notice: string | null;
  onForget: () => void;
  forgetPending: boolean;
}) {
  const [selectedVersion, setSelectedVersion] = useState(memory.id);
  const [asOf] = useState(() => Date.now());
  const currentVersion = history.versions.find(
    (version) => version.memory.id === selectedVersion,
  )?.memory;
  const displayMemory = currentVersion || memory;
  const orderedEvents = [...history.events].sort(compareLifecycleEvents);
  const evidence = orderedEvents.filter(
    (event) =>
      event.memory_id === displayMemory.id && event.evidence_excerpt?.trim(),
  );
  const visibleEvidence =
    evidence.length > 3 ? [evidence[0], ...evidence.slice(-2)] : evidence;
  const otherEvidence = evidence.length > 3 ? evidence.slice(1, -2) : [];
  const previousVersion = history.versions
    .filter((version) => version.memory.superseded_by_id === displayMemory.id)
    .at(-1)?.memory;
  const disputedPeer =
    displayMemory.status === "disputed"
      ? history.versions
          .filter(
            (version) =>
              version.memory.id !== displayMemory.id &&
              version.memory.status === "disputed",
          )
          .at(-1)?.memory
      : null;
  const consolidationSources = [
    ...new Set(
      orderedEvents.filter(isConsolidationEvent).flatMap(preservedSourceIds),
    ),
  ];
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
            {[displayMemory.subject, displayMemory.context_key]
              .filter(Boolean)
              .join(" · ") || "General context"}
            {" · "}Stored {formatDate(displayMemory.created_at)}
          </p>
          <div className="detail-state-line">
            <span>{statusDescription(displayMemory, asOf)}</span>
            {displayMemory.status === "disputed" ? (
              <Link href="/review">Open Memory Review →</Link>
            ) : null}
          </div>
          {previousVersion ||
          disputedPeer ||
          consolidationSources.length ||
          displayMemory.superseded_by_id ? (
            <div className="detail-lineage-links">
              {previousVersion ? (
                <Link href={`/memories/${previousVersion.id}`}>
                  Replaced previous memory →
                </Link>
              ) : null}
              {disputedPeer ? (
                <Link href={`/memories/${disputedPeer.id}`}>
                  Related disputed memory →
                </Link>
              ) : null}
              {consolidationSources.length ? (
                <span className="detail-lineage-sources">
                  Consolidated from {consolidationSources.length} previous
                  memories:
                  {consolidationSources.map((id, index) => (
                    <Link key={id} href={`/memories/${id}`}>
                      Source {index + 1}
                    </Link>
                  ))}
                </span>
              ) : null}
              {displayMemory.status === "superseded" &&
              displayMemory.superseded_by_id ? (
                <Link href={`/memories/${displayMemory.superseded_by_id}`}>
                  View current memory →
                </Link>
              ) : null}
            </div>
          ) : null}
        </div>
        <div className="detail-actions">
          {isOwner ? (
            <button
              className="danger-button"
              type="button"
              disabled={forgetPending || displayMemory.status === "forgotten"}
              onClick={onForget}
            >
              <Trash2 size={14} />
              {forgetPending ? "Forgetting…" : "Forget lineage"}
            </button>
          ) : null}
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
              <span className="eyebrow">Provenance</span>
              <h2>Evidence &amp; sources</h2>
            </div>
          </div>
          <div className="detail-evidence-list">
            {visibleEvidence.length ? (
              <>
                <EvidenceRow event={visibleEvidence[0]} />
                {otherEvidence.length ? (
                  <details className="detail-evidence-more">
                    <summary>
                      Show {otherEvidence.length} more evidence record
                      {otherEvidence.length === 1 ? "" : "s"}
                    </summary>
                    {otherEvidence.map((event) => (
                      <EvidenceRow key={event.id} event={event} />
                    ))}
                  </details>
                ) : null}
                {visibleEvidence.slice(1).map((event) => (
                  <EvidenceRow key={event.id} event={event} />
                ))}
              </>
            ) : (
              <p className="detail-evidence-empty">
                No source excerpt was recorded for this memory.
              </p>
            )}
          </div>
          <div className="detail-metrics">
            <DetailMetric label="Confidence" value={displayMemory.confidence} />
            <DetailMetric label="Importance" value={displayMemory.importance} />
            <div className="detail-metric">
              <span>Reinforcements</span>
              <strong>{displayMemory.reinforcement_count}</strong>
              <small>distinct interactions</small>
            </div>
            <div className="detail-metric">
              <span>Last confirmed</span>
              <strong>{formatDate(displayMemory.last_confirmed_at)}</strong>
              <small>
                {relativeDays(displayMemory.last_confirmed_at, asOf)}
              </small>
            </div>
          </div>
          <details className="detail-policy-details">
            <summary>Memory details</summary>
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
            {displayMemory.why.length ? (
              <div className="detail-policy-notes">
                <span>Stored policy notes</span>
                <ul>
                  {displayMemory.why.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </details>
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
                {version.is_current && version.memory.status === "active" ? (
                  <span className="current-label">current</span>
                ) : null}
              </label>
            ))}
          </div>
        </article>
      </section>

      <section className="panel timeline-panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Audit trail</span>
            <h2>Memory lifecycle</h2>
          </div>
          <span className="timeline-count">
            {orderedEvents.length} events · oldest first
          </span>
        </div>
        {orderedEvents.length ? (
          <div className="timeline-list">
            {orderedEvents.map((event) => (
              <TimelineRow event={event} key={event.id} />
            ))}
          </div>
        ) : (
          <div className="empty-panel">
            No events have been recorded for this lineage yet.
          </div>
        )}
      </section>
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
function EvidenceRow({ event }: { event: MemoryEvent }) {
  const evidenceTime = event.source_occurred_at || event.created_at;
  return (
    <div className="detail-evidence-row">
      <div className="detail-evidence-heading">
        <strong>{evidenceLabel(event)}</strong>
        <time dateTime={evidenceTime}>{formatDate(evidenceTime)}</time>
      </div>
      <blockquote>“{event.evidence_excerpt}”</blockquote>
      {event.provenance ? (
        <small>Source: {sourceLabel(event.provenance)}</small>
      ) : null}
    </div>
  );
}

function sourceLabel(provenance: string) {
  if (provenance.startsWith("demo-fixture")) return "Demo fixture";
  if (provenance.startsWith("demo:")) return "Demo interaction";
  if (provenance === "playground") return "Ingestion Playground";
  if (provenance.startsWith("review:")) return "Memory Review";
  return provenance;
}

function evidenceLabel(event: MemoryEvent) {
  if (event.reason_code === "demo_seed") return "Original source";
  if (isConsolidationEvent(event)) return "Consolidation evidence";
  if (event.event_type === "reinforced") return "Confirmed again";
  if (event.event_type === "disputed") return "Conflicting evidence";
  if (event.event_type === "superseded") return "Correction evidence";
  return "Initial evidence";
}

function isConsolidationEvent(event: MemoryEvent) {
  return [
    "memory_consolidated",
    "consolidation_approved",
    "consolidation_source_preserved",
  ].includes(event.reason_code);
}

function statusDescription(memory: MemoryRecord, asOf: number) {
  if (memory.status === "active") {
    if (memory.expires_at && Date.parse(memory.expires_at) <= asOf)
      return "Expired; excluded from normal recall.";
    if (Date.parse(memory.effective_at) > asOf)
      return "Not yet effective for recall.";
    return "Current memory available to normal recall.";
  }
  return {
    disputed: "Conflicting evidence needs review.",
    superseded: "Historical memory replaced by the current memory.",
    forgotten: "Excluded from normal recall.",
  }[memory.status];
}

function TimelineRow({ event }: { event: MemoryEvent }) {
  const sources = preservedSourceIds(event);
  const isReinforcement = event.event_type === "reinforced";
  const beforeCount = snapshotNumber(event.before, "reinforcement_count");
  const afterCount = snapshotNumber(event.after, "reinforcement_count");
  const beforeConfidence = snapshotNumber(event.before, "confidence");
  const afterConfidence = snapshotNumber(event.after, "confidence");
  const relationConfidence = snapshotNumber(event.after, "relation_confidence");
  const eventLabel = isConsolidationEvent(event)
    ? "Consolidated"
    : event.event_type.replaceAll("_", " ");
  return (
    <div className="timeline-row">
      <span className={`timeline-dot ${event.event_type}`} />
      <div className="timeline-event-copy">
        <div className="timeline-event-title">
          <strong>{eventLabel}</strong>
          <time dateTime={event.created_at}>
            {formatDate(event.created_at)}
          </time>
        </div>
        <p>
          {isReinforcement
            ? "Confirmed by another supporting interaction."
            : event.reason_summary}
        </p>
        {sources.length && !isConsolidationEvent(event) ? (
          <div className="timeline-source-links">
            <span>Preserved {sources.length === 1 ? "source" : "sources"}</span>
            {sources.map((id) => (
              <Link href={`/memories/${id}`} key={id} title={id}>
                Memory {shortId(id)}
              </Link>
            ))}
          </div>
        ) : null}
        <details className="timeline-details">
          <summary>Details</summary>
          {event.evidence_excerpt ? (
            <blockquote>“{event.evidence_excerpt}”</blockquote>
          ) : null}
          <dl className="timeline-details-grid">
            <div>
              <dt>Event ID</dt>
              <dd>
                <code title={event.id}>{shortId(event.id)}</code>
              </dd>
            </div>
            <div>
              <dt>Canonical memory</dt>
              <dd>
                <code title={event.memory_id}>{shortId(event.memory_id)}</code>
              </dd>
            </div>
            {event.interaction_id ? (
              <div>
                <dt>Source interaction</dt>
                <dd>
                  <code title={event.interaction_id}>
                    {shortId(event.interaction_id)}
                  </code>
                </dd>
              </div>
            ) : null}
            {event.source_occurred_at ? (
              <div>
                <dt>Source occurred</dt>
                <dd>{formatDateTime(event.source_occurred_at)}</dd>
              </div>
            ) : null}
            {sources.length && isConsolidationEvent(event) ? (
              <div>
                <dt>Preserved sources</dt>
                <dd>
                  {sources.map((id, index) => (
                    <Link
                      className="detail-result-link"
                      key={id}
                      href={`/memories/${id}`}
                    >
                      Source {index + 1}
                      {index < sources.length - 1 ? ", " : ""}
                    </Link>
                  ))}
                </dd>
              </div>
            ) : null}
            {event.related_memory_id ? (
              <div>
                <dt>Related memory</dt>
                <dd>
                  <Link
                    className="detail-result-link"
                    href={`/memories/${event.related_memory_id}`}
                  >
                    {shortId(event.related_memory_id)}
                  </Link>
                </dd>
              </div>
            ) : null}
            {event.provenance ? (
              <div>
                <dt>Source</dt>
                <dd>{event.provenance}</dd>
              </div>
            ) : null}
            <div>
              <dt>Policy reason</dt>
              <dd>{event.reason_code}</dd>
            </div>
            {beforeCount !== null && afterCount !== null ? (
              <div>
                <dt>Reinforcements</dt>
                <dd>
                  {beforeCount} → {afterCount}
                </dd>
              </div>
            ) : null}
            {beforeConfidence !== null && afterConfidence !== null ? (
              <div>
                <dt>Confidence</dt>
                <dd>
                  {beforeConfidence.toFixed(2)} → {afterConfidence.toFixed(2)}
                </dd>
              </div>
            ) : null}
            {relationConfidence !== null ? (
              <div>
                <dt>Relation confidence</dt>
                <dd>{relationConfidence.toFixed(2)}</dd>
              </div>
            ) : null}
            <div>
              <dt>Recorded</dt>
              <dd>{formatDateTime(event.created_at)}</dd>
            </div>
          </dl>
        </details>
      </div>
    </div>
  );
}
const MEMORY_ID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function preservedSourceIds(event: MemoryEvent) {
  const values = Array.isArray(event.after?.source_memory_ids)
    ? event.after.source_memory_ids
    : [event.after?.source_memory_id];
  return [
    ...new Set(
      values.filter(
        (value): value is string =>
          typeof value === "string" && MEMORY_ID_PATTERN.test(value),
      ),
    ),
  ];
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}
function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(new Date(value));
}
function shortId(value: string) {
  return `${value.slice(0, 8)}…`;
}
function snapshotNumber(snapshot: Record<string, unknown> | null, key: string) {
  const value = snapshot?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
function relativeDays(value: string, asOf: number) {
  const days = Math.round((asOf - new Date(value).getTime()) / 86_400_000);
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
