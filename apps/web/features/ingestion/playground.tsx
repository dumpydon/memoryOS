"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type QueryKey,
} from "@tanstack/react-query";
import {
  ArrowRight,
  ArrowUpRight,
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
import { TypeBadge } from "@/components/type-badge";
import { useWorkspace } from "@/components/workspace-context";
import { ApiClientError } from "@/lib/api/client";
import {
  getCapabilities,
  getDemoCatalog,
  postInteraction,
} from "@/lib/api/queries";
import type { DemoScenario, IngestInteractionResponse } from "@/lib/api/types";

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
  const [text, setText] = useState("");
  const [result, setResult] = useState<IngestInteractionResponse | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const feedbackTimer = useRef<number | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState(
    () => `memoryos-${Date.now()}`,
  );

  useEffect(
    () => () => {
      if (feedbackTimer.current !== null) {
        window.clearTimeout(feedbackTimer.current);
      }
    },
    [],
  );

  function showFeedback(next: Feedback, duration = 5_500) {
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
  const selectedScenario = useMemo(
    () =>
      scenarioId
        ? scenarios.find((scenario) => scenario.id === scenarioId)
        : scenarios[0],
    [scenarioId, scenarios],
  );
  const displayText = mode === "demo" ? selectedScenario?.text || "" : text;
  const liveUnavailable =
    mode === "live" &&
    capabilities.data &&
    !capabilities.data.live_ingestion_available;

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
        refreshIngestionCaches(queryClient, response, scopeId, mode);
      }
      return response;
    },
    onSuccess: (response, variables) => {
      setResult(response);
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
    setResult(null);
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
    setResult(null);
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
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Input</span>
              <h2>Choose an interaction</h2>
            </div>
            <span className="provider-label">
              <FlaskConical size={13} />
              {mode === "demo" ? "fixture mode" : "owner mode"}
            </span>
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
          {selectedScenario ? (
            <div className="expected-outcome">
              <span className="eyebrow">Expected policy outcome</span>
              <p>{selectedScenario.expected_outcome}</p>
            </div>
          ) : null}
          <div className="editor-actions">
            <button
              className={`secondary-button${ingest.isPending && ingest.variables?.preview ? " processing" : ""}`}
              type="button"
              disabled={ingest.isPending}
              onClick={() => run(true)}
            >
              {ingest.isPending && ingest.variables?.preview ? (
                <LoaderCircle className="spin" size={14} />
              ) : (
                <Play size={14} />
              )}
              {ingest.isPending && ingest.variables?.preview
                ? "Analyzing…"
                : "Preview graph"}
            </button>
            <button
              className={`primary-button${ingest.isPending && !ingest.variables?.preview ? " processing" : ""}`}
              type="button"
              disabled={ingest.isPending || !isOwner}
              onClick={() => run(false)}
            >
              {ingest.isPending && !ingest.variables?.preview ? (
                <LoaderCircle className="spin" size={14} />
              ) : (
                <Sparkles size={14} />
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
            <IngestionResult
              result={result}
              onNewInteraction={() => {
                setResult(null);
                setFeedback(null);
                setText("");
                setIdempotencyKey(`memoryos-${Date.now()}`);
              }}
            />
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

function refreshIngestionCaches(
  queryClient: QueryClient,
  response: IngestInteractionResponse,
  scopeId: string,
  mode: IngestInteractionResponse["mode"],
) {
  const affectedMemoryIds = new Set(
    response.memory_ids.map((memoryId) => String(memoryId)),
  );
  response.decisions.forEach((decision) => {
    if (decision.memory_id) affectedMemoryIds.add(String(decision.memory_id));
    if (decision.related_memory_id) {
      affectedMemoryIds.add(String(decision.related_memory_id));
    }
  });

  const staleKeys: QueryKey[] = [
    ["memories"],
    ["review-memory-pool", scopeId, mode],
  ];
  affectedMemoryIds.forEach((memoryId) => {
    staleKeys.push(
      ["memory", scopeId, memoryId],
      ["memory-history", scopeId, memoryId],
    );
  });
  const hasReviewImpact = response.decisions.some(
    (decision) => decision.decision_type === "disputed",
  );
  if (hasReviewImpact) {
    staleKeys.push(["reviews", scopeId, mode]);
  }

  for (const queryKey of staleKeys) {
    void queryClient.invalidateQueries({ queryKey, refetchType: "none" });
  }
  void queryClient.invalidateQueries({
    queryKey: ["overview", scopeId, mode],
    refetchType: "active",
  });
}

const processingStages = [
  {
    label: "Analyzing interaction",
    detail: "Reading the submitted text",
    icon: Sparkles,
  },
  {
    label: "Extracting candidates",
    detail: "Finding atomic memory signals",
    icon: BrainCircuit,
  },
  {
    label: "Embedding candidates",
    detail: "Preparing semantic vectors",
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
        <div className="processing-icon">
          <LoaderCircle className="spin" size={18} aria-hidden="true" />
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
          return (
            <li
              className={`processing-stage${index === activeStep ? " current" : ""}`}
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
    ["created", "reinforced", "superseded", "disputed"].includes(
      decision.decision_type,
    ),
  );
  if (preview) {
    if (actionable.length === 0) {
      return {
        title: "Analysis complete",
        message:
          "No memory change was recommended. No database changes were made.",
        tone: "info",
      };
    }
    const count = result.candidates.filter(
      (candidate) => candidate.worth_remembering,
    ).length;
    return {
      title: "Analysis complete",
      message: `MemoryOS found ${count || actionable.length} potential memor${count === 1 ? "y" : "ies"}. No database changes were made.`,
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
    ["created", "reinforced", "superseded", "disputed"].includes(
      decision.decision_type,
    ),
  );
  if (result.status === "preview") {
    if (actionable.length === 0) {
      return {
        headline: "No memory change recommended",
        detail:
          "MemoryOS found no supported durable signal strong enough to change the current memory set.",
      };
    }
    const action = humanAction(actionable[0].decision_type);
    return {
      headline: `MemoryOS found ${actionable.length} potential memor${actionable.length === 1 ? "y" : "ies"}`,
      detail: `Proposed action: ${action}. Preview is complete and nothing was written to the database.`,
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
      reinforced: "Reinforce an existing memory",
      superseded: "Replace an older memory version",
      disputed: "Send the conflict to Memory Review",
    }[decisionType] || "Review the policy decision"
  );
}

function humanCommitHeadline(decisionTypes: string[]) {
  if (decisionTypes.includes("disputed") && decisionTypes.length === 1) {
    return "Conflict sent to Memory Review";
  }
  if (decisionTypes.includes("created")) return "New memory saved";
  if (decisionTypes.includes("reinforced")) return "Existing memory reinforced";
  if (decisionTypes.includes("superseded"))
    return "Memory updated with a newer version";
  return "Interaction processed";
}

function IngestionResult({
  result,
  onNewInteraction,
}: {
  result: IngestInteractionResponse;
  onNewInteraction: () => void;
}) {
  const summary = humanSummaryForResult(result);
  const hasStoredMemory =
    result.status === "completed" && result.memory_ids.length > 0;
  const needsReview =
    result.status === "completed" &&
    result.decisions.some((decision) => decision.decision_type === "disputed");
  return (
    <div className="trace-stack result-enter">
      <div className="panel result-summary">
        <div className="result-summary-top">
          <div>
            <span className="eyebrow">
              {result.status === "preview"
                ? "Preview result"
                : "Committed result"}
            </span>
            <h2>{summary.headline}</h2>
            <p className="result-summary-detail">{summary.detail}</p>
          </div>
          <span className="status-badge active">{result.mode}</span>
        </div>
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
          <button
            className="result-new-button"
            type="button"
            onClick={onNewInteraction}
          >
            <RotateCcw size={13} /> New interaction
          </button>
        </div>
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
            <span className="eyebrow">Structured extraction</span>
            <h2>Candidates</h2>
          </div>
        </div>
        <div className="candidate-list">
          {result.candidates.length ? (
            result.candidates.map((candidate) => (
              <div className="candidate-card" key={candidate.candidate_id}>
                <div className="candidate-card-top">
                  <TypeBadge type={candidate.memory_type} />
                  <span className="candidate-confidence">
                    confidence {candidate.confidence.toFixed(2)}
                  </span>
                </div>
                <strong>{candidate.content}</strong>
                <p>“{candidate.evidence_excerpt}”</p>
                <div className="candidate-scores">
                  <span>
                    importance <b>{candidate.importance.toFixed(2)}</b>
                  </span>
                  <span>
                    {candidate.worth_remembering
                      ? "eligible to remember"
                      : candidate.skip_reason || "skipped"}
                  </span>
                </div>
              </div>
            ))
          ) : (
            <div className="empty-panel">
              No memory candidates were extracted.
            </div>
          )}
        </div>
      </div>
      <div className="panel decisions-panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Policy decisions</span>
            <h2>What changed</h2>
          </div>
        </div>
        <div className="decision-list">
          {result.decisions.length ? (
            result.decisions.map((decision, index) => (
              <div
                className="decision-row"
                key={`${decision.candidate_id}-${index}`}
              >
                <span className={`decision-icon ${decision.decision_type}`}>
                  <DecisionIcon type={decision.decision_type} />
                </span>
                <div>
                  <strong>{decision.decision_type}</strong>
                  <p>{decision.reason_summary}</p>
                </div>
              </div>
            ))
          ) : (
            <div className="empty-panel">
              No persistence decision was necessary.
            </div>
          )}
        </div>
      </div>
      <div className="panel graph-trace">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Execution trace</span>
            <h2>{result.trace.policy_version}</h2>
          </div>
        </div>
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
      </div>
    </div>
  );
}

function DecisionIcon({ type }: { type: string }) {
  if (type === "reinforced") return <GitBranch size={13} />;
  if (type === "superseded") return <ArrowUpRight size={13} />;
  if (type === "disputed") return <ShieldAlert size={13} />;
  if (type === "skipped" || type === "rejected") return <Minus size={13} />;
  return <Check size={13} />;
}

function traceLabel(node: string) {
  return (
    {
      extract: "Extract",
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
