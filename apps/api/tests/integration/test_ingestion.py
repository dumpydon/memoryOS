"""End-to-end ingestion lifecycle against an isolated PostgreSQL scope."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select, text
from sqlalchemy.exc import OperationalError

from memoryos.config import Settings
from memoryos.contracts.ingestion import (
    CandidateMemory,
    IngestInteractionRequest,
    RelationAssessment,
)
from memoryos.db.models import Interaction, Memory, MemoryEvent, Scope
from memoryos.db.repositories import MemoryRepository
from memoryos.db.session import create_db_engine, create_session_factory
from memoryos.domain.enums import (
    ExecutionMode,
    IngestDecisionType,
    MemoryRelation,
    MemoryStatus,
    MemoryType,
)
from memoryos.providers.errors import ProviderUnavailable
from memoryos.seed.catalog import DEMO_MODEL, fixture_embeddings
from memoryos.services.errors import ServiceError
from memoryos.services.ingestion import MemoryIngestionService

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _settings() -> Settings:
    return Settings(
        database_url=os.environ.get("TEST_DATABASE_URL") or Settings().database_url,
        demo_embedding_model=DEMO_MODEL,
        demo_embedding_dimensions=1536,
    )


@pytest.fixture(scope="session")
def database() -> Settings:
    settings = _settings()
    engine = create_db_engine(settings)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except (OperationalError, OSError) as exc:
        engine.dispose()
        if os.environ.get("TEST_DATABASE_URL"):
            pytest.fail(f"TEST_DATABASE_URL is unavailable: {exc}")
        pytest.skip(f"PostgreSQL integration database is unavailable: {exc}")
    cfg = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    cfg.attributes["database_url"] = settings.database_url
    command.upgrade(cfg, "head")
    yield settings
    engine.dispose()


@pytest.fixture()
def isolated_scope(database: Settings):
    factory = create_session_factory(database)
    scope_id = uuid4()
    with factory.begin() as session:
        MemoryRepository(session, database).create_scope(
            scope_id=scope_id,
            name="isolated-ingestion-test",
            embedding_model=DEMO_MODEL,
        )
        repo = MemoryRepository(session, database)
        vector = fixture_embeddings(["Atlas prefers concise answers with Python examples."])[0]
        repo.insert_memory(
            scope_id=scope_id,
            content="Atlas prefers concise answers with Python examples.",
            memory_type="preference",
            subject="Atlas",
            context_key="answer-style",
            attribute_key="response-format",
            importance=0.8,
            confidence=0.8,
            embedding=vector,
            embedding_model=DEMO_MODEL,
            effective_at=NOW - timedelta(days=2),
            last_confirmed_at=NOW - timedelta(days=2),
        )
    try:
        yield factory, scope_id
    finally:
        with factory.begin() as session:
            session.execute(delete(Scope).where(Scope.id == scope_id))
        factory.kw["bind"].dispose()


def test_remember_reinforce_supersede_dispute_is_atomic_and_scoped(isolated_scope) -> None:
    factory, scope_id = isolated_scope
    service = MemoryIngestionService(_settings(), factory)

    reinforce = service.ingest(
        IngestInteractionRequest(
            scope_id=scope_id,
            text="As before, Atlas still prefers concise Python examples.",
            occurred_at=NOW,
            idempotency_key="lifecycle-reinforce",
            mode=ExecutionMode.DEMO,
        )
    )
    assert reinforce.decisions[0].decision_type is IngestDecisionType.REINFORCED
    assert reinforce.decisions[0].confidence == pytest.approx(0.8095)

    with factory() as session:
        repo = MemoryRepository(session, _settings())
        reinforced = repo.get_by_id(scope_id, reinforce.memory_ids[0])
        assert reinforced is not None
        assert reinforced.reinforcement_count == 1
        assert reinforced.confidence == pytest.approx(0.8095)

    superseded = service.ingest(
        IngestInteractionRequest(
            scope_id=scope_id,
            text="From now on, Atlas wants short answers with one concrete example.",
            occurred_at=NOW + timedelta(days=1),
            idempotency_key="lifecycle-supersede",
            mode=ExecutionMode.DEMO,
        )
    )
    assert superseded.decisions[0].decision_type is IngestDecisionType.SUPERSEDED
    assert len(superseded.memory_ids) == 2

    disputed = service.ingest(
        IngestInteractionRequest(
            scope_id=scope_id,
            text="Atlas might prefer a different response style.",
            occurred_at=NOW + timedelta(days=2),
            idempotency_key="lifecycle-dispute",
            mode=ExecutionMode.DEMO,
        )
    )
    assert disputed.decisions[0].decision_type is IngestDecisionType.DISPUTED
    assert len(disputed.memory_ids) == 2
    assert [step.node for step in disputed.trace.steps] == [
        "extract",
        "embed",
        "find_related",
        "assess_relations",
        "validate_plan",
        "persist",
    ]

    with factory() as session:
        rows = list(
            session.query(Memory)
            .filter(
                Memory.scope_id == scope_id,
                Memory.context_key == "answer-style",
                Memory.attribute_key == "response-format",
            )
            .all()
        )
        assert sum(row.status is MemoryStatus.ACTIVE for row in rows) == 0
        assert sum(row.status is MemoryStatus.DISPUTED for row in rows) == 2


def test_live_style_paraphrase_reinforces_existing_memory_without_duplicate(isolated_scope) -> None:
    factory, scope_id = isolated_scope
    settings = _settings()
    source = (
        "I still strongly prefer concise explanations when learning algorithms. "
        "Please keep explanations short and focused."
    )
    existing_id = uuid4()
    with factory.begin() as session:
        repo = MemoryRepository(session, settings)
        repo.insert_memory(
            scope_id=scope_id,
            memory_id=existing_id,
            content="The user prefers concise explanations when learning algorithms.",
            memory_type=MemoryType.PREFERENCE,
            subject="user",
            context_key="learning_algorithms",
            attribute_key="explanation_length",
            importance=0.8,
            confidence=0.99,
            embedding=fixture_embeddings(
                ["Atlas prefers concise answers with Python examples."]
            )[0],
            embedding_model=DEMO_MODEL,
            effective_at=NOW - timedelta(days=1),
            last_confirmed_at=NOW - timedelta(days=1),
        )

    class StubEmbeddingProvider:
        model_name = DEMO_MODEL
        dimensions = 1536

        def embed(self, texts):
            vector = fixture_embeddings(
                ["Atlas prefers concise answers with Python examples."]
            )[0]
            return [list(vector) for _ in texts]

    class StubStructuredProvider:
        model_name = "test-structured"

        def extract_candidates(self, *, text):
            return [
                CandidateMemory(
                    candidate_id="reported-paraphrase",
                    content=(
                        "The user strongly prefers short, focused explanations "
                        "when learning algorithms."
                    ),
                    memory_type=MemoryType.PREFERENCE,
                    subject="user",
                    context_key="learning_algorithms",
                    attribute_key="explanation_style",
                    importance=0.88,
                    confidence=0.99,
                    evidence_excerpt=source,
                )
            ]

        def assess_relations(self, *, candidates, related_memories, source_text=None):
            target = next(memory for memory in related_memories if memory.id == existing_id)
            return [
                RelationAssessment(
                    candidate_id=candidates[0].candidate_id,
                    related_memory_id=target.id,
                    relation=MemoryRelation.REINFORCE,
                    confidence=0.95,
                    evidence_excerpt=source_text or source,
                    reason_code="same_context_confirmation",
                    reason_summary="The source confirms the existing preference.",
                )
            ]

    service = MemoryIngestionService(
        settings,
        factory,
        embedding_factory=lambda mode, current_settings: StubEmbeddingProvider(),
        structured_factory=lambda mode, current_settings: StubStructuredProvider(),
    )
    response = service.ingest(
        IngestInteractionRequest(
            scope_id=scope_id,
            text=source,
            occurred_at=NOW,
            idempotency_key="reported-paraphrase-reinforcement",
            mode=ExecutionMode.DEMO,
        )
    )

    assert response.decisions[0].decision_type is IngestDecisionType.REINFORCED
    assert response.decisions[0].memory_id == existing_id
    assert response.memory_ids == [existing_id]
    with factory() as session:
        repo = MemoryRepository(session, settings)
        reinforced = repo.get_by_id(scope_id, existing_id)
        history = repo.get_history(scope_id=scope_id, memory_id=existing_id)
        rows = list(session.scalars(select(Memory).where(Memory.scope_id == scope_id)))
        assert reinforced is not None
        assert reinforced.reinforcement_count == 1
        assert reinforced.last_confirmed_at == NOW
        assert history is not None
        assert history.events[-1].event_type.value == "reinforced"
        assert history.events[-1].evidence_excerpt == source
        assert len(rows) == 2


def test_distinct_reinforcements_keep_provenance_and_replay_is_idempotent(isolated_scope) -> None:
    factory, scope_id = isolated_scope
    settings = _settings()
    source_a = (
        "I still strongly prefer concise explanations when learning algorithms. "
        "Please keep explanations short and focused."
    )
    source_b = (
        "For algorithm lessons, I continue to prefer concise, short, focused explanations."
    )
    existing_id = uuid4()
    with factory.begin() as session:
        repo = MemoryRepository(session, settings)
        repo.insert_memory(
            scope_id=scope_id,
            memory_id=existing_id,
            content="The user prefers concise explanations when learning algorithms.",
            memory_type=MemoryType.PREFERENCE,
            subject="user",
            context_key="learning_algorithms",
            attribute_key="explanation_length",
            importance=0.80,
            confidence=0.80,
            embedding=fixture_embeddings(
                ["Atlas prefers concise answers with Python examples."]
            )[0],
            embedding_model=DEMO_MODEL,
            effective_at=NOW - timedelta(days=1),
            last_confirmed_at=NOW - timedelta(days=1),
        )

    class StubEmbeddingProvider:
        model_name = DEMO_MODEL
        dimensions = 1536

        def embed(self, texts):
            vector = fixture_embeddings(
                ["Atlas prefers concise answers with Python examples."]
            )[0]
            return [list(vector) for _ in texts]

    class StubStructuredProvider:
        model_name = "test-structured"

        def extract_candidates(self, *, text):
            return [
                CandidateMemory(
                    candidate_id="distinct-reinforcement",
                    content=(
                        "The user strongly prefers concise, focused explanations "
                        "when learning algorithms."
                    ),
                    memory_type=MemoryType.PREFERENCE,
                    subject="user",
                    context_key="learning_algorithms",
                    attribute_key="explanation_style",
                    importance=0.86,
                    confidence=0.99,
                    evidence_excerpt=text,
                )
            ]

        def assess_relations(self, *, candidates, related_memories, source_text=None):
            target = next(memory for memory in related_memories if memory.id == existing_id)
            return [
                RelationAssessment(
                    candidate_id=candidates[0].candidate_id,
                    related_memory_id=target.id,
                    relation=MemoryRelation.REINFORCE,
                    confidence=0.95,
                    evidence_excerpt=source_text or source_a,
                    reason_code="same_context_confirmation",
                    reason_summary="The source confirms the existing preference.",
                )
            ]

    service = MemoryIngestionService(
        settings,
        factory,
        embedding_factory=lambda mode, current_settings: StubEmbeddingProvider(),
        structured_factory=lambda mode, current_settings: StubStructuredProvider(),
    )
    request_a = IngestInteractionRequest(
        scope_id=scope_id,
        text=source_a,
        source_ref="playground",
        occurred_at=NOW,
        idempotency_key="distinct-reinforcement-a",
        mode=ExecutionMode.DEMO,
    )
    request_b = IngestInteractionRequest(
        scope_id=scope_id,
        text=source_b,
        source_ref="playground",
        occurred_at=NOW + timedelta(hours=1),
        idempotency_key="distinct-reinforcement-b",
        mode=ExecutionMode.DEMO,
    )
    first = service.ingest(request_a)
    second = service.ingest(request_b)
    replay = service.ingest(request_b)

    assert first.decisions[0].decision_type is IngestDecisionType.REINFORCED
    assert second.decisions[0].decision_type is IngestDecisionType.REINFORCED
    assert first.candidates[0].importance == pytest.approx(0.86)
    assert second.candidates[0].importance == pytest.approx(0.86)
    assert replay == second
    with factory() as session:
        repo = MemoryRepository(session, settings)
        memory = repo.get_by_id(scope_id, existing_id)
        assert memory is not None
        assert memory.importance == pytest.approx(0.80)
        assert memory.reinforcement_count == 2
        events = list(
            session.scalars(
                select(MemoryEvent)
                .where(
                    MemoryEvent.scope_id == scope_id,
                    MemoryEvent.memory_id == existing_id,
                    MemoryEvent.event_type == "reinforced",
                )
                .order_by(MemoryEvent.created_at.asc(), MemoryEvent.id.asc())
            )
        )
        assert len(events) == 2
        assert len({event.id for event in events}) == 2
        assert [event.created_at for event in events] == sorted(
            event.created_at for event in events
        )
        assert all(event.memory_id == existing_id for event in events)
        assert all(event.related_memory_id == existing_id for event in events)
        assert [event.interaction_id for event in events] == [
            first.interaction_id,
            second.interaction_id,
        ]
        assert [event.evidence_excerpt for event in events] == [source_a, source_b]
        assert [event.relation for event in events] == [
            MemoryRelation.REINFORCE,
            MemoryRelation.REINFORCE,
        ]
        assert [event.provenance for event in events] == ["playground", "playground"]
        assert events[0].after["relation_confidence"] == pytest.approx(0.95)
        assert events[1].after["relation_confidence"] == pytest.approx(0.95)
        interactions = list(
            session.scalars(
                select(Interaction)
                .where(
                    Interaction.scope_id == scope_id,
                    Interaction.id.in_([event.interaction_id for event in events]),
                )
                .order_by(Interaction.occurred_at.asc(), Interaction.id.asc())
            )
        )
        assert [interaction.idempotency_key for interaction in interactions] == [
            request_a.idempotency_key,
            request_b.idempotency_key,
        ]
        memory_rows = list(
            session.scalars(
                select(Memory).where(
                    Memory.scope_id == scope_id,
                    Memory.id == existing_id,
                )
            )
        )
        assert len(memory_rows) == 1


def test_replay_and_preview_do_not_write_again(isolated_scope) -> None:
    factory, scope_id = isolated_scope
    service = MemoryIngestionService(_settings(), factory)
    request = IngestInteractionRequest(
        scope_id=scope_id,
        text="To start Atlas locally, run uv run uvicorn memoryos.main:app --reload.",
        idempotency_key="replay-request",
        mode=ExecutionMode.DEMO,
    )
    first = service.ingest(request)
    with factory() as session:
        before = MemoryRepository(session, _settings()).require_scope(scope_id).revision
    replay = service.ingest(request)
    with factory() as session:
        after = MemoryRepository(session, _settings()).require_scope(scope_id).revision
    assert replay.interaction_id == first.interaction_id
    assert replay.memory_ids == first.memory_ids
    assert replay == first
    assert before == after

    preview = service.ingest(
        IngestInteractionRequest(
            scope_id=scope_id,
            text="Thanks for the update!",
            mode=ExecutionMode.DEMO,
            preview=True,
        )
    )
    with factory() as session:
        final = MemoryRepository(session, _settings()).require_scope(scope_id).revision
    assert preview.status.value == "preview"
    assert preview.decisions[0].decision_type is IngestDecisionType.SKIPPED
    assert final == after


def test_provider_failure_leaves_scope_and_interactions_unchanged(isolated_scope) -> None:
    factory, scope_id = isolated_scope

    def failing_embedding(mode, settings):
        raise ProviderUnavailable("fixture failure")

    service = MemoryIngestionService(
        _settings(),
        factory,
        embedding_factory=failing_embedding,
    )
    with factory() as session:
        before = MemoryRepository(session, _settings()).require_scope(scope_id).revision
    with pytest.raises(ServiceError) as error:
        service.ingest(
            IngestInteractionRequest(
                scope_id=scope_id,
                text="To start Atlas locally, run uv run uvicorn memoryos.main:app --reload.",
                idempotency_key="provider-failure",
                mode=ExecutionMode.DEMO,
            )
        )
    with factory() as session:
        repo = MemoryRepository(session, _settings())
        after = repo.require_scope(scope_id).revision
        assert (
            repo.get_interaction_by_idempotency(
                scope_id=scope_id,
                idempotency_key="provider-failure",
            )
            is None
        )
    assert error.value.code == "provider_unavailable"
    assert after == before
