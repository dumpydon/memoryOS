"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  BrainCircuit,
  Check,
  GitBranch,
  Inbox,
  Layers3,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import { ErrorState, LoadingState } from "@/components/status-state";
import { TypeBadge } from "@/components/type-badge";
import { getDemoCatalog } from "@/lib/api/queries";
import type { DemoScenario } from "@/lib/api/types";

const fallbackScenarios: DemoScenario[] = [
  {
    id: "demo-pref-python-new",
    title: "Capture a response preference",
    description: "Create a concise-answer preference with a Python example.",
    text: "For Atlas, keep answers concise and use Python examples.",
    expected_outcome: "created",
  },
  {
    id: "demo-pref-python-reinforce",
    title: "Reinforce an existing preference",
    description: "Confirm the same preference in a distinct interaction.",
    text: "As before, Atlas still prefers concise Python examples.",
    expected_outcome: "reinforced",
  },
  {
    id: "demo-pref-style-supersede",
    title: "Apply an explicit correction",
    description: "Use an explicit from-now-on correction to create a new version.",
    text: "From now on, Atlas wants short answers with one concrete example.",
    expected_outcome: "superseded",
  },
];

const steps = [
  {
    number: "01",
    title: "An interaction arrives",
    detail:
      "MemoryOS receives the original text and keeps its source reference for the audit trail.",
    icon: Inbox,
  },
  {
    number: "02",
    title: "A candidate is extracted",
    detail:
      "Structured inference turns useful language into an atomic memory with type, evidence, and confidence.",
    icon: Sparkles,
  },
  {
    number: "03",
    title: "Context is compared",
    detail:
      "Subject, context, attribute, timing, and active history determine whether the candidate is new or related.",
    icon: GitBranch,
  },
  {
    number: "04",
    title: "Policy validates the proposal",
    detail:
      "The model proposes. Deterministic policy decides whether to create, reinforce, supersede, skip, or dispute.",
    icon: ShieldCheck,
  },
  {
    number: "05",
    title: "A lineage is preserved",
    detail:
      "Every version and decision stays linked to evidence, so a correction never erases what came before.",
    icon: Layers3,
  },
  {
    number: "06",
    title: "Recall ranks what matters",
    detail:
      "A hybrid score combines similarity, importance, recency, reinforcement, and confidence with an explanation.",
    icon: Search,
  },
];

export function HowItWorks() {
  const catalog = useQuery({
    queryKey: ["demo-catalog", "how-it-works"],
    queryFn: () => getDemoCatalog(),
  });
  const scenarios = catalog.data?.scenarios || fallbackScenarios;
  const examples = useMemo(
    () => ({
      created:
        scenarios.find((scenario) => scenario.expected_outcome === "created") ||
        fallbackScenarios[0],
      reinforced:
        scenarios.find(
          (scenario) => scenario.expected_outcome === "reinforced",
        ) || fallbackScenarios[1],
      superseded:
        scenarios.find(
          (scenario) => scenario.expected_outcome === "superseded",
        ) || fallbackScenarios[2],
    }),
    [scenarios],
  );

  return (
    <div className="page-wrap onboarding-page">
      <header className="page-header">
        <div>
          <div className="breadcrumb">
            <span>Workspace</span>
            <span>/</span>
            <strong>How MemoryOS works</strong>
          </div>
          <h1>How MemoryOS works</h1>
          <p className="page-subtitle">
            A quick tour from one interaction to an explainable memory you can
            use later.
          </p>
        </div>
        <div className="header-actions">
          <Link className="primary-button" href="/ingestion">
            Try an interaction <ArrowRight size={14} />
          </Link>
        </div>
      </header>

      <section className="panel onboarding-hero">
        <div className="onboarding-hero-copy">
          <span className="eyebrow">The memory loop</span>
          <h2>Useful information becomes accountable memory.</h2>
          <p>
            MemoryOS makes each decision inspectable: what was extracted, what
            it was compared with, and why the system chose to remember it.
          </p>
        </div>
        <div className="onboarding-hero-mark" aria-hidden="true">
          <BrainCircuit size={28} />
          <span />
          <span />
          <span />
        </div>
      </section>

      <section className="onboarding-flow" aria-label="MemoryOS flow">
        {steps.map((step, index) => {
          const Icon = step.icon;
          return (
            <div className="onboarding-flow-step" key={step.number}>
              <div className="onboarding-step-number">{step.number}</div>
              <Icon size={16} aria-hidden="true" />
              <strong>{step.title}</strong>
              {index < steps.length - 1 ? (
                <ArrowRight
                  className="onboarding-flow-arrow"
                  size={14}
                  aria-hidden="true"
                />
              ) : null}
            </div>
          );
        })}
      </section>

      <section className="onboarding-steps" aria-label="How each step works">
        {steps.map((step) => {
          const Icon = step.icon;
          return (
            <article className="panel onboarding-step-card" key={step.number}>
              <div className="onboarding-step-card-head">
                <span className="onboarding-card-number">{step.number}</span>
                <span className="onboarding-card-icon">
                  <Icon size={16} aria-hidden="true" />
                </span>
              </div>
              <h2>{step.title}</h2>
              <p>{step.detail}</p>
            </article>
          );
        })}
      </section>

      <section className="panel onboarding-examples">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Real demo examples</span>
            <h2>Same signal, different policy outcome</h2>
          </div>
          {catalog.isPending ? <LoadingState label="Loading examples" /> : null}
        </div>
        {catalog.isError ? (
          <div className="onboarding-example-error">
            <ErrorState error={catalog.error} />
            <p>Showing the authored examples while the catalog reconnects.</p>
          </div>
        ) : null}
        <div className="onboarding-example-grid">
          <ExampleCard scenario={examples.created} outcome="NEW" tone="created" />
          <ExampleCard
            scenario={examples.reinforced}
            outcome="REINFORCEMENT"
            tone="reinforced"
          />
          <ExampleCard
            scenario={examples.superseded}
            outcome="SUPERSESSION"
            tone="superseded"
          />
        </div>
      </section>

      <section className="onboarding-footer-callout">
        <div>
          <strong>Want to see the evidence?</strong>
          <p>
            Run a demo scenario, then open its memory lineage to inspect the
            exact candidate, decision, and score components.
          </p>
        </div>
        <div className="onboarding-footer-actions">
          <Link className="secondary-button" href="/memories">
            Explore memories
          </Link>
          <Link className="primary-button" href="/recall">
            Open Recall Lab <ArrowRight size={14} />
          </Link>
        </div>
      </section>
    </div>
  );
}

function ExampleCard({
  scenario,
  outcome,
  tone,
}: {
  scenario: DemoScenario;
  outcome: string;
  tone: "created" | "reinforced" | "superseded";
}) {
  return (
    <article className={`onboarding-example-card ${tone}`}>
      <div className="onboarding-example-topline">
        <span className={`onboarding-outcome ${tone}`}>
          <Check size={12} aria-hidden="true" />
          {outcome}
        </span>
        <span className="onboarding-example-title">{scenario.title}</span>
      </div>
      <blockquote>“{scenario.text}”</blockquote>
      <div className="onboarding-example-result">
        {tone === "created" ? (
          <>
            <TypeBadge type="preference" />
            <span>new atomic preference</span>
          </>
        ) : tone === "reinforced" ? (
          <>
            <GitBranch size={13} aria-hidden="true" />
            <span>same subject + context confirms the active memory</span>
          </>
        ) : (
          <>
            <Layers3 size={13} aria-hidden="true" />
            <span>explicit correction creates a new lineage version</span>
          </>
        )}
      </div>
    </article>
  );
}
