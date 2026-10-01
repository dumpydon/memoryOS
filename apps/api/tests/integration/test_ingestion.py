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
    AdmissionSignals,
    CandidateMemory,
    IngestInteractionRequest,
    RelationAssessment,
)
from memoryos.contracts.recall import RecallRequest
from memoryos.db.models import Interaction, Memory, MemoryEvent, MemoryReview, Scope
from memoryos.db.repositories import MemoryRepository
from memoryos.db.session import create_db_engine, create_session_factory
from memoryos.domain.enums import (
    ExecutionMode,
    IngestDecisionType,
    MemoryEventType,
    MemoryRelation,
    MemoryStatus,
    MemoryType,
)
from memoryos.providers.errors import ProviderUnavailable
from memoryos.seed.catalog import DEMO_MODEL, fixture_embeddings
from memoryos.services.errors import ServiceError
from memoryos.services.ingestion import MemoryIngestionService
from memoryos.services.query import MemoryQueryService

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
            text="Atlas prefers paragraph answers without examples.",
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
            embedding=fixture_embeddings(["Atlas prefers concise answers with Python examples."])[
                0
            ],
            embedding_model=DEMO_MODEL,
            effective_at=NOW - timedelta(days=1),
            last_confirmed_at=NOW - timedelta(days=1),
        )

    class StubEmbeddingProvider:
        model_name = DEMO_MODEL
        dimensions = 1536

        def embed(self, texts):
            vector = fixture_embeddings(["Atlas prefers concise answers with Python examples."])[0]
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
                    admission=AdmissionSignals(
                        durability="lasting",
                        future_value="personalization",
                        specificity="specific",
                        evidence_source="user",
                        content_kind="information",
                    ),
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
    source_b = "For algorithm lessons, I continue to prefer concise, short, focused explanations."
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
            embedding=fixture_embeddings(["Atlas prefers concise answers with Python examples."])[
                0
            ],
            embedding_model=DEMO_MODEL,
            effective_at=NOW - timedelta(days=1),
            last_confirmed_at=NOW - timedelta(days=1),
        )

    class StubEmbeddingProvider:
        model_name = DEMO_MODEL
        dimensions = 1536

        def embed(self, texts):
            vector = fixture_embeddings(["Atlas prefers concise answers with Python examples."])[0]
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
                    admission=AdmissionSignals(
                        durability="lasting",
                        future_value="personalization",
                        specificity="specific",
                        evidence_source="user",
                        content_kind="information",
                    ),
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


@pytest.mark.parametrize(
    "text",
    [
        "thanks",
        "okay",
        "Explain this error once for this conversation.",
        "Atlas might prefer a different response style.",
        "Assistant: Atlas uses MongoDB. The user has not confirmed this.",
        "What time is it?",
        "I am tired right now.",
    ],
)
def test_admission_rejection_has_no_embedding_memory_or_history_side_effects(isolated_scope, text):
    from memoryos.providers.demo import DemoStructuredProvider

    factory, scope_id = isolated_scope
    settings = _settings()
    calls = []

    class NoEmbedding:
        model_name = DEMO_MODEL
        dimensions = 1536

        def embed(self, texts):
            raise AssertionError("Rejected information reached the embedding provider.")

    class Structured(DemoStructuredProvider):
        def extract_candidates(self, *, text):
            calls.append(text)
            return super().extract_candidates(text=text)

        def assess_relations(self, **kwargs):
            raise AssertionError("Rejected information reached relationship assessment.")

    service = MemoryIngestionService(
        settings,
        factory,
        embedding_factory=lambda mode, settings: NoEmbedding(),
        structured_factory=lambda mode, settings: Structured(settings),
    )
    preview = service.ingest(IngestInteractionRequest(scope_id=scope_id, text=text, preview=True))
    assert preview.memory_ids == []
    assert [step.node for step in preview.trace.steps] == ["extract", "validate_plan", "persist"]
    request = IngestInteractionRequest(
        scope_id=scope_id, text=text, idempotency_key="rejected-input"
    )
    committed = service.ingest(request)
    replay = service.ingest(request)
    assert committed == replay
    assert len(calls) == 2  # Preview and commit; an exact replay never reruns extraction.
    assert committed.memory_ids == []
    assert all(
        decision.decision_type in {IngestDecisionType.SKIPPED, IngestDecisionType.REJECTED}
        for decision in committed.decisions
    )
    with factory() as session:
        rows = list(session.scalars(select(Memory).where(Memory.scope_id == scope_id)))
        assert len(rows) == 1  # Only the pre-existing fixture memory.
        assert rows[0].reinforcement_count == 0
        assert not list(
            session.scalars(select(MemoryEvent).where(MemoryEvent.scope_id == scope_id))
        )
        receipts = list(
            session.scalars(select(Interaction).where(Interaction.scope_id == scope_id))
        )
        assert len(receipts) == 1  # The existing commit/replay receipt, not a memory-history event.


def test_mixed_admission_keeps_the_surviving_candidate_vector_aligned(isolated_scope):
    from memoryos.seed.catalog import fixture_candidates

    factory, scope_id = isolated_scope
    settings = _settings()
    vector = [0.0] * 1536
    vector[1] = 1.0
    embedded = []

    class Embeddings:
        model_name = DEMO_MODEL
        dimensions = 1536

        def embed(self, texts):
            embedded.extend(texts)
            return [vector[:] for text in texts]

    class Structured:
        def extract_candidates(self, *, text):
            return [
                *fixture_candidates("Thanks for the update!"),
                *fixture_candidates("Atlas stores memory event timestamps in UTC."),
            ]

        def assess_relations(self, **kwargs):
            raise AssertionError("No same-type related memory exists in this isolated scope.")

    service = MemoryIngestionService(
        settings,
        factory,
        embedding_factory=lambda mode, settings: Embeddings(),
        structured_factory=lambda mode, settings: Structured(),
    )
    result = service.ingest(
        IngestInteractionRequest(
            scope_id=scope_id,
            text="Thanks for the update! Atlas stores memory event timestamps in UTC.",
            idempotency_key="mixed-admission",
        )
    )
    assert embedded == ["Atlas stores memory event timestamps in UTC."]
    assert len(result.candidates) == 2
    assert [item.decision_type for item in result.decisions] == [
        IngestDecisionType.SKIPPED,
        IngestDecisionType.CREATED,
    ]
    with factory() as session:
        stored = MemoryRepository(session, settings).get_stored_by_id(
            scope_id, result.memory_ids[0]
        )
        assert stored.record.content == embedded[0]
        assert stored.embedding == tuple(vector)


def test_exact_existing_preference_overrides_new_suggestion_to_reinforcement(isolated_scope):
    from memoryos.providers.demo import DemoStructuredProvider

    factory, scope_id = isolated_scope
    settings = _settings()

    class ProposesNew(DemoStructuredProvider):
        def assess_relations(self, *, candidates, related_memories, source_text=None):
            return [
                RelationAssessment(
                    candidate_id=candidates[0].candidate_id,
                    relation=MemoryRelation.NEW,
                    confidence=0.99,
                    evidence_excerpt=candidates[0].evidence_excerpt,
                    reason_code="new",
                    reason_summary="The extractor suggested another memory.",
                )
            ]

    service = MemoryIngestionService(
        settings, factory, structured_factory=lambda mode, settings: ProposesNew(settings)
    )
    request = IngestInteractionRequest(
        scope_id=scope_id,
        text="As before, Atlas still prefers concise Python examples.",
        idempotency_key="exact-repeat",
    )
    result = service.ingest(request)
    assert result.decisions[0].decision_type is IngestDecisionType.REINFORCED
    assert service.ingest(request) == result
    with factory() as session:
        rows = list(session.scalars(select(Memory).where(Memory.scope_id == scope_id)))
        assert len(rows) == 1
        assert rows[0].reinforcement_count == 1
        assert rows[0].importance == 0.8
        events = list(session.scalars(select(MemoryEvent).where(MemoryEvent.scope_id == scope_id)))
        assert len(events) == 1
        assert events[0].event_type is MemoryEventType.REINFORCED


@pytest.mark.parametrize(
    "case,source,old_text,new_text,old_context,new_context,old_attribute,new_attribute,relation,comparison,expected",
    [
        (
            "paraphrase",
            "I still prefer short, focused explanations for DSA.",
            "The user prefers concise explanations when learning algorithms.",
            "The user prefers short, focused explanations when learning algorithms.",
            "learning_algorithms",
            "learning_algorithms",
            "explanation_length",
            "explanation_style",
            MemoryRelation.REINFORCE,
            "equivalent",
            IngestDecisionType.REINFORCED,
        ),
        (
            "editor",
            "I switched from VS Code to Cursor. Cursor is now my primary editor.",
            "The user's primary editor is VS Code.",
            "The user's primary editor is Cursor.",
            "development",
            "development",
            "primary_editor",
            "editor_preference",
            MemoryRelation.SUPERSEDE,
            "incompatible",
            IngestDecisionType.SUPERSEDED,
        ),
        (
            "context",
            "From now on, for system design I prefer detailed explanations with diagrams.",
            "The user prefers concise explanations for DSA.",
            "The user prefers detailed explanations with diagrams for system design.",
            "dsa",
            "system_design",
            "explanation_length",
            "explanation_style",
            MemoryRelation.SUPERSEDE,
            "incompatible",
            IngestDecisionType.CREATED,
        ),
        (
            "conflict",
            "I prefer working from the office.",
            "The user prefers remote work.",
            "The user prefers working from the office.",
            "work",
            "work",
            "workplace_preference",
            "workplace_location",
            MemoryRelation.DISPUTE,
            "incompatible",
            IngestDecisionType.DISPUTED,
        ),
        (
            "separate",
            "I deploy MemoryOS using Render.",
            "The user uses Python for interviews.",
            "The user deploys MemoryOS using Render.",
            "interviews",
            "deployment",
            "programming_language",
            "hosting_provider",
            MemoryRelation.DISPUTE,
            "distinct",
            IngestDecisionType.CREATED,
        ),
    ],
)
def test_validated_relationships_preserve_history_review_and_idempotency(
    isolated_scope,
    case,
    source,
    old_text,
    new_text,
    old_context,
    new_context,
    old_attribute,
    new_attribute,
    relation,
    comparison,
    expected,
):
    factory, scope_id = isolated_scope
    settings = _settings()
    existing_id = uuid4()
    vector = fixture_embeddings(["Atlas prefers concise answers with Python examples."])[0]
    with factory.begin() as session:
        MemoryRepository(session, settings).insert_memory(
            scope_id=scope_id,
            memory_id=existing_id,
            content=old_text,
            memory_type=MemoryType.PREFERENCE,
            subject="user",
            context_key=old_context,
            attribute_key=old_attribute,
            importance=0.85,
            confidence=0.90,
            embedding=vector,
            embedding_model=DEMO_MODEL,
            effective_at=NOW - timedelta(days=1),
            last_confirmed_at=NOW - timedelta(days=1),
        )

    class EmbeddingStub:
        model_name = DEMO_MODEL
        dimensions = 1536

        def embed(self, texts):
            return [vector for _ in texts]

    class StructuredStub:
        def extract_candidates(self, *, text):
            return [
                CandidateMemory(
                    candidate_id="incoming",
                    content=new_text,
                    memory_type=MemoryType.PREFERENCE,
                    subject="user",
                    context_key=new_context,
                    attribute_key=new_attribute,
                    importance=0.85,
                    confidence=0.95,
                    evidence_excerpt=text,
                    admission=AdmissionSignals(
                        durability="lasting",
                        future_value="personalization",
                        specificity="specific",
                        evidence_source="user",
                        content_kind="information",
                    ),
                )
            ]

        def assess_relations(self, *, candidates, related_memories, source_text=None):
            assert existing_id in {item.id for item in related_memories}
            return [
                RelationAssessment(
                    candidate_id="incoming",
                    related_memory_id=existing_id,
                    relation=relation,
                    confidence=0.95,
                    value_comparison=comparison,
                    evidence_excerpt=source,
                    replacement_evidence=source if relation is MemoryRelation.SUPERSEDE else None,
                    reason_code="test_proposal",
                    reason_summary="A proposed relationship, subject to policy.",
                )
            ]

    service = MemoryIngestionService(
        settings,
        factory,
        embedding_factory=lambda *args: EmbeddingStub(),
        structured_factory=lambda *args: StructuredStub(),
    )
    request = IngestInteractionRequest(
        scope_id=scope_id,
        text=source,
        occurred_at=NOW,
        idempotency_key=f"relationship-{case}",
        preview=True,
    )
    preview = service.ingest(request)
    assert preview.decisions[0].decision_type is expected
    assert preview.relation_assessments[0].relation is relation
    with factory() as session:
        assert (
            len(list(session.scalars(select(MemoryEvent).where(MemoryEvent.scope_id == scope_id))))
            == 0
        )
    request = request.model_copy(update={"preview": False})
    result = service.ingest(request)
    assert result.decisions[0].decision_type is expected
    assert service.ingest(request) == result
    with factory() as session:
        repo = MemoryRepository(session, settings)
        old = repo.get_by_id(scope_id, existing_id)
        current = repo.get_by_id(scope_id, result.decisions[0].memory_id)
        assert old is not None and current is not None
        assert old.content == old_text
        rows = list(session.scalars(select(Memory).where(Memory.scope_id == scope_id)))
        events = list(session.scalars(select(MemoryEvent).where(MemoryEvent.scope_id == scope_id)))
        reviews = list(
            session.scalars(select(MemoryReview).where(MemoryReview.scope_id == scope_id))
        )
        assert len(events) == 1
        assert events[0].interaction_id == result.interaction_id
        assert len(rows) == (2 if expected is IngestDecisionType.REINFORCED else 3)
        if expected is IngestDecisionType.REINFORCED:
            assert current.id == existing_id
            assert current.reinforcement_count == 1
            assert events[0].event_type is MemoryEventType.REINFORCED
        elif expected is IngestDecisionType.SUPERSEDED:
            assert old.status is MemoryStatus.SUPERSEDED
            assert old.superseded_by_id == current.id
            assert current.status is MemoryStatus.ACTIVE
            assert current.lineage_id == old.lineage_id
            assert current.version == old.version + 1
            assert events[0].event_type is MemoryEventType.SUPERSEDED
            assert events[0].evidence_excerpt == source
        elif expected is IngestDecisionType.DISPUTED:
            assert old.status is current.status is MemoryStatus.DISPUTED
            assert current.lineage_id == old.lineage_id
            assert len(reviews) == 1 and reviews[0].status == "pending"
            assert reviews[0].existing_memory_id == existing_id
            assert reviews[0].memory_id == current.id
            assert reviews[0].evidence_excerpt == source
        else:
            assert old.status is current.status is MemoryStatus.ACTIVE
            assert old.lineage_id != current.lineage_id
            assert events[0].event_type is MemoryEventType.CREATED
            assert result.decisions[0].reason_code == (
                "contextual_coexistence" if case == "context" else "new_memory"
            )
        if expected is not IngestDecisionType.DISPUTED:
            assert reviews == []
        history = repo.get_history(scope_id=scope_id, memory_id=current.id)
        assert history is not None
        assert history.events[-1].event_type is events[0].event_type


@pytest.mark.parametrize("pending_review", [False, True])
def test_ingestion_consolidation_preserves_sources_counts_recall_and_replay(
    isolated_scope, pending_review
):
    from memoryos.seed.catalog import fixture_candidates

    factory, scope_id = isolated_scope
    settings = _settings()
    source_texts = [
        "Atlas prefers concise algorithm explanations.",
        "Atlas likes short, focused DSA explanations.",
    ]
    source_ids = []
    source_records = []
    source = "Atlas still prefers short, focused explanations for algorithms."
    with factory.begin() as session:
        repo = MemoryRepository(session, settings)
        for index, content in enumerate(source_texts):
            stored = repo.insert_memory(
                scope_id=scope_id,
                content=content,
                memory_type=MemoryType.PREFERENCE,
                subject="Atlas",
                context_key="algorithms",
                attribute_key="explanation-length" if index == 0 else "explanation-style",
                importance=0.85,
                confidence=0.95,
                reinforcement_count=2 if index == 0 else 1,
                embedding=fixture_embeddings([content])[0],
                embedding_model=DEMO_MODEL,
                effective_at=NOW - timedelta(days=2),
                last_confirmed_at=NOW - timedelta(days=1),
            )
            source_ids.append(stored.record.id)
            source_records.append(stored.record)
            repo.insert_event(
                scope_id=scope_id,
                memory_id=stored.record.id,
                event_type=MemoryEventType.CREATED,
                evidence_excerpt=content,
                provenance=f"legacy-import-{index}",
                reason_code="legacy_import",
                reason_summary="Imported source evidence.",
            )
        if pending_review:
            repo.create_review(
                scope_id=scope_id,
                kind="consolidation",
                candidate=fixture_candidates(source)[0].model_copy(
                    update={"content": source_texts[1]}
                ),
                existing_memory=None,
                source_memories=source_records,
                proposed_relation=MemoryRelation.NEW,
                confidence=0.95,
                evidence_excerpt=source_texts[1],
                reason_code="pending_consolidation",
                reason_summary="Awaiting an owner decision.",
                mode=ExecutionMode.DEMO,
            )
    service = MemoryIngestionService(settings, factory)
    request = IngestInteractionRequest(
        scope_id=scope_id,
        text=source,
        occurred_at=NOW,
        source_ref="consolidation-test",
        idempotency_key="consolidation",
        preview=True,
    )
    preview = service.ingest(request)
    expected = IngestDecisionType.REINFORCED if pending_review else IngestDecisionType.CONSOLIDATED
    assert preview.decisions[0].decision_type is expected
    with factory() as session:
        assert len(list(session.scalars(select(Memory).where(Memory.scope_id == scope_id)))) == 3
    request = request.model_copy(update={"preview": False})
    committed = service.ingest(request)
    assert committed.decisions[0].decision_type is expected
    assert service.ingest(request) == committed
    with factory() as session:
        repo = MemoryRepository(session, settings)
        old = [repo.get_by_id(scope_id, value) for value in source_ids]
        current = repo.get_by_id(scope_id, committed.decisions[0].memory_id)
        assert current is not None
        rows = list(session.scalars(select(Memory).where(Memory.scope_id == scope_id)))
        events = list(session.scalars(select(MemoryEvent).where(MemoryEvent.scope_id == scope_id)))
        if pending_review:
            assert all(row.status is MemoryStatus.ACTIVE for row in rows)
            assert len(rows) == 3
            assert "pending review" in committed.decisions[0].consolidation_note
            return
        assert len(rows) == 4
        assert current.content == source_texts[1]
        assert current.reinforcement_count == 3  # max(2, 1) + one distinct confirmation
        assert current.confidence == 0.95
        assert current.status is MemoryStatus.ACTIVE
        assert all(
            memory.status is MemoryStatus.SUPERSEDED and memory.superseded_by_id == current.id
            for memory in old
        )
        assert [memory.content for memory in old] == source_texts
        assert len(events) == 5  # two import events, canonical creation, two retirements
        assert {event.provenance for event in events if event.reason_code == "legacy_import"} == {
            "legacy-import-0",
            "legacy-import-1",
        }
        history = repo.get_history(scope_id=scope_id, memory_id=current.id)
        assert history is not None
        creation = next(
            event for event in history.events if event.reason_code == "memory_consolidated"
        )
        assert set(creation.after["source_memory_ids"]) == {str(value) for value in source_ids}
        assert creation.evidence_excerpt == source
        for value in source_ids:
            source_history = repo.get_history(scope_id=scope_id, memory_id=value)
            assert len(source_history.events) == 2
    recall = MemoryQueryService(settings, factory).recall(
        RecallRequest(
            scope_id=scope_id,
            query=source_texts[1],
            as_of=NOW,
            limit=20,
            min_similarity=0,
        )
    )
    recalled_ids = {item.memory.id for item in recall.items}
    assert current.id in recalled_ids
    assert not recalled_ids & set(source_ids)
    confirmed = service.ingest(
        request.model_copy(update={"idempotency_key": "canonical-confirmation"})
    )
    assert confirmed.decisions[0].decision_type is IngestDecisionType.REINFORCED
    assert confirmed.memory_ids == [current.id]
    with factory() as session:
        assert len(list(session.scalars(select(Memory).where(Memory.scope_id == scope_id)))) == 4
