"""Deterministic, finite demo catalog used by seed, ingestion, and public routes.

Every vector and candidate in this module is authored fixture data.  It is never
described as an OpenAI recording and it is intentionally finite so public demo
requests cannot turn into arbitrary provider calls.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import NAMESPACE_URL, UUID, uuid5

from memoryos.contracts.demo import DemoCatalogResponse, DemoQuery, DemoScenario
from memoryos.contracts.ingestion import CandidateMemory
from memoryos.domain.enums import MemoryRelation, MemoryStatus, MemoryType

DEMO_SCOPE_ID: Final[UUID] = UUID("00000000-0000-0000-0000-000000000001")
LIVE_SCOPE_ID: Final[UUID] = UUID("00000000-0000-0000-0000-000000000002")
DEMO_MODEL: Final[str] = "demo-fixture-v1"
DEMO_DIMENSIONS: Final[int] = 1536
CATALOG_NOTICE: Final[str] = (
    "Demo content, relationships, and embeddings are deterministic authored fixtures; "
    "they are not recorded OpenAI calls."
)

_SPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Anchor relative demo ages once when seeding; reruns leave persisted dates intact.
_SEED_NOW = datetime.now(UTC)

# These are authored semantic buckets for the demo. They make the Recall Lab
# useful without pretending to be an embedding model or an OpenAI recording.
_TOPIC_WORDS: dict[str, frozenset[str]] = {
    "answer-style": frozenset(
        {
            "answer",
            "answers",
            "concise",
            "short",
            "example",
            "examples",
            "python",
            "style",
            "paragraph",
            "explanations",
        }
    ),
    "persistence": frozenset(
        {
            "memory",
            "memories",
            "lineage",
            "lineages",
            "version",
            "versions",
            "postgresql",
            "pgvector",
            "scope",
            "scopes",
            "scoped",
            "database",
            "history",
            "archive",
            "archived",
        }
    ),
    "recall": frozenset(
        {
            "recall",
            "similarity",
            "importance",
            "recency",
            "reinforcement",
            "confidence",
            "ranking",
            "rank",
            "retrieval",
            "query",
            "vectors",
        }
    ),
    "runbook": frozenset(
        {
            "run",
            "runbook",
            "uv",
            "uvicorn",
            "alembic",
            "start",
            "apply",
            "local",
            "migrations",
            "check",
            "connect",
            "resolve",
            "forget",
            "load",
            "review",
            "retry",
        }
    ),
    "incident": frozenset(
        {
            "incident",
            "cache",
            "stampede",
            "slow",
            "index",
            "recovered",
            "fixed",
            "staging",
            "rehearsal",
        }
    ),
    "process": frozenset(
        {
            "review",
            "sprint",
            "conference",
            "retro",
            "study",
            "design",
            "contracts",
            "team",
            "milestone",
            "presented",
        }
    ),
    "integration": frozenset(
        {"mcp", "endpoint", "provider", "demo", "openai", "api", "key", "connect", "client"}
    ),
    "security": frozenset({"owner", "bearer", "private", "auth", "security", "token"}),
}


def _normalize(value: str) -> str:
    return _SPACE_RE.sub(" ", value.strip()).casefold()


@dataclass(frozen=True, slots=True)
class SeedMemorySpec:
    """Portable seed row; IDs are derived from ``key`` for rerun safety."""

    key: str
    content: str
    memory_type: MemoryType
    subject: str
    context_key: str
    attribute_key: str
    importance: float
    confidence: float
    status: MemoryStatus = MemoryStatus.ACTIVE
    reinforcement_count: int = 0
    version: int = 1
    lineage_key: str | None = None
    superseded_by_key: str | None = None
    effective_days_ago: int = 30
    confirmed_days_ago: int = 5
    expires_days_ago: int | None = None

    @property
    def id(self) -> UUID:
        return _stable_uuid(f"memory:{self.key}")

    @property
    def lineage_id(self) -> UUID:
        return _stable_uuid(f"lineage:{self.lineage_key or self.key}")

    @property
    def effective_at(self) -> datetime:
        return _SEED_NOW - timedelta(days=self.effective_days_ago)

    @property
    def last_confirmed_at(self) -> datetime:
        return _SEED_NOW - timedelta(days=self.confirmed_days_ago)

    @property
    def expires_at(self) -> datetime | None:
        if self.expires_days_ago is None:
            return None
        return _SEED_NOW - timedelta(days=self.expires_days_ago)


def _stable_uuid(value: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"https://memoryos.example/demo/{value}")


def _spec(
    key: str,
    content: str,
    memory_type: MemoryType,
    *,
    subject: str,
    context: str,
    attribute: str,
    importance: float = 0.72,
    confidence: float = 0.88,
    status: MemoryStatus = MemoryStatus.ACTIVE,
    reinforcement_count: int = 0,
    version: int = 1,
    lineage: str | None = None,
    superseded_by: str | None = None,
    effective_days_ago: int = 30,
    confirmed_days_ago: int = 5,
    expires_days_ago: int | None = None,
) -> SeedMemorySpec:
    return SeedMemorySpec(
        key=key,
        content=content,
        memory_type=memory_type,
        subject=subject,
        context_key=context,
        attribute_key=attribute,
        importance=importance,
        confidence=confidence,
        status=status,
        reinforcement_count=reinforcement_count,
        version=version,
        lineage_key=lineage,
        superseded_by_key=superseded_by,
        effective_days_ago=effective_days_ago,
        confirmed_days_ago=confirmed_days_ago,
        expires_days_ago=expires_days_ago,
    )


# The rows are intentionally fictional but form one coherent Atlas engineering
# story. There are 48 rows across all four memory types, including versioned,
# disputed, forgotten, and expired cases for the explorer/history views.
_SEED_SPECS: tuple[SeedMemorySpec, ...] = (
    # Preferences (13 rows)
    _spec(
        "pref-answer-style-v1",
        "Atlas prefers detailed explanations with several examples.",
        MemoryType.PREFERENCE,
        subject="Atlas",
        context="answer-style",
        attribute="response-format",
        importance=0.82,
        confidence=0.91,
        status=MemoryStatus.SUPERSEDED,
        lineage="pref-answer-style",
        superseded_by="pref-answer-style-v2",
        effective_days_ago=250,
        confirmed_days_ago=220,
    ),
    _spec(
        "pref-answer-style-v2",
        "Atlas prefers concise answers with one concrete example.",
        MemoryType.PREFERENCE,
        subject="Atlas",
        context="answer-style",
        attribute="response-format",
        importance=0.94,
        confidence=0.96,
        status=MemoryStatus.ACTIVE,
        reinforcement_count=3,
        version=2,
        lineage="pref-answer-style",
        effective_days_ago=120,
        confirmed_days_ago=2,
    ),
    _spec(
        "pref-python-examples",
        "Atlas prefers Python examples for implementation questions.",
        MemoryType.PREFERENCE,
        subject="Atlas",
        context="examples",
        attribute="programming-language",
        importance=0.9,
        confidence=0.95,
        reinforcement_count=2,
        confirmed_days_ago=7,
    ),
    _spec(
        "pref-timezone",
        "Atlas prefers meeting times shown in India Standard Time.",
        MemoryType.PREFERENCE,
        subject="Atlas",
        context="scheduling",
        attribute="timezone",
        importance=0.75,
        confidence=0.9,
        confirmed_days_ago=24,
    ),
    _spec(
        "pref-direct-feedback",
        "Atlas prefers direct feedback with a proposed fix.",
        MemoryType.PREFERENCE,
        subject="Atlas",
        context="collaboration",
        attribute="feedback-style",
        importance=0.8,
        confidence=0.87,
        reinforcement_count=4,
        confirmed_days_ago=12,
    ),
    _spec(
        "pref-jargon",
        "Atlas prefers plain language over marketing jargon.",
        MemoryType.PREFERENCE,
        subject="Atlas",
        context="writing",
        attribute="language-style",
        importance=0.7,
        confidence=0.86,
        confirmed_days_ago=42,
    ),
    _spec(
        "pref-release-notes",
        "Atlas prefers release notes grouped by user impact.",
        MemoryType.PREFERENCE,
        subject="Atlas",
        context="release-process",
        attribute="notes-format",
        importance=0.65,
        confidence=0.83,
        confirmed_days_ago=68,
    ),
    _spec(
        "pref-pairing",
        "Atlas prefers pairing on tricky debugging sessions in the afternoon.",
        MemoryType.PREFERENCE,
        subject="Atlas",
        context="debugging",
        attribute="collaboration-window",
        importance=0.67,
        confidence=0.84,
        confirmed_days_ago=31,
    ),
    _spec(
        "pref-dark-mode",
        "Atlas prefers dark mode in the engineering dashboard.",
        MemoryType.PREFERENCE,
        subject="Atlas",
        context="dashboard",
        attribute="theme",
        importance=0.48,
        confidence=0.8,
        confirmed_days_ago=100,
    ),
    _spec(
        "pref-comments",
        "Atlas prefers code comments that explain why rather than what.",
        MemoryType.PREFERENCE,
        subject="Atlas",
        context="code-review",
        attribute="comment-style",
        importance=0.76,
        confidence=0.9,
        confirmed_days_ago=18,
    ),
    _spec(
        "pref-metrics",
        "Atlas prefers metric units in technical documentation.",
        MemoryType.PREFERENCE,
        subject="Atlas",
        context="documentation",
        attribute="units",
        importance=0.55,
        confidence=0.79,
        confirmed_days_ago=140,
    ),
    _spec(
        "pref-design-review",
        "Atlas prefers a short design review before changing public APIs.",
        MemoryType.PREFERENCE,
        subject="Atlas",
        context="api-design",
        attribute="review-process",
        importance=0.84,
        confidence=0.92,
        confirmed_days_ago=9,
    ),
    _spec(
        "pref-notifications",
        "Atlas prefers deployment notifications in the team channel.",
        MemoryType.PREFERENCE,
        subject="Atlas",
        context="deployments",
        attribute="notification-channel",
        importance=0.6,
        confidence=0.82,
        confirmed_days_ago=75,
    ),
    # Semantic knowledge (13 rows)
    _spec(
        "semantic-api",
        "Atlas serves its public API with FastAPI.",
        MemoryType.SEMANTIC,
        subject="Atlas",
        context="architecture",
        attribute="api-framework",
        importance=0.86,
        confidence=0.98,
        confirmed_days_ago=3,
    ),
    _spec(
        "semantic-db",
        "Atlas stores durable memories in PostgreSQL with pgvector.",
        MemoryType.SEMANTIC,
        subject="Atlas",
        context="architecture",
        attribute="database",
        importance=0.93,
        confidence=0.99,
        confirmed_days_ago=2,
    ),
    _spec(
        "semantic-graph",
        "Atlas uses a bounded graph to validate extraction and relationships.",
        MemoryType.SEMANTIC,
        subject="Atlas",
        context="architecture",
        attribute="orchestration",
        importance=0.82,
        confidence=0.9,
        confirmed_days_ago=14,
    ),
    _spec(
        "semantic-demo-mode",
        "Atlas demo mode uses deterministic fixture providers without an API key.",
        MemoryType.SEMANTIC,
        subject="Atlas",
        context="runtime",
        attribute="demo-provider",
        importance=0.9,
        confidence=0.97,
        confirmed_days_ago=5,
    ),
    _spec(
        "semantic-live-mode",
        "Atlas live mode uses the configured OpenAI embedding model.",
        MemoryType.SEMANTIC,
        subject="Atlas",
        context="runtime",
        attribute="live-provider",
        importance=0.83,
        confidence=0.91,
        confirmed_days_ago=28,
    ),
    _spec(
        "semantic-recall-score",
        "Atlas recall combines similarity, importance, recency, reinforcement, and confidence.",
        MemoryType.SEMANTIC,
        subject="Atlas",
        context="recall",
        attribute="ranking-formula",
        importance=0.94,
        confidence=0.95,
        confirmed_days_ago=8,
    ),
    _spec(
        "semantic-lineage",
        "Atlas preserves corrected facts as immutable memory lineage versions.",
        MemoryType.SEMANTIC,
        subject="Atlas",
        context="persistence",
        attribute="versioning",
        importance=0.92,
        confidence=0.98,
        confirmed_days_ago=6,
    ),
    _spec(
        "semantic-scope",
        "Atlas scopes every interaction and memory to one isolated namespace.",
        MemoryType.SEMANTIC,
        subject="Atlas",
        context="persistence",
        attribute="isolation",
        importance=0.92,
        confidence=0.99,
        confirmed_days_ago=4,
    ),
    _spec(
        "semantic-auth",
        "Atlas uses one owner bearer token for private mutation access.",
        MemoryType.SEMANTIC,
        subject="Atlas",
        context="security",
        attribute="owner-auth",
        importance=0.79,
        confidence=0.9,
        confirmed_days_ago=35,
    ),
    _spec(
        "semantic-mcp",
        "Atlas exposes remember, recall, forget, and list memories through MCP.",
        MemoryType.SEMANTIC,
        subject="Atlas",
        context="integrations",
        attribute="mcp-tools",
        importance=0.74,
        confidence=0.86,
        confirmed_days_ago=60,
    ),
    _spec(
        "semantic-contracts",
        "Atlas uses Pydantic models as the shared API contract source of truth.",
        MemoryType.SEMANTIC,
        subject="Atlas",
        context="engineering",
        attribute="contracts",
        importance=0.75,
        confidence=0.89,
        confirmed_days_ago=50,
    ),
    _spec(
        "semantic-embedding-dimension",
        "Atlas recall vectors have 1536 dimensions.",
        MemoryType.SEMANTIC,
        subject="Atlas",
        context="recall",
        attribute="embedding-dimensions",
        importance=0.81,
        confidence=0.96,
        confirmed_days_ago=20,
    ),
    _spec(
        "semantic-expired-release",
        "Atlas kept the spring beta release note as historical context.",
        MemoryType.SEMANTIC,
        subject="Atlas",
        context="release-history",
        attribute="beta-release",
        importance=0.46,
        confidence=0.78,
        expires_days_ago=4,
        confirmed_days_ago=180,
    ),
    _spec(
        "semantic-retention-v1",
        "Atlas retains archived memories for one quarter.",
        MemoryType.SEMANTIC,
        subject="Atlas",
        context="retention-policy",
        attribute="archive-window",
        importance=0.62,
        confidence=0.77,
        status=MemoryStatus.DISPUTED,
        version=1,
        lineage="semantic-retention",
        effective_days_ago=75,
        confirmed_days_ago=70,
    ),
    _spec(
        "semantic-retention-v2",
        "Atlas retains archived memories for six months.",
        MemoryType.SEMANTIC,
        subject="Atlas",
        context="retention-policy",
        attribute="archive-window",
        importance=0.7,
        confidence=0.79,
        status=MemoryStatus.DISPUTED,
        version=2,
        lineage="semantic-retention",
        effective_days_ago=45,
        confirmed_days_ago=40,
    ),
    # Episodic memories (11 rows)
    _spec(
        "episode-review-april",
        "Atlas demo review happened after the April reliability sprint.",
        MemoryType.EPISODIC,
        subject="Atlas",
        context="team-history",
        attribute="demo-review",
        importance=0.58,
        confidence=0.88,
        confirmed_days_ago=110,
    ),
    _spec(
        "episode-review-may",
        "Atlas demo review happened after the May retrieval sprint.",
        MemoryType.EPISODIC,
        subject="Atlas",
        context="team-history",
        attribute="demo-review",
        importance=0.64,
        confidence=0.9,
        confirmed_days_ago=78,
    ),
    _spec(
        "episode-incident-cache",
        "Atlas recovered from a cache stampede during the staging rehearsal.",
        MemoryType.EPISODIC,
        subject="Atlas",
        context="incidents",
        attribute="cache-stampede",
        importance=0.86,
        confidence=0.94,
        confirmed_days_ago=26,
    ),
    _spec(
        "episode-incident-index",
        "Atlas fixed a slow memory history query by adding a scoped index.",
        MemoryType.EPISODIC,
        subject="Atlas",
        context="incidents",
        attribute="history-index",
        importance=0.78,
        confidence=0.91,
        confirmed_days_ago=44,
    ),
    _spec(
        "episode-user-study",
        "Atlas user study showed that explanations are easier to trust with visible evidence.",
        MemoryType.EPISODIC,
        subject="Atlas",
        context="research",
        attribute="evidence-study",
        importance=0.81,
        confidence=0.87,
        confirmed_days_ago=90,
    ),
    _spec(
        "episode-sprint-jan",
        "Atlas completed its first memory ingestion sprint in January.",
        MemoryType.EPISODIC,
        subject="Atlas",
        context="milestones",
        attribute="ingestion-sprint",
        importance=0.62,
        confidence=0.92,
        confirmed_days_ago=190,
    ),
    _spec(
        "episode-sprint-feb",
        "Atlas completed its first explainable recall sprint in February.",
        MemoryType.EPISODIC,
        subject="Atlas",
        context="milestones",
        attribute="recall-sprint",
        importance=0.7,
        confidence=0.93,
        confirmed_days_ago=170,
    ),
    _spec(
        "episode-conference",
        "Atlas team presented the lineage explorer at the fictional Lantern conference.",
        MemoryType.EPISODIC,
        subject="Atlas",
        context="milestones",
        attribute="lantern-conference",
        importance=0.58,
        confidence=0.82,
        confirmed_days_ago=130,
    ),
    _spec(
        "episode-migration",
        "Atlas migrated its staging database to PostgreSQL 17 during a quiet window.",
        MemoryType.EPISODIC,
        subject="Atlas",
        context="operations",
        attribute="postgres-migration",
        importance=0.77,
        confidence=0.9,
        confirmed_days_ago=57,
    ),
    _spec(
        "episode-retro",
        "Atlas retro identified ambiguous supersession as a risk worth preserving.",
        MemoryType.EPISODIC,
        subject="Atlas",
        context="team-process",
        attribute="supersession-risk",
        importance=0.79,
        confidence=0.88,
        confirmed_days_ago=36,
    ),
    _spec(
        "episode-design-day",
        "Atlas held a design day for the public memory contracts.",
        MemoryType.EPISODIC,
        subject="Atlas",
        context="team-process",
        attribute="contract-design",
        importance=0.65,
        confidence=0.86,
        status=MemoryStatus.FORGOTTEN,
        confirmed_days_ago=240,
    ),
    # Procedural memories (11 rows)
    _spec(
        "procedure-local-api",
        "Run Atlas locally with uv run uvicorn memoryos.main:app --reload.",
        MemoryType.PROCEDURAL,
        subject="Atlas",
        context="local-development",
        attribute="start-api",
        importance=0.88,
        confidence=0.96,
        confirmed_days_ago=4,
    ),
    _spec(
        "procedure-migrations",
        "Apply Atlas schema changes with uv run alembic upgrade head.",
        MemoryType.PROCEDURAL,
        subject="Atlas",
        context="local-development",
        attribute="apply-migrations",
        importance=0.9,
        confidence=0.98,
        confirmed_days_ago=3,
    ),
    _spec(
        "procedure-seed",
        "Load Atlas demo fixtures with uv run memoryos-seed.",
        MemoryType.PROCEDURAL,
        subject="Atlas",
        context="local-development",
        attribute="load-demo",
        importance=0.78,
        confidence=0.92,
        confirmed_days_ago=16,
    ),
    _spec(
        "procedure-review-memory",
        "Review a new Atlas memory by checking evidence, identity keys, and confidence.",
        MemoryType.PROCEDURAL,
        subject="Atlas",
        context="ingestion",
        attribute="validate-memory",
        importance=0.84,
        confidence=0.93,
        confirmed_days_ago=11,
    ),
    _spec(
        "procedure-resolve",
        "Resolve an Atlas conflict by selecting one disputed lineage version.",
        MemoryType.PROCEDURAL,
        subject="Atlas",
        context="memory-maintenance",
        attribute="resolve-conflict",
        importance=0.82,
        confidence=0.9,
        confirmed_days_ago=22,
    ),
    _spec(
        "procedure-forget",
        "Forget an Atlas fact only through the owner mutation endpoint.",
        MemoryType.PROCEDURAL,
        subject="Atlas",
        context="memory-maintenance",
        attribute="forget-memory",
        importance=0.8,
        confidence=0.9,
        confirmed_days_ago=27,
    ),
    _spec(
        "procedure-recall-lab",
        "Use Atlas recall compare to inspect naive similarity beside policy ranking.",
        MemoryType.PROCEDURAL,
        subject="Atlas",
        context="evaluation",
        attribute="compare-recall",
        importance=0.73,
        confidence=0.88,
        confirmed_days_ago=48,
    ),
    _spec(
        "procedure-rollback",
        "Roll back an Atlas mutation by retrying from the observed scope revision.",
        MemoryType.PROCEDURAL,
        subject="Atlas",
        context="operations",
        attribute="revision-retry",
        importance=0.78,
        confidence=0.86,
        confirmed_days_ago=61,
    ),
    _spec(
        "procedure-health",
        "Check Atlas readiness with GET /health/ready before a private mutation.",
        MemoryType.PROCEDURAL,
        subject="Atlas",
        context="operations",
        attribute="readiness-check",
        importance=0.64,
        confidence=0.85,
        confirmed_days_ago=70,
    ),
    _spec(
        "procedure-mcp",
        "Connect an MCP client to Atlas at the streamable HTTP /mcp endpoint.",
        MemoryType.PROCEDURAL,
        subject="Atlas",
        context="integrations",
        attribute="mcp-connect",
        importance=0.66,
        confidence=0.83,
        confirmed_days_ago=84,
    ),
    _spec(
        "procedure-expiring",
        "Archive the Atlas beta reminder after its expiry date passes.",
        MemoryType.PROCEDURAL,
        subject="Atlas",
        context="release-process",
        attribute="archive-expired",
        importance=0.45,
        confidence=0.76,
        expires_days_ago=2,
        confirmed_days_ago=180,
    ),
)


_SCENARIOS: tuple[DemoScenario, ...] = (
    DemoScenario(
        id="demo-pref-python-new",
        title="Capture a response preference",
        description="Create a concise-answer preference with a Python example.",
        text="For Atlas, keep answers concise and use Python examples.",
        expected_outcome="created",
    ),
    DemoScenario(
        id="demo-pref-python-reinforce",
        title="Reinforce an existing preference",
        description="Confirm the same preference in a distinct interaction.",
        text="As before, Atlas still prefers concise Python examples.",
        expected_outcome="reinforced",
    ),
    DemoScenario(
        id="demo-pref-style-supersede",
        title="Apply an explicit correction",
        description="Use an explicit from-now-on correction to create a new version.",
        text="From now on, Atlas wants short answers with one concrete example.",
        expected_outcome="superseded",
    ),
    DemoScenario(
        id="demo-pref-style-dispute",
        title="Preserve an ambiguous conflict",
        description="Keep both versions when the correction evidence is ambiguous.",
        text="Atlas might prefer a different response style.",
        expected_outcome="disputed",
    ),
    DemoScenario(
        id="demo-procedure-new",
        title="Remember a runbook step",
        description="Create a procedural memory for starting the API.",
        text="To start Atlas locally, run uv run uvicorn memoryos.main:app --reload.",
        expected_outcome="created",
    ),
    DemoScenario(
        id="demo-episode-new",
        title="Remember a milestone",
        description="Create an episodic memory about the Lantern conference.",
        text="Atlas presented the lineage explorer at the Lantern conference.",
        expected_outcome="created",
    ),
    DemoScenario(
        id="demo-skip-greeting",
        title="Skip conversational filler",
        description="Show that a greeting does not create a durable memory.",
        text="Thanks for the update!",
        expected_outcome="skipped",
    ),
)

_QUERIES: tuple[DemoQuery, ...] = (
    DemoQuery(
        id="demo-query-answer-style",
        title="Answer style",
        query="Atlas wants short answers with one concrete example.",
    ),
    DemoQuery(
        id="demo-query-python",
        title="Python examples",
        query="Atlas prefers Python examples for implementation questions.",
    ),
    DemoQuery(
        id="demo-query-persistence",
        title="Persistence",
        query="Atlas preserves corrected facts as immutable memory lineage versions.",
    ),
    DemoQuery(
        id="demo-query-recall",
        title="Recall ranking",
        query=(
            "Atlas recall combines similarity, importance, recency, reinforcement, and confidence."
        ),
    ),
    DemoQuery(
        id="demo-query-runbook",
        title="Local runbook",
        query="Apply Atlas schema changes with uv run alembic upgrade head.",
    ),
    DemoQuery(
        id="demo-query-incident",
        title="Incident history",
        query="Atlas recovered from a cache stampede during the staging rehearsal.",
    ),
    DemoQuery(
        id="demo-query-mcp",
        title="MCP integration",
        query="Atlas exposes remember, recall, forget, and list memories through MCP.",
    ),
    DemoQuery(
        id="demo-query-tie",
        title="Team process",
        query="Atlas retro identified ambiguous supersession as a risk worth preserving.",
    ),
)


_SCENARIO_CANDIDATES: dict[str, tuple[CandidateMemory, MemoryRelation]] = {
    "demo-pref-python-new": (
        CandidateMemory(
            candidate_id="demo:pref-python:new",
            content="Atlas prefers concise answers with Python examples.",
            memory_type=MemoryType.PREFERENCE,
            subject="Atlas",
            context_key="answer-style",
            attribute_key="response-format",
            importance=0.9,
            confidence=0.94,
            evidence_excerpt="keep answers concise and use Python examples",
        ),
        MemoryRelation.NEW,
    ),
    "demo-pref-python-reinforce": (
        CandidateMemory(
            candidate_id="demo:pref-python:reinforce",
            content="Atlas prefers concise answers with Python examples.",
            memory_type=MemoryType.PREFERENCE,
            subject="Atlas",
            context_key="answer-style",
            attribute_key="response-format",
            importance=0.9,
            confidence=0.95,
            evidence_excerpt="still prefers concise Python examples",
        ),
        MemoryRelation.REINFORCE,
    ),
    "demo-pref-style-supersede": (
        CandidateMemory(
            candidate_id="demo:pref-style:supersede",
            content="Atlas wants short answers with one concrete example.",
            memory_type=MemoryType.PREFERENCE,
            subject="Atlas",
            context_key="answer-style",
            attribute_key="response-format",
            importance=0.92,
            confidence=0.94,
            evidence_excerpt="From now on, Atlas wants short answers",
        ),
        MemoryRelation.SUPERSEDE,
    ),
    "demo-pref-style-dispute": (
        CandidateMemory(
            candidate_id="demo:pref-style:dispute",
            content="Atlas may prefer paragraph answers without examples.",
            memory_type=MemoryType.PREFERENCE,
            subject="Atlas",
            context_key="answer-style",
            attribute_key="response-format",
            importance=0.75,
            confidence=0.86,
            evidence_excerpt="might prefer a different response style",
        ),
        MemoryRelation.DISPUTE,
    ),
    "demo-procedure-new": (
        CandidateMemory(
            candidate_id="demo:procedure:start-api:new",
            content="Run Atlas locally with uv run uvicorn memoryos.main:app --reload.",
            memory_type=MemoryType.PROCEDURAL,
            subject="Atlas",
            context_key="local-development",
            attribute_key="start-api",
            importance=0.88,
            confidence=0.96,
            evidence_excerpt="run uv run uvicorn memoryos.main:app --reload",
        ),
        MemoryRelation.NEW,
    ),
    "demo-episode-new": (
        CandidateMemory(
            candidate_id="demo:episode:lantern:new",
            content="Atlas presented the lineage explorer at the Lantern conference.",
            memory_type=MemoryType.EPISODIC,
            subject="Atlas",
            context_key="milestones",
            attribute_key="lantern-conference",
            importance=0.58,
            confidence=0.9,
            evidence_excerpt="presented the lineage explorer at the Lantern conference",
        ),
        MemoryRelation.NEW,
    ),
    "demo-skip-greeting": (
        CandidateMemory(
            candidate_id="demo:greeting:skip",
            content="Atlas exchanged a routine greeting.",
            memory_type=MemoryType.EPISODIC,
            subject="Atlas",
            context_key="conversation",
            attribute_key="greeting",
            importance=0.1,
            confidence=0.99,
            evidence_excerpt="Thanks for the update",
            worth_remembering=False,
            skip_reason="Routine conversational filler is not durable memory.",
        ),
        MemoryRelation.SKIP,
    ),
}

_SCENARIO_BY_TEXT = {_normalize(scenario.text): scenario for scenario in _SCENARIOS}
_RELATION_BY_CANDIDATE = {
    candidate.candidate_id: relation for candidate, relation in _SCENARIO_CANDIDATES.values()
}


def seed_specs() -> tuple[SeedMemorySpec, ...]:
    """Return immutable seed definitions for the idempotent CLI."""

    return _SEED_SPECS


def get_catalog() -> DemoCatalogResponse:
    """Return the finite public catalog description."""

    return DemoCatalogResponse(
        scope_id=DEMO_SCOPE_ID,
        embedding_model=DEMO_MODEL,
        notice=CATALOG_NOTICE,
        scenarios=list(_SCENARIOS),
        queries=list(_QUERIES),
    )


def is_allowed_demo_scenario(text: str) -> bool:
    return _normalize(text) in _SCENARIO_BY_TEXT


def is_allowed_demo_query(text: str) -> bool:
    return any(_normalize(text) == _normalize(query.query) for query in _QUERIES)


def fixture_candidates(text: str) -> list[CandidateMemory]:
    """Return candidates for one exact allowlisted scenario text."""

    scenario = _SCENARIO_BY_TEXT.get(_normalize(text))
    if scenario is None:
        raise ValueError("unsupported demo input")
    candidate, _ = _SCENARIO_CANDIDATES[scenario.id]
    return [candidate]


def fixture_relation(candidate_id: str) -> MemoryRelation:
    """Return the allowlisted relation encoded by a fixture candidate ID."""

    try:
        return _RELATION_BY_CANDIDATE[candidate_id]
    except KeyError as exc:
        raise ValueError("unknown demo candidate") from exc


def _known_fixture_texts() -> set[str]:
    values = {_normalize(spec.content) for spec in _SEED_SPECS}
    values.update(_normalize(scenario.text) for scenario in _SCENARIOS)
    values.update(_normalize(candidate.content) for candidate, _ in _SCENARIO_CANDIDATES.values())
    values.update(_normalize(query.query) for query in _QUERIES)
    return values


_KNOWN_FIXTURE_TEXTS = _known_fixture_texts()


def _fixture_vector(text: str) -> list[float]:
    """Build a stable authored-topic vector, never a claimed provider embedding."""

    normalized = _normalize(text)
    digest = hashlib.sha256(normalized.encode("utf-8")).digest()
    values = [0.0] * DEMO_DIMENSIONS
    tokens = set(_TOKEN_RE.findall(normalized))
    matched_topics = [
        topic for topic, vocabulary in _TOPIC_WORDS.items() if tokens.intersection(vocabulary)
    ]
    # Related authored memories share these topic axes, while token axes retain
    # enough variation for honest cosine ties and near-ties.
    for topic in matched_topics:
        topic_digest = hashlib.sha256(topic.encode("utf-8")).digest()
        base = int.from_bytes(topic_digest[:2], "big") % DEMO_DIMENSIONS
        values[base] += 1.0
        values[(base + 1) % DEMO_DIMENSIONS] += 0.35
        values[(base + 2) % DEMO_DIMENSIONS] += 0.2
    for token in tokens:
        token_digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(token_digest[:2], "big") % DEMO_DIMENSIONS
        values[index] += 0.08
    # Keep every fixture vector nonzero, including an unusual but known text
    # that has no topic vocabulary.
    if not matched_topics:
        for offset in range(0, len(digest), 2):
            index = int.from_bytes(digest[offset : offset + 2], "big") % DEMO_DIMENSIONS
            values[index] += 0.1
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        values[0] = 1.0
        norm = 1.0
    return [value / norm for value in values]


def fixture_embeddings(texts: Sequence[str]) -> list[list[float]]:
    """Embed only known catalog texts with deterministic 1536-D fixture vectors."""

    vectors: list[list[float]] = []
    for text in texts:
        if _normalize(text) not in _KNOWN_FIXTURE_TEXTS:
            raise ValueError("unsupported demo input")
        vectors.append(_fixture_vector(text))
    return vectors


__all__ = [
    "CATALOG_NOTICE",
    "DEMO_DIMENSIONS",
    "DEMO_MODEL",
    "DEMO_SCOPE_ID",
    "LIVE_SCOPE_ID",
    "SeedMemorySpec",
    "fixture_candidates",
    "fixture_embeddings",
    "fixture_relation",
    "get_catalog",
    "is_allowed_demo_query",
    "is_allowed_demo_scenario",
    "seed_specs",
]
