"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  BrainCircuit,
  CheckCircle2,
  Clock3,
  GitBranch,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { useId } from "react";

import { MetricCard } from "@/components/metric-card";
import { ErrorState, LoadingState } from "@/components/status-state";
import { useWorkspace } from "@/components/workspace-context";
import { getOverview } from "@/lib/api/queries";
import type { MemoryEvent, MemoryType } from "@/lib/api/types";

const typeOrder: MemoryType[] = [
  "preference",
  "semantic",
  "episodic",
  "procedural",
];

export default function OverviewPage() {
  const { scopeId, mode, token } = useWorkspace();
  const overview = useQuery({
    queryKey: ["overview", scopeId, mode],
    queryFn: () => getOverview(scopeId, token),
  });

  return (
    <div className="page-wrap overview-page">
      <header className="page-header">
        <div>
          <div className="breadcrumb">
            <span>Workspace</span>
            <span>/</span>
            <strong>Overview</strong>
          </div>
          <h1>Memory overview</h1>
          <p className="page-subtitle">
            A live view of what {mode === "live" ? "your agent" : "Atlas"}{" "}
            knows, how it changed, and what it would recall.
          </p>
        </div>
        <div className="header-actions">
          <span className="demo-pill">
            <span className="status-dot" />
            {mode === "demo" ? "Demo mode" : "Live scope"}
          </span>
          <Link
            className="primary-button overview-action overview-primary-action"
            href="/ingestion"
          >
            <Sparkles size={15} />
            Ingest interaction
          </Link>
        </div>
      </header>

      {overview.isPending ? <LoadingState label="Loading overview" /> : null}
      {overview.isError ? (
        <ErrorState
          error={overview.error}
          onRetry={() => void overview.refetch()}
        />
      ) : null}
      {overview.data ? <OverviewContent data={overview.data} /> : null}
    </div>
  );
}

function OverviewContent({
  data,
}: {
  data: Awaited<ReturnType<typeof getOverview>>;
}) {
  const glassId = useId();
  const total = data.type_counts.reduce((sum, item) => sum + item.count, 0);
  const counts = new Map(
    data.type_counts.map((item) => [item.memory_type, item.count]),
  );
  const percentFor = (type: MemoryType) =>
    total ? Math.round(((counts.get(type) || 0) / total) * 100) : 0;
  const stops = typeOrder.reduce<{ value: number; parts: string[] }>(
    (acc, type) => {
      const start = acc.value;
      const end = start + percentFor(type);
      acc.value = end;
      acc.parts.push(`${typeColor(type)} ${start}% ${end}%`);
      return acc;
    },
    { value: 0, parts: [] },
  ).parts;
  const segments = typeOrder.reduce<
    Array<{
      type: MemoryType;
      start: number;
      share: number;
    }>
  >((items, type) => {
    const count = counts.get(type) || 0;
    const share = total ? (count / total) * 100 : 0;
    const start = items.reduce((sum, item) => sum + item.share, 0);
    items.push({ type, start, share });
    return items;
  }, []);

  return (
    <>
      <section className="metric-grid" aria-label="Memory summary">
        <MetricCard
          label="Active memories"
          value={String(data.active_memories)}
          detail="currently eligible for recall"
          icon={BrainCircuit}
          tone="violet"
        />
        <MetricCard
          label="Reinforced"
          value={String(data.reinforced_last_30_days)}
          detail="in the last 30 days"
          icon={GitBranch}
          tone="blue"
        />
        <MetricCard
          label="Needs review"
          value={String(data.unresolved_review_count ?? data.disputed_memories)}
          detail="unresolved decisions"
          icon={Clock3}
          tone="amber"
        />
        <MetricCard
          label="Interactions"
          value={String(data.interactions_last_30_days)}
          detail="received in the last 30 days"
          icon={CheckCircle2}
          tone="teal"
        />
      </section>

      <section className="overview-grid">
        <article className="panel composition-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Memory composition</span>
              <h2>What is in the system</h2>
            </div>
            <Link
              className="text-link overview-action overview-inline-action"
              href="/memories"
            >
              Explore <ArrowRight size={14} />
            </Link>
          </div>
          {total ? (
            <div className="composition-body">
              <div
                className="donut"
                style={{ background: `conic-gradient(${stops.join(", ")})` }}
                aria-label={`${total} memories across four types`}
              >
                <svg
                  className="donut-segments"
                  viewBox="0 0 100 100"
                  aria-hidden="true"
                >
                  <defs>
                    <linearGradient
                      id={`${glassId}-reflection`}
                      x1="0"
                      y1="0"
                      x2="1"
                      y2="1"
                    >
                      <stop offset="0" stopColor="white" stopOpacity="0.85" />
                      <stop
                        offset="0.45"
                        stopColor="white"
                        stopOpacity="0.35"
                      />
                      <stop offset="1" stopColor="white" stopOpacity="0" />
                    </linearGradient>
                    <mask id={`${glassId}-ring`}>
                      <circle
                        cx="50"
                        cy="50"
                        r="41.5"
                        fill="none"
                        stroke="white"
                        strokeWidth="16"
                      />
                    </mask>
                  </defs>
                  {segments.map((segment) => (
                    <circle
                      className={`donut-segment ${typeTone(segment.type)}`}
                      cx="50"
                      cy="50"
                      r="40.5"
                      pathLength="100"
                      strokeDasharray={`${Math.max(segment.share - 0.7, 0)} ${100 - Math.max(segment.share - 0.7, 0)}`}
                      strokeDashoffset={-(segment.start + 0.35)}
                      key={segment.type}
                    />
                  ))}
                  {segments.map((segment) => (
                    <circle
                      className={`donut-segment-streak ${typeTone(segment.type)}`}
                      cx="50"
                      cy="50"
                      r="45.5"
                      pathLength="100"
                      strokeDasharray={`${segment.share * 0.55} ${100 - segment.share * 0.55}`}
                      strokeDashoffset={-(segment.start + segment.share * 0.12)}
                      key={`${segment.type}-streak`}
                    />
                  ))}
                  <g
                    className="donut-reflections"
                    mask={`url(#${glassId}-ring)`}
                  >
                    <path
                      d="M 5 58 C 3 23 30 3 64 13"
                      stroke={`url(#${glassId}-reflection)`}
                      strokeWidth="3.2"
                    />
                    <path
                      d="M 9 61 C 7 30 32 9 66 18"
                      stroke={`url(#${glassId}-reflection)`}
                      strokeWidth="0.8"
                    />
                    <path
                      d="M 34 87 C 58 94 85 76 88 54"
                      stroke={`url(#${glassId}-reflection)`}
                      strokeWidth="1.2"
                      opacity="0.4"
                    />
                  </g>
                  <g className="donut-seams">
                    {segments
                      .filter((segment) => segment.share > 0)
                      .map((segment) => (
                        <g
                          key={`${segment.type}-edge`}
                          transform={`rotate(${segment.start * 3.6} 50 50)`}
                        >
                          <path
                            d="M 50 0.5 V 16.5"
                            className="donut-seam-shadow"
                          />
                          <path
                            d="M 50.65 1 V 16.5"
                            className="donut-seam-light"
                          />
                        </g>
                      ))}
                  </g>
                </svg>
                <span className="donut-shine" aria-hidden="true" />
                <div className="donut-center">
                  <strong>{total}</strong>
                  <span>tracked</span>
                </div>
              </div>
              <div className="legend-list">
                {typeOrder.map((type) => (
                  <LegendRow
                    color={type}
                    label={capitalize(type)}
                    count={String(counts.get(type) || 0)}
                    percent={`${percentFor(type)}%`}
                    key={type}
                  />
                ))}
              </div>
            </div>
          ) : (
            <div className="empty-panel">
              No memories have been seeded in this scope yet.
            </div>
          )}
          <div className="panel-note">
            <span className="tiny-spark" />
            Scores combine similarity, importance, recency, reinforcement, and
            confidence.
          </div>
        </article>

        <article className="panel activity-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Recent activity</span>
              <h2>Memory changes</h2>
            </div>
            <Link
              className="text-link overview-action overview-inline-action"
              href="/memories"
            >
              View history <ArrowRight size={14} />
            </Link>
          </div>
          {data.recent_events.length ? (
            <div className="activity-list">
              {data.recent_events.slice(0, 6).map((event) => (
                <ActivityRow event={event} key={event.id} />
              ))}
            </div>
          ) : (
            <div className="empty-panel">
              Events will appear here as memories are ingested.
            </div>
          )}
        </article>
      </section>

      <section className="callout-row">
        <div className="callout-icon">
          <Sparkles size={18} />
        </div>
        <div>
          <strong>Try the Recall Lab</strong>
          <p>
            See why MemoryOS can choose a slightly older, more important memory
            over a near-duplicate.
          </p>
        </div>
        <Link
          className="secondary-button overview-action overview-secondary-action"
          href="/recall"
        >
          Open lab <ArrowRight size={14} />
        </Link>
      </section>
    </>
  );
}

function ActivityRow({ event }: { event: MemoryEvent }) {
  const type = eventTypeColor(event.event_type);
  const title =
    (event as MemoryEvent & { memory_content?: string | null })
      .memory_content || event.reason_summary;
  return (
    <Link className="activity-row" href={`/memories/${event.memory_id}`}>
      <span className={`memory-type-dot ${typeTone(type)}`} />
      <div className="activity-copy">
        <strong>{title}</strong>
        <span>
          <em className={`event-label ${event.event_type}`}>
            {event.event_type}
          </em>{" "}
          · {formatRelative(event.created_at)}
        </span>
      </div>
      <ArrowRight size={14} className="activity-arrow" aria-hidden="true" />
    </Link>
  );
}

function LegendRow({
  color,
  label,
  count,
  percent,
}: {
  color: MemoryType;
  label: string;
  count: string;
  percent: string;
}) {
  const tone = typeTone(color);
  return (
    <div className={`legend-row ${tone}`}>
      <span className={`legend-dot ${tone}`} />
      <span>{label}</span>
      <strong>{count}</strong>
      <small>{percent}</small>
    </div>
  );
}

function typeColor(type: MemoryType) {
  return type === "preference"
    ? "#7263d7"
    : type === "semantic"
      ? "#4c86d8"
      : type === "episodic"
        ? "#db9c38"
        : "#37a79b";
}

function typeTone(type: MemoryType): "violet" | "blue" | "amber" | "teal" {
  return type === "preference"
    ? "violet"
    : type === "semantic"
      ? "blue"
      : type === "episodic"
        ? "amber"
        : "teal";
}

function eventTypeColor(eventType: MemoryEvent["event_type"]): MemoryType {
  if (eventType === "reinforced") return "preference";
  if (eventType === "superseded" || eventType === "disputed") return "episodic";
  if (eventType === "resolved") return "semantic";
  return "procedural";
}

function capitalize(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function formatRelative(value: string) {
  const date = new Date(value);
  const minutes = Math.max(
    0,
    Math.round((Date.now() - date.getTime()) / 60_000),
  );
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  return `${Math.round(hours / 24)} days ago`;
}
