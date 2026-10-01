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
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  EmptyState,
  ErrorState,
  InlineNotice,
  LoadingState,
} from "@/components/status-state";
import { StatusBadge, TypeBadge } from "@/components/type-badge";
import { useWorkspace } from "@/components/workspace-context";
import { ApiClientError } from "@/lib/api/client";
import { sourceEvidence } from "@/lib/api/history";
import {
  getMemories,
  getReviews,
  proposeConsolidation,
  resolveReview,
} from "@/lib/api/queries";
import type {
  MemoryEvent,
  MemoryRecord,
  ReviewListResponse,
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
    value: "keep_existing",
    label: "Keep A",
    description: "A stays active. B becomes historical.",
    tone: "quiet",
  },
  {
    value: "use_new",
    label: "Keep B",
    description: "B stays active. A becomes historical.",
    tone: "primary",
  },
  {
    value: "keep_both",
    label: "Keep both",
    description: "For separate contexts or timeframes.",
    tone: "secondary",
  },
  {
    value: "merge",
    label: "Merge",
    description: "Write one corrected memory · live mode.",
    tone: "secondary",
  },
  {
    value: "invalid",
    label: "Reject proposal",
    description: "Preserve the original source memories.",
    tone: "danger",
  },
];

export function MemoryReview() {
  const { scopeId, mode, token, isOwner } = useWorkspace();
  const [expandedReviewId, setExpandedReviewId] = useState<string | null>(null);
  const [status, setStatus] = useState<ReviewStatus>("pending");
  const [notice, setNotice] = useState<{
    message: string;
    tone: "success" | "warning" | "info";
    memoryId?: string;
  } | null>(null);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const noticeRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (notice) {
      noticeRef.current?.focus({ preventScroll: true });
      noticeRef.current?.scrollIntoView({ block: "nearest" });
    }
  }, [notice]);
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
      mergedContent,
    }: {
      reviewId: string;
      action: ReviewAction;
      reason: string;
      mergedContent?: string;
    }) =>
      resolveReview(scopeId, reviewId, action, reason, token, mergedContent),
    onSuccess: async (item) => {
      setExpandedReviewId(null);
      setNotice({
        message: "Decision saved. Original evidence and history are preserved.",
        tone: "success",
        memoryId: item.result_memory?.id,
      });
      // Update the inbox only after the server has persisted the decision.
      queryClient.setQueryData<ReviewListResponse>(
        ["reviews", scopeId, mode, "pending"],
        (current) => {
          if (
            !current ||
            !current.items.some((review) => review.id === item.id)
          )
            return current;
          return {
            ...current,
            items: current.items.filter((review) => review.id !== item.id),
            total: Math.max(0, current.total - 1),
          };
        },
      );
      await Promise.all(
        [
          "reviews",
          "overview",
          "memories",
          "memory",
          "memory-history",
          "review-memory-pool",
          "recall-compare",
        ].map((key) => queryClient.invalidateQueries({ queryKey: [key] })),
      );
    },
    onError: (error) => {
      setNotice({
        message:
          error instanceof Error
            ? error.message
            : "The review could not be resolved.",
        tone: "warning",
      });
      if (
        error instanceof ApiClientError &&
        error.code === "revision_conflict"
      ) {
        void queryClient.invalidateQueries({ queryKey: ["reviews"] });
      }
    },
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
        message:
          "Consolidation proposal added to the review inbox. Originals remain unchanged.",
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
        .filter((memory): memory is (typeof activeMemories)[number] =>
          Boolean(memory),
        ),
    [activeMemories, selectedMemoryIds],
  );

  function updateReason(reviewId: string, reason: string) {
    setReasons((current) => ({ ...current, [reviewId]: reason }));
  }

  function handleResolve(
    item: ReviewItem,
    action: ReviewAction,
    mergedContent?: string,
  ) {
    if (resolve.isPending) return;
    if (!isOwner) {
      setNotice({
        message:
          "An owner token is required to resolve a review. Add one in Settings.",
        tone: "warning",
      });
      return;
    }
    resolve.mutate({
      reviewId: item.id,
      action,
      reason: reasons[item.id]?.trim() || defaultReason(action),
      mergedContent,
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
        message:
          "An owner token is required to propose a consolidation. Add one in Settings.",
        tone: "warning",
      });
      return;
    }
    if (selectedMemoryIds.length < 2) {
      setNotice({
        message:
          "Select at least two active memories to propose a consolidation.",
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
            Compare the evidence and decide what stays active.
          </p>
        </div>
        <div className="header-actions">
          <span className="count-pill">
            {status === "pending"
              ? `${reviews.data?.total ?? "—"} pending`
              : "Resolved history"}
          </span>
          <Link className="primary-button" href="/ingestion">
            <Sparkles size={14} />
            Ingest interaction
          </Link>
        </div>
      </header>

      {status === "pending" ? (
        <section className="review-intro">
          <div className="review-intro-icon">
            <ShieldAlert size={18} />
          </div>
          <div>
            <strong>Every decision preserves history.</strong>
            <p>
              Compare the sources, choose an outcome, and confirm the decision.
            </p>
          </div>
          {!isOwner ? (
            <Link className="review-owner-link" href="/settings">
              <LockKeyhole size={14} /> Add owner token
            </Link>
          ) : null}
        </section>
      ) : null}

      {notice ? (
        <div ref={noticeRef} className="review-notice" tabIndex={-1}>
          <InlineNotice tone={notice.tone}>
            {notice.tone === "success" ? (
              <CheckCircle2 size={15} />
            ) : notice.tone === "warning" ? (
              <AlertTriangle size={15} />
            ) : (
              <Info size={15} />
            )}
            {notice.message}
            {notice.memoryId ? (
              <Link href={`/memories/${notice.memoryId}`}>
                View resulting memory →
              </Link>
            ) : null}
          </InlineNotice>
        </div>
      ) : null}

      <section className="review-toolbar panel">
        <div className="review-tabs" role="tablist" aria-label="Review status">
          <button
            className={
              status === "pending" ? "review-tab active" : "review-tab"
            }
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
            className={
              status === "resolved" ? "review-tab active" : "review-tab"
            }
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
        <ErrorState
          error={reviews.error}
          onRetry={() => void reviews.refetch()}
        />
      ) : null}
      {reviews.data && reviews.data.items.length === 0 ? (
        <EmptyState
          title={
            status === "pending"
              ? "The review inbox is clear"
              : "No resolved reviews yet"
          }
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
              key={`${scopeId}:${mode}:${status}:${item.id}`}
              item={item}
              isOwner={isOwner}
              expanded={expandedReviewId === item.id}
              onToggle={() =>
                setExpandedReviewId((current) =>
                  current === item.id ? null : item.id,
                )
              }
              reason={reasons[item.id] || ""}
              pending={resolve.isPending}
              onReasonChange={(reason) => updateReason(item.id, reason)}
              onResolve={(action, mergedContent) =>
                handleResolve(item, action, mergedContent)
              }
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
  expanded,
  onToggle,
  onReasonChange,
  onResolve,
}: {
  item: ReviewItem;
  isOwner: boolean;
  reason: string;
  pending: boolean;
  expanded: boolean;
  onToggle: () => void;
  onReasonChange: (reason: string) => void;
  onResolve: (action: ReviewAction, mergedContent?: string) => void;
}) {
  const [selectedAction, setSelectedAction] = useState<ReviewAction | null>(
    null,
  );
  const [mergedContent, setMergedContent] = useState("");
  const [confirming, setConfirming] = useState(false);
  const isConsolidation = item.kind === "consolidation";
  const stale =
    !isConsolidation && item.status === "pending" && conflictIsStale(item);
  const itemActions = isConsolidation
    ? actions.filter(
        (action) => action.value === "use_new" || action.value === "invalid",
      )
    : actions.filter((action) => action.value !== "invalid");
  const title = isConsolidation
    ? "Consolidation proposal"
    : formatReasonCode(
        item.candidate.attribute_key ||
          item.candidate.context_key ||
          "Memory conflict",
      );
  const actionLabel = (action: ReviewAction) =>
    isConsolidation && action === "use_new"
      ? "Approve proposal"
      : formatAction(action);
  const actionUnavailable = (action: ReviewAction) => {
    if (action === "merge") return item.merge_unavailable_reason;
    if (action === "keep_both") return item.keep_both_unavailable_reason;
    if (action === "keep_existing" && !item.existing_memory)
      return "There is no stored memory A.";
    if (action === "use_new" && !isConsolidation && !item.candidate_memory)
      return "The candidate has not been stored.";
    return null;
  };
  const noteRequired =
    selectedAction === "keep_both" || selectedAction === "merge";
  const canConfirm =
    isOwner &&
    !pending &&
    !stale &&
    selectedAction !== null &&
    !actionUnavailable(selectedAction) &&
    (!noteRequired || reason.trim().length > 0) &&
    (selectedAction !== "merge" ||
      (mergedContent.trim().length > 0 &&
        mergedContent.trim() !== item.candidate.content &&
        mergedContent.trim() !== item.existing_memory?.content));
  return (
    <article className={`panel review-card ${item.status} ${item.kind}`}>
      <div className="review-card-header">
        <div className="review-card-kicker">
          <span className={`review-kind ${item.kind}`}>
            {isConsolidation ? (
              <Layers3 size={12} />
            ) : (
              <AlertTriangle size={12} />
            )}
            {isConsolidation
              ? "Consolidation"
              : item.status === "pending"
                ? "Unresolved conflict"
                : "Resolved conflict"}
          </span>
          <span className="review-created">{formatDate(item.created_at)}</span>
        </div>
      </div>
      <div className="review-card-title-row">
        <div>
          <h2>{title}</h2>
          <p>
            {[
              item.candidate.subject,
              item.candidate.context_key?.replaceAll("-", " "),
            ]
              .filter(Boolean)
              .join(" · ") || "Two competing memories"}
          </p>
        </div>
        <button
          className="secondary-button review-open-button"
          type="button"
          aria-expanded={expanded}
          aria-controls={`review-${item.id}`}
          onClick={() => {
            setConfirming(false);
            onToggle();
          }}
          disabled={pending}
        >
          {expanded
            ? "Close"
            : item.status === "pending"
              ? "Review decision"
              : "View decision"}
          <ChevronDown size={14} />
        </button>
      </div>
      {expanded ? (
        <div id={`review-${item.id}`} className="review-expanded">
          <p className="review-conflict-explanation">
            {isConsolidation ? item.reason_summary : conflictExplanation(item)}
          </p>
          {stale ? (
            <InlineNotice tone="warning">
              This review’s sources have changed. The original evidence is
              preserved; this decision cannot overwrite a newer state.
            </InlineNotice>
          ) : null}
          {isConsolidation ? (
            <div className="review-comparison consolidation-comparison">
              <div className="review-memory-stack">
                <span className="review-section-label">Preserved sources</span>
                {item.source_memories.map((memory) => (
                  <MemoryEvidenceCard memory={memory} key={memory.id} />
                ))}
              </div>
              <CandidateCard item={item} />
            </div>
          ) : (
            <div className="review-comparison">
              <MemoryEvidenceCard
                memory={item.current_existing_memory || item.existing_memory}
                label="A · Existing memory"
                evidence={sourceEvidence(
                  item.existing_evidence,
                  item.created_at,
                )}
              />
              <div className="review-compare-arrow" aria-hidden="true">
                <GitBranch size={15} />
              </div>
              <CandidateCard item={item} />
            </div>
          )}
          <details className="review-policy-context">
            <summary>Why this was flagged</summary>
            <p>{item.reason_summary}</p>
            <span>{formatReasonCode(item.reason_code)}</span>
          </details>
          {item.status === "resolved" ? (
            <div className="review-resolved-row">
              <CheckCircle2 size={15} />
              <span>
                <strong>
                  {actionLabel(item.resolution || "keep_existing")}
                </strong>
                {item.resolved_at ? ` · ${formatDate(item.resolved_at)}` : ""}
              </span>
              {item.resolution_reason ? (
                <em>“{item.resolution_reason}”</em>
              ) : null}
              {item.result_memory ? (
                <Link href={`/memories/${item.result_memory.id}`}>
                  View resulting memory →
                </Link>
              ) : null}
            </div>
          ) : (
            <div className="review-actions">
              <div
                className="review-decision-options"
                role="radiogroup"
                aria-label={`Resolution for ${title}`}
              >
                {itemActions.map((action) => {
                  const unavailable = actionUnavailable(action.value);
                  return (
                    <label
                      className={`review-decision-option ${selectedAction === action.value ? "selected" : ""} ${unavailable ? "unavailable" : ""}`}
                      key={action.value}
                      title={unavailable || action.description}
                    >
                      <input
                        type="radio"
                        name={`action-${item.id}`}
                        value={action.value}
                        checked={selectedAction === action.value}
                        disabled={
                          !isOwner || pending || stale || Boolean(unavailable)
                        }
                        onChange={() => {
                          setSelectedAction(action.value);
                          setConfirming(false);
                        }}
                      />
                      <span>
                        <strong>{actionLabel(action.value)}</strong>
                        <small>
                          {isConsolidation && action.value === "use_new"
                            ? "Activate the canonical statement. Preserve source history."
                            : action.description}
                        </small>
                      </span>
                    </label>
                  );
                })}
              </div>
              {!isConsolidation &&
              (item.merge_unavailable_reason ||
                item.keep_both_unavailable_reason) ? (
                <details className="review-policy-context">
                  <summary>Action availability</summary>
                  {item.keep_both_unavailable_reason ? (
                    <p>
                      <strong>Keep both:</strong>{" "}
                      {item.keep_both_unavailable_reason}
                    </p>
                  ) : null}
                  {item.merge_unavailable_reason ? (
                    <p>
                      <strong>Merge:</strong> {item.merge_unavailable_reason}
                    </p>
                  ) : null}
                </details>
              ) : null}
              {selectedAction === "merge" ? (
                <label className="review-correction-field">
                  <span className="review-section-label">Corrected memory</span>
                  <textarea
                    rows={3}
                    value={mergedContent}
                    maxLength={2000}
                    placeholder="Write the accurate statement with any relevant conditions"
                    onChange={(event) => {
                      setMergedContent(event.target.value);
                      setConfirming(false);
                    }}
                    disabled={pending}
                  />
                  <small>
                    A new version will preserve both sources in its audit trail.
                  </small>
                </label>
              ) : null}
              <label className="review-reason-field">
                <span className="review-section-label">
                  {noteRequired
                    ? "Decision note · required"
                    : "Decision note · optional"}
                </span>
                <input
                  value={reason}
                  onChange={(event) => {
                    onReasonChange(event.target.value);
                    setConfirming(false);
                  }}
                  placeholder={
                    selectedAction === "keep_both"
                      ? "Explain the separate contexts or timeframes"
                      : "Explain the evidence behind your decision"
                  }
                  maxLength={500}
                  disabled={!isOwner || pending || stale}
                />
              </label>
              {confirming && selectedAction ? (
                <div
                  className="review-confirmation"
                  role="group"
                  aria-label="Confirm memory decision"
                >
                  <h3>Confirm {actionLabel(selectedAction)}</h3>
                  <p>
                    {resolutionConsequence(selectedAction, isConsolidation)}
                  </p>
                  {selectedAction === "keep_existing" ? (
                    <blockquote>{item.existing_memory?.content}</blockquote>
                  ) : null}
                  {selectedAction === "use_new" ? (
                    <blockquote>{item.candidate.content}</blockquote>
                  ) : null}
                  {selectedAction === "merge" ? (
                    <blockquote>{mergedContent.trim()}</blockquote>
                  ) : null}
                  <div className="review-confirmation-buttons">
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={() => setConfirming(false)}
                      disabled={pending}
                    >
                      Back
                    </button>
                    <button
                      className="primary-button"
                      type="button"
                      disabled={!canConfirm}
                      onClick={() =>
                        onResolve(
                          selectedAction,
                          selectedAction === "merge"
                            ? mergedContent.trim()
                            : undefined,
                        )
                      }
                    >
                      <Check size={14} />
                      {pending ? "Saving decision…" : "Confirm resolution"}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="review-decision-footer">
                  <span>Original memories and evidence stay in history.</span>
                  <button
                    className="primary-button"
                    type="button"
                    disabled={!canConfirm}
                    onClick={() => setConfirming(true)}
                  >
                    Review decision →
                  </button>
                </div>
              )}
            </div>
          )}
          {!isOwner && item.status === "pending" ? (
            <div className="review-card-footnote">
              <LockKeyhole size={13} /> Add an owner token in{" "}
              <Link href="/settings">Settings</Link> to record a decision.
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function CandidateCard({ item }: { item: ReviewItem }) {
  const candidate = item.candidate;
  const memory = item.candidate_memory;
  const evidence = sourceEvidence(item.candidate_evidence, item.created_at);
  return (
    <div className="review-memory-card candidate">
      <div className="review-memory-card-top">
        <span className="review-section-label">
          {item.kind === "consolidation"
            ? "Proposed summary"
            : "B · New memory"}
        </span>
        {memory ? (
          <StatusBadge status={memory.status} />
        ) : (
          <span className="review-proposal-status">Proposed</span>
        )}
      </div>
      <strong>{candidate.content}</strong>
      <div className="review-memory-facts">
        <TypeBadge type={candidate.memory_type} />
        {memory ? <span>Version {memory.version}</span> : null}
      </div>
      <div className="review-memory-meta">
        <span>{candidate.context_key || "General context"}</span>
        <span>{candidate.confidence.toFixed(2)} confidence</span>
        <span>{candidate.importance.toFixed(2)} importance</span>
      </div>
      <blockquote className="review-source-excerpt">
        “
        {evidence?.evidence_excerpt ||
          item.evidence_excerpt ||
          candidate.evidence_excerpt}
        ”
      </blockquote>
      <EvidenceSource evidence={evidence} />
      {memory ? (
        <Link
          className="review-memory-history-link"
          href={`/memories/${memory.id}`}
        >
          View memory & history →
        </Link>
      ) : null}
    </div>
  );
}

function MemoryEvidenceCard({
  memory,
  label = "Source memory",
  evidence,
}: {
  memory: MemoryRecord | null;
  label?: string;
  evidence?: MemoryEvent;
}) {
  if (!memory)
    return (
      <div className="review-memory-card missing">
        <span className="review-section-label">{label}</span>
        <strong>No stored memory found</strong>
      </div>
    );
  return (
    <div className="review-memory-card">
      <div className="review-memory-card-top">
        <span className="review-section-label">{label}</span>
        <StatusBadge status={memory.status} />
      </div>
      <strong>{memory.content}</strong>
      <div className="review-memory-facts">
        <TypeBadge type={memory.memory_type} />
        <span>Version {memory.version}</span>
      </div>
      <div className="review-memory-meta">
        <span>{memory.context_key || "General context"}</span>
        <span>{memory.confidence.toFixed(2)} confidence</span>
        <span>{memory.importance.toFixed(2)} importance</span>
      </div>
      {evidence?.evidence_excerpt ? (
        <blockquote className="review-source-excerpt">
          “{evidence.evidence_excerpt}”
        </blockquote>
      ) : null}
      <EvidenceSource evidence={evidence} />
      <Link
        className="review-memory-history-link"
        href={`/memories/${memory.id}`}
      >
        View memory & history →
      </Link>
    </div>
  );
}

function EvidenceSource({ evidence }: { evidence?: MemoryEvent }) {
  if (!evidence)
    return (
      <small className="review-source-label">
        No earlier source excerpt recorded.
      </small>
    );
  return (
    <small
      className="review-source-label"
      title={evidence.interaction_id || evidence.id}
    >
      {evidence.provenance ||
        (evidence.interaction_id
          ? `Interaction ${evidence.interaction_id.slice(0, 8)}`
          : "Recorded evidence")}{" "}
      · {formatDate(evidence.source_occurred_at || evidence.created_at)}
    </small>
  );
}

function conflictExplanation(item: ReviewItem) {
  const a = item.existing_memory;
  const b = item.candidate;
  if (
    a &&
    a.subject === b.subject &&
    a.context_key === b.context_key &&
    a.attribute_key === b.attribute_key
  ) {
    return `Two different values describe ${b.attribute_key?.replaceAll("-", " ") || "the same fact"} in ${b.context_key?.replaceAll("-", " ") || "the same context"}. ${item.status === "resolved" ? "Both originals are preserved in history." : "MemoryOS kept both for your decision."}`;
  }
  return "These memories appear to disagree. Compare their contexts and evidence before choosing what stays active.";
}

function conflictIsStale(item: ReviewItem) {
  const candidate = item.candidate_memory;
  const existing = item.current_existing_memory;
  const fields = [
    "content",
    "memory_type",
    "subject",
    "context_key",
    "attribute_key",
    "importance",
    "confidence",
    "effective_at",
    "expires_at",
  ] as const;
  if (
    !candidate ||
    candidate.status !== "disputed" ||
    fields.some((field) => candidate[field] !== item.candidate[field])
  )
    return true;
  return item.existing_memory
    ? !existing ||
        existing.status === "forgotten" ||
        existing.status === "superseded" ||
        existing.status !== item.existing_memory.status ||
        existing.version !== item.existing_memory.version ||
        fields.some(
          (field) => existing[field] !== item.existing_memory?.[field],
        )
    : false;
}

function resolutionConsequence(action: ReviewAction, consolidation: boolean) {
  if (consolidation && action === "use_new")
    return "The canonical memory becomes active. Sources are superseded and remain accessible with their original evidence.";
  switch (action) {
    case "keep_existing":
      return "A becomes active and B is superseded. Both original records and their evidence remain in history.";
    case "use_new":
      return "B becomes active and A is superseded. Both original records and their evidence remain in history.";
    case "keep_both":
      return "Both remain active for their separate contexts or timeframes. A separate lineage is created if needed.";
    case "merge":
      return "This corrected statement becomes a new active version. A and B are superseded, with links to both preserved sources.";
    default:
      return "The proposal is rejected. Its source memories and review record are preserved.";
  }
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
    const haystack =
      `${memory.content} ${memory.subject || ""} ${memory.context_key || ""}`.toLowerCase();
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
          <small>
            Group two to eight equivalent active memories into one reviewable
            proposal.
          </small>
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
            <div className="empty-panel">
              No active memories are available for consolidation.
            </div>
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
                    disabled={
                      !isOwner ||
                      (!selectedIds.includes(memory.id) &&
                        selectedIds.length >= 8)
                    }
                  />
                  <span>
                    <strong>{memory.content}</strong>
                    <small>
                      {memory.subject || "Unscoped"} ·{" "}
                      {memory.context_key || "general context"}
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
                {selectedMemories.length
                  ? `${selectedMemories.length} source memories will be preserved`
                  : "Select source memories to continue"}
              </span>
            )}
            <button
              className="primary-button"
              type="button"
              onClick={onSubmit}
              disabled={!isOwner || pending || selectedIds.length < 2}
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

function formatAction(value: ReviewItem["resolution"]) {
  if (!value) return "pending";
  return actions.find((action) => action.value === value)?.label || value;
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
