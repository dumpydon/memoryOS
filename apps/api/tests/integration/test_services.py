"""Real PostgreSQL integration coverage for query/lifecycle services."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import OperationalError

from memoryos.config import Settings
from memoryos.contracts.memory import ForgetMemoryRequest, ResolveMemoryRequest
from memoryos.contracts.recall import RecallRequest
from memoryos.db.models import Memory, MemoryEvent, Scope
from memoryos.db.repositories import MemoryRepository
from memoryos.db.session import create_db_engine, create_session_factory
from memoryos.domain.enums import ExecutionMode, MemoryStatus, MemoryType
from memoryos.seed.catalog import DEMO_MODEL, fixture_embeddings
from memoryos.services.errors import ServiceError
from memoryos.services.query import MemoryQueryService


def _settings() -> Settings:
    return Settings(
        database_url=os.environ.get(
            "TEST_DATABASE_URL",
            "postgresql+psycopg://memoryos@127.0.0.1:54329/memoryos",
        ),
        demo_embedding_model=DEMO_MODEL,
    )


def test_live_recall_without_key_has_clear_provider_error() -> None:
    service = MemoryQueryService(Settings(openai_api_key=None))
    with pytest.raises(ServiceError) as error:
        service._embed_query(query="Which examples should I use?", mode=ExecutionMode.LIVE)
    assert getattr(error.value, "code", None) == "provider_unavailable"
    assert "OPENAI_API_KEY" in str(error.value)
    service.close()


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
    yield settings
    engine.dispose()


@pytest.fixture()
def service_context(db_settings: Settings):
    factory = create_session_factory(db_settings)
    scope_id = uuid4()
    with factory.begin() as session:
        MemoryRepository(session, db_settings).create_scope(
            scope_id=scope_id,
            name="query-service-integration",
            embedding_model=DEMO_MODEL,
        )
    try:
        yield db_settings, factory, scope_id
    finally:
        with factory.begin() as session:
            session.execute(
                update(Memory).where(Memory.scope_id == scope_id).values(superseded_by_id=None)
            )
            session.execute(delete(MemoryEvent).where(MemoryEvent.scope_id == scope_id))
            session.execute(delete(Memory).where(Memory.scope_id == scope_id))
            session.execute(delete(Scope).where(Scope.id == scope_id))
        factory.kw["bind"].dispose()


def _memory(
    repo: MemoryRepository,
    scope_id: UUID,
    *,
    content: str,
    lineage_id: UUID | None = None,
    version: int = 1,
    status: MemoryStatus = MemoryStatus.ACTIVE,
) -> UUID:
    return repo.insert_memory(
        scope_id=scope_id,
        content=content,
        memory_type=MemoryType.SEMANTIC,
        subject="Atlas",
        context_key="persistence",
        attribute_key="lineage",
        importance=0.8,
        confidence=0.9,
        embedding=fixture_embeddings([content])[0],
        embedding_model=DEMO_MODEL,
        lineage_id=lineage_id,
        version=version,
        status=status,
        effective_at=datetime.now(UTC) - timedelta(days=1),
    ).record.id


def test_forget_commits_lineage_and_clears_pointers(service_context) -> None:
    settings, factory, scope_id = service_context
    with factory.begin() as session:
        repo = MemoryRepository(session, settings)
        first_id = _memory(
            repo,
            scope_id,
            content="Atlas preserves corrected facts as immutable memory lineage versions.",
        )
        second_id = _memory(
            repo,
            scope_id,
            content="Atlas stores durable memories in PostgreSQL with pgvector.",
            lineage_id=repo.get_by_id(scope_id, first_id).lineage_id,
            version=2,
            status=MemoryStatus.SUPERSEDED,
        )
        repo.set_memory_state(
            scope_id=scope_id,
            memory_id=first_id,
            status=MemoryStatus.SUPERSEDED,
            superseded_by_id=second_id,
        )
    service = MemoryQueryService(settings, factory)
    result = service.forget(
        scope_id=scope_id,
        memory_id=first_id,
        request=ForgetMemoryRequest(reason="integration forget"),
    )
    assert set(result.forgotten_memory_ids) == {first_id, second_id}
    with factory() as session:
        rows = list(session.scalars(select(Memory).where(Memory.scope_id == scope_id)))
        assert {row.status for row in rows} == {MemoryStatus.FORGOTTEN}
        assert all(row.superseded_by_id is None for row in rows)
        assert (
            session.scalar(
                select(func.count())
                .select_from(MemoryEvent)
                .where(
                    MemoryEvent.scope_id == scope_id,
                    MemoryEvent.event_type == "forgotten",
                )
            )
            == 2
        )


def test_resolve_commits_selected_version_in_same_lineage(service_context) -> None:
    settings, factory, scope_id = service_context
    with factory.begin() as session:
        repo = MemoryRepository(session, settings)
        first_id = _memory(
            repo,
            scope_id,
            content="Atlas uses a bounded graph to validate extraction and relationships.",
        )
        first = repo.get_by_id(scope_id, first_id)
        assert first is not None
        second_id = _memory(
            repo,
            scope_id,
            content="Atlas preserves corrected facts as immutable memory lineage versions.",
            lineage_id=first.lineage_id,
            version=2,
            status=MemoryStatus.DISPUTED,
        )
    service = MemoryQueryService(settings, factory)
    result = service.resolve(
        scope_id=scope_id,
        memory_id=first_id,
        request=ResolveMemoryRequest(selected_memory_id=second_id, reason="integration resolve"),
    )
    assert result.selected_memory_id == second_id
    with factory() as session:
        rows = list(
            session.scalars(
                select(Memory).where(Memory.scope_id == scope_id).order_by(Memory.version)
            )
        )
        selected = next(row for row in rows if row.id == second_id)
        old = next(row for row in rows if row.id == first_id)
        assert selected.status is MemoryStatus.ACTIVE
        assert selected.superseded_by_id is None
        assert old.status is MemoryStatus.SUPERSEDED
        assert old.superseded_by_id == selected.id


def test_recall_and_compare_use_curated_fixture_snapshot(service_context) -> None:
    settings, factory, scope_id = service_context
    content = (
        "Atlas recall combines similarity, importance, recency, reinforcement, and confidence."
    )
    with factory.begin() as session:
        _memory(repo := MemoryRepository(session, settings), scope_id, content=content)
        _memory(
            repo,
            scope_id,
            content="Atlas recall vectors have 1536 dimensions.",
        )
        _memory(
            repo,
            scope_id,
            content=(
                "Atlas recall combines similarity, importance, recency, reinforcement, "
                "and confidence."
            ),
        )
    service = MemoryQueryService(settings, factory)
    request = RecallRequest(scope_id=scope_id, query=content, limit=3)
    response = service.recall(request)
    comparison = service.compare(request)
    assert response.candidate_count >= 2
    assert response.items
    assert response.items[0].score.raw_similarity >= response.items[-1].score.raw_similarity
    assert comparison.candidate_count == response.candidate_count
    assert all(item.memoryos_score.policy_version == "memoryos-v2" for item in comparison.memoryos)
