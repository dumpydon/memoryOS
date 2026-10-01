"""Human review workflows for ambiguous memory decisions.

The review inbox is deliberately conservative.  A review stores immutable
snapshots of the candidate and its related memories, then a resolution performs
only allowlisted lifecycle changes inside one scope revision transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from memoryos.config import Settings
from memoryos.contracts.ingestion import CandidateMemory
from memoryos.contracts.memory import MemoryRecord
from memoryos.contracts.review import (
    ResolveReviewRequest,
    ReviewItem,
    ReviewListResponse,
    ReviewStatus,
)
from memoryos.db.errors import (
    InvalidEmbedding,
    ScopeNotFoundError,
    ScopeRevisionConflict,
)
from memoryos.db.models import Memory, MemoryReview
from memoryos.db.repositories import MemoryRepository
from memoryos.domain.enums import (
    ExecutionMode,
    MemoryEventType,
    MemoryRelation,
    MemoryStatus,
)
from memoryos.domain.policies import (
    memory_why_for_creation,
    memory_why_for_supersession,
)
from memoryos.providers.errors import ProviderOutputInvalid, ProviderTimeout, ProviderUnavailable
from memoryos.services.errors import ServiceError

_REVIEW_ACTIONS = {"keep_both", "use_new", "keep_existing", "invalid", "merge"}
_REVIEW_STATUSES = {"pending", "resolved"}


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
            "The scope changed while the review was being resolved.",
            retryable=True,
        )
    if isinstance(exc, InvalidEmbedding):
        return ServiceError("invalid_request", "The proposed memory embedding is invalid.")
    if isinstance(exc, (ProviderTimeout, ProviderUnavailable)):
        return ServiceError("provider_unavailable", str(exc), retryable=True)
    if isinstance(exc, ProviderOutputInvalid):
        return ServiceError("provider_output_invalid", str(exc))
    if isinstance(exc, ValueError):
        return ServiceError("invalid_request", str(exc))
    if isinstance(exc, SQLAlchemyError):
        return ServiceError(
            "database_unavailable",
            "The memory database is temporarily unavailable.",
            retryable=True,
        )
    return ServiceError("internal_error", "The review operation could not be completed.")


def _snapshot_candidate(value: object) -> CandidateMemory:
    try:
        return (
            value if isinstance(value, CandidateMemory) else CandidateMemory.model_validate(value)
        )
    except Exception as exc:
        raise ServiceError("internal_error", "A stored review candidate is malformed.") from exc


def _snapshot_memory(value: object) -> MemoryRecord:
    try:
        return value if isinstance(value, MemoryRecord) else MemoryRecord.model_validate(value)
    except Exception as exc:
        raise ServiceError(
            "internal_error",
            "A stored review memory snapshot is malformed.",
        ) from exc


def _review_contract(row: MemoryReview) -> ReviewItem:
    candidate = _snapshot_candidate(row.candidate_json)
    existing = (
        _snapshot_memory(row.existing_memory_json) if row.existing_memory_json is not None else None
    )
    sources = [_snapshot_memory(item) for item in (row.source_memories_json or [])]
    try:
        status = cast(ReviewStatus, row.status)
        if status not in _REVIEW_STATUSES:
            raise ValueError("invalid review status")
        return ReviewItem(
            id=row.id,
            scope_id=row.scope_id,
            kind=row.kind,
            status=status,
            candidate=candidate,
            existing_memory=existing,
            source_memories=sources,
            proposed_relation=row.proposed_relation,
            confidence=row.confidence,
            evidence_excerpt=row.evidence_excerpt,
            reason_code=row.reason_code,
            reason_summary=row.reason_summary,
            created_at=row.created_at,
            resolved_at=row.resolved_at,
            resolution=cast(Any, row.resolution),
            resolution_reason=row.resolution_reason,
            memory_id=row.memory_id,
        )
    except Exception as exc:
        if isinstance(exc, ServiceError):
            raise
        raise ServiceError("internal_error", "A stored review item is malformed.") from exc


def _embedding_values(row: Memory) -> list[float]:
    raw_vector = row.embedding
    return [] if raw_vector is None else [float(value) for value in raw_vector]


def _row_memory(row: Memory) -> MemoryRecord:
    """Use the repository's public projection without requiring a second session."""

    # ``get_by_id`` would issue another query and may lose a row lock.  Convert
    # the selected row directly while it is still part of the transaction.
    vector = _embedding_values(row)
    why = list(row.why or []) or memory_why_for_creation(
        row.memory_type,
        importance=row.importance,
        confidence=row.confidence,
        conflict_found=row.status is MemoryStatus.DISPUTED,
    )
    return MemoryRecord(
        id=row.id,
        scope_id=row.scope_id,
        lineage_id=row.lineage_id,
        version=row.version,
        content=row.content,
        memory_type=row.memory_type,
        status=row.status,
        subject=row.subject,
        context_key=row.context_key,
        attribute_key=row.attribute_key,
        importance=row.importance,
        confidence=row.confidence,
        reinforcement_count=row.reinforcement_count,
        embedding_model=row.embedding_model,
        embedding_dimensions=len(vector),
        created_at=row.created_at,
        effective_at=row.effective_at,
        last_confirmed_at=row.last_confirmed_at,
        expires_at=row.expires_at,
        superseded_by_id=row.superseded_by_id,
        why=why,
    )


class MemoryReviewService:
    """List and resolve persisted conflict/consolidation review items."""

    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        *,
        embedding_factory: Callable[[ExecutionMode, Settings], Any] | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.embedding_factory = embedding_factory

    @staticmethod
    def _merge_unavailable(row: MemoryReview) -> str | None:
        if row.kind != "conflict" or row.existing_memory_json is None or row.memory_id is None:
            return "Merge requires two stored competing memories."
        candidate = _snapshot_candidate(row.candidate_json)
        existing = _snapshot_memory(row.existing_memory_json)
        if any(
            getattr(candidate, field) != getattr(existing, field)
            for field in ("memory_type", "subject", "context_key", "attribute_key")
        ):
            return "These memories describe different contexts. Consider keeping both instead."
        if row.mode == ExecutionMode.DEMO:
            return (
                "Custom corrections require live embeddings. "
                "Demo mode only supports fixed fixture vectors."
            )
        return None

    @staticmethod
    def _keep_both_unavailable(row: MemoryReview) -> str | None:
        if row.kind != "conflict" or row.existing_memory_json is None or row.memory_id is None:
            return "Keep both requires two stored memories."
        candidate = _snapshot_candidate(row.candidate_json)
        existing = _snapshot_memory(row.existing_memory_json)
        separate_contexts = any(
            getattr(candidate, field)
            and getattr(existing, field)
            and getattr(candidate, field) != getattr(existing, field)
            for field in ("subject", "context_key", "attribute_key")
        )
        separate_timeframes = (
            existing.expires_at is not None
            and candidate.effective_at is not None
            and existing.expires_at <= candidate.effective_at
        ) or (candidate.expires_at is not None and candidate.expires_at <= existing.effective_at)
        if not separate_contexts and not separate_timeframes:
            return (
                "Keep both requires clearly separate contexts or timeframes. "
                "Otherwise choose one or merge a correction."
            )
        return None

    def _present(self, row: MemoryReview, repo: MemoryRepository) -> ReviewItem:
        item = _review_contract(row)
        item.merge_unavailable_reason = self._merge_unavailable(row)
        item.keep_both_unavailable_reason = self._keep_both_unavailable(row)
        if row.existing_memory_id:
            item.current_existing_memory = repo.get_by_id(row.scope_id, row.existing_memory_id)
            item.existing_evidence = repo.list_events(
                scope_id=row.scope_id, memory_id=row.existing_memory_id
            )
        if row.memory_id:
            current = repo.get_by_id(row.scope_id, row.memory_id)
            if row.status == "pending":
                item.candidate_memory = current
                item.candidate_evidence = repo.list_events(
                    scope_id=row.scope_id, memory_id=row.memory_id
                )
            else:
                item.result_memory = current
                if row.kind == "conflict" and row.source_memory_ids:
                    original_id = UUID(row.source_memory_ids[-1])
                    item.candidate_memory = repo.get_by_id(row.scope_id, original_id)
                    item.candidate_evidence = repo.list_events(
                        scope_id=row.scope_id, memory_id=original_id
                    )
        return item

    def _resolved_retry(
        self, row: MemoryReview, request: ResolveReviewRequest, repo: MemoryRepository
    ) -> ReviewItem:
        result = repo.get_by_id(row.scope_id, row.memory_id) if row.memory_id else None
        if (
            row.resolution == request.action
            and row.resolution_reason == request.reason
            and (
                request.action != "merge"
                or (result is not None and result.content == request.merged_content)
            )
        ):
            return self._present(row, repo)
        raise ServiceError(
            "revision_conflict",
            "This review already has a different decision. Refresh to see the result.",
        )

    def _session(self) -> AbstractContextManager[Session]:
        return self.session_factory()

    def list_reviews(
        self,
        *,
        scope_id: UUID,
        status: ReviewStatus = "pending",
        limit: int = 50,
    ) -> ReviewListResponse:
        if status not in _REVIEW_STATUSES:
            raise ServiceError("invalid_request", "Review status must be pending or resolved.")
        try:
            with self._session() as session:
                repo = MemoryRepository(session, self.settings)
                repo.require_scope(scope_id)
                rows, total = repo.list_reviews(scope_id=scope_id, status=status, limit=limit)
                return ReviewListResponse(
                    items=[self._present(row, repo) for row in rows],
                    total=total,
                )
        except ServiceError:
            raise
        except Exception as exc:
            raise _error_from_db(exc) from exc

    def get(self, *, scope_id: UUID, review_id: UUID) -> ReviewItem:
        try:
            with self._session() as session:
                repo = MemoryRepository(session, self.settings)
                repo.require_scope(scope_id)
                row = repo.get_review(scope_id=scope_id, review_id=review_id)
                if row is None:
                    raise ServiceError("not_found", "The review item was not found in this scope.")
                return self._present(row, repo)
        except ServiceError:
            raise
        except Exception as exc:
            raise _error_from_db(exc) from exc

    def create_conflict(
        self,
        *,
        scope_id: UUID,
        candidate: CandidateMemory,
        existing_memory: MemoryRecord | None,
        proposed_relation: MemoryRelation = MemoryRelation.DISPUTE,
        confidence: float,
        evidence_excerpt: str,
        reason_code: str,
        reason_summary: str,
        memory_id: UUID | None = None,
        interaction_id: UUID | None = None,
        mode: ExecutionMode = ExecutionMode.DEMO,
    ) -> ReviewItem:
        """Create an explicit conflict review for ingestion adapters.

        The disputed-event repository hook normally calls this behavior
        implicitly.  The method remains public for providers that need to
        attach richer candidate metadata than a persisted memory row contains.
        """

        try:
            with self.session_factory.begin() as session:
                repo = MemoryRepository(session, self.settings)
                scope = repo.require_scope(scope_id)
                with repo.mutation(scope_id=scope_id, expected_revision=scope.revision):
                    row = repo.create_review(
                        scope_id=scope_id,
                        kind="conflict",
                        candidate=candidate,
                        existing_memory=existing_memory,
                        source_memories=(),
                        proposed_relation=proposed_relation,
                        confidence=confidence,
                        evidence_excerpt=evidence_excerpt,
                        reason_code=reason_code,
                        reason_summary=reason_summary,
                        memory_id=memory_id,
                        existing_memory_id=existing_memory.id if existing_memory else None,
                        mode=mode,
                    )
                    return self._present(row, repo)
        except ServiceError:
            raise
        except Exception as exc:
            raise _error_from_db(exc) from exc

    def resolve(
        self,
        *,
        scope_id: UUID,
        review_id: UUID,
        request: ResolveReviewRequest,
    ) -> ReviewItem:
        if request.action not in _REVIEW_ACTIONS:
            raise ServiceError("invalid_request", "Unsupported review action.")
        try:
            with self.session_factory.begin() as session:
                repo = MemoryRepository(session, self.settings)
                scope = repo.require_scope(scope_id)
                row = repo.get_review(scope_id=scope_id, review_id=review_id)
                if row is None:
                    raise ServiceError("not_found", "The review item was not found in this scope.")
                # A retried request with the same action is safely idempotent.
                if row.status == "resolved":
                    return self._resolved_retry(row, request, repo)
                # Provider work precedes the scope lock; any failure leaves the review untouched.
                merge_vector = None
                if request.action == "merge":
                    unavailable = self._merge_unavailable(row)
                    if unavailable:
                        raise ServiceError("invalid_request", unavailable)
                    if request.merged_content is None:
                        raise ServiceError("invalid_request", "A corrected statement is required.")
                    sources = [
                        _snapshot_candidate(row.candidate_json).content,
                        _snapshot_memory(row.existing_memory_json).content,
                    ]
                    if request.merged_content in sources:
                        raise ServiceError(
                            "invalid_request",
                            "Choose Keep A or Keep B to retain an unchanged statement.",
                        )
                    from memoryos.providers.factory import make_embedding_provider

                    provider = (self.embedding_factory or make_embedding_provider)(
                        ExecutionMode(row.mode), self.settings
                    )
                    if provider.model_name != scope.embedding_model:
                        raise ServiceError(
                            "embedding_model_mismatch",
                            "The correction must use this scope's embedding model.",
                        )
                    vectors = provider.embed([request.merged_content])
                    if len(vectors) != 1:
                        raise ServiceError(
                            "provider_output_invalid", "The correction embedding was not returned."
                        )
                    merge_vector = vectors[0]
                if request.action == "keep_both":
                    unavailable = self._keep_both_unavailable(row)
                    if unavailable:
                        raise ServiceError("invalid_request", unavailable)
                # Refresh cached rows before acquiring the scope lock. A concurrent
                # writer during embedding must be detected by the revision check.
                session.expire_all()
                with repo.mutation(scope_id=scope_id, expected_revision=scope.revision):
                    row = repo.get_review(
                        scope_id=scope_id,
                        review_id=review_id,
                        for_update=True,
                    )
                    if row is None:
                        raise ServiceError(
                            "not_found", "The review item was not found in this scope."
                        )
                    if row.status == "resolved":
                        return self._resolved_retry(row, request, repo)
                    self._assert_current_snapshot(session, row)
                    if row.kind == "consolidation" and request.action == "keep_both":
                        raise ServiceError(
                            "invalid_request",
                            "Consolidation proposals require use_new, keep_existing, or invalid.",
                        )
                    original_pair = {
                        memory_id
                        for memory_id in (row.memory_id, row.existing_memory_id)
                        if memory_id is not None
                    }
                    source_snapshots = {
                        str(memory_id): record.model_dump(mode="json")
                        for memory_id in original_pair
                        if (record := repo.get_by_id(scope_id, memory_id)) is not None
                    }
                    if row.kind == "conflict":
                        self._preserve_review_sources(row, source_snapshots)
                    resolved_memory_id = self._apply_action(
                        session=session,
                        repo=repo,
                        row=row,
                        action=request.action,
                        reason=request.reason,
                        merged_content=request.merged_content,
                        merge_vector=merge_vector,
                    )
                    row.status = "resolved"
                    row.resolution = request.action
                    row.resolution_reason = request.reason
                    row.resolved_at = utc_now()
                    if resolved_memory_id is not None:
                        row.memory_id = resolved_memory_id
                    # Older fixtures can contain mirrored reviews of the very same pair.
                    # Resolve both orientations atomically so no impossible pending item remains.
                    if row.kind == "conflict" and len(original_pair) == 2:
                        mirrors = session.scalars(
                            select(MemoryReview)
                            .where(
                                MemoryReview.scope_id == scope_id,
                                MemoryReview.status == "pending",
                                MemoryReview.kind == "conflict",
                                MemoryReview.id != row.id,
                                MemoryReview.memory_id.in_(original_pair),
                                MemoryReview.existing_memory_id.in_(original_pair),
                            )
                            .with_for_update()
                        )
                        for mirror in mirrors:
                            swapped = mirror.existing_memory_id != row.existing_memory_id
                            action = request.action
                            if swapped and action in {"use_new", "keep_existing"}:
                                action = "keep_existing" if action == "use_new" else "use_new"
                            elif swapped and action == "invalid":
                                action = "use_new"
                            self._preserve_review_sources(mirror, source_snapshots)
                            mirror.status = "resolved"
                            mirror.resolution = action
                            mirror.resolution_reason = request.reason
                            mirror.resolved_at = row.resolved_at
                            mirror.memory_id = resolved_memory_id
                    session.flush()
                    return self._present(row, repo)
        except ServiceError:
            raise
        except Exception as exc:
            raise _error_from_db(exc) from exc

    @staticmethod
    def _preserve_review_sources(row: MemoryReview, snapshots: dict[str, dict[str, Any]]) -> None:
        ids = [str(value) for value in (row.existing_memory_id, row.memory_id) if value]
        row.source_memory_ids = ids
        row.source_memories_json = [snapshots[value] for value in ids if value in snapshots]

    def _assert_current_snapshot(self, session: Session, row: MemoryReview) -> None:
        """Fail closed if a memory changed after the review was opened."""

        expected_candidate = _snapshot_candidate(row.candidate_json)
        if row.memory_id is not None:
            candidate_row = session.scalar(
                select(Memory)
                .where(Memory.scope_id == row.scope_id, Memory.id == row.memory_id)
                .with_for_update()
            )
            if candidate_row is None:
                raise ServiceError("revision_conflict", "The review candidate no longer exists.")
            if candidate_row.content != expected_candidate.content:
                raise ServiceError(
                    "revision_conflict", "The review candidate changed after it was proposed."
                )
            if candidate_row.effective_at != expected_candidate.effective_at:
                raise ServiceError(
                    "revision_conflict", "The review candidate changed after it was proposed."
                )
            if any(
                getattr(candidate_row, field) != getattr(expected_candidate, field)
                for field in (
                    "memory_type",
                    "subject",
                    "context_key",
                    "attribute_key",
                    "importance",
                    "confidence",
                    "expires_at",
                )
            ):
                raise ServiceError(
                    "revision_conflict",
                    "The candidate's context or evidence score changed. Refresh the review.",
                )
            if row.kind == "conflict" and candidate_row.status is not MemoryStatus.DISPUTED:
                raise ServiceError(
                    "revision_conflict", "The review candidate is no longer pending review."
                )
        if row.existing_memory_id is not None:
            existing_row = session.scalar(
                select(Memory)
                .where(
                    Memory.scope_id == row.scope_id,
                    Memory.id == row.existing_memory_id,
                )
                .with_for_update()
            )
            expected_existing = (
                _snapshot_memory(row.existing_memory_json)
                if row.existing_memory_json is not None
                else None
            )
            if existing_row is None or expected_existing is None:
                raise ServiceError(
                    "revision_conflict", "The existing review memory is no longer available."
                )
            if (
                existing_row.content != expected_existing.content
                or existing_row.version != expected_existing.version
                or existing_row.lineage_id != expected_existing.lineage_id
                or existing_row.status is not expected_existing.status
                or any(
                    getattr(existing_row, field) != getattr(expected_existing, field)
                    for field in (
                        "memory_type",
                        "subject",
                        "context_key",
                        "attribute_key",
                        "importance",
                        "confidence",
                        "effective_at",
                        "expires_at",
                    )
                )
            ):
                raise ServiceError(
                    "revision_conflict", "The existing memory changed after review was proposed."
                )
            if existing_row.status is MemoryStatus.SUPERSEDED:
                raise ServiceError(
                    "revision_conflict",
                    "The existing memory was superseded after review was proposed.",
                )
            if existing_row.status is MemoryStatus.FORGOTTEN:
                raise ServiceError(
                    "revision_conflict",
                    "The existing memory was forgotten after review was proposed.",
                )
        for source in row.source_memories_json or []:
            expected_source = _snapshot_memory(source)
            source_row = session.scalar(
                select(Memory)
                .where(Memory.scope_id == row.scope_id, Memory.id == expected_source.id)
                .with_for_update()
            )
            if source_row is None:
                raise ServiceError("revision_conflict", "A consolidation source no longer exists.")
            if (
                source_row.content != expected_source.content
                or source_row.version != expected_source.version
                or source_row.status is not expected_source.status
            ):
                raise ServiceError(
                    "revision_conflict",
                    "A consolidation source changed after proposal.",
                )

    def _apply_action(
        self,
        *,
        session: Session,
        repo: MemoryRepository,
        row: MemoryReview,
        action: str,
        reason: str,
        merged_content: str | None = None,
        merge_vector: list[float] | None = None,
    ) -> UUID | None:
        candidate_row = (
            session.scalar(
                select(Memory)
                .where(Memory.scope_id == row.scope_id, Memory.id == row.memory_id)
                .with_for_update()
            )
            if row.memory_id is not None
            else None
        )
        existing_row = (
            session.scalar(
                select(Memory)
                .where(Memory.scope_id == row.scope_id, Memory.id == row.existing_memory_id)
                .with_for_update()
            )
            if row.existing_memory_id is not None
            else None
        )

        if row.kind == "consolidation":
            if action == "use_new":
                return self._approve_consolidation(
                    session=session,
                    repo=repo,
                    row=row,
                    reason=reason,
                )
            # keep_existing and invalid both reject the proposal while retaining
            # the source snapshots and review audit row.
            return None

        if action == "merge":
            if (
                candidate_row is None
                or existing_row is None
                or merged_content is None
                or merge_vector is None
            ):
                raise ServiceError(
                    "invalid_request", "Merge requires both sources and a corrected statement."
                )
            return self._merge(
                session,
                repo,
                row,
                existing_row,
                candidate_row,
                merged_content,
                merge_vector,
                reason,
            )
        if action == "keep_both":
            return self._keep_both(
                session=session,
                repo=repo,
                review=row,
                candidate_row=candidate_row,
                existing_row=existing_row,
                reason=reason,
            )
        if action == "use_new":
            if candidate_row is None:
                raise ServiceError("invalid_request", "The review candidate is not materialized.")
            if existing_row is not None:
                self._supersede(
                    repo=repo,
                    old=existing_row,
                    new=candidate_row,
                    reason_code="review_use_new",
                    reason=reason,
                )
            candidate_row.status = MemoryStatus.ACTIVE
            candidate_row.superseded_by_id = None
            repo.insert_event(
                scope_id=row.scope_id,
                memory_id=candidate_row.id,
                related_memory_id=existing_row.id if existing_row else None,
                event_type=MemoryEventType.RESOLVED,
                reason_code="review_use_new",
                reason_summary=reason,
                after={"status": MemoryStatus.ACTIVE.value, "review_id": str(row.id)},
            )
            return candidate_row.id
        if action == "keep_existing":
            if existing_row is None:
                raise ServiceError("invalid_request", "There is no existing memory to keep.")
            if candidate_row is not None:
                candidate_row.status = MemoryStatus.SUPERSEDED
                candidate_row.superseded_by_id = existing_row.id if existing_row else None
                repo.insert_event(
                    scope_id=row.scope_id,
                    memory_id=candidate_row.id,
                    related_memory_id=existing_row.id if existing_row else None,
                    event_type=MemoryEventType.SUPERSEDED,
                    reason_code="review_keep_existing",
                    reason_summary=reason,
                    after={
                        "status": MemoryStatus.SUPERSEDED.value,
                        "superseded_by_id": str(existing_row.id) if existing_row else None,
                        "review_id": str(row.id),
                    },
                )
            if existing_row is not None:
                self._activate(existing_row)
                repo.insert_event(
                    scope_id=row.scope_id,
                    memory_id=existing_row.id,
                    related_memory_id=candidate_row.id if candidate_row else None,
                    event_type=MemoryEventType.RESOLVED,
                    reason_code="review_keep_existing",
                    reason_summary=reason,
                    after={"status": MemoryStatus.ACTIVE.value, "review_id": str(row.id)},
                )
            return existing_row.id if existing_row is not None else None
        if action == "invalid":
            if candidate_row is not None:
                candidate_row.status = MemoryStatus.FORGOTTEN
                candidate_row.superseded_by_id = None
                repo.insert_event(
                    scope_id=row.scope_id,
                    memory_id=candidate_row.id,
                    related_memory_id=existing_row.id if existing_row else None,
                    event_type=MemoryEventType.FORGOTTEN,
                    reason_code="review_candidate_invalid",
                    reason_summary=reason,
                    after={"status": MemoryStatus.FORGOTTEN.value, "review_id": str(row.id)},
                )
                repo.insert_event(
                    scope_id=row.scope_id,
                    memory_id=candidate_row.id,
                    related_memory_id=existing_row.id if existing_row else None,
                    event_type=MemoryEventType.RESOLVED,
                    reason_code="review_candidate_invalid",
                    reason_summary=reason,
                    after={"status": MemoryStatus.FORGOTTEN.value, "review_id": str(row.id)},
                )
            if existing_row is not None:
                self._activate(existing_row)
                repo.insert_event(
                    scope_id=row.scope_id,
                    memory_id=existing_row.id,
                    related_memory_id=candidate_row.id if candidate_row else None,
                    event_type=MemoryEventType.RESOLVED,
                    reason_code="review_candidate_invalid",
                    reason_summary=reason,
                    after={"status": MemoryStatus.ACTIVE.value, "review_id": str(row.id)},
                )
            return existing_row.id if existing_row is not None else None
        raise ServiceError("invalid_request", "Unsupported review action.")

    def _keep_both(
        self,
        *,
        session: Session,
        repo: MemoryRepository,
        review: MemoryReview,
        candidate_row: Memory | None,
        existing_row: Memory | None,
        reason: str,
    ) -> UUID | None:
        if candidate_row is None:
            raise ServiceError("invalid_request", "The review candidate is not materialized.")
        if existing_row is not None:
            self._activate(existing_row)
        if existing_row is not None and candidate_row.lineage_id == existing_row.lineage_id:
            # Preserve the disputed version as historical evidence, then copy
            # it into a new lineage so both interpretations can be active.
            candidate_record = _row_memory(candidate_row)
            copy = repo.insert_memory(
                scope_id=review.scope_id,
                content=candidate_row.content,
                memory_type=candidate_row.memory_type,
                importance=candidate_row.importance,
                confidence=candidate_row.confidence,
                reinforcement_count=candidate_row.reinforcement_count,
                embedding=_embedding_values(candidate_row),
                embedding_model=candidate_row.embedding_model,
                status=MemoryStatus.ACTIVE,
                subject=candidate_row.subject,
                context_key=candidate_row.context_key,
                attribute_key=candidate_row.attribute_key,
                lineage_id=uuid.uuid4(),
                version=1,
                created_at=utc_now(),
                effective_at=candidate_row.effective_at,
                last_confirmed_at=candidate_row.last_confirmed_at,
                expires_at=candidate_row.expires_at,
                why=[
                    *candidate_record.why,
                    "kept as a separate active interpretation after owner review",
                ],
            )
            repo.insert_event(
                scope_id=review.scope_id,
                memory_id=copy.record.id,
                related_memory_id=candidate_row.id,
                event_type=MemoryEventType.CREATED,
                reason_code="review_keep_both_source",
                reason_summary=reason,
                evidence_excerpt=review.evidence_excerpt,
                after={"review_id": str(review.id), "source_memory_id": str(candidate_row.id)},
            )
            candidate_row.status = MemoryStatus.SUPERSEDED
            candidate_row.superseded_by_id = copy.record.id
            repo.insert_event(
                scope_id=review.scope_id,
                memory_id=candidate_row.id,
                related_memory_id=copy.record.id,
                event_type=MemoryEventType.SUPERSEDED,
                reason_code="review_keep_both_copy",
                reason_summary=reason,
                after={
                    "status": MemoryStatus.SUPERSEDED.value,
                    "superseded_by_id": str(copy.record.id),
                    "review_id": str(review.id),
                },
            )
            repo.insert_event(
                scope_id=review.scope_id,
                memory_id=copy.record.id,
                related_memory_id=existing_row.id,
                event_type=MemoryEventType.RESOLVED,
                reason_code="review_keep_both",
                reason_summary=reason,
                after={"status": MemoryStatus.ACTIVE.value, "review_id": str(review.id)},
            )
            repo.insert_event(
                scope_id=review.scope_id,
                memory_id=existing_row.id,
                related_memory_id=copy.record.id,
                event_type=MemoryEventType.RESOLVED,
                reason_code="review_keep_both",
                reason_summary=reason,
                after={"status": MemoryStatus.ACTIVE.value, "review_id": str(review.id)},
            )
            return copy.record.id
        candidate_row.status = MemoryStatus.ACTIVE
        candidate_row.superseded_by_id = None
        repo.insert_event(
            scope_id=review.scope_id,
            memory_id=candidate_row.id,
            related_memory_id=existing_row.id if existing_row else None,
            event_type=MemoryEventType.RESOLVED,
            reason_code="review_keep_both",
            reason_summary=reason,
            after={"status": MemoryStatus.ACTIVE.value, "review_id": str(review.id)},
        )
        if existing_row is not None:
            repo.insert_event(
                scope_id=review.scope_id,
                memory_id=existing_row.id,
                related_memory_id=candidate_row.id,
                event_type=MemoryEventType.RESOLVED,
                reason_code="review_keep_both",
                reason_summary=reason,
                after={"status": MemoryStatus.ACTIVE.value, "review_id": str(review.id)},
            )
        return candidate_row.id

    def _merge(
        self,
        session: Session,
        repo: MemoryRepository,
        review: MemoryReview,
        existing: Memory,
        candidate: Memory,
        content: str,
        vector: list[float],
        reason: str,
    ) -> UUID:
        # A correction is a new immutable version, never an edit of either source.
        scope = repo.require_scope(review.scope_id)
        if any(source.embedding_model != scope.embedding_model for source in (existing, candidate)):
            raise ServiceError(
                "embedding_model_mismatch",
                "Both sources must use this scope's embedding model before they can be merged.",
            )
        version = (
            session.scalar(
                select(func.max(Memory.version)).where(
                    Memory.scope_id == review.scope_id, Memory.lineage_id == existing.lineage_id
                )
            )
            or 0
        )
        merged = repo.insert_memory(
            scope_id=review.scope_id,
            content=content,
            memory_type=existing.memory_type,
            subject=existing.subject,
            context_key=existing.context_key,
            attribute_key=existing.attribute_key,
            lineage_id=existing.lineage_id,
            version=version + 1,
            status=MemoryStatus.DISPUTED,
            importance=max(existing.importance, candidate.importance),
            confidence=min(existing.confidence, candidate.confidence),
            embedding=vector,
            embedding_model=existing.embedding_model,
            effective_at=utc_now(),
            last_confirmed_at=utc_now(),
            expires_at=min(
                (expiry for expiry in (existing.expires_at, candidate.expires_at) if expiry),
                default=None,
            ),
            why=["corrected by owner review; both source versions preserved", reason],
        )
        merged_row = session.get(Memory, merged.record.id)
        assert merged_row is not None
        for source in (existing, candidate):
            self._supersede(
                repo=repo, old=source, new=merged_row, reason_code="review_merge", reason=reason
            )
        self._activate(merged_row)
        repo.insert_event(
            scope_id=review.scope_id,
            memory_id=merged_row.id,
            related_memory_id=candidate.id,
            event_type=MemoryEventType.CREATED,
            reason_code="review_merge",
            reason_summary=reason,
            evidence_excerpt=review.evidence_excerpt,
            after={
                "review_id": str(review.id),
                "source_memory_ids": [str(existing.id), str(candidate.id)],
            },
        )
        repo.insert_event(
            scope_id=review.scope_id,
            memory_id=merged_row.id,
            related_memory_id=existing.id,
            event_type=MemoryEventType.RESOLVED,
            reason_code="review_merge",
            reason_summary=reason,
            after={"status": "active", "review_id": str(review.id)},
        )
        return merged_row.id

    @staticmethod
    def _activate(row: Memory) -> None:
        row.status = MemoryStatus.ACTIVE
        row.superseded_by_id = None

    @staticmethod
    def _supersede(
        *,
        repo: MemoryRepository,
        old: Memory,
        new: Memory,
        reason_code: str,
        reason: str,
    ) -> None:
        old_before = {
            "status": old.status.value,
            "superseded_by_id": str(old.superseded_by_id) if old.superseded_by_id else None,
        }
        old.status = MemoryStatus.SUPERSEDED
        old.superseded_by_id = new.id
        repo.insert_event(
            scope_id=old.scope_id,
            memory_id=old.id,
            related_memory_id=new.id,
            event_type=MemoryEventType.SUPERSEDED,
            relation=MemoryRelation.SUPERSEDE,
            reason_code=reason_code,
            reason_summary=reason,
            before=old_before,
            after={"status": MemoryStatus.SUPERSEDED.value, "superseded_by_id": str(new.id)},
        )
        new.why = list(
            dict.fromkeys(
                [
                    *(new.why or []),
                    *memory_why_for_supersession(
                        relation_confidence=new.confidence,
                        reason_summary=reason,
                        explicit_change=False,
                    ),
                ]
            )
        )[:8]

    def _approve_consolidation(
        self,
        *,
        session: Session,
        repo: MemoryRepository,
        row: MemoryReview,
        reason: str,
    ) -> UUID:
        # Use the same policy and persistence path as ingestion. Approval never
        # makes an arbitrary summary or centroid stand in for distinct facts.
        from memoryos.domain.policies import validate_consolidation
        from memoryos.services.consolidation import persist_consolidation

        source_rows = list(
            session.scalars(
                select(Memory)
                .where(
                    Memory.scope_id == row.scope_id,
                    Memory.id.in_([UUID(str(value)) for value in row.source_memory_ids or []]),
                )
                .order_by(Memory.id.asc())
                .with_for_update()
            )
        )
        validation = validate_consolidation(
            [_row_memory(source) for source in source_rows],
            as_of=utc_now(),
            automatic=False,
        )
        candidate = _snapshot_candidate(row.candidate_json)
        if validation.plan is None or validation.plan.canonical.content != candidate.content:
            raise ServiceError("invalid_request", validation.reason)
        scope = repo.require_scope(row.scope_id)
        if validation.plan.canonical.embedding_model != scope.embedding_model:
            raise ServiceError("embedding_model_mismatch", "The source embedding space changed.")
        return persist_consolidation(
            session=session,
            repo=repo,
            plan=validation.plan,
            provenance="owner-review",
            review_id=row.id,
        )


ReviewService = MemoryReviewService


__all__ = ["MemoryReviewService", "ReviewService"]
