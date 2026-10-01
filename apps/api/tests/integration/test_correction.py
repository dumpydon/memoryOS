"""Focused correction lifecycle using real persistence and deterministic providers."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, update

from memoryos.config import Settings
from memoryos.contracts.ingestion import IngestInteractionRequest
from memoryos.contracts.recall import RecallRequest
from memoryos.db.models import Interaction, Memory, MemoryEvent, Scope
from memoryos.db.repositories import MemoryRepository
from memoryos.db.session import create_session_factory
from memoryos.domain.enums import IngestDecisionType, MemoryEventType, MemoryStatus
from memoryos.main import create_app
from memoryos.seed.catalog import DEMO_MODEL, fixture_embeddings, get_catalog
from memoryos.services.errors import ServiceError
from memoryos.services.ingestion import MemoryIngestionService, _hash_request
from memoryos.services.query import MemoryQueryService

SCENARIOS = {item.id: item for item in get_catalog().scenarios}
REPLACE = SCENARIOS["demo-recall-correction-algorithms"].text
COEXIST = SCENARIOS["demo-recall-correction-system-design"].text


@pytest.fixture()
def correction_scope():
    settings = Settings(app_env="development")
    factory = create_session_factory(settings)
    scope_id = uuid4()
    with factory.begin() as session:
        repo = MemoryRepository(session, settings)
        repo.create_scope(
            scope_id=scope_id, name="disposable-correction-test", embedding_model=DEMO_MODEL
        )
        content = "Atlas prefers concise algorithm explanations."
        old = repo.insert_memory(
            scope_id=scope_id,
            content=content,
            memory_type="preference",
            subject="Atlas",
            context_key="algorithms",
            attribute_key="explanation-style",
            importance=0.9,
            confidence=0.97,
            embedding=fixture_embeddings([content])[0],
            embedding_model=DEMO_MODEL,
            effective_at=datetime.now(UTC) - timedelta(days=2),
        ).record
        repo.insert_event(
            scope_id=scope_id,
            memory_id=old.id,
            event_type=MemoryEventType.CREATED,
            evidence_excerpt=content,
            reason_code="test_source",
            reason_summary="Original evidence.",
        )
    try:
        yield settings, factory, scope_id, old
    finally:
        with factory.begin() as session:
            session.execute(
                update(Memory).where(Memory.scope_id == scope_id).values(superseded_by_id=None)
            )
            session.execute(delete(Scope).where(Scope.id == scope_id))
        factory.kw["bind"].dispose()


def prepare(ctx, text=REPLACE):
    settings, factory, scope_id, old = ctx
    service = MemoryIngestionService(settings, factory)
    base = dict(
        scope_id=scope_id,
        text=text,
        correction_memory_id=old.id,
        source_ref="Recall Lab correction",
        metadata={"correction_memory_id": str(old.id)},
    )
    preview = service.ingest(IngestInteractionRequest(**base, preview=True))
    request = IngestInteractionRequest(
        **base,
        idempotency_key="correction-commit",
        expected_scope_revision=preview.preview_revision,
        reviewed_decisions=[item.decision_type for item in preview.decisions],
        reviewed_targets=[item.related_memory_id or item.memory_id for item in preview.decisions],
    )
    return service, preview, request


def counts(ctx):
    _, factory, sid, _ = ctx
    with factory() as session:
        return tuple(
            session.scalar(select(func.count()).select_from(m).where(m.scope_id == sid))
            for m in (Memory, MemoryEvent, Interaction)
        )


def test_correction_supersedes_preserves_evidence_replays_and_improves_recall(correction_scope):
    ctx = correction_scope
    settings, factory, sid, old = ctx
    before = counts(ctx)
    service, preview, request = prepare(ctx)
    assert (
        counts(ctx) == before
        and preview.decisions[0].decision_type is IngestDecisionType.SUPERSEDED
    )
    committed = service.ingest(request)
    after = counts(ctx)
    assert service.ingest(request) == committed and counts(ctx) == after
    new_id = committed.decisions[0].memory_id
    query = MemoryQueryService(settings, factory)
    assert query.get_memory(scope_id=sid, memory_id=old.id).status is MemoryStatus.SUPERSEDED
    new = query.get_memory(scope_id=sid, memory_id=new_id)
    assert new.status is MemoryStatus.ACTIVE and new.lineage_id == old.lineage_id
    history = query.history(scope_id=sid, memory_id=old.id)
    assert history.events[0].evidence_excerpt == old.content
    assert history.events[-1].evidence_excerpt == REPLACE
    assert history.events[-1].provenance == "Recall Lab correction"
    ids = {
        item.memory.id
        for item in query.recall(
            RecallRequest(
                scope_id=sid,
                query="Atlas wants short answers with one concrete example.",
                min_similarity=0,
            )
        ).items
    }
    assert new_id in ids and old.id not in ids


def test_context_specific_correction_coexists(correction_scope):
    settings, factory, sid, old = correction_scope
    service, preview, request = prepare(correction_scope, COEXIST)
    assert preview.decisions[0].reason_code == "contextual_coexistence"
    result = service.ingest(request)
    query = MemoryQueryService(settings, factory)
    assert query.get_memory(scope_id=sid, memory_id=old.id).status is MemoryStatus.ACTIVE
    new = query.get_memory(scope_id=sid, memory_id=result.decisions[0].memory_id)
    assert new.lineage_id != old.lineage_id and new.context_key == "system-design"


def test_stale_preview_and_unreviewed_outcome_do_not_write(correction_scope):
    settings, factory, sid, old = correction_scope
    service, preview, request = prepare(correction_scope)
    before = counts(correction_scope)
    changed = request.model_copy(update={"reviewed_decisions": [IngestDecisionType.CREATED]})
    with pytest.raises(ServiceError, match="proposed outcome changed"):
        service.ingest(changed)
    assert counts(correction_scope) == before
    changed_target = request.model_copy(update={"reviewed_targets": [uuid4()]})
    with pytest.raises(ServiceError, match="affected memory changed"):
        service.ingest(changed_target)
    assert counts(correction_scope) == before
    with factory.begin() as session:
        repo = MemoryRepository(session, settings)
        with repo.mutation(scope_id=sid, expected_revision=preview.preview_revision):
            repo.set_memory_state(scope_id=sid, memory_id=old.id, status=MemoryStatus.FORGOTTEN)
    with pytest.raises(ServiceError, match="no longer active"):
        service.ingest(request)
    assert counts(correction_scope) == before


def test_production_demo_correction_is_preview_only(correction_scope):
    _, factory, sid, old = correction_scope
    settings = Settings(app_env="production", owner_api_token="correction-test-owner")
    app = create_app(settings)
    before = counts(correction_scope)
    with TestClient(app) as client:
        endpoint = f"/v1/memories/{old.id}/correct"
        headers = {"Authorization": "Bearer correction-test-owner"}
        preview = client.post(
            endpoint, headers=headers, json={"scope_id": str(sid), "text": REPLACE}
        ).json()
        assert not preview["correction_commit_allowed"]
        committed = client.post(
            endpoint,
            headers=headers,
            json={
                "scope_id": str(sid),
                "text": REPLACE,
                "preview": False,
                "idempotency_key": "production-demo",
                "expected_scope_revision": preview["preview_revision"],
                "reviewed_decisions": ["superseded"],
                "reviewed_targets": [str(old.id)],
            },
        )
        assert committed.status_code == 403
    assert counts(correction_scope) == before


def test_existing_interaction_hashes_do_not_change():
    request = IngestInteractionRequest(scope_id=uuid4(), text="A durable fact.", preview=True)
    legacy = request.model_dump(
        mode="json",
        exclude={
            "idempotency_key",
            "occurred_at",
            "correction_memory_id",
            "expected_scope_revision",
            "reviewed_decisions",
            "reviewed_targets",
        },
    )
    expected = hashlib.sha256(
        json.dumps(legacy, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    assert _hash_request(request) == expected
