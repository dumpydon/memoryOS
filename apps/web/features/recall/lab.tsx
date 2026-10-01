"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  FlaskConical,
  Info,
  Search,
  ShieldAlert,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
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
import { RecallUseMemory } from "./use-memory";

const featuredDemoIds = new Set([
  "demo-query-answer-style",
  "demo-query-persistence",
  "demo-query-mcp",
]);

export function RecallLab() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { scopeId, mode, token, isOwner, sessionKey } = useWorkspace();
  const useMemory = searchParams.get("view") === "context";
  const catalog = useQuery({
    queryKey: ["demo-catalog", "recall"],
    queryFn: () => getDemoCatalog(token),
    enabled: mode === "demo",
  });
  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: () => getCapabilities(token),
    enabled: mode === "live",
  });
  // Lead the finite public demo with its clearest real ranking change.
  const activeQuery = searchParams.has("q")
    ? searchParams.get("q") || ""
    : mode === "demo"
      ? catalog.data?.queries.find(
          (item) => item.id === "demo-query-answer-style",
        )?.query || ""
      : "";
  const [draft, setDraft] = useState<{ source: string; value: string } | null>(
    null,
  );
  const draftQuery = draft?.source === activeQuery ? draft.value : activeQuery;
  const knownQuery = useMemo(
    () => catalog.data?.queries.find((item) => item.query === activeQuery),
    [activeQuery, catalog.data],
  );
  const liveUnavailable =
    mode === "live" &&
    capabilities.data &&
    !capabilities.data.live_recall_available;
  const allowedQuery =
    mode === "live"
      ? isOwner &&
        Boolean(activeQuery.trim()) &&
        capabilities.data?.live_recall_available === true
      : Boolean(knownQuery);
  const comparison = useQuery({
    queryKey: ["recall-compare", scopeId, mode, activeQuery],
    queryFn: () =>
      postRecallCompare(
        { scope_id: scopeId, query: activeQuery, limit: 5, mode },
        token,
      ),
    enabled: allowedQuery && !useMemory,
  });

  function runQuery(value: string) {
    const next = value.trim();
    setDraft(null);
    router.replace(`/recall?q=${encodeURIComponent(next)}`, { scroll: false });
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
        </div>
        <div className="header-actions">
          <span className="demo-pill">
            <span className="status-dot" />
            {mode === "demo"
              ? "Demo mode"
              : useMemory
                ? "Live generation"
                : "Live recall"}
          </span>
        </div>
      </header>

      <nav className="recall-mode-switch" aria-label="Recall Lab mode">
        <Link href="/recall" aria-current={!useMemory ? "page" : undefined}>
          Compare retrieval
        </Link>
        <Link
          href="/recall?view=context"
          aria-current={useMemory ? "page" : undefined}
        >
          Use memory
        </Link>
      </nav>

      {useMemory ? (
        <RecallUseMemory
          key={sessionKey}
          available={capabilities.data?.live_recall_available === true}
          checking={mode === "live" && capabilities.isPending}
        />
      ) : (
        <>
          {liveUnavailable ? (
            <InlineNotice tone="warning">
              <ShieldAlert size={15} /> Live recall needs an OpenAI key on the
              API server. Add <code>OPENAI_API_KEY</code> there to run your own
              queries; demo queries remain available.
            </InlineNotice>
          ) : null}

          <section
            className="panel recall-query-panel"
            aria-label="Recall query"
          >
            <div className="query-heading">
              <h2>Query</h2>
            </div>
            <form
              className="recall-query-form"
              onSubmit={(event) => {
                event.preventDefault();
                runQuery(draftQuery);
              }}
            >
              <div className="search-field">
                <Search size={16} aria-hidden="true" />
                <input
                  value={draftQuery}
                  onChange={(event) =>
                    setDraft({ source: activeQuery, value: event.target.value })
                  }
                  placeholder="Ask about a preference, project, or procedure"
                  aria-label="Recall query"
                />
                <button className="search-submit" type="submit">
                  Compare retrieval <ArrowRight size={14} />
                </button>
              </div>
            </form>
            {mode === "demo" && catalog.data ? (
              <div className="query-presets">
                <span className="toolbar-label">Try</span>
                {catalog.data.queries
                  .filter((item) => featuredDemoIds.has(item.id))
                  .map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className={`query-preset ${activeQuery === item.query ? "selected" : ""}`}
                      aria-pressed={activeQuery === item.query}
                      onClick={() => runQuery(item.query)}
                    >
                      {item.title}
                    </button>
                  ))}
                <details className="recall-more-queries">
                  <summary>More</summary>
                  <div>
                    {catalog.data.queries
                      .filter((item) => !featuredDemoIds.has(item.id))
                      .map((item) => (
                        <button
                          key={item.id}
                          type="button"
                          className={`query-preset ${activeQuery === item.query ? "selected" : ""}`}
                          aria-pressed={activeQuery === item.query}
                          onClick={() => runQuery(item.query)}
                        >
                          {item.title}
                        </button>
                      ))}
                  </div>
                </details>
                <span
                  className="recall-demo-hint"
                  title="Public demo queries use authored fixture vectors."
                  aria-label="Public demo queries use authored fixture vectors."
                  tabIndex={0}
                >
                  <Info size={13} aria-hidden="true" />
                </span>
              </div>
            ) : null}
          </section>

          {mode === "demo" && catalog.isPending ? (
            <LoadingState label="Preparing demo queries" />
          ) : null}
          {mode === "demo" && catalog.isError ? (
            <ErrorState
              error={catalog.error}
              onRetry={() => void catalog.refetch()}
            />
          ) : null}
          {mode === "demo" && activeQuery && !knownQuery && catalog.data ? (
            <InlineNotice tone="warning">
              <ShieldAlert size={15} /> The public demo accepts the example
              queries above. Live mode with an owner token accepts arbitrary
              queries.
            </InlineNotice>
          ) : null}
          {mode === "live" && !isOwner ? (
            <InlineNotice tone="warning">
              <ShieldAlert size={15} /> Add an owner token in Settings to run
              live recall.
            </InlineNotice>
          ) : null}
          {mode === "live" && isOwner && liveUnavailable && activeQuery ? (
            <InlineNotice>
              <Info size={15} /> Your query is ready. MemoryOS will not send it
              to a provider until live recall is configured.
            </InlineNotice>
          ) : null}
          {mode === "live" && isOwner && capabilities.isPending ? (
            <LoadingState label="Checking live provider readiness" />
          ) : null}
          {allowedQuery && comparison.isPending ? (
            <LoadingState label="Comparing both rankings" />
          ) : null}
          {allowedQuery && comparison.isError ? (
            <ErrorState
              error={comparison.error}
              onRetry={() => void comparison.refetch()}
            />
          ) : null}
          {allowedQuery && comparison.data ? (
            <ComparisonResults
              data={comparison.data}
              key={`${scopeId}:${mode}:${comparison.data.query}`}
            />
          ) : null}
          {!activeQuery && !(mode === "demo" && catalog.isPending) ? (
            <div className="panel recall-empty">
              <FlaskConical size={23} aria-hidden="true" />
              <strong>Start with a memory question</strong>
              <p>
                Compare the same eligible memories under similarity alone and
                the MemoryOS policy.
              </p>
              {mode === "demo" && catalog.data?.queries[0] ? (
                <button
                  type="button"
                  className="search-submit"
                  onClick={() =>
                    runQuery(catalog.data?.queries[0]?.query || "")
                  }
                >
                  Run the answer style example <ArrowRight size={14} />
                </button>
              ) : null}
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

function ComparisonResults({ data }: { data: RecallComparisonResponse }) {
  const initial =
    data.memoryos.find((item) => (item.rank_delta || 0) > 0) ||
    data.memoryos.find((item) => item.rank_delta) ||
    data.memoryos[0];
  const [selectedId, setSelectedId] = useState(initial?.memory.id || "");
  const selected = [...data.memoryos, ...data.naive].find(
    (item) => item.memory.id === selectedId,
  );
  const baselineTop = data.naive[0];
  const memoryosTop = data.memoryos[0];
  const topChanged =
    baselineTop &&
    memoryosTop &&
    baselineTop.memory.id !== memoryosTop.memory.id;
  const movedCount = data.memoryos.filter(
    (item) => item.rank_delta !== null && item.rank_delta !== 0,
  ).length;

  if (!data.memoryos.length) {
    return (
      <div className="panel recall-empty" role="status">
        <Search size={23} aria-hidden="true" />
        <strong>No eligible memories matched</strong>
        <p>
          Nothing passed the relevance floor for this query. Try another example
          or a broader query.
        </p>
      </div>
    );
  }

  return (
    <div className="recall-results">
      <div className="comparison-meta">
        <span>{data.candidate_count} eligible memories</span>
        <details className="recall-audit">
          <summary>
            <Info size={13} aria-hidden="true" /> Method
          </summary>
          <p>
            Same query vector and eligible snapshot ·{" "}
            {formatDateTime(data.evaluated_at)} · {data.policy_version}
          </p>
        </details>
      </div>
      <section
        className="recall-story"
        aria-label="What changed in the ranking"
      >
        <div>
          <span className="eyebrow">Ranking outcome</span>
          <h2>
            {topChanged
              ? `Closest match moves to #${baselineTop.memoryos_rank ?? "—"}`
              : movedCount
                ? `Same #1 · ${movedCount} other ranks changed`
                : "Both rankings agree"}
          </h2>
        </div>
        {movedCount ? (
          <a className="recall-story-jump" href="#selected-memory">
            See why ↓
          </a>
        ) : null}
      </section>
      <div className="comparison-grid">
        <RankColumn
          title="Vector only"
          items={data.naive}
          kind="naive"
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
        <RankColumn
          title="MemoryOS"
          items={data.memoryos}
          kind="memoryos"
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
      </div>
      {selected ? (
        <ScoreInspector item={selected} weights={data.score_weights} />
      ) : null}
    </div>
  );
}

function RankColumn({
  title,
  items,
  kind,
  selectedId,
  onSelect,
}: {
  title: string;
  items: RecallComparisonItem[];
  kind: "naive" | "memoryos";
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <section
      className={`panel rank-column ${kind}`}
      aria-label={`${title} ranking`}
    >
      <div className="rank-column-heading">
        <h2>{title}</h2>
        <span className="rank-score-label">
          {kind === "naive" ? "Similarity" : "Memory score"}
        </span>
      </div>
      <div className="rank-list">
        {items.map((item) => (
          <RankRow
            item={item}
            kind={kind}
            selected={selectedId === item.memory.id}
            onSelect={() => onSelect(item.memory.id)}
            key={item.memory.id}
          />
        ))}
      </div>
    </section>
  );
}

function RankRow({
  item,
  kind,
  selected,
  onSelect,
}: {
  item: RecallComparisonItem;
  kind: "naive" | "memoryos";
  selected: boolean;
  onSelect: () => void;
}) {
  const score = item.memoryos_score;
  const rank = kind === "naive" ? item.naive_rank : item.memoryos_rank;
  return (
    <button
      type="button"
      className={`rank-row ${selected ? "selected" : ""}`}
      onClick={onSelect}
      aria-pressed={selected}
      aria-label={`${item.memory.content}. ${kind === "naive" ? "Vector" : "MemoryOS"} rank ${rank}. ${item.rank_delta === 0 ? "Unchanged" : formatMovement(item.rank_delta)}.`}
      title={item.memory.content}
    >
      <span className="rank-number">{rank ?? "—"}</span>
      <span className="rank-row-main">
        <TypeBadge type={item.memory.memory_type} />
        <strong>{item.memory.content}</strong>
      </span>
      <span className="rank-row-end">
        <strong>
          {kind === "naive"
            ? item.naive_similarity.toFixed(3)
            : score.total.toFixed(3)}
        </strong>
        <span className={`rank-movement ${movementTone(item.rank_delta)}`}>
          {formatMovement(item.rank_delta)}
        </span>
      </span>
    </button>
  );
}

function ScoreInspector({
  item,
  weights,
}: {
  item: RecallComparisonItem;
  weights: Record<string, number>;
}) {
  const score = item.memoryos_score;
  const signals: Array<{
    key: string;
    label: string;
    value: number;
    contribution: number;
  }> = [
    {
      key: "similarity",
      label: "Similarity",
      value: score.similarity,
      contribution: score.weighted_similarity,
    },
    {
      key: "importance",
      label: "Importance",
      value: score.importance,
      contribution: score.weighted_importance,
    },
    {
      key: "recency",
      label: "Recency",
      value: score.recency,
      contribution: score.weighted_recency,
    },
    {
      key: "reinforcement",
      label: "Reinforcement",
      value: score.reinforcement,
      contribution: score.weighted_reinforcement,
    },
    {
      key: "confidence",
      label: "Confidence",
      value: score.confidence,
      contribution: score.weighted_confidence,
    },
  ];
  const policyDetail = `Weights: ${signals
    .map(
      (signal) =>
        `${signal.label.toLowerCase()} ${Math.round((weights[signal.key] || 0) * 100)}%`,
    )
    .join(
      " · ",
    )}. Recency uses this memory's ${score.half_life_days}-day type half-life and last confirmation ${score.days_since_confirmation.toFixed(0)} days ago. Policy ${score.policy_version}.`;
  return (
    <section
      id="selected-memory"
      className="panel recall-inspector"
      aria-label="Selected memory score breakdown"
      aria-live="polite"
    >
      <div className="recall-inspector-lead">
        <div>
          <span className="eyebrow">
            Selected memory · vector #{item.naive_rank ?? "—"} → MemoryOS #
            {item.memoryos_rank ?? "—"}
          </span>
          <h2>{item.memory.content}</h2>
          <p>{item.movement_reason}</p>
        </div>
        <div className="recall-final-score">
          <strong>{score.total.toFixed(3)}</strong>
          <span>Final score</span>
        </div>
      </div>
      <div className="recall-signal-list">
        {signals.map((signal) => (
          <div className="recall-signal-row" key={signal.key}>
            <span
              className="recall-signal-name"
              title={`${Math.round((weights[signal.key] || 0) * 100)}% policy weight`}
            >
              {signal.label}
            </span>
            <div
              className="recall-signal-track"
              role="meter"
              aria-label={signal.label}
              aria-valuemin={0}
              aria-valuemax={1}
              aria-valuenow={signal.value}
              aria-valuetext={`${Math.round(signal.value * 100)}% normalized; ${Math.round((weights[signal.key] || 0) * 100)}% policy weight`}
              title={`${Math.round(signal.value * 100)}% normalized · ${Math.round((weights[signal.key] || 0) * 100)}% weight`}
            >
              <i style={{ width: `${Math.round(signal.value * 100)}%` }} />
            </div>
            <b title="Weighted contribution">
              +{signal.contribution.toFixed(3)}
            </b>
          </div>
        ))}
      </div>
      <details className="recall-inspector-method">
        <summary>Scoring details</summary>
        <p>{policyDetail}</p>
      </details>
    </section>
  );
}

function formatMovement(value: number | null) {
  if (value === null) return "outside list";
  if (value === 0) return "—";
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
