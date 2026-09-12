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
from memoryos.contracts.review import ConsolidationRequest, ResolveReviewRequest
from memoryos.db.models import Memory, MemoryReview, Scope
from memoryos.db.repositories import VECTOR_DIMENSIONS, MemoryRepository
from memoryos.db.session import create_db_engine, create_session_factory
from memoryos.domain.enums import (
    ExecutionMode,
    MemoryEventType,
    MemoryRelation,
    MemoryStatus,
    MemoryType,
)
from memoryos.services.consolidation import MemoryConsolidationService
from memoryos.services.errors import ServiceError
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
                context_key="examples",
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
                context_key="examples",
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
        assert session.scalar(
            select(MemoryReview.status).where(MemoryReview.id == pending.items[0].id)
        ) == "resolved"


def test_consolidation_is_review_first_and_preserves_sources(scope_context) -> None:
    settings, factory, scope_id = scope_context
    source_ids: list[UUID] = []
    with factory.begin() as session:
        repo = MemoryRepository(session, settings)
        scope = repo.require_scope(scope_id)
        with repo.mutation(scope_id=scope_id, expected_revision=scope.revision):
            for index, content in enumerate(
                (
                    "Atlas deployed Monday.",
                    "Atlas redeployed after fixing CORS.",
                    "Atlas production deploy completed successfully.",
                )
            ):
                source_ids.append(
                    repo.insert_memory(
                        scope_id=scope_id,
                        content=content,
                        memory_type=MemoryType.EPISODIC,
                        subject="atlas",
                        context_key="deployment",
                        attribute_key="production",
                        importance=0.75,
                        confidence=0.85,
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
        assert all(row.status is MemoryStatus.ACTIVE for row in rows)


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
