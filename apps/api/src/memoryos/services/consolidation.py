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
from memoryos.domain.enums import ExecutionMode, MemoryRelation, MemoryStatus, MemoryType
from memoryos.domain.policies import normalize_text
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


def _consolidated_content(rows: list[Memory]) -> str:
    """Compose only source-backed text; no inferred facts are introduced."""

    ordered = sorted(rows, key=lambda row: (row.effective_at, str(row.id)))
    unique: list[str] = []
    for row in ordered:
        text = " ".join(row.content.split())
        if text and normalize_text(text) not in {normalize_text(item) for item in unique}:
            unique.append(text)
    body = " ".join(unique)
    prefix = "Consolidated memory: "
    available = MAX_CONTENT_CHARS - len(prefix)
    if len(body) > available:
        body = body[: max(1, available - 1)].rstrip() + "…"
    return prefix + body


class MemoryConsolidationService:
    """Generate reviewable proposals from highly similar source memories."""

    def __init__(self, settings: Settings, session_factory: sessionmaker[Session]) -> None:
        self.settings = settings
        self.session_factory = session_factory

    def _session(self) -> AbstractContextManager[Session]:
        return self.session_factory()

    def propose(self, request: ConsolidationRequest) -> ReviewItem:
        source_ids = list(dict.fromkeys(request.source_memory_ids))
        if len(source_ids) < 3 or len(source_ids) > 8:
            raise ServiceError("invalid_request", "Choose between 3 and 8 source memories.")
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
                            "Highly similar semantic or episodic memories can be represented "
                            "by one owner-approved summary; source memories remain preserved."
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
        memory_type = rows[0].memory_type
        if memory_type not in {MemoryType.SEMANTIC, MemoryType.EPISODIC}:
            raise ServiceError(
                "invalid_request",
                "Only semantic and episodic memories can be consolidated automatically.",
            )
        identity = (
            normalize_text(rows[0].subject or ""),
            normalize_text(rows[0].context_key or ""),
            normalize_text(rows[0].attribute_key or ""),
        )
        if not all(identity):
            raise ServiceError(
                "invalid_request",
                "Consolidation requires explicit subject, context, and attribute keys.",
            )
        if any(
            row.memory_type is not memory_type
            or (
                normalize_text(row.subject or ""),
                normalize_text(row.context_key or ""),
                normalize_text(row.attribute_key or ""),
            )
            != identity
            for row in rows[1:]
        ):
            raise ServiceError(
                "invalid_request",
                "Consolidation sources must describe one typed subject, context, and attribute.",
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

    @staticmethod
    def _candidate(rows: list[Memory]) -> CandidateMemory:
        latest = max(rows, key=lambda row: (row.effective_at, str(row.id)))
        confidence = min(row.confidence for row in rows)
        importance = max(row.importance for row in rows)
        content = _consolidated_content(rows)
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
            expires_at=None,
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
