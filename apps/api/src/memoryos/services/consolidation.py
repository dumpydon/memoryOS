"""Conservative, review-first memory consolidation proposals."""

from __future__ import annotations

import math
import uuid
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from memoryos.config import Settings
from memoryos.contracts.ingestion import CandidateMemory
from memoryos.contracts.review import ConsolidationRequest, ReviewItem
from memoryos.db.errors import ScopeNotFoundError, ScopeRevisionConflict
from memoryos.db.models import Memory, MemoryReview
from memoryos.db.repositories import MemoryRepository
from memoryos.domain.enums import ExecutionMode, MemoryEventType, MemoryRelation, MemoryStatus
from memoryos.domain.policies import ConsolidationPlan, validate_consolidation
from memoryos.services.errors import ServiceError
from memoryos.services.review import _review_contract, _row_memory

MIN_PAIRWISE_SIMILARITY = 0.68
MAX_CONTENT_CHARS = 2_000


def utc_now() -> datetime:
    return datetime.now(UTC)


def _error_from_db(exc: Exception) -> ServiceError:
    if isinstance(exc, ServiceError):
        return exc
    if isinstance(exc, ScopeNotFoundError):
        return ServiceError("not_found", "The requested scope was not found.")
    if isinstance(exc, ScopeRevisionConflict):
        return ServiceError(
            "revision_conflict",
            "The scope changed while the consolidation was being proposed.",
            retryable=True,
        )
    if isinstance(exc, ValueError):
        return ServiceError("invalid_request", str(exc))
    if isinstance(exc, SQLAlchemyError):
        return ServiceError(
            "database_unavailable",
            "The memory database is temporarily unavailable.",
            retryable=True,
        )
    return ServiceError("internal_error", "The consolidation proposal could not be created.")


def _vector(row: Memory) -> list[float]:
    raw = row.embedding
    return [] if raw is None else [float(value) for value in raw]


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left or not right:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def persist_consolidation(
    *,
    session: Session,
    repo: MemoryRepository,
    plan: ConsolidationPlan,
    interaction_id: UUID | None = None,
    confirmation_at: datetime | None = None,
    provenance: str | None = None,
    review_id: UUID | None = None,
    evidence_excerpt: str | None = None,
) -> UUID:
    """Apply a validated plan inside the caller's existing scope mutation."""
    scope_id = plan.canonical.scope_id
    rows = list(
        session.scalars(
            select(Memory)
            .where(
                Memory.scope_id == scope_id,
                Memory.id.in_([m.id for m in plan.sources]),
            )
            .order_by(Memory.id.asc())
            .with_for_update()
        )
    )
    snapshots = {m.id: m for m in plan.sources}
    if len(rows) != len(snapshots) or any(
        row.status is not MemoryStatus.ACTIVE or _row_memory(row) != snapshots[row.id]
        for row in rows
    ):
        raise ServiceError(
            "revision_conflict", "A consolidation source changed before persistence."
        )
    canonical_row = next(row for row in rows if row.id == plan.canonical.id)
    carried_count = max(row.reinforcement_count for row in rows)
    count = carried_count + (1 if confirmation_at is not None else 0)
    confirmed = max(
        [row.last_confirmed_at for row in rows] + ([confirmation_at] if confirmation_at else [])
    )
    inserted = repo.insert_memory(
        scope_id=scope_id,
        content=plan.canonical.content,
        memory_type=plan.canonical.memory_type,
        importance=max(m.importance for m in plan.sources),
        confidence=min(m.confidence for m in plan.sources),
        reinforcement_count=count,
        embedding=_vector(canonical_row),
        embedding_model=plan.canonical.embedding_model,
        status=MemoryStatus.ACTIVE,
        subject=plan.canonical.subject,
        context_key=plan.canonical.context_key,
        attribute_key=plan.canonical.attribute_key,
        effective_at=plan.canonical.effective_at,
        expires_at=plan.canonical.expires_at,
        last_confirmed_at=confirmed,
        why=[
            f"consolidated from {len(rows)} equivalent memories",
            "original statements and evidence preserved in source history",
            "reinforcement carried forward conservatively; counts were not summed",
        ],
    )
    repo.insert_event(
        scope_id=scope_id,
        memory_id=inserted.record.id,
        interaction_id=interaction_id,
        event_type=MemoryEventType.CREATED,
        relation=MemoryRelation.NEW,
        reason_code="memory_consolidated",
        reason_summary="Consolidated — these memories express the same durable proposition.",
        evidence_excerpt=evidence_excerpt or plan.canonical.content[:1000],
        provenance=provenance,
        after={
            "source_memory_ids": [str(row.id) for row in rows],
            "canonical_source_id": str(plan.canonical.id),
            "carried_reinforcement_count": carried_count,
            "new_confirmation": confirmation_at is not None,
            "reinforcement_count": count,
            "review_id": str(review_id) if review_id else None,
        },
    )
    for row in rows:
        repo.set_memory_state(
            scope_id=scope_id,
            memory_id=row.id,
            status=MemoryStatus.SUPERSEDED,
            superseded_by_id=inserted.record.id,
        )
        repo.insert_event(
            scope_id=scope_id,
            memory_id=row.id,
            related_memory_id=inserted.record.id,
            interaction_id=interaction_id,
            event_type=MemoryEventType.SUPERSEDED,
            reason_code="consolidation_source_preserved",
            reason_summary=(
                "Canonical memory replaces this source; "
                "original evidence remains in history."
            ),
            evidence_excerpt=evidence_excerpt or row.content[:1000],
            provenance=provenance,
            before={"status": MemoryStatus.ACTIVE.value},
            after={
                "status": MemoryStatus.SUPERSEDED.value,
                "superseded_by_id": str(inserted.record.id),
                "review_id": str(review_id) if review_id else None,
            },
        )
    return inserted.record.id


class MemoryConsolidationService:
    """Generate reviewable proposals from highly similar source memories."""

    def __init__(self, settings: Settings, session_factory: sessionmaker[Session]) -> None:
        self.settings = settings
        self.session_factory = session_factory

    def _session(self) -> AbstractContextManager[Session]:
        return self.session_factory()

    def propose(self, request: ConsolidationRequest) -> ReviewItem:
        source_ids = list(dict.fromkeys(request.source_memory_ids))
        if len(source_ids) < 2 or len(source_ids) > 8:
            raise ServiceError("invalid_request", "Choose between 2 and 8 source memories.")
        try:
            with self.session_factory.begin() as session:
                repo = MemoryRepository(session, self.settings)
                scope = repo.require_scope(request.scope_id)
                expected_model = (
                    self.settings.demo_embedding_model
                    if request.mode is ExecutionMode.DEMO
                    else self.settings.embedding_model
                )
                if scope.embedding_model != expected_model:
                    raise ServiceError(
                        "embedding_model_mismatch",
                        "The requested consolidation mode does not match this scope.",
                    )
                # Lock by UUID order to avoid two concurrent proposals taking
                # overlapping source locks in opposite orders.
                rows = list(
                    session.scalars(
                        select(Memory)
                        .where(
                            Memory.scope_id == request.scope_id,
                            Memory.id.in_(sorted(source_ids, key=str)),
                        )
                        .order_by(Memory.id.asc())
                        .with_for_update()
                    )
                )
                by_id = {row.id: row for row in rows}
                if len(by_id) != len(source_ids):
                    raise ServiceError(
                        "not_found", "Every consolidation source must exist in this scope."
                    )
                ordered_rows = [by_id[source_id] for source_id in source_ids]
                self._validate_sources(ordered_rows, expected_model)
                pending = self._pending_duplicate(
                    session,
                    scope_id=request.scope_id,
                    source_ids=source_ids,
                )
                if pending is not None:
                    return _review_contract(pending)
                candidate = self._candidate(ordered_rows)
                source_records = [_row_memory(row) for row in ordered_rows]
                with repo.mutation(scope_id=request.scope_id, expected_revision=scope.revision):
                    review = repo.create_review(
                        scope_id=request.scope_id,
                        kind="consolidation",
                        candidate=candidate,
                        existing_memory=None,
                        source_memories=source_records,
                        proposed_relation=MemoryRelation.NEW,
                        confidence=candidate.confidence,
                        evidence_excerpt=candidate.evidence_excerpt,
                        reason_code="consolidation_candidate",
                        reason_summary=(
                            "Equivalent memories can share one canonical statement; "
                            "sources become historical after approval and retain their evidence."
                        ),
                        mode=request.mode,
                        review_id=uuid.uuid4(),
                    )
                    return _review_contract(review)
        except ServiceError:
            raise
        except Exception as exc:
            raise _error_from_db(exc) from exc

    @staticmethod
    def _validate_sources(
        rows: list[Memory],
        expected_model: str,
    ) -> None:
        if any(row.status is not MemoryStatus.ACTIVE for row in rows):
            raise ServiceError(
                "invalid_request",
                "Consolidation requires active source memories; disputed or superseded "
                "rows need review first.",
            )
        if any(row.embedding_model != expected_model for row in rows):
            raise ServiceError(
                "embedding_model_mismatch",
                "All consolidation sources must use the requested embedding model.",
            )
        pairwise: list[float] = []
        for index, left in enumerate(rows):
            for right in rows[index + 1 :]:
                pairwise.append(_cosine(_vector(left), _vector(right)))
        if not pairwise or min(pairwise) < MIN_PAIRWISE_SIMILARITY:
            raise ServiceError(
                "invalid_request",
                "Source memories are not similar enough for a conservative proposal.",
            )
        validation = validate_consolidation(
            [_row_memory(row) for row in rows],
            as_of=utc_now(),
            automatic=False,
        )
        if validation.plan is None:
            raise ServiceError("invalid_request", validation.reason)

    @staticmethod
    def _candidate(rows: list[Memory]) -> CandidateMemory:
        validation = validate_consolidation(
            [_row_memory(row) for row in rows],
            as_of=utc_now(),
            automatic=False,
        )
        if validation.plan is None:
            raise ServiceError("invalid_request", validation.reason)
        latest = validation.plan.canonical
        confidence = min(row.confidence for row in rows)
        importance = max(row.importance for row in rows)
        content = latest.content
        return CandidateMemory(
            candidate_id=f"consolidation-{uuid.uuid4().hex}",
            content=content,
            memory_type=latest.memory_type,
            subject=latest.subject,
            context_key=latest.context_key,
            attribute_key=latest.attribute_key,
            importance=importance,
            confidence=confidence,
            evidence_excerpt=latest.content[:1000],
            effective_at=latest.effective_at,
            expires_at=latest.expires_at,
            worth_remembering=True,
        )

    @staticmethod
    def _pending_duplicate(
        session: Session,
        *,
        scope_id: UUID,
        source_ids: list[UUID],
    ) -> MemoryReview | None:
        target = {str(source_id) for source_id in source_ids}
        rows = session.scalars(
            select(MemoryReview).where(
                MemoryReview.scope_id == scope_id,
                MemoryReview.kind == "consolidation",
                MemoryReview.status == "pending",
            )
        )
        for row in rows:
            if {str(source_id) for source_id in (row.source_memory_ids or [])} == target:
                return row
        return None


ConsolidationService = MemoryConsolidationService


__all__ = ["ConsolidationService", "MemoryConsolidationService"]
