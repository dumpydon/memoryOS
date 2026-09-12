"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  ChevronDown,
  FlaskConical,
  GitBranch,
  Info,
  Search,
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
  postRecallCompare,
} from "@/lib/api/queries";
import type {
  RecallComparisonItem,
  RecallComparisonResponse,
} from "@/lib/api/types";

export function RecallLab() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { scopeId, mode, token, isOwner } = useWorkspace();
  const catalog = useQuery({
    queryKey: ["demo-catalog", "recall"],
    queryFn: () => getDemoCatalog(token),
  });
  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: () => getCapabilities(token),
  });
  const activeQuery = searchParams.get("q") || "";
  const [draftQuery, setDraftQuery] = useState(activeQuery);
  const knownQuery = useMemo(
    () => catalog.data?.queries.find((item) => item.query === activeQuery),
    [activeQuery, catalog.data],
  );
  const allowedQuery =
    mode === "live"
      ? isOwner &&
        Boolean(activeQuery.trim()) &&
        capabilities.data?.live_recall_available === true
      : Boolean(knownQuery);
  const liveUnavailable =
    mode === "live" &&
    capabilities.data &&
    !capabilities.data.live_recall_available;
  const comparison = useQuery({
    queryKey: ["recall-compare", scopeId, mode, activeQuery],
    queryFn: () =>
      postRecallCompare(
        { scope_id: scopeId, query: activeQuery, limit: 5, mode },
        token,
      ),
    enabled: allowedQuery,
  });

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next = draftQuery.trim();
    router.replace(next ? `/recall?q=${encodeURIComponent(next)}` : "/recall", {
      scroll: false,
    });
  }

  return (
    <div className="page-wrap recall-page">
      <header className="page-header">
        <div>
          <div className="breadcrumb">
            <span>Workspace</span>
            <span>/</span>
            <strong>Recall lab</strong>
          </div>
          <h1>Recall Lab</h1>
          <p className="page-subtitle">
            Compare naive vector similarity with MemoryOS ranking on the same
            query and memory snapshot.
          </p>
        </div>
        <div className="header-actions">
          <span className="demo-pill">
            <span className="status-dot" />
            {mode === "demo" ? "Demo fixture queries" : "Live recall"}
          </span>
        </div>
      </header>

      {liveUnavailable ? (
        <InlineNotice tone="warning">
          <ShieldAlert size={15} />
          Live recall is unavailable because the API server has no OpenAI key
          configured. Add <code>OPENAI_API_KEY</code> to the API environment,
          then refresh this page. Demo queries remain available.
        </InlineNotice>
      ) : null}

      <section className="panel recall-query-panel">
        <div className="query-heading">
          <div className="lab-icon">
            <FlaskConical size={18} />
          </div>
          <div>
            <span className="eyebrow">Retrieval experiment</span>
            <h2>What should MemoryOS remember?</h2>
          </div>
        </div>
        <form className="recall-query-form" onSubmit={submit}>
          <div className="search-field">
            <Search size={16} aria-hidden="true" />
            <input
              value={draftQuery}
              onChange={(event) => setDraftQuery(event.target.value)}
              placeholder="Ask about a project, preference, or procedure"
              aria-label="Recall query"
            />
            <button className="search-submit" type="submit">
              Run comparison <ArrowRight size={14} />
            </button>
          </div>
        </form>
        {mode === "demo" && catalog.data ? (
          <div className="query-presets">
            <span className="toolbar-label">Try a preset</span>
            {catalog.data.queries.map((query) => (
              <button
                type="button"
                className={`query-preset ${activeQuery === query.query ? "selected" : ""}`}
                key={query.id}
                onClick={() => {
                  setDraftQuery(query.query);
                  router.replace(
                    `/recall?q=${encodeURIComponent(query.query)}`,
                    { scroll: false },
                  );
                }}
              >
                {query.title}
                <ChevronDown size={12} />
              </button>
            ))}
          </div>
        ) : null}
      </section>

      {mode === "demo" && activeQuery && !knownQuery ? (
        <InlineNotice tone="warning">
          <ShieldAlert size={15} />
          This public demo only runs catalog queries. Choose a preset above;
          arbitrary recall requires Live mode with an owner token.
        </InlineNotice>
      ) : null}
      {mode === "live" && !isOwner ? (
        <InlineNotice tone="warning">
          <ShieldAlert size={15} />
          Live recall requires an owner token. Add one in Settings before
          running arbitrary queries.
        </InlineNotice>
      ) : null}
      {mode === "live" && isOwner && liveUnavailable && activeQuery ? (
        <InlineNotice tone="info">
          <Info size={15} />
          Your query is ready, but MemoryOS will not send it to a provider until
          the API reports live recall as configured.
        </InlineNotice>
      ) : null}
      {mode === "live" && isOwner && !capabilities.data && capabilities.isPending ? (
        <LoadingState label="Checking live provider readiness" />
      ) : null}
      {allowedQuery && comparison.isPending ? (
        <LoadingState label="Scoring the same memory snapshot" />
      ) : null}
      {comparison.isError ? (
        <ErrorState
          error={comparison.error}
          onRetry={() => void comparison.refetch()}
        />
      ) : null}
      {comparison.data ? <ComparisonResults data={comparison.data} /> : null}
      {!activeQuery ? (
        <div className="panel recall-empty">
          <Sparkles size={22} />
          <strong>Pick a query to see rank movement</strong>
          <p>
            MemoryOS exposes every score component so the difference is
            inspectable, not a black box.
          </p>
        </div>
      ) : null}
    </div>
  );
}

function ComparisonResults({ data }: { data: RecallComparisonResponse }) {
  return (
    <div className="recall-results">
      <div className="comparison-meta">
        <div>
          <span className="eyebrow">Same-snapshot comparison</span>
          <strong>“{data.query}”</strong>
        </div>
        <span>
          Evaluated {formatDateTime(data.evaluated_at)} · {data.candidate_count}{" "}
          eligible memories · policy {data.policy_version}
        </span>
      </div>
      <div className="comparison-grid">
        <RankColumn
          title="Naive vector retrieval"
          subtitle="Sorted by cosine similarity only"
          items={data.naive}
          kind="naive"
        />
        <RankColumn
          title="MemoryOS ranking"
          subtitle="Similarity + importance + recency + reinforcement + confidence"
          items={data.memoryos}
          kind="memoryos"
        />
      </div>
      <RankChangeSummary data={data} />
      <div className="lab-note">
        <Info size={14} />
        <span>
          Both columns use the same query embedding, eligibility rules,
          relevance floor, and evaluation time. MemoryOS receives no extra
          candidates.
        </span>
      </div>
    </div>
  );
}

function RankChangeSummary({ data }: { data: RecallComparisonResponse }) {
  const moved = data.memoryos
    .filter((item) => item.rank_delta !== null && item.rank_delta !== 0)
    .sort((left, right) => Math.abs(right.rank_delta || 0) - Math.abs(left.rank_delta || 0));
  const lead = moved[0];
  return (
    <div className="rank-change-summary">
      <div className="rank-change-summary-icon">
        <GitBranch size={15} aria-hidden="true" />
      </div>
      <div>
        <strong>Why ranks move</strong>
        <p>
          {lead
            ? lead.explanation ||
              `${lead.memory.content} moved ${formatMovement(lead.rank_delta)} because MemoryOS combines similarity with importance, recency, reinforcement, and confidence.`
            : "MemoryOS applies the same score components to every eligible memory, so rank changes are inspectable."}
        </p>
      </div>
    </div>
  );
}

function RankColumn({
  title,
  subtitle,
  items,
  kind,
}: {
  title: string;
  subtitle: string;
  items: RecallComparisonItem[];
  kind: "naive" | "memoryos";
}) {
  return (
    <article className={`panel rank-column ${kind}`}>
      <div className="rank-column-heading">
        <div>
          <h2>{title}</h2>
          <p>{subtitle}</p>
        </div>
        <span className="rank-count">{items.length} results</span>
      </div>
      {items.length ? (
        <div className="rank-list">
          {items.map((item) => (
            <RankCard item={item} kind={kind} key={item.memory.id} />
          ))}
        </div>
      ) : (
        <div className="empty-panel">Nothing passed the relevance floor.</div>
      )}
    </article>
  );
}

function RankCard({
  item,
  kind,
}: {
  item: RecallComparisonItem;
  kind: "naive" | "memoryos";
}) {
  const rank = kind === "naive" ? item.naive_rank : item.memoryos_rank;
  return (
    <details className="rank-card">
      <summary>
        <span className="rank-number">{rank ?? "—"}</span>
        <div className="rank-copy">
          <div>
            <TypeBadge type={item.memory.memory_type} />
            <span className="rank-status">{item.memory.status}</span>
          </div>
          <strong>{item.memory.content}</strong>
          <small>
            {kind === "naive"
              ? `similarity ${item.naive_similarity.toFixed(3)}`
              : item.memoryos_score.total.toFixed(3)}{" "}
            · {item.memory.reinforcement_count} reinforcements
          </small>
          <small className="rank-card-explanation">
            {item.explanation ||
              (kind === "naive"
                ? "Baseline uses semantic similarity only."
                : "MemoryOS blends similarity with importance, recency, reinforcement, and confidence.")}
          </small>
        </div>
        <span className={`rank-movement ${movementTone(item.rank_delta)}`}>
          {formatMovement(item.rank_delta)}
        </span>
      </summary>
      <div className="score-breakdown">
        {kind === "memoryos" ? (
          <>
            <ScoreBar
              label="Similarity"
              value={item.memoryos_score.similarity}
              contribution={item.memoryos_score.weighted_similarity}
            />
            <ScoreBar
              label="Importance"
              value={item.memoryos_score.importance}
              contribution={item.memoryos_score.weighted_importance}
            />
            <ScoreBar
              label="Recency"
              value={item.memoryos_score.recency}
              contribution={item.memoryos_score.weighted_recency}
            />
            <ScoreBar
              label="Reinforcement"
              value={item.memoryos_score.reinforcement}
              contribution={item.memoryos_score.weighted_reinforcement}
            />
            <ScoreBar
              label="Confidence"
              value={item.memoryos_score.confidence}
              contribution={item.memoryos_score.weighted_confidence}
            />
            <p className="rank-explanation">
              {item.explanation ||
                `${item.memoryos_score.total.toFixed(3)} total score · ${item.memoryos_score.days_since_confirmation.toFixed(0)} days since confirmation · ${item.memoryos_score.half_life_days}d half-life`}
            </p>
          </>
        ) : (
          <ScoreBar
            label="Cosine similarity"
            value={item.naive_similarity}
            contribution={item.naive_similarity}
          />
        )}
      </div>
    </details>
  );
}

function ScoreBar({
  label,
  value,
  contribution,
}: {
  label: string;
  value: number;
  contribution: number;
}) {
  return (
    <div className="score-bar-row">
      <span>{label}</span>
      <div className="score-bar">
        <i style={{ width: `${Math.round(Math.max(0, value) * 100)}%` }} />
      </div>
      <b>{contribution.toFixed(3)}</b>
    </div>
  );
}
function formatMovement(value: number | null) {
  if (value === null) return "outside top 5";
  if (value === 0) return "same";
  return value > 0 ? `↑ ${value}` : `↓ ${Math.abs(value)}`;
}
function movementTone(value: number | null) {
  if (value === null) return "outside";
  if (value === 0) return "flat";
  return value > 0 ? "up" : "down";
}
function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}
