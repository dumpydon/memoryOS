"""Focused persistence coverage for the Phase 2 review engine."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select, text
from sqlalchemy.exc import OperationalError

from memoryos.config import Settings
from memoryos.contracts.ingestion import CandidateMemory
from memoryos.contracts.review import ConsolidationRequest, ResolveReviewRequest
from memoryos.db.models import Memory, MemoryReview, Scope
from memoryos.db.models import MemoryEvent as MemoryEventRow
from memoryos.db.repositories import VECTOR_DIMENSIONS, MemoryRepository
from memoryos.db.session import create_db_engine, create_session_factory
from memoryos.domain.enums import (
    ExecutionMode,
    MemoryEventType,
    MemoryRelation,
    MemoryStatus,
    MemoryType,
)
from memoryos.providers.errors import ProviderUnavailable
from memoryos.services.consolidation import MemoryConsolidationService
from memoryos.services.errors import ServiceError
from memoryos.services.query import MemoryQueryService
from memoryos.services.review import MemoryReviewService


def _settings() -> Settings:
    return Settings(
        database_url=os.environ.get(
            "TEST_DATABASE_URL",
            "postgresql+psycopg://memoryos@127.0.0.1:54329/memoryos",
        ),
        demo_embedding_model="demo-fixture-v1",
    )


@pytest.fixture(scope="session")
def db_settings() -> Settings:
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
def scope_context(db_settings: Settings):
    factory = create_session_factory(db_settings)
    scope_id = uuid4()
    with factory.begin() as session:
        MemoryRepository(session, db_settings).create_scope(
            scope_id=scope_id,
            name="review-test",
            embedding_model=db_settings.demo_embedding_model,
        )
    try:
        yield db_settings, factory, scope_id
    finally:
        with factory.begin() as session:
            session.execute(delete(Scope).where(Scope.id == scope_id))
        factory.kw["bind"].dispose()


def _vector() -> list[float]:
    values = [0.0] * VECTOR_DIMENSIONS
    values[0] = 1.0
    return values


def test_conflict_review_keep_both_activates_independent_lineages(scope_context) -> None:
    settings, factory, scope_id = scope_context
    vector = _vector()
    with factory.begin() as session:
        repo = MemoryRepository(session, settings)
        scope = repo.require_scope(scope_id)
        with repo.mutation(scope_id=scope_id, expected_revision=scope.revision):
            old = repo.insert_memory(
                scope_id=scope_id,
                content="Alex prefers Python examples",
                memory_type=MemoryType.PREFERENCE,
                subject="alex",
                context_key="python-projects",
                attribute_key="language",
                importance=0.8,
                confidence=0.9,
                embedding=vector,
                embedding_model=settings.demo_embedding_model,
                effective_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
            old_row = session.get(Memory, old.record.id)
            assert old_row is not None
            old_row.status = MemoryStatus.DISPUTED
            new = repo.insert_memory(
                scope_id=scope_id,
                content="Alex prefers TypeScript examples",
                memory_type=MemoryType.PREFERENCE,
                subject="alex",
                context_key="typescript-projects",
                attribute_key="language",
                importance=0.8,
                confidence=0.9,
                embedding=vector,
                embedding_model=settings.demo_embedding_model,
                lineage_id=old.record.lineage_id,
                version=2,
                status=MemoryStatus.DISPUTED,
                effective_at=datetime(2026, 2, 1, tzinfo=UTC),
            )
            repo.insert_event(
                scope_id=scope_id,
                memory_id=new.record.id,
                related_memory_id=old.record.id,
                event_type=MemoryEventType.DISPUTED,
                relation=MemoryRelation.DISPUTE,
                reason_code="ambiguous_conflict",
                reason_summary="Owner review required.",
                evidence_excerpt="TypeScript examples",
            )

    service = MemoryReviewService(settings, factory)
    pending = service.list_reviews(scope_id=scope_id)
    assert pending.total == 1
    resolved = service.resolve(
        scope_id=scope_id,
        review_id=pending.items[0].id,
        request=ResolveReviewRequest(action="keep_both", reason="Both contexts matter."),
    )
    assert resolved.status == "resolved"
    assert resolved.resolution == "keep_both"
    with factory() as session:
        rows = list(session.scalars(select(Memory).where(Memory.scope_id == scope_id)))
        assert sum(row.status is MemoryStatus.ACTIVE for row in rows) == 2
        assert sum(row.status is MemoryStatus.SUPERSEDED for row in rows) == 1
        assert (
            session.scalar(
                select(MemoryReview.status).where(MemoryReview.id == pending.items[0].id)
            )
            == "resolved"
        )


def test_consolidation_is_review_first_and_preserves_sources(scope_context) -> None:
    settings, factory, scope_id = scope_context
    source_ids: list[UUID] = []
    with factory.begin() as session:
        repo = MemoryRepository(session, settings)
        scope = repo.require_scope(scope_id)
        with repo.mutation(scope_id=scope_id, expected_revision=scope.revision):
            for index, content in enumerate(
                (
                    "Atlas uses PostgreSQL for durable memory.",
                    "Atlas uses PostgreSQL for durable memories.",
                    "Atlas uses PostgreSQL for durable memory storage.",
                )
            ):
                source_ids.append(
                    repo.insert_memory(
                        scope_id=scope_id,
                        content=content,
                        memory_type=MemoryType.SEMANTIC,
                        subject="atlas",
                        context_key="persistence",
                        attribute_key="database",
                        importance=0.75,
                        confidence=0.95,
                        embedding=_vector(),
                        embedding_model=settings.demo_embedding_model,
                        effective_at=datetime(2026, 1, index + 1, tzinfo=UTC),
                    ).record.id
                )
    proposal = MemoryConsolidationService(settings, factory).propose(
        ConsolidationRequest(
            scope_id=scope_id,
            source_memory_ids=source_ids,
            mode=ExecutionMode.DEMO,
        )
    )
    assert proposal.kind == "consolidation"
    assert proposal.status == "pending"
    assert {item.id for item in proposal.source_memories} == set(source_ids)
    resolved = MemoryReviewService(settings, factory).resolve(
        scope_id=scope_id,
        review_id=proposal.id,
        request=ResolveReviewRequest(action="use_new", reason="Approved summary."),
    )
    assert resolved.memory_id is not None
    with factory() as session:
        rows = list(session.scalars(select(Memory).where(Memory.scope_id == scope_id)))
        assert len(rows) == 4
        assert sum(row.status is MemoryStatus.ACTIVE for row in rows) == 1
        assert sum(row.status is MemoryStatus.SUPERSEDED for row in rows) == 3
        assert all(
            row.superseded_by_id == resolved.memory_id
            for row in rows
            if row.status is MemoryStatus.SUPERSEDED
        )
        history = MemoryRepository(session, settings).get_history(
            scope_id=scope_id, memory_id=resolved.memory_id
        )
        assert history is not None
        creation = next(
            event for event in history.events if event.reason_code == "memory_consolidated"
        )
        assert set(creation.after["source_memory_ids"]) == {str(value) for value in source_ids}


def test_consolidation_rejects_non_similar_sources(scope_context) -> None:
    settings, factory, scope_id = scope_context
    source_ids: list[UUID] = []
    first_vector = _vector()
    second_vector = _vector()
    second_vector[0] = 0.0
    second_vector[1] = 1.0
    with factory.begin() as session:
        repo = MemoryRepository(session, settings)
        scope = repo.require_scope(scope_id)
        with repo.mutation(scope_id=scope_id, expected_revision=scope.revision):
            for index in range(3):
                source_ids.append(
                    repo.insert_memory(
                        scope_id=scope_id,
                        content=f"Atlas fact {index}",
                        memory_type=MemoryType.SEMANTIC,
                        subject="atlas",
                        context_key="facts",
                        attribute_key="status",
                        importance=0.7,
                        confidence=0.8,
                        embedding=first_vector if index == 0 else second_vector,
                        embedding_model=settings.demo_embedding_model,
                    ).record.id
                )
    with pytest.raises(ServiceError, match="not similar enough"):
        MemoryConsolidationService(settings, factory).propose(
            ConsolidationRequest(scope_id=scope_id, source_memory_ids=source_ids)
        )


def _conflict(
    scope_context,
    *,
    mode=ExecutionMode.DEMO,
    mirror=False,
    separate_lineages=False,
    candidate_context="retention",
):
    settings, factory, scope_id = scope_context
    with factory.begin() as session:
        repo = MemoryRepository(session, settings)
        scope = repo.require_scope(scope_id)
        with repo.mutation(scope_id=scope_id, expected_revision=scope.revision):
            old = repo.insert_memory(
                scope_id=scope_id,
                content="Atlas keeps archives for one quarter.",
                memory_type=MemoryType.SEMANTIC,
                subject="Atlas",
                context_key="retention",
                attribute_key="archive-window",
                importance=0.7,
                confidence=0.8,
                embedding=_vector(),
                embedding_model=settings.demo_embedding_model,
                status=MemoryStatus.DISPUTED,
            )
            repo.insert_event(
                scope_id=scope_id,
                memory_id=old.record.id,
                event_type=MemoryEventType.CREATED,
                evidence_excerpt="Archive policy: one quarter.",
                reason_code="captured_policy",
                reason_summary="Recorded the archive policy.",
            )
            new = repo.insert_memory(
                scope_id=scope_id,
                content="Atlas keeps archives for six months.",
                memory_type=MemoryType.SEMANTIC,
                subject="Atlas",
                context_key=candidate_context,
                attribute_key="archive-window",
                importance=0.75,
                confidence=0.85,
                embedding=_vector(),
                embedding_model=settings.demo_embedding_model,
                status=MemoryStatus.DISPUTED,
                lineage_id=None if separate_lineages else old.record.lineage_id,
                version=1 if separate_lineages else 2,
            )
            repo.insert_event(
                scope_id=scope_id,
                memory_id=new.record.id,
                related_memory_id=old.record.id,
                event_type=MemoryEventType.DISPUTED,
                relation=MemoryRelation.DISPUTE,
                evidence_excerpt="Archive policy: six months.",
                reason_code="ambiguous_conflict",
                reason_summary="Two policies apply to the same archive window.",
            )
            review = session.scalar(select(MemoryReview).where(MemoryReview.scope_id == scope_id))
            assert review is not None
            review.mode = mode
            review_id = review.id
            if mirror:
                repo.create_review(
                    scope_id=scope_id,
                    kind="conflict",
                    memory_id=old.record.id,
                    existing_memory_id=new.record.id,
                    existing_memory=new.record,
                    candidate=CandidateMemory(
                        candidate_id=f"memory-{old.record.id}",
                        content=old.record.content,
                        memory_type=old.record.memory_type,
                        subject=old.record.subject,
                        context_key=old.record.context_key,
                        attribute_key=old.record.attribute_key,
                        importance=old.record.importance,
                        confidence=old.record.confidence,
                        effective_at=old.record.effective_at,
                        evidence_excerpt="One quarter.",
                    ),
                    confidence=0.8,
                    evidence_excerpt="One quarter.",
                    reason_code="legacy_mirror",
                    reason_summary="The same policy conflict.",
                    mode=mode,
                )
    return review_id, old.record.id, new.record.id


@pytest.mark.parametrize("action", ["keep_existing", "use_new"])
def test_selecting_source_closes_mirrors_and_preserves_history(scope_context, action):
    settings, factory, scope_id = scope_context
    review_id, old_id, new_id = _conflict(scope_context, mirror=True)
    service = MemoryReviewService(settings, factory)
    assert service.list_reviews(scope_id=scope_id).total == 1
    overview = MemoryQueryService(settings, factory).get_overview(scope_id=scope_id)
    assert overview.unresolved_review_count == 1
    request = ResolveReviewRequest(action=action, reason="Confirmed the policy with the owner.")
    resolved = service.resolve(scope_id=scope_id, review_id=review_id, request=request)
    selected_id, retired_id = (old_id, new_id) if action == "keep_existing" else (new_id, old_id)
    assert resolved.result_memory.id == selected_id
    assert resolved.candidate_memory.id == new_id
    assert service.list_reviews(scope_id=scope_id).total == 0
    assert service.list_reviews(scope_id=scope_id, status="resolved").total == 1
    with factory() as session:
        repo = MemoryRepository(session, settings)
        assert repo.get_by_id(scope_id, selected_id).status is MemoryStatus.ACTIVE
        retired = repo.get_by_id(scope_id, retired_id)
        assert retired.status is MemoryStatus.SUPERSEDED
        assert retired.superseded_by_id == selected_id
        history = repo.get_history(scope_id=scope_id, memory_id=old_id)
        assert len(history.versions) == 2
        assert [v.memory.id for v in history.versions if v.is_current] == [selected_id]
        assert {event.evidence_excerpt for event in history.events} >= {
            "Archive policy: one quarter.",
            "Archive policy: six months.",
        }
        assert len([e for e in history.events if e.event_type is MemoryEventType.RESOLVED]) == 1
        assert all(
            row.status == "resolved"
            for row in session.scalars(
                select(MemoryReview).where(MemoryReview.scope_id == scope_id)
            )
        )
        event_count = len(history.events)
    # The exact retried decision is idempotent, including its reason.
    again = service.resolve(scope_id=scope_id, review_id=review_id, request=request)
    assert again.memory_id == selected_id
    with factory() as session:
        repo = MemoryRepository(session, settings)
        assert len(repo.get_history(scope_id=scope_id, memory_id=old_id).events) == event_count
        # Replaying an old dispute event must not reopen a resolved conflict.
        event = session.scalar(
            select(MemoryEventRow).where(
                MemoryEventRow.memory_id == new_id,
                MemoryEventRow.event_type == MemoryEventType.DISPUTED,
            )
        )
        assert repo.ensure_conflict_review(event) is None
    with pytest.raises(ServiceError) as error:
        service.resolve(
            scope_id=scope_id,
            review_id=review_id,
            request=ResolveReviewRequest(action=action, reason="A different decision."),
        )
    assert error.value.code == "revision_conflict"


@pytest.mark.parametrize("candidate_context", ["retention", None])
def test_incompatible_coexistence_and_demo_merge_are_rejected(scope_context, candidate_context):
    settings, factory, scope_id = scope_context
    review_id, _, _ = _conflict(scope_context, candidate_context=candidate_context)
    service = MemoryReviewService(settings, factory)
    item = service.get(scope_id=scope_id, review_id=review_id)
    assert item.keep_both_unavailable_reason
    assert item.merge_unavailable_reason
    for request in (
        ResolveReviewRequest(action="keep_both", reason="I would like both."),
        ResolveReviewRequest(
            action="merge", reason="Corrected policy.", merged_content="One year."
        ),
    ):
        with pytest.raises(ServiceError) as error:
            service.resolve(scope_id=scope_id, review_id=review_id, request=request)
        assert error.value.code == "invalid_request"
    assert service.get(scope_id=scope_id, review_id=review_id).status == "pending"


def test_resolution_rejects_changed_source_scores_without_writing(scope_context):
    settings, factory, scope_id = scope_context
    review_id, old_id, _ = _conflict(scope_context)
    with factory.begin() as session:
        repo = MemoryRepository(session, settings)
        scope = repo.require_scope(scope_id)
        with repo.mutation(scope_id=scope_id, expected_revision=scope.revision):
            session.get(Memory, old_id).confidence = 0.9
    service = MemoryReviewService(settings, factory)
    with pytest.raises(ServiceError) as error:
        service.resolve(
            scope_id=scope_id, review_id=review_id, request=ResolveReviewRequest(action="use_new")
        )
    assert error.value.code == "revision_conflict"
    assert service.get(scope_id=scope_id, review_id=review_id).status == "pending"


@pytest.mark.parametrize("separate_lineages", [False, True])
def test_merge_creates_embedded_version_with_both_preserved_sources(
    scope_context, separate_lineages
):
    settings, factory, scope_id = scope_context
    review_id, old_id, new_id = _conflict(
        scope_context, mode=ExecutionMode.LIVE, separate_lineages=separate_lineages
    )
    content = "Atlas keeps archive metadata for six months; attachments expire after one quarter."
    calls = []

    class Embeddings:
        model_name = settings.demo_embedding_model

        def embed(self, texts):
            calls.append(texts)
            vector = _vector()
            vector[0], vector[1] = 0.0, 1.0
            return [vector]

    service = MemoryReviewService(
        settings, factory, embedding_factory=lambda mode, settings: Embeddings()
    )
    request = ResolveReviewRequest(
        action="merge", merged_content=content, reason="Clarified the two retention categories."
    )
    result = service.resolve(scope_id=scope_id, review_id=review_id, request=request)
    assert calls == [[content]]
    assert result.result_memory.content == content
    assert result.result_memory.version == (2 if separate_lineages else 3)
    assert result.result_memory.status is MemoryStatus.ACTIVE
    with factory() as session:
        repo = MemoryRepository(session, settings)
        for source_id in (old_id, new_id):
            source = repo.get_by_id(scope_id, source_id)
            assert source.status is MemoryStatus.SUPERSEDED
            assert source.superseded_by_id == result.memory_id
            assert any(
                event.evidence_excerpt
                for event in repo.list_events(scope_id=scope_id, memory_id=source_id)
            )
        stored = repo.get_stored_by_id(scope_id, result.memory_id)
        assert stored.embedding[1] == 1.0
        history = repo.get_history(scope_id=scope_id, memory_id=result.memory_id)
        assert len(history.versions) == (2 if separate_lineages else 3)
        merge_event = next(
            e
            for e in history.events
            if e.event_type is MemoryEventType.CREATED and e.reason_code == "review_merge"
        )
        assert set(merge_event.after["source_memory_ids"]) == {str(old_id), str(new_id)}
        assert result.candidate_memory.id == new_id
    service.resolve(scope_id=scope_id, review_id=review_id, request=request)
    assert calls == [[content]]
    with pytest.raises(ServiceError) as error:
        service.resolve(
            scope_id=scope_id,
            review_id=review_id,
            request=ResolveReviewRequest(
                action="merge",
                merged_content="A different corrected policy.",
                reason=request.reason,
            ),
        )
    assert error.value.code == "revision_conflict"


@pytest.mark.parametrize("failure", ["provider", "concurrent_change"])
def test_merge_failure_or_scope_race_rolls_back_entire_decision(scope_context, failure):
    settings, factory, scope_id = scope_context
    review_id, old_id, new_id = _conflict(scope_context, mode=ExecutionMode.LIVE)

    class Embeddings:
        model_name = settings.demo_embedding_model

        def embed(self, texts):
            if failure == "provider":
                raise ProviderUnavailable("Embedding service unavailable.")
            with factory.begin() as session:
                repo = MemoryRepository(session, settings)
                scope = repo.require_scope(scope_id)
                with repo.mutation(scope_id=scope_id, expected_revision=scope.revision):
                    pass
            return [_vector()]

    service = MemoryReviewService(
        settings, factory, embedding_factory=lambda mode, settings: Embeddings()
    )
    with pytest.raises(ServiceError) as error:
        service.resolve(
            scope_id=scope_id,
            review_id=review_id,
            request=ResolveReviewRequest(
                action="merge",
                reason="Owner correction.",
                merged_content="Atlas keeps archives for one year.",
            ),
        )
    assert error.value.code == (
        "provider_unavailable" if failure == "provider" else "revision_conflict"
    )
    assert service.get(scope_id=scope_id, review_id=review_id).status == "pending"
    with factory() as session:
        rows = list(session.scalars(select(Memory).where(Memory.scope_id == scope_id)))
        assert {row.id for row in rows} == {old_id, new_id}
        assert all(row.status is MemoryStatus.DISPUTED for row in rows)
