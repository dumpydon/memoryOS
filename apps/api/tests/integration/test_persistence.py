"""Integration coverage for the PostgreSQL/pgvector persistence boundary."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, text
from sqlalchemy.exc import IntegrityError, OperationalError

from memoryos.config import Settings
from memoryos.contracts.recall import RecallRequest
from memoryos.db.errors import DuplicateReinforcement, IdempotencyConflict, ScopeRevisionConflict
from memoryos.db.models import Scope
from memoryos.db.repositories import VECTOR_DIMENSIONS, MemoryRepository
from memoryos.db.session import create_db_engine, create_session_factory
from memoryos.domain.enums import (
    ExecutionMode,
    InteractionStatus,
    MemoryEventType,
    MemoryRelation,
    MemoryStatus,
    MemoryType,
)

DEMO_SCOPE = UUID("00000000-0000-0000-0000-000000000001")
LIVE_SCOPE = UUID("00000000-0000-0000-0000-000000000002")


def _settings() -> Settings:
    database_url = os.environ.get("TEST_DATABASE_URL")
    return Settings(
        database_url=database_url or Settings().database_url,
        demo_embedding_model="demo-fixture-v1",
        embedding_model="text-embedding-3-small",
    )


@pytest.fixture(scope="session")
def database():
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
def db(database: Settings):
    factory = create_session_factory(database)
    scope_id = uuid4()
    try:
        with factory.begin() as session:
            repo = MemoryRepository(session, database)
            repo.create_scope(
                scope_id=scope_id,
                name="integration",
                embedding_model=database.demo_embedding_model,
            )
        yield factory, scope_id
    finally:
        with factory.begin() as session:
            session.execute(delete(Scope).where(Scope.id == scope_id))
        factory.kw["bind"].dispose()


def _vector(value: float = 1.0) -> list[float]:
    result = [0.0] * VECTOR_DIMENSIONS
    result[0] = value
    return result


def test_scope_revision_and_rollback(db):
    factory, scope_id = db

    with pytest.raises(RuntimeError):
        with factory.begin() as session:
            repo = MemoryRepository(session)
            with repo.mutation(scope_id=scope_id, expected_revision=0):
                repo.insert_interaction(
                    scope_id=scope_id,
                    text="rolled back",
                    idempotency_key="rollback-1",
                    request_hash="hash-rollback",
                )
                raise RuntimeError("provider-independent mutation failure")

    with factory.begin() as session:
        repo = MemoryRepository(session)
        assert repo.current_scope_revision(scope_id) == 0
        assert (
            repo.get_interaction_by_idempotency(
                scope_id=scope_id,
                idempotency_key="rollback-1",
            )
            is None
        )
        with repo.mutation(scope_id=scope_id, expected_revision=0) as revision:
            assert revision.previous == 0
            assert revision.current == 1
            repo.insert_interaction(
                scope_id=scope_id,
                text="committed",
                idempotency_key="commit-1",
                request_hash="hash-commit",
                status=InteractionStatus.COMPLETED,
            )

    with factory.begin() as session:
        repo = MemoryRepository(session)
        assert repo.current_scope_revision(scope_id) == 1
        with pytest.raises(ScopeRevisionConflict):
            with repo.mutation(scope_id=scope_id, expected_revision=0):
                pytest.fail("stale mutation must not enter its body")


def test_idempotency_and_scoped_constraints(db):
    factory, scope_id = db
    other_scope_id = uuid4()
    with factory.begin() as session:
        repo = MemoryRepository(session)
        repo.create_scope(scope_id=other_scope_id, name="other", embedding_model="demo-fixture-v1")
        first = repo.insert_interaction(
            scope_id=scope_id,
            text="same",
            idempotency_key="same-key",
            request_hash="same-hash",
        )
        assert (
            repo.insert_interaction(
                scope_id=scope_id,
                text="same",
                idempotency_key="same-key",
                request_hash="same-hash",
            ).id
            == first.id
        )
        with pytest.raises(IdempotencyConflict):
            repo.insert_interaction(
                scope_id=scope_id,
                text="different",
                idempotency_key="same-key",
                request_hash="different-hash",
            )
        memory = repo.insert_memory(
            scope_id=scope_id,
            content="one",
            memory_type=MemoryType.SEMANTIC,
            importance=0.5,
            confidence=0.9,
            embedding=_vector(),
            embedding_model="demo-fixture-v1",
        )
        with pytest.raises(IntegrityError), session.begin_nested():
            repo.insert_memory(
                scope_id=scope_id,
                lineage_id=memory.record.lineage_id,
                version=1,
                content="duplicate version",
                memory_type=MemoryType.SEMANTIC,
                importance=0.5,
                confidence=0.9,
                embedding=_vector(),
                embedding_model="demo-fixture-v1",
            )
        other_memory = repo.insert_memory(
            scope_id=other_scope_id,
            content="other",
            memory_type=MemoryType.SEMANTIC,
            importance=0.5,
            confidence=0.9,
            embedding=_vector(),
            embedding_model="demo-fixture-v1",
        )
        with pytest.raises(IntegrityError), session.begin_nested():
            repo.insert_event(
                scope_id=scope_id,
                memory_id=memory.record.id,
                related_memory_id=other_memory.record.id,
                event_type=MemoryEventType.DISPUTED,
                relation=MemoryRelation.DISPUTE,
                reason_code="cross-scope",
                reason_summary="must be rejected",
            )
        session.execute(delete(Scope).where(Scope.id == other_scope_id))


def test_reinforcement_is_once_per_interaction_and_history_preserves_versions(db):
    factory, scope_id = db
    with factory.begin() as session:
        repo = MemoryRepository(session)
        interaction = repo.insert_interaction(
            scope_id=scope_id,
            text="confirm",
            idempotency_key="confirm-1",
            request_hash="confirm-hash",
        )
        memory = repo.insert_memory(
            scope_id=scope_id,
            content="Python is preferred",
            memory_type=MemoryType.PREFERENCE,
            importance=0.8,
            confidence=0.9,
            embedding=_vector(),
            embedding_model="demo-fixture-v1",
        )
        reinforced, event = repo.reinforce_memory(
            scope_id=scope_id,
            memory_id=memory.record.id,
            interaction_id=interaction.id,
            evidence_excerpt="confirm",
        )
        assert reinforced.record.reinforcement_count == 1
        assert event.event_type == MemoryEventType.REINFORCED
        with pytest.raises(DuplicateReinforcement):
            repo.reinforce_memory(
                scope_id=scope_id,
                memory_id=memory.record.id,
                interaction_id=interaction.id,
            )
        version_two = repo.insert_memory(
            scope_id=scope_id,
            lineage_id=memory.record.lineage_id,
            version=2,
            content="Python examples are preferred",
            memory_type=MemoryType.PREFERENCE,
            importance=0.85,
            confidence=0.95,
            embedding=_vector(),
            embedding_model="demo-fixture-v1",
            status=MemoryStatus.DISPUTED,
        )
        repo.set_memory_state(
            scope_id=scope_id,
            memory_id=memory.record.id,
            status=MemoryStatus.SUPERSEDED,
            superseded_by_id=version_two.record.id,
        )
        history = repo.get_history(scope_id=scope_id, memory_id=version_two.record.id)
        assert history is not None
        assert [item.memory.version for item in history.versions] == [1, 2]
        assert history.versions[-1].is_current
        assert len(history.events) == 1


def test_exact_pgvector_recall_filters_scope_mode_expiry_and_model(db):
    factory, scope_id = db
    now = datetime.now(UTC)
    with factory.begin() as session:
        repo = MemoryRepository(session)
        repo.insert_memory(
            scope_id=scope_id,
            content="matching",
            memory_type=MemoryType.SEMANTIC,
            importance=0.5,
            confidence=0.9,
            embedding=_vector(),
            embedding_model="demo-fixture-v1",
            effective_at=now - timedelta(minutes=1),
        )
        repo.insert_memory(
            scope_id=scope_id,
            content="expired",
            memory_type=MemoryType.SEMANTIC,
            importance=0.5,
            confidence=0.9,
            embedding=_vector(),
            embedding_model="demo-fixture-v1",
            expires_at=now - timedelta(seconds=1),
        )
        repo.insert_memory(
            scope_id=scope_id,
            content="live model",
            memory_type=MemoryType.SEMANTIC,
            importance=0.5,
            confidence=0.9,
            embedding=_vector(),
            embedding_model="text-embedding-3-small",
        )
        request = RecallRequest(
            scope_id=scope_id,
            query="matching",
            mode=ExecutionMode.DEMO,
            min_similarity=0.99,
        )
        candidates = repo.list_active_for_recall(
            request,
            as_of=now,
            query_embedding=_vector(),
        )
        assert len(candidates) == 1
        assert candidates[0].record.content == "matching"
        assert candidates[0].raw_similarity == pytest.approx(1.0)
        assert len(candidates[0].embedding) == VECTOR_DIMENSIONS
        # Optional identity keys must still produce valid SQL for graph candidates.
        related = repo.related_candidates(
            scope_id=scope_id,
            query_embedding=_vector(),
            embedding_model="demo-fixture-v1",
            as_of=now,
            limit=5,
        )
        assert [item.record.content for item in related] == ["matching"]
        assert not related[0].attribute_match
        assert not related[0].context_match
