"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import {
  ErrorState,
  InlineNotice,
  LoadingState,
} from "@/components/status-state";
import { useWorkspace } from "@/components/workspace-context";
import { refreshIngestionCaches } from "@/lib/api/cache";
import { ApiClientError } from "@/lib/api/client";
import {
  getDemoCatalog,
  getMemory,
  postMemoryCorrection,
} from "@/lib/api/queries";
import type { IngestInteractionResponse } from "@/lib/api/types";

const outcomeLabels: Record<string, string> = {
  superseded: "Supersedes",
  reinforced: "Reinforces",
  created: "Creates a memory",
  disputed: "Needs review",
  consolidated: "Consolidates",
  skipped: "Not remembered",
  rejected: "Rejected",
};

export function CorrectMemory({
  memoryId,
  onClose,
  onCommitted,
}: {
  memoryId: string;
  onClose: () => void;
  onCommitted: (response: IngestInteractionResponse) => void;
}) {
  const { scopeId, mode, token, isOwner } = useWorkspace();
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const [scenarioId, setScenarioId] = useState("");
  const [preview, setPreview] = useState<IngestInteractionResponse | null>(
    null,
  );
  const memory = useQuery({
    queryKey: ["memory", scopeId, memoryId],
    queryFn: () => getMemory(scopeId, memoryId, token),
  });
  const catalog = useQuery({
    queryKey: ["demo-catalog", "recall-correction"],
    queryFn: () => getDemoCatalog(token),
    enabled: mode === "demo",
  });
  const context = memory.data?.context_key;
  const primaryId =
    context === "algorithms"
      ? "demo-recall-correction-algorithms"
      : context === "examples"
        ? "demo-recall-correction-python"
        : context === "answer-style"
          ? "demo-pref-style-supersede"
          : null;
  const options =
    catalog.data?.scenarios.filter(
      (item) =>
        item.id === primaryId ||
        item.id === "demo-recall-correction-system-design",
    ) || [];
  const selectedScenario =
    options.find((item) => item.id === scenarioId) ||
    options.find((item) => item.id === primaryId) ||
    options[0];
  const correctionText = mode === "demo" ? selectedScenario?.text || "" : text;
  const active = memory.data?.status === "active";
  const mutation = useMutation({
    mutationFn: async (commit: boolean) => {
      const response = await postMemoryCorrection(
        memoryId,
        {
          scope_id: scopeId,
          text: correctionText,
          mode,
          preview: !commit,
          ...(commit && preview
            ? {
                idempotency_key: `recall-correction-${preview.interaction_id}`,
                expected_scope_revision: preview.preview_revision ?? undefined,
                reviewed_decisions: preview.decisions.map(
                  (decision) => decision.decision_type,
                ),
                reviewed_targets: preview.decisions.map(
                  (decision) =>
                    decision.related_memory_id || decision.memory_id || null,
                ),
              }
            : {}),
        },
        token,
      );
      if (commit) await refreshIngestionCaches(queryClient, response);
      return response;
    },
    retry: false,
    onSuccess: (response, commit) => {
      if (commit) onCommitted(response);
      else setPreview(response);
    },
    onError: (error) => {
      if (
        error instanceof ApiClientError &&
        error.code === "revision_conflict"
      ) {
        setPreview(null);
        void memory.refetch();
      }
    },
  });
  const canCommit =
    active &&
    isOwner &&
    preview?.correction_commit_allowed &&
    preview.preview_revision !== null &&
    preview.decisions.some((decision) =>
      [
        "created",
        "reinforced",
        "superseded",
        "disputed",
        "consolidated",
      ].includes(decision.decision_type),
    );

  return (
    <section
      className="panel recall-correction"
      aria-label="Correct recalled memory"
    >
      <div className="context-response-heading">
        <h2>Correct memory</h2>
        <button
          className="secondary-button"
          type="button"
          onClick={onClose}
          disabled={mutation.isPending}
        >
          Close
        </button>
      </div>
      {memory.isPending ? (
        <LoadingState label="Loading the current memory" />
      ) : null}
      {memory.isError ? (
        <ErrorState
          error={memory.error}
          onRetry={() => void memory.refetch()}
        />
      ) : null}
      {mode === "demo" && catalog.isPending ? (
        <LoadingState label="Loading correction examples" />
      ) : null}
      {mode === "demo" && catalog.isError ? (
        <ErrorState
          error={catalog.error}
          onRetry={() => void catalog.refetch()}
        />
      ) : null}
      {memory.data ? (
        <>
          <span className="correction-label">Current memory</span>
          <blockquote>{memory.data.content}</blockquote>
          {!active ? (
            <InlineNotice tone="warning">
              This memory is no longer active. Generate again to recall its
              current state.
            </InlineNotice>
          ) : null}
          {mode === "demo" ? (
            <>
              <label className="correction-label" htmlFor="correction-example">
                Correction example
              </label>
              <select
                id="correction-example"
                value={selectedScenario?.id || ""}
                disabled={!active || mutation.isPending}
                onChange={(event) => {
                  setScenarioId(event.target.value);
                  setPreview(null);
                  mutation.reset();
                }}
              >
                {options.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title}
                  </option>
                ))}
              </select>
            </>
          ) : null}
          <label className="correction-label" htmlFor="correction-text">
            Correction
          </label>
          <textarea
            id="correction-text"
            value={correctionText}
            readOnly={mode === "demo"}
            disabled={!active || mutation.isPending}
            maxLength={2000}
            rows={3}
            placeholder="I switched from concise to detailed explanations. From now on, I prefer detailed algorithm explanations."
            onChange={(event) => {
              setText(event.target.value);
              setPreview(null);
              mutation.reset();
            }}
          />
          {preview ? (
            <div
              className="correction-preview"
              aria-label="Proposed correction outcome"
            >
              <span className="correction-label">Proposed change</span>
              {preview.decisions.map((decision, index) => {
                const candidate = preview.candidates.find(
                  (item) => item.candidate_id === decision.candidate_id,
                );
                const label =
                  decision.reason_code === "contextual_coexistence"
                    ? "Coexists"
                    : outcomeLabels[decision.decision_type] ||
                      decision.decision_type;
                return (
                  <div key={index}>
                    <strong>{label}</strong>
                    {candidate ? (
                      <p>{decision.canonical_content || candidate.content}</p>
                    ) : null}
                    <small>{decision.reason_summary}</small>
                    {decision.related_memory_id &&
                    decision.related_memory_id !== memoryId ? (
                      <Link href={`/memories/${decision.related_memory_id}`}>
                        View the related memory →
                      </Link>
                    ) : null}
                  </div>
                );
              })}
              {!preview.correction_commit_allowed ? (
                <p className="context-request-note">
                  Preview only. No memory was changed.
                </p>
              ) : null}
            </div>
          ) : null}
          {mutation.isError ? (
            <ErrorState
              error={mutation.error}
              onRetry={() => mutation.mutate(Boolean(preview && canCommit))}
            />
          ) : null}
          <div className="correction-actions">
            <button
              type="button"
              className="secondary-button"
              onClick={() => {
                setPreview(null);
                mutation.reset();
              }}
              disabled={!preview || mutation.isPending}
            >
              Back
            </button>
            {preview ? (
              <button
                type="button"
                className="primary-button"
                disabled={!canCommit || mutation.isPending}
                onClick={() => mutation.mutate(true)}
              >
                {mutation.isPending
                  ? "Saving correction…"
                  : "Confirm correction"}
              </button>
            ) : (
              <button
                type="button"
                className="primary-button"
                disabled={
                  !active ||
                  !correctionText.trim() ||
                  mutation.isPending ||
                  (mode === "live" && !isOwner)
                }
                onClick={() => mutation.mutate(false)}
              >
                {mutation.isPending ? "Reviewing…" : "Review correction"}
              </button>
            )}
          </div>
        </>
      ) : null}
    </section>
  );
}
