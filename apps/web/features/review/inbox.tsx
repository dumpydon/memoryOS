"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronDown,
  GitBranch,
  Info,
  Layers3,
  LockKeyhole,
  Plus,
  RotateCcw,
  ShieldAlert,
  Sparkles,
  X,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import {
  EmptyState,
  ErrorState,
  InlineNotice,
  LoadingState,
} from "@/components/status-state";
import { StatusBadge, TypeBadge } from "@/components/type-badge";
import { useWorkspace } from "@/components/workspace-context";
import {
  getMemories,
  getReviews,
  proposeConsolidation,
  resolveReview,
} from "@/lib/api/queries";
import type {
  MemoryRecord,
  ReviewAction,
  ReviewItem,
  ReviewStatus,
} from "@/lib/api/types";

const actions: Array<{
  value: ReviewAction;
  label: string;
  description: string;
  tone: "primary" | "secondary" | "quiet" | "danger";
}> = [
  {
    value: "keep_both",
    label: "Keep both",
    description: "Preserve both as active memories with their contexts.",
    tone: "secondary",
  },
  {
    value: "use_new",
    label: "Use new",
    description: "Accept the candidate and let the lineage record the choice.",
    tone: "primary",
  },
  {
    value: "keep_existing",
    label: "Keep existing",
    description: "Keep the active memory and reject this proposed change.",
    tone: "quiet",
  },
  {
    value: "invalid",
    label: "Mark invalid",
    description: "Reject the candidate as unsupported or incorrect.",
    tone: "danger",
  },
];

export function MemoryReview() {
  const { scopeId, mode, token, isOwner } = useWorkspace();
  const [status, setStatus] = useState<ReviewStatus>("pending");
  const [notice, setNotice] = useState<{
    message: string;
    tone: "success" | "warning" | "info";
  } | null>(null);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [selectedMemoryIds, setSelectedMemoryIds] = useState<string[]>([]);
  const queryClient = useQueryClient();
  const reviews = useQuery({
    queryKey: ["reviews", scopeId, mode, status],
    queryFn: () => getReviews(scopeId, status, 50, token),
  });
  const memoryPool = useQuery({
    queryKey: ["review-memory-pool", scopeId, mode],
    queryFn: () =>
      getMemories({ scopeId, limit: 100, statuses: ["active"] }, token),
  });
  const resolve = useMutation({
    mutationFn: ({
      reviewId,
      action,
      reason,
    }: {
      reviewId: string;
      action: ReviewAction;
      reason: string;
    }) => resolveReview(scopeId, reviewId, action, reason, token),
    onSuccess: (item) => {
      setNotice({
        message: `${formatKind(item.kind)} resolved. The decision is recorded in the history trail.`,
        tone: "success",
      });
      void queryClient.invalidateQueries({ queryKey: ["reviews"] });
      void queryClient.invalidateQueries({ queryKey: ["overview"] });
      void queryClient.invalidateQueries({ queryKey: ["memories"] });
    },
    onError: (error) =>
      setNotice({
        message: error instanceof Error ? error.message : "The review could not be resolved.",
        tone: "warning",
      }),
  });
  const propose = useMutation({
    mutationFn: () =>
      proposeConsolidation(
        { scope_id: scopeId, source_memory_ids: selectedMemoryIds, mode },
        token,
      ),
    onSuccess: () => {
      setSelectedMemoryIds([]);
      setNotice({
        message: "Consolidation proposal added to the review inbox. Originals remain unchanged.",
        tone: "success",
      });
      void queryClient.invalidateQueries({ queryKey: ["reviews"] });
    },
    onError: (error) =>
      setNotice({
        message:
          error instanceof Error
            ? error.message
            : "The consolidation proposal could not be created.",
        tone: "warning",
      }),
  });
  const activeMemories = useMemo(
    () => memoryPool.data?.items || [],
    [memoryPool.data],
  );
  const selectedMemories = useMemo(
    () =>
      selectedMemoryIds
        .map((id) => activeMemories.find((memory) => memory.id === id))
        .filter((memory): memory is (typeof activeMemories)[number] => Boolean(memory)),
    [activeMemories, selectedMemoryIds],
  );

  function updateReason(reviewId: string, reason: string) {
    setReasons((current) => ({ ...current, [reviewId]: reason }));
  }

  function handleResolve(item: ReviewItem, action: ReviewAction) {
    if (!isOwner) {
      setNotice({
        message: "An owner token is required to resolve a review. Add one in Settings.",
        tone: "warning",
      });
      return;
    }
    resolve.mutate({
      reviewId: item.id,
      action,
      reason: reasons[item.id]?.trim() || defaultReason(action),
    });
  }

  function toggleMemory(memory: MemoryRecord) {
    setSelectedMemoryIds((current) => {
      if (current.includes(memory.id)) {
        return current.filter((id) => id !== memory.id);
      }
      if (current.length >= 8) return current;
      return [...current, memory.id];
    });
  }

  function submitProposal() {
    if (!isOwner) {
      setNotice({
        message: "An owner token is required to propose a consolidation. Add one in Settings.",
        tone: "warning",
      });
      return;
    }
    if (selectedMemoryIds.length < 3) {
      setNotice({
        message: "Select at least three active memories to propose a consolidation.",
        tone: "warning",
      });
      return;
    }
    propose.mutate();
  }

  return (
    <div className="page-wrap review-page">
      <header className="page-header">
        <div>
          <div className="breadcrumb">
            <span>Workspace</span>
            <span>/</span>
            <strong>Memory review</strong>
          </div>
          <h1>Memory review</h1>
          <p className="page-subtitle">
            Resolve the few decisions where context or evidence is too close to
            call automatically.
          </p>
        </div>
        <div className="header-actions">
          <span className="count-pill">
            {status === "pending" ? `${reviews.data?.total ?? "—"} pending` : "Resolved history"}
          </span>
          <Link className="primary-button" href="/ingestion">
            <Sparkles size={14} />
            Ingest interaction
          </Link>
        </div>
      </header>

      <section className="review-intro">
        <div className="review-intro-icon">
          <ShieldAlert size={18} />
        </div>
        <div>
          <strong>MemoryOS pauses when evidence is ambiguous.</strong>
          <p>
            Choose a deliberate outcome below. Each action becomes an auditable
            history event; no original memory is silently deleted.
          </p>
        </div>
        {!isOwner ? (
          <Link className="review-owner-link" href="/settings">
            <LockKeyhole size={14} /> Add owner token
          </Link>
        ) : null}
      </section>

      {notice ? (
        <InlineNotice tone={notice.tone}>
          {notice.tone === "success" ? (
            <CheckCircle2 size={15} />
          ) : notice.tone === "warning" ? (
            <AlertTriangle size={15} />
          ) : (
            <Info size={15} />
          )}
          {notice.message}
        </InlineNotice>
      ) : null}

      <section className="review-toolbar panel">
        <div className="review-tabs" role="tablist" aria-label="Review status">
          <button
            className={status === "pending" ? "review-tab active" : "review-tab"}
            type="button"
            role="tab"
            aria-selected={status === "pending"}
            onClick={() => setStatus("pending")}
          >
            Pending
            {status === "pending" && reviews.data ? (
              <span>{reviews.data.total}</span>
            ) : null}
          </button>
          <button
            className={status === "resolved" ? "review-tab active" : "review-tab"}
            type="button"
            role="tab"
            aria-selected={status === "resolved"}
            onClick={() => setStatus("resolved")}
          >
            Resolved
          </button>
        </div>
        <span className="review-toolbar-copy">
          {status === "pending"
            ? "Pending conflicts and consolidation proposals"
            : "Recent owner decisions"}
        </span>
        <button
          className="icon-button review-refresh"
          type="button"
          onClick={() => void reviews.refetch()}
          aria-label="Refresh reviews"
        >
          <RotateCcw size={14} />
        </button>
      </section>

      {reviews.isPending ? <LoadingState label="Loading review inbox" /> : null}
      {reviews.isError ? (
        <ErrorState error={reviews.error} onRetry={() => void reviews.refetch()} />
      ) : null}
      {reviews.data && reviews.data.items.length === 0 ? (
        <EmptyState
          title={status === "pending" ? "The review inbox is clear" : "No resolved reviews yet"}
          detail={
            status === "pending"
              ? "Ambiguous conflicts will appear here when MemoryOS pauses a decision."
              : "Resolved decisions will remain available here for auditability."
          }
        />
      ) : null}
      {reviews.data && reviews.data.items.length ? (
        <div className="review-list">
          {reviews.data.items.map((item) => (
            <ReviewCard
              key={item.id}
              item={item}
              isOwner={isOwner}
              reason={reasons[item.id] || ""}
              pending={resolve.isPending && resolve.variables?.reviewId === item.id}
              onReasonChange={(reason) => updateReason(item.id, reason)}
              onResolve={(action) => handleResolve(item, action)}
            />
          ))}
        </div>
      ) : null}

      {status === "pending" ? (
        <ConsolidationBuilder
          memories={activeMemories}
          selectedMemories={selectedMemories}
          selectedIds={selectedMemoryIds}
          isOwner={isOwner}
          loading={memoryPool.isPending}
          pending={propose.isPending}
          onToggle={toggleMemory}
          onSubmit={submitProposal}
        />
      ) : null}
    </div>
  );
}

function ReviewCard({
  item,
  isOwner,
  reason,
  pending,
  onReasonChange,
  onResolve,
}: {
  item: ReviewItem;
  isOwner: boolean;
  reason: string;
  pending: boolean;
  onReasonChange: (reason: string) => void;
  onResolve: (action: ReviewAction) => void;
}) {
  const isConsolidation = item.kind === "consolidation";
  const itemActions = isConsolidation
    ? actions.filter((action) => action.value === "use_new" || action.value === "invalid")
    : actions;
  return (
    <article className={`panel review-card ${item.status} ${item.kind}`}>
      <div className="review-card-header">
        <div className="review-card-kicker">
          <span className={`review-kind ${item.kind}`}>
            {isConsolidation ? <Layers3 size={12} /> : <AlertTriangle size={12} />}
            {isConsolidation ? "Consolidation proposal" : "Unresolved conflict"}
          </span>
          <span className={`relation-chip ${item.proposed_relation}`}>
            Proposed: {formatRelation(item.proposed_relation)}
          </span>
        </div>
        <span className="review-created">{formatDate(item.created_at)}</span>
      </div>
      <div className="review-card-title-row">
        <div>
          <h2>{isConsolidation ? "Can these memories become one durable fact?" : "Which evidence should stay active?"}</h2>
          <p>{item.reason_summary}</p>
        </div>
        <span className="review-confidence">
          <b>{item.confidence.toFixed(2)}</b>
          <small>confidence</small>
        </span>
      </div>

      {isConsolidation ? (
        <div className="review-comparison consolidation-comparison">
          <div className="review-memory-stack">
            <span className="review-section-label">Source memories · preserved</span>
            {item.source_memories.map((memory) => (
              <MemoryEvidenceCard memory={memory} key={memory.id} />
            ))}
          </div>
          <div className="review-candidate-column">
            <span className="review-section-label">Proposed consolidated memory</span>
            <CandidateCard item={item} />
          </div>
        </div>
      ) : (
        <div className="review-comparison">
          <MemoryEvidenceCard memory={item.existing_memory} label="Existing memory" />
          <div className="review-compare-arrow" aria-hidden="true">
            <GitBranch size={15} />
          </div>
          <div className="review-candidate-column">
            <span className="review-section-label">New candidate</span>
            <CandidateCard item={item} />
          </div>
        </div>
      )}

      <div className="review-evidence-row">
        <div className="review-evidence">
          <span className="review-section-label">Evidence</span>
          <blockquote>“{item.evidence_excerpt || item.candidate.evidence_excerpt}”</blockquote>
        </div>
        <div className="review-reason">
          <span className="review-section-label">Why MemoryOS paused</span>
          <p>
            <strong>{formatReasonCode(item.reason_code)}</strong>
            {item.reason_summary}
          </p>
        </div>
      </div>

      {item.status === "resolved" ? (
        <div className="review-resolved-row">
          <CheckCircle2 size={15} />
          <span>
            Resolved with <strong>{formatAction(item.resolution)}</strong>
            {item.resolved_at ? ` · ${formatDate(item.resolved_at)}` : ""}
          </span>
          {item.resolution_reason ? <em>“{item.resolution_reason}”</em> : null}
        </div>
      ) : (
        <div className="review-actions">
          <label className="review-reason-field">
            <span className="review-section-label">Decision note (optional)</span>
            <input
              value={reason}
              onChange={(event) => onReasonChange(event.target.value)}
              placeholder="Add context for the audit trail"
              maxLength={500}
              disabled={!isOwner || pending}
            />
          </label>
          <div className="review-action-buttons">
            {itemActions.map((action) => (
              <button
                className={`review-action-button ${action.tone}`}
                type="button"
                key={action.value}
                onClick={() => onResolve(action.value)}
                disabled={!isOwner || pending}
                title={action.description}
              >
                {action.value === "invalid" ? <X size={13} /> : action.value === "use_new" ? <Check size={13} /> : null}
                {pending ? "Saving…" : action.label}
              </button>
            ))}
          </div>
        </div>
      )}
      {!isOwner && item.status === "pending" ? (
        <div className="review-card-footnote">
          <LockKeyhole size={13} /> Add an owner token in <Link href="/settings">Settings</Link> to record a decision.
        </div>
      ) : null}
    </article>
  );
}

function CandidateCard({ item }: { item: ReviewItem }) {
  const candidate = item.candidate;
  return (
    <div className="review-memory-card candidate">
      <div className="review-memory-card-top">
        <TypeBadge type={candidate.memory_type} />
        <span>{candidate.confidence.toFixed(2)} confidence</span>
      </div>
      <strong>{candidate.content}</strong>
      <div className="review-memory-meta">
        <span>{candidate.subject || "Unscoped"}</span>
        <span>{candidate.context_key || "general context"}</span>
      </div>
    </div>
  );
}

function MemoryEvidenceCard({
  memory,
  label = "Existing memory",
}: {
  memory: MemoryRecord | null;
  label?: string;
}) {
  if (!memory) {
    return (
      <div className="review-memory-card missing">
        <span className="review-section-label">{label}</span>
        <strong>No active memory was found</strong>
      </div>
    );
  }
  return (
    <Link className="review-memory-card" href={`/memories/${memory.id}`}>
      <div className="review-memory-card-top">
        <span className="review-section-label">{label}</span>
        <StatusBadge status={memory.status} />
      </div>
      <strong>{memory.content}</strong>
      <div className="review-memory-meta">
        <span>{memory.subject || "Unscoped"}</span>
        <span>{memory.context_key || "general context"}</span>
        <span>{memory.reinforcement_count} confirmations</span>
      </div>
    </Link>
  );
}

function ConsolidationBuilder({
  memories,
  selectedMemories,
  selectedIds,
  isOwner,
  loading,
  pending,
  onToggle,
  onSubmit,
}: {
  memories: MemoryRecord[];
  selectedMemories: MemoryRecord[];
  selectedIds: string[];
  isOwner: boolean;
  loading: boolean;
  pending: boolean;
  onToggle: (memory: MemoryRecord) => void;
  onSubmit: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const filtered = memories.filter((memory) => {
    const haystack = `${memory.content} ${memory.subject || ""} ${memory.context_key || ""}`.toLowerCase();
    return haystack.includes(filter.toLowerCase());
  });
  return (
    <section className={`panel consolidation-builder ${open ? "open" : ""}`}>
      <button
        className="consolidation-builder-toggle"
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span className="consolidation-builder-icon">
          <Plus size={16} />
        </span>
        <span>
          <strong>Propose a consolidation</strong>
          <small>Group three to eight similar active memories into one reviewable proposal.</small>
        </span>
        <ChevronDown className="consolidation-chevron" size={16} />
      </button>
      {open ? (
        <div className="consolidation-builder-body">
          <div className="consolidation-builder-copy">
            <span className="eyebrow">Conservative by design</span>
            <p>
              MemoryOS keeps every source memory and asks for approval before a
              consolidated version becomes active.
            </p>
          </div>
          <div className="consolidation-controls">
            <input
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder="Filter active memories"
              aria-label="Filter active memories"
            />
            <span className="consolidation-selection">
              {selectedIds.length} selected · choose 3–8
            </span>
          </div>
          {loading ? <LoadingState label="Loading active memories" /> : null}
          {!loading && memories.length === 0 ? (
            <div className="empty-panel">No active memories are available for consolidation.</div>
          ) : null}
          {filtered.length ? (
            <div className="consolidation-memory-list">
              {filtered.map((memory) => (
                <label
                  className={`consolidation-memory-option ${selectedIds.includes(memory.id) ? "selected" : ""}`}
                  key={memory.id}
                >
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(memory.id)}
                    onChange={() => onToggle(memory)}
                    disabled={!isOwner || (!selectedIds.includes(memory.id) && selectedIds.length >= 8)}
                  />
                  <span>
                    <strong>{memory.content}</strong>
                    <small>
                      {memory.subject || "Unscoped"} · {memory.context_key || "general context"}
                    </small>
                  </span>
                  <TypeBadge type={memory.memory_type} />
                </label>
              ))}
            </div>
          ) : null}
          <div className="consolidation-builder-footer">
            {!isOwner ? (
              <span className="owner-required">
                <LockKeyhole size={13} /> Owner token required
              </span>
            ) : (
              <span className="consolidation-source-count">
                {selectedMemories.length ? `${selectedMemories.length} source memories will be preserved` : "Select source memories to continue"}
              </span>
            )}
            <button
              className="primary-button"
              type="button"
              onClick={onSubmit}
              disabled={!isOwner || pending || selectedIds.length < 3}
            >
              <Layers3 size={14} />
              {pending ? "Proposing…" : "Create proposal"}
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function formatRelation(value: ReviewItem["proposed_relation"]) {
  const labels: Record<ReviewItem["proposed_relation"], string> = {
    new: "new",
    reinforce: "reinforcement",
    supersede: "supersession",
    dispute: "dispute",
    skip: "skip",
  };
  return labels[value];
}

function formatAction(value: ReviewItem["resolution"]) {
  if (!value) return "pending";
  return actions.find((action) => action.value === value)?.label || value;
}

function formatKind(value: ReviewItem["kind"]) {
  return value === "consolidation" ? "Consolidation proposal" : "Review";
}

function formatReasonCode(value: string) {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function defaultReason(action: ReviewAction) {
  return `${actions.find((item) => item.value === action)?.label || "Review"} by owner`;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}
