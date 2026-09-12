"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  ChevronDown,
  Clock3,
  FlaskConical,
  Info,
  Play,
  RotateCcw,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import {
  ErrorState,
  InlineNotice,
  LoadingState,
} from "@/components/status-state";
import { TypeBadge } from "@/components/type-badge";
import { useWorkspace } from "@/components/workspace-context";
import {
  getCapabilities,
  getDemoCatalog,
  postInteraction,
} from "@/lib/api/queries";
import type { DemoScenario, IngestInteractionResponse } from "@/lib/api/types";

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
  const [notice, setNotice] = useState<{
    message: string;
    tone: "warning" | "info" | "success";
  } | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState(
    () => `memoryos-${Date.now()}`,
  );

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
    mutationFn: ({ preview }: { preview: boolean }) =>
      postInteraction(
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
      ),
    onSuccess: (response, variables) => {
      setResult(response);
      setNotice({
        message: variables.preview
          ? "Preview complete. No memory was changed."
          : "Interaction committed. The explorer will refresh from the API.",
        tone: variables.preview ? "info" : "success",
      });
      if (!variables.preview) {
        void queryClient.invalidateQueries({ queryKey: ["overview"] });
        void queryClient.invalidateQueries({ queryKey: ["memories"] });
      }
    },
    onError: (error) =>
      setNotice({
        message:
          error instanceof Error
            ? error.message
            : "The ingestion request failed.",
        tone: "warning",
      }),
  });

  function selectScenario(scenario: DemoScenario) {
    setResult(null);
    setNotice(null);
    setIdempotencyKey(`memoryos-${scenario.id}-${Date.now()}`);
    router.replace(`/ingestion?scenario=${encodeURIComponent(scenario.id)}`, {
      scroll: false,
    });
  }

  function run(preview: boolean) {
    setNotice(null);
    if (!displayText.trim())
      return setNotice({
        message: "Add an interaction before running the graph.",
        tone: "warning",
      });
    if (mode === "demo" && !selectedScenario)
      return setNotice({
        message:
          "Public demo mode only accepts a catalog scenario. Choose one from the picker.",
        tone: "warning",
      });
    if (!preview && !isOwner)
      return setNotice({
        message:
          "An owner token is required to commit a mutation. Preview is available publicly.",
        tone: "warning",
      });
    if (mode === "live" && !isOwner)
      return setNotice({
        message: "Live ingestion requires an owner token. Add one in Settings.",
        tone: "warning",
      });
    if (mode === "live" && capabilities.data?.live_ingestion_available !== true)
      return setNotice({
        message:
          capabilities.data?.reason ||
          (capabilities.isPending
            ? "Checking live provider readiness. Try again in a moment."
            : "Live ingestion is unavailable until OPENAI_API_KEY is configured on the API server."),
        tone: "warning",
      });
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
          Live ingestion is unavailable because the API server has no OpenAI
          key configured. Add <code>OPENAI_API_KEY</code> to the API
          environment, then refresh this page. Demo mode remains available.
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
            readOnly={mode === "demo"}
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
              className="secondary-button"
              type="button"
              disabled={ingest.isPending}
              onClick={() => run(true)}
            >
              <Play size={14} />
              {ingest.isPending ? "Running graph…" : "Preview graph"}
            </button>
            <button
              className="primary-button"
              type="button"
              disabled={ingest.isPending || !isOwner}
              onClick={() => run(false)}
            >
              <Sparkles size={14} />
              Commit memory
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

        <section className="trace-column">
          {notice ? (
            <InlineNotice tone={notice.tone}>
              {notice.tone === "success" ? (
                <Check size={15} />
              ) : (
                <Info size={15} />
              )}
              {notice.message}
            </InlineNotice>
          ) : null}
          {ingest.isPending ? (
            <div className="panel waiting-card">
              <Clock3 size={18} />
              <div>
                <strong>Waiting for the API</strong>
                <p>
                  The graph is synchronous; this view will show the trace when
                  the request completes.
                </p>
              </div>
            </div>
          ) : null}
          {result ? (
            <IngestionResult result={result} />
          ) : (
            <div className="panel trace-empty">
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
    </div>
  );
}

function IngestionResult({ result }: { result: IngestInteractionResponse }) {
  return (
    <div className="trace-stack">
      <div className="panel result-summary">
        <div className="result-summary-top">
          <div>
            <span className="eyebrow">
              {result.status === "preview"
                ? "Preview result"
                : "Committed result"}
            </span>
            <h2>
              {result.candidates.length} candidate
              {result.candidates.length === 1 ? "" : "s"} ·{" "}
              {result.decisions.length} decision
              {result.decisions.length === 1 ? "" : "s"}
            </h2>
          </div>
          <span className="status-badge active">{result.mode}</span>
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
                  <Check size={13} />
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
        <div className="trace-steps">
          {result.trace.steps.map((step) => (
            <div className="trace-step" key={step.node}>
              <span className="trace-step-dot" />
              <strong>{step.node}</strong>
              <small>{Math.round(step.duration_ms)}ms</small>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
