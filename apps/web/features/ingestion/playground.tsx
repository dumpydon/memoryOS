"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  BrainCircuit,
  Check,
  CheckCircle2,
  CircleAlert,
  ChevronDown,
  FlaskConical,
  GitBranch,
  Info,
  Layers3,
  LoaderCircle,
  Minus,
  Play,
  RotateCcw,
  ShieldAlert,
  Sparkles,
  X,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  ErrorState,
  InlineNotice,
  LoadingState,
} from "@/components/status-state";
import { useIngestionSession } from "@/components/ingestion-session-context";
import { TypeBadge } from "@/components/type-badge";
import { useWorkspace } from "@/components/workspace-context";
import { ApiClientError } from "@/lib/api/client";
import {
  getCapabilities,
  getDemoCatalog,
  postInteraction,
} from "@/lib/api/queries";
import { refreshIngestionCaches } from "@/lib/api/cache";
import type {
  DemoScenario,
  IngestDecision,
  IngestInteractionResponse,
} from "@/lib/api/types";

type Feedback = {
  title: string;
  message: string;
  tone: "info" | "success" | "warning" | "error";
  detail?: string;
};

export function IngestionPlayground() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const { scopeId, mode, token, isOwner } = useWorkspace();
  const {
    text,
    result,
    scenarioId: rememberedScenarioId,
    idempotencyKey,
    setText,
    setIdempotencyKey,
    setScenarioId,
    clearResult,
    complete,
    reset,
  } = useIngestionSession();
  const catalog = useQuery({
    queryKey: ["demo-catalog"],
    queryFn: () => getDemoCatalog(token),
    enabled: mode === "demo",
  });
  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: () => getCapabilities(token),
  });
  const scenarioId = searchParams.get("scenario") || "";
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const feedbackTimer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (feedbackTimer.current !== null) {
        window.clearTimeout(feedbackTimer.current);
      }
    },
    [],
  );

  function showFeedback(
    next: Feedback,
    duration = next.tone === "error" ? 5_500 : 3_600,
  ) {
    setFeedback(next);
    if (feedbackTimer.current !== null) {
      window.clearTimeout(feedbackTimer.current);
    }
    feedbackTimer.current = window.setTimeout(() => {
      setFeedback(null);
      feedbackTimer.current = null;
    }, duration);
  }

  const scenarios = useMemo(
    () => catalog.data?.scenarios || [],
    [catalog.data],
  );
  const activeScenarioId = scenarioId || rememberedScenarioId || "";
  const selectedScenario = useMemo(
    () =>
      activeScenarioId
        ? scenarios.find((scenario) => scenario.id === activeScenarioId) ||
          scenarios[0]
        : scenarios[0],
    [activeScenarioId, scenarios],
  );
  const displayText = mode === "demo" ? selectedScenario?.text || "" : text;
  const liveUnavailable =
    mode === "live" &&
    capabilities.data &&
    !capabilities.data.live_ingestion_available;

  useEffect(() => {
    if (scenarioId && scenarioId !== rememberedScenarioId) {
      setScenarioId(scenarioId);
    }
  }, [rememberedScenarioId, scenarioId, setScenarioId]);

  const ingest = useMutation({
    mutationFn: async ({ preview }: { preview: boolean }) => {
      const response = await postInteraction(
        {
          scope_id: scopeId,
          text: displayText.trim(),
          source_ref:
            mode === "demo"
              ? `demo:${selectedScenario?.id || "unknown"}`
              : "playground",
          idempotency_key: preview ? undefined : idempotencyKey,
          mode,
          preview,
        },
        token,
      );
      if (!preview) {
        await refreshIngestionCaches(queryClient, response);
      }
      return response;
    },
    onSuccess: (response, variables) => {
      complete(response, variables.preview ? "preview" : "commit");
      showFeedback(feedbackForResult(response, variables.preview));
    },
    onError: (error, variables) => {
      const apiError = error instanceof ApiClientError ? error : null;
      const timedOut =
        apiError?.code === "provider_timeout" ||
        apiError?.code === "backend_timeout";
      showFeedback({
        title: timedOut
          ? "Memory analysis timed out"
          : variables.preview
            ? "MemoryOS couldn’t complete this analysis"
            : "Nothing was saved",
        message: timedOut
          ? "Your interaction was not changed. Try the analysis again."
          : variables.preview
            ? "The interaction is unchanged. Try again when the API is available."
            : "The interaction was not changed. Check the API and try again.",
        tone: "error",
        detail:
          apiError?.message ||
          (error instanceof Error ? error.message : undefined),
      });
    },
  });

  function selectScenario(scenario: DemoScenario) {
    clearResult();
    setScenarioId(scenario.id);
    setFeedback(null);
    setIdempotencyKey(`memoryos-${scenario.id}-${Date.now()}`);
    router.replace(`/ingestion?scenario=${encodeURIComponent(scenario.id)}`, {
      scroll: false,
    });
  }

  function run(preview: boolean) {
    setFeedback(null);
    if (!displayText.trim())
      return showFeedback({
        title: "Add an interaction",
        message: "Enter an interaction before running the graph.",
        tone: "warning",
      });
    if (mode === "demo" && !selectedScenario)
      return showFeedback({
        title: "Choose a demo scenario",
        message:
          "Public demo mode only accepts fixture scenarios. Choose one from the picker.",
        tone: "warning",
      });
    if (!preview && !isOwner)
      return showFeedback({
        title: "Owner access is required",
        message:
          "Preview is available publicly; add an owner token before committing a memory.",
        tone: "warning",
      });
    if (mode === "live" && !isOwner)
      return showFeedback({
        title: "Owner access is required",
        message: "Live ingestion needs an owner token. Add one in Settings.",
        tone: "warning",
      });
    if (mode === "live" && capabilities.data?.live_ingestion_available !== true)
      return showFeedback({
        title: "Live analysis is unavailable",
        message:
          capabilities.data?.reason ||
          (capabilities.isPending
            ? "Checking live provider readiness. Try again in a moment."
            : "Live ingestion is unavailable until OPENAI_API_KEY is configured on the API server."),
        tone: "warning",
      });
    clearResult();
    ingest.mutate({ preview });
  }

  return (
    <div className="page-wrap ingestion-page">
      <header className="page-header">
        <div>
          <div className="breadcrumb">
            <span>Workspace</span>
            <span>/</span>
            <strong>Ingestion playground</strong>
          </div>
          <h1>Ingestion playground</h1>
          <p className="page-subtitle">
            Run one interaction through extraction, relationship assessment, and
            deterministic policy validation.
          </p>
        </div>
        <div className="header-actions">
          <span className="demo-pill">
            <span className="status-dot" />
            {mode === "demo" ? "Demo fixture provider" : "Live provider"}
          </span>
        </div>
      </header>

      {liveUnavailable ? (
        <InlineNotice tone="warning">
          <ShieldAlert size={15} />
          Live ingestion is unavailable because the API server has no OpenAI key
          configured. Add <code>OPENAI_API_KEY</code> to the API environment,
          then refresh this page. Demo mode remains available.
        </InlineNotice>
      ) : null}

      <div className="playground-layout">
        <section className="panel interaction-editor">
          <div className="panel-heading interaction-panel-heading">
            <div>
              <span className="eyebrow">Input</span>
              <h2>Choose an interaction</h2>
            </div>
            <div className="interaction-heading-actions">
              <span className="provider-label">
                <FlaskConical size={13} />
                {mode === "demo" ? "fixture mode" : "owner mode"}
              </span>
              <button
                className="result-new-button"
                type="button"
                disabled={ingest.isPending}
                onClick={() => {
                  reset();
                  setFeedback(null);
                }}
              >
                <RotateCcw className="result-new-icon" size={15} />
                <span>New interaction</span>
              </button>
            </div>
          </div>
          {mode === "demo" && catalog.isPending ? (
            <LoadingState label="Loading demo scenarios" />
          ) : null}
          {mode === "demo" && catalog.isError ? (
            <ErrorState
              error={catalog.error}
              onRetry={() => void catalog.refetch()}
            />
          ) : null}
          {mode === "demo" && catalog.data ? (
            <div className="scenario-picker">
              <label className="field-label" htmlFor="scenario-select">
                Demo fixture scenario
              </label>
              <div className="select-wrap">
                <select
                  id="scenario-select"
                  value={selectedScenario?.id || ""}
                  disabled={ingest.isPending}
                  onChange={(event) => {
                    const scenario = scenarios.find(
                      (item) => item.id === event.target.value,
                    );
                    if (scenario) selectScenario(scenario);
                  }}
                >
                  <option value="" disabled>
                    Select a demo fixture scenario
                  </option>
                  {scenarios.map((scenario) => (
                    <option value={scenario.id} key={scenario.id}>
                      {scenario.title}
                    </option>
                  ))}
                </select>
                <ChevronDown size={15} aria-hidden="true" />
              </div>
              {selectedScenario ? (
                <p className="field-hint">{selectedScenario.description}</p>
              ) : null}
            </div>
          ) : null}
          <label className="field-label" htmlFor="interaction-text">
            Interaction text
          </label>
          <textarea
            id="interaction-text"
            className="interaction-textarea"
            value={displayText}
            readOnly={mode === "demo" || ingest.isPending}
            aria-busy={ingest.isPending}
            onChange={(event) => setText(event.target.value)}
            placeholder={
              mode === "demo"
                ? "Choose a scenario…"
                : "Tell MemoryOS something that may matter later…"
            }
          />
          {mode === "demo" ? (
            <div className="editor-footnote">
              <Info size={14} />
              The public demo accepts only demo fixture scenario text. Fixture
              embeddings are labelled demo-fixture-v1.
            </div>
          ) : (
            <div className="editor-footnote">
              <Info size={14} />
              Live input is sent to the configured provider for preview or
              commit; preview never persists a memory.
            </div>
          )}
          <div className="editor-actions">
            <button
              className={`secondary-button ingestion-action-button${ingest.isPending && ingest.variables?.preview ? " processing" : ""}`}
              type="button"
              disabled={ingest.isPending}
              onClick={() => run(true)}
            >
              {ingest.isPending && ingest.variables?.preview ? (
                <LoaderCircle className="spin" size={14} />
              ) : (
                <Play className="ingestion-action-icon" size={14} />
              )}
              {ingest.isPending && ingest.variables?.preview
                ? "Analyzing…"
                : "Preview graph"}
            </button>
            <button
              className={`primary-button ingestion-action-button commit-memory-button${ingest.isPending && !ingest.variables?.preview ? " processing" : ""}`}
              type="button"
              disabled={ingest.isPending || !isOwner}
              onClick={() => run(false)}
            >
              {ingest.isPending && !ingest.variables?.preview ? (
                <LoaderCircle className="spin" size={14} />
              ) : (
                <Sparkles className="ingestion-action-icon" size={14} />
              )}
              {ingest.isPending && !ingest.variables?.preview
                ? "Committing…"
                : "Commit memory"}
            </button>
          </div>
          {!isOwner ? (
            <div className="owner-required-banner">
              <ShieldAlert size={14} />
              Preview is public. Add an owner token in{" "}
              <a href="/settings">Settings</a> to commit.
            </div>
          ) : null}
          {isOwner ? (
            <div className="idempotency-row">
              <label htmlFor="idempotency-key">Commit key</label>
              <input
                id="idempotency-key"
                value={idempotencyKey}
                onChange={(event) => setIdempotencyKey(event.target.value)}
              />
              <button
                className="icon-button"
                type="button"
                aria-label="Generate a new commit key"
                onClick={() => setIdempotencyKey(`memoryos-${Date.now()}`)}
              >
                <RotateCcw size={14} />
              </button>
            </div>
          ) : null}
        </section>

        <section className="trace-column" aria-live="polite">
          {ingest.isPending ? (
            <ProcessingCard preview={ingest.variables?.preview === true} />
          ) : null}
          {result ? (
            <IngestionResult result={result} />
          ) : (
            <div
              className={`panel trace-empty${ingest.isPending ? " is-hidden" : ""}`}
            >
              <Sparkles size={21} />
              <strong>Decision trace appears here</strong>
              <p>
                Preview an interaction to inspect candidates, relationships, and
                policy decisions without changing the database.
              </p>
            </div>
          )}
        </section>
      </div>
      {feedback ? (
        <IngestionToast
          feedback={feedback}
          onDismiss={() => setFeedback(null)}
        />
      ) : null}
    </div>
  );
}

const processingStages = [
  {
    label: "Analyzing interaction",
    detail: "Reading the submitted text",
    icon: Sparkles,
  },
  {
    label: "Extracting and screening",
    detail: "Checking evidence and future usefulness",
    icon: BrainCircuit,
  },
  {
    label: "Embedding admitted candidates",
    detail: "Rejected candidates bypass this step",
    icon: Layers3,
  },
  {
    label: "Comparing memory",
    detail: "Checking related history",
    icon: GitBranch,
  },
  {
    label: "Applying policy",
    detail: "Validating evidence and identity",
    icon: ShieldAlert,
  },
  {
    label: "Preparing result",
    detail: "Building the auditable response",
    icon: CheckCircle2,
  },
];

function ProcessingCard({ preview }: { preview: boolean }) {
  const [activeStep, setActiveStep] = useState(0);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const timer = window.setInterval(() => {
      setActiveStep((step) => (step + 1) % processingStages.length);
    }, 850);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="panel processing-card" role="status" aria-busy="true">
      <div className="processing-card-header">
        <div className="processing-orbit" aria-hidden="true">
          <svg viewBox="0 0 40 40">
            <circle
              className="processing-orbit-track"
              cx="20"
              cy="20"
              r="15.5"
              pathLength="100"
            />
            <circle
              className="processing-orbit-trail"
              cx="20"
              cy="20"
              r="15.5"
              pathLength="100"
            />
            <circle
              className="processing-orbit-lead"
              cx="20"
              cy="20"
              r="15.5"
              pathLength="100"
            />
          </svg>
        </div>
        <div>
          <span className="eyebrow">
            {preview
              ? "Preview · no database write"
              : "Commit · validated write"}
          </span>
          <h2>
            {preview ? "Analyzing interaction…" : "Saving memory decision…"}
          </h2>
        </div>
        <span className="processing-indicator">In progress</span>
      </div>
      <p className="processing-copy">
        {preview
          ? "MemoryOS is extracting candidates and comparing them with existing memory."
          : "MemoryOS is writing the validated decision and preserving its history."}
        <span>
          This activity trail is indeterminate until the synchronous response
          returns.
        </span>
      </p>
      <ol
        className="processing-pipeline"
        aria-label="Indeterminate processing activity"
      >
        {processingStages.map((stage, index) => {
          const Icon = stage.icon;
          const stageState =
            index === activeStep
              ? " current"
              : index < activeStep
                ? " completed"
                : "";
          return (
            <li
              className={`processing-stage${stageState}`}
              aria-current={index === activeStep ? "step" : undefined}
              key={stage.label}
            >
              <div className="processing-stage-marker">
                <Icon size={14} aria-hidden="true" />
              </div>
              <div>
                <strong>{stage.label}</strong>
                <small>{stage.detail}</small>
              </div>
              {index < processingStages.length - 1 ? (
                <span className="processing-connector" aria-hidden="true" />
              ) : null}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function IngestionToast({
  feedback,
  onDismiss,
}: {
  feedback: Feedback;
  onDismiss: () => void;
}) {
  const Icon =
    feedback.tone === "success"
      ? CheckCircle2
      : feedback.tone === "error"
        ? CircleAlert
        : Info;
  return (
    <div
      className={`ingestion-toast ${feedback.tone}`}
      role={feedback.tone === "error" ? "alert" : "status"}
      aria-live={feedback.tone === "error" ? "assertive" : "polite"}
    >
      <Icon size={17} aria-hidden="true" />
      <div className="ingestion-toast-copy">
        <strong>{feedback.title}</strong>
        <span>{feedback.message}</span>
        {feedback.detail ? (
          <details>
            <summary>Technical details</summary>
            <code>{feedback.detail}</code>
          </details>
        ) : null}
      </div>
      <button
        className="ingestion-toast-dismiss"
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss notification"
      >
        <X size={14} aria-hidden="true" />
      </button>
    </div>
  );
}

function feedbackForResult(
  result: IngestInteractionResponse,
  preview: boolean,
): Feedback {
  const actionable = result.decisions.filter((decision) =>
    [
      "created",
      "reinforced",
      "superseded",
      "disputed",
      "consolidated",
    ].includes(decision.decision_type),
  );
  if (preview) {
    if (actionable.length === 0) {
      if (
        result.decisions.some(
          (item) => item.reason_code === "pending_conflict_already_represented",
        )
      ) {
        return {
          title: "Already in Memory Review",
          message:
            "This information is part of an unresolved conflict. No database changes were made.",
          tone: "info",
        };
      }
      return {
        title: "Analysis complete",
        message:
          "No memory change was recommended. No database changes were made.",
        tone: "info",
      };
    }
    const count = actionable.length;
    return {
      title: "Analysis complete",
      message: `${count} memory decision${count === 1 ? "" : "s"} recommended. No database changes were made.`,
      tone: "info",
    };
  }
  const created = result.decisions.filter(
    (item) => item.decision_type === "created",
  ).length;
  const reinforced = result.decisions.filter(
    (item) => item.decision_type === "reinforced",
  ).length;
  const superseded = result.decisions.filter(
    (item) => item.decision_type === "superseded",
  ).length;
  const disputed = result.decisions.filter(
    (item) => item.decision_type === "disputed",
  ).length;
  if (created > 0) {
    return {
      title: `${created} memor${created === 1 ? "y" : "ies"} added`,
      message:
        "The interaction was recorded and the approved decision is now available in Memory Explorer.",
      tone: "success",
    };
  }
  if (reinforced > 0) {
    return {
      title: `${reinforced} memor${reinforced === 1 ? "y" : "ies"} reinforced`,
      message: `The interaction was recorded and ${reinforced === 1 ? "the existing memory was" : "the existing memories were"} confirmed.`,
      tone: "success",
    };
  }
  if (superseded > 0) {
    return {
      title: "Memory updated",
      message:
        "The interaction was recorded and a newer memory version replaced the older one, with history preserved.",
      tone: "success",
    };
  }
  if (disputed > 0) {
    return {
      title: "Review required",
      message:
        "The interaction was recorded, but the conflict was sent to Memory Review because the evidence was ambiguous.",
      tone: "success",
    };
  }
  return {
    title: "No memory change",
    message:
      "The interaction was recorded, but policy safely left long-term memory unchanged.",
    tone: "info",
  };
}

function humanSummaryForResult(result: IngestInteractionResponse) {
  const actionable = result.decisions.filter((decision) =>
    [
      "created",
      "reinforced",
      "superseded",
      "disputed",
      "consolidated",
    ].includes(decision.decision_type),
  );
  if (result.status === "preview") {
    if (actionable.length === 0) {
      if (
        result.decisions.some(
          (item) => item.reason_code === "pending_conflict_already_represented",
        )
      ) {
        return {
          headline: "Already in Memory Review",
          detail:
            "This information is part of an unresolved conflict. Preview made no database changes.",
        };
      }
      return {
        headline: "Nothing worth remembering",
        detail: result.trace.steps.some((step) => step.node === "embed")
          ? "No safe memory change is recommended. Preview made no database changes."
          : "Rejected before embedding. Preview made no database changes.",
      };
    }
    const action = humanAction(actionable[0].decision_type);
    const onlyReinforcement = actionable.every(
      (item) => item.decision_type === "reinforced",
    );
    return {
      headline: onlyReinforcement
        ? "Already represented in memory"
        : `${actionable.length} candidate${actionable.length === 1 ? "" : "s"} admitted`,
      detail: onlyReinforcement
        ? "This interaction can reinforce existing memory without creating a duplicate. Nothing was written."
        : `Proposed action: ${action}. Preview made no database changes.`,
    };
  }
  if (actionable.length === 0) {
    return {
      headline: "No memory changes were necessary",
      detail:
        "The interaction was processed and the existing memory set stayed the same.",
    };
  }
  return {
    headline: humanCommitHeadline(
      actionable.map((decision) => decision.decision_type),
    ),
    detail:
      "MemoryOS saved the validated decision and preserved its audit trail.",
  };
}

function humanAction(decisionType: string) {
  return (
    {
      created: "Create a new memory",
      consolidated:
        "Consolidate equivalent memories and preserve their sources",
      reinforced: "Reinforce an existing memory",
      superseded: "Replace an older memory version",
      disputed: "Send the conflict to Memory Review",
    }[decisionType] || "Review the policy decision"
  );
}

function humanCommitHeadline(decisionTypes: string[]) {
  if (decisionTypes.includes("consolidated"))
    return "Equivalent memories consolidated";
  if (decisionTypes.includes("disputed") && decisionTypes.length === 1) {
    return "Conflict sent to Memory Review";
  }
  if (decisionTypes.includes("created")) return "New memory saved";
  if (decisionTypes.includes("reinforced")) return "Existing memory reinforced";
  if (decisionTypes.includes("superseded"))
    return "Memory updated with a newer version";
  return "Interaction processed";
}

function admissionOutcome(decision: IngestDecision | undefined) {
  if (!decision)
    return {
      label: "Rejected",
      tone: "rejected",
      reason: "No validated decision is available.",
    };
  switch (decision.decision_type) {
    case "consolidated":
      return {
        label: "Consolidates",
        tone: "accepted",
        reason: decision.reason_summary,
      };
    case "created":
      return {
        label:
          decision.reason_code === "contextual_coexistence"
            ? "Coexists"
            : "New memory",
        tone: "accepted",
        reason: decision.reason_summary,
      };
    case "reinforced":
      return {
        label: "Reinforcement",
        tone: "reinforced",
        reason: decision.reason_summary,
      };
    case "superseded":
      return {
        label: "Supersedes",
        tone: "accepted",
        reason: decision.reason_summary,
      };
    case "disputed":
      return {
        label: "Needs review",
        tone: "review",
        reason: decision.reason_summary,
      };
    default:
      return {
        label:
          decision.reason_code === "pending_conflict_already_represented"
            ? "Needs review"
            : "Rejected",
        tone:
          decision.reason_code === "pending_conflict_already_represented"
            ? "review"
            : "rejected",
        reason: decision.reason_summary,
      };
  }
}

function IngestionResult({ result }: { result: IngestInteractionResponse }) {
  const summary = humanSummaryForResult(result);
  const hasStoredMemory =
    result.status === "completed" && result.memory_ids.length > 0;
  const needsReview =
    result.status === "completed" &&
    result.decisions.some((decision) => decision.decision_type === "disputed");
  const completionTone = resultCompletionTone(result);
  return (
    <div className={`trace-stack result-enter result-tone-${completionTone}`}>
      <div className="panel result-summary">
        <div className="result-summary-top">
          <div className="result-summary-heading">
            <ResultStatusGlyph tone={completionTone} />
            <div>
              <span className="eyebrow">
                {result.status === "preview"
                  ? "Preview result"
                  : "Committed result"}
              </span>
              <h2>{summary.headline}</h2>
              <p className="result-summary-detail">{summary.detail}</p>
            </div>
          </div>
          <span
            className={`status-badge ${
              completionTone === "success"
                ? "active"
                : completionTone === "review"
                  ? "disputed"
                  : completionTone === "preview"
                    ? "preview"
                    : ""
            }`}
          >
            {result.mode}
          </span>
        </div>
        {hasStoredMemory || needsReview ? (
          <div className="result-summary-actions">
            {hasStoredMemory ? (
              <Link className="text-link" href="/memories">
                View in Memory Explorer <ArrowRight size={14} />
              </Link>
            ) : null}
            {needsReview ? (
              <Link className="text-link" href="/review">
                Open Memory Review <ArrowRight size={14} />
              </Link>
            ) : null}
          </div>
        ) : null}
        {result.warnings.map((warning) => (
          <div className="result-warning" key={warning}>
            <ShieldAlert size={14} />
            {warning}
          </div>
        ))}
      </div>
      <div className="panel candidates-panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Extracted information</span>
            <h2>Memory decisions</h2>
          </div>
        </div>
        <div className="candidate-list">
          {result.candidates.length ? (
            result.candidates.map((candidate) => {
              const decision = result.decisions.find(
                (item) => item.candidate_id === candidate.candidate_id,
              );
              const outcome = admissionOutcome(decision);
              const relation = result.relation_assessments.find(
                (item) => item.candidate_id === candidate.candidate_id,
              );
              const showEvidence =
                candidate.evidence_excerpt.trim().toLowerCase() !==
                candidate.content.trim().toLowerCase();
              return (
                <div className="candidate-card" key={candidate.candidate_id}>
                  <div className="candidate-card-top">
                    {!candidate.admission ||
                    candidate.admission.content_kind === "information" ? (
                      <TypeBadge type={candidate.memory_type} />
                    ) : null}
                    <span className={`candidate-admission ${outcome.tone}`}>
                      {outcome.label}
                    </span>
                  </div>
                  <strong>{candidate.content}</strong>
                  <p className="candidate-decision-reason">{outcome.reason}</p>
                  {showEvidence ? (
                    <p className="candidate-evidence">
                      “{candidate.evidence_excerpt}”
                    </p>
                  ) : null}
                  <details className="candidate-policy-details">
                    <summary>Policy details</summary>
                    <div className="candidate-scores">
                      <span>
                        Importance <b>{candidate.importance.toFixed(2)}</b>
                      </span>
                      <span>
                        Confidence <b>{candidate.confidence.toFixed(2)}</b>
                      </span>
                    </div>
                    {candidate.admission ? (
                      <p className="candidate-policy-signals">
                        {[
                          `Durability: ${candidate.admission.durability}`,
                          `Future use: ${candidate.admission.future_value.replaceAll("_", " ")}`,
                          `Specificity: ${candidate.admission.specificity}`,
                          `Evidence: ${candidate.admission.evidence_source}`,
                        ].join(" · ")}
                      </p>
                    ) : null}
                    {relation ? (
                      <>
                        <p className="candidate-policy-signals">
                          Proposed: {relation.relation} · Values:{" "}
                          {relation.value_comparison} · Relation confidence:{" "}
                          {relation.confidence.toFixed(2)}
                        </p>
                        {relation.related_memory_id ? (
                          <Link
                            href={`/memories/${relation.related_memory_id}`}
                          >
                            Inspect related memory <ArrowRight size={11} />
                          </Link>
                        ) : null}
                        {relation.replacement_evidence ? (
                          <p className="candidate-policy-signals">
                            Replacement evidence: “
                            {relation.replacement_evidence}”
                          </p>
                        ) : null}
                      </>
                    ) : null}
                    {decision?.canonical_content ? (
                      <p className="candidate-policy-signals">
                        Canonical statement: “{decision.canonical_content}”
                      </p>
                    ) : null}
                    {decision?.source_memory_ids?.length ? (
                      <p className="candidate-policy-signals">
                        Preserved sources:{" "}
                        {decision.source_memory_ids.map((id, index) => (
                          <Link key={id} href={`/memories/${id}`}>
                            {" "}
                            {index + 1}{" "}
                          </Link>
                        ))}
                      </p>
                    ) : null}
                    {decision?.consolidation_note ? (
                      <p className="candidate-policy-signals">
                        {decision.consolidation_note}
                      </p>
                    ) : null}
                    {decision && decision.reason_summary !== outcome.reason ? (
                      <p className="candidate-policy-signals">
                        {decision.reason_summary}
                      </p>
                    ) : null}
                    <code>{decision?.reason_code || "decision_missing"}</code>
                  </details>
                </div>
              );
            })
          ) : (
            <div className="empty-panel">
              <span className="candidate-admission rejected">Rejected</span>
              <p>
                {result.decisions[0]?.reason_summary ||
                  "No supported durable information was extracted."}
              </p>
            </div>
          )}
        </div>
      </div>
      <details className="panel graph-trace ingestion-execution-details">
        <summary>
          Execution details <span>{result.trace.policy_version}</span>
        </summary>
        <div className="trace-timeline">
          {result.trace.steps.map((step, index) => (
            <div className="trace-timeline-item" key={step.node}>
              <div className="trace-step">
                <span className="trace-step-dot" />
                <div>
                  <strong>{traceLabel(step.node)}</strong>
                  <small>{formatDuration(step.duration_ms)}</small>
                </div>
              </div>
              {index < result.trace.steps.length - 1 ? (
                <span className="trace-connector" aria-hidden="true" />
              ) : null}
            </div>
          ))}
        </div>
      </details>
    </div>
  );
}

function resultCompletionTone(
  result: IngestInteractionResponse,
): "success" | "preview" | "review" | "neutral" {
  if (result.status === "preview") return "preview";
  if (
    result.decisions.some((decision) =>
      ["created", "reinforced", "superseded", "consolidated"].includes(
        decision.decision_type,
      ),
    )
  ) {
    return "success";
  }
  if (
    result.decisions.some((decision) => decision.decision_type === "disputed")
  ) {
    return "review";
  }
  return "neutral";
}

function ResultStatusGlyph({
  tone,
}: {
  tone: "success" | "preview" | "review" | "neutral";
}) {
  const Icon =
    tone === "success"
      ? Check
      : tone === "review"
        ? ShieldAlert
        : tone === "preview"
          ? Info
          : Minus;
  return (
    <span className={`result-status-glyph ${tone}`} aria-hidden="true">
      <Icon size={16} strokeWidth={2.1} />
    </span>
  );
}

function traceLabel(node: string) {
  return (
    {
      extract: "Extract & screen",
      embed: "Embed",
      find_related: "Find related",
      assess_relations: "Assess",
      validate_plan: "Validate",
      persist: "Persist",
    }[node] || node
  );
}

function formatDuration(duration: number) {
  if (duration < 1) return "<1ms";
  if (duration < 1000) return `${Math.round(duration)}ms`;
  return `${(duration / 1000).toFixed(1)}s`;
}
