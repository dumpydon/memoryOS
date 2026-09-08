"""Synchronous SQLAlchemy repositories used by the ingestion and query workers.

The repository intentionally leaves transaction ownership to its caller.  Reads
may be used directly; every write that changes a scope should be wrapped in
``repo.mutation(scope_id, expected_revision)`` (or the lower-level
``scope_revision_transaction`` helper).
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import uuid
from collections.abc import Iterable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from memoryos.config import Settings, get_settings
from memoryos.contracts.memory import (
    MemoryEvent as MemoryEventContract,
)
from memoryos.contracts.memory import (
    MemoryHistoryResponse,
    MemoryListItem,
    MemoryListResponse,
    MemoryRecord,
    MemoryVersion,
)
from memoryos.contracts.recall import RecallRequest
from memoryos.db.errors import (
    DuplicateReinforcement,
    IdempotencyConflict,
    InvalidEmbedding,
    ScopeNotFoundError,
)
from memoryos.db.models import Interaction, Memory, MemoryEvent, Scope
from memoryos.db.transactions import ScopeRevision, scope_revision_transaction
from memoryos.domain.enums import (
    ExecutionMode,
    InteractionStatus,
    MemoryEventType,
    MemoryRelation,
    MemoryStatus,
    MemoryType,
)

VECTOR_DIMENSIONS = 1536


def utc_now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None, *, default: datetime | None = None) -> datetime:
    result = value or default or utc_now()
    if result.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return result.astimezone(UTC)


def _jsonable(value: Any) -> Any:
    """Convert the small set of Pydantic/domain values used in write payloads."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _jsonable(model_dump(mode="json"))
    enum_value = getattr(value, "value", None)
    if enum_value is not None:
        return _jsonable(enum_value)
    return str(value)


def _enum_value(value: Any, enum_type: type[Any]) -> Any:
    if isinstance(value, enum_type):
        return value
    return enum_type(value)


def _validate_vector(embedding: Sequence[float] | None) -> list[float]:
    if embedding is None:
        raise InvalidEmbedding("an embedding is required for every persisted memory")
    values = [float(value) for value in embedding]
    if len(values) != VECTOR_DIMENSIONS:
        raise InvalidEmbedding(
            f"expected an embedding with {VECTOR_DIMENSIONS} dimensions, found {len(values)}"
        )
    if not all(math.isfinite(value) for value in values):
        raise InvalidEmbedding("embedding values must be finite")
    if not any(value != 0 for value in values):
        raise InvalidEmbedding("embedding must have a non-zero norm for cosine search")
    return values


def _row_vector(row: Memory) -> tuple[float, ...]:
    """Normalize psycopg/pgvector's list or ndarray result without truth tests."""

    raw = row.embedding
    if raw is None:
        return ()
    return tuple(float(value) for value in raw)


def _encode_cursor(created_at: datetime, memory_id: UUID) -> str:
    raw = json.dumps({"created_at": created_at.isoformat(), "id": str(memory_id)}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        timestamp = datetime.fromisoformat(payload["created_at"])
        if timestamp.tzinfo is None:
            raise ValueError
        return timestamp.astimezone(UTC), UUID(payload["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid memory list cursor") from exc


@dataclass(frozen=True, slots=True)
class ScopeResult:
    id: UUID
    name: str
    revision: int
    embedding_model: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class InteractionResult:
    id: UUID
    scope_id: UUID
    idempotency_key: str | None
    request_hash: str
    provenance: str | None
    text: str
    occurred_at: datetime
    received_at: datetime
    status: InteractionStatus
    mode: ExecutionMode
    decisions: list[dict[str, Any]]
    trace: dict[str, Any]
    metadata: dict[str, Any]
    error_code: str | None
    error_message: str | None
    error_details: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class StoredMemory:
    """Internal memory projection that retains the vector for ranking."""

    record: MemoryRecord
    embedding: tuple[float, ...]
    embedding_model: str
    embedding_dimensions: int


@dataclass(frozen=True, slots=True)
class RecallCandidate(StoredMemory):
    """A scoped memory plus its exact pgvector cosine score, when requested."""

    raw_similarity: float | None = None


@dataclass(frozen=True, slots=True)
class RelatedCandidate(RecallCandidate):
    attribute_match: bool = False
    context_match: bool = False


@dataclass(frozen=True, slots=True)
class ScopeMutation:
    """Convenience object yielded by ``MemoryRepository.mutation``."""

    revision: ScopeRevision


def _scope_result(row: Scope) -> ScopeResult:
    return ScopeResult(
        id=row.id,
        name=row.name,
        revision=row.revision,
        embedding_model=row.embedding_model,
        created_at=row.created_at,
    )


def _interaction_result(row: Interaction) -> InteractionResult:
    return InteractionResult(
        id=row.id,
        scope_id=row.scope_id,
        idempotency_key=row.idempotency_key,
        request_hash=row.request_hash,
        provenance=row.provenance,
        text=row.text,
        occurred_at=row.occurred_at,
        received_at=row.received_at,
        status=row.status,
        mode=row.mode,
        decisions=row.decisions or [],
        trace=row.trace or {},
        metadata=row.metadata_json or {},
        error_code=row.error_code,
        error_message=row.error_message,
        error_details=row.error_details,
    )


def _memory_record(row: Memory) -> MemoryRecord:
    vector = _row_vector(row)
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
    )


def _stored_memory(row: Memory) -> StoredMemory:
    vector = _row_vector(row)
    return StoredMemory(
        record=_memory_record(row),
        embedding=vector,
        embedding_model=row.embedding_model,
        embedding_dimensions=len(vector),
    )


def _event_contract(row: MemoryEvent) -> MemoryEventContract:
    return MemoryEventContract(
        id=row.id,
        scope_id=row.scope_id,
        memory_id=row.memory_id,
        interaction_id=row.interaction_id,
        event_type=row.event_type,
        related_memory_id=row.related_memory_id,
        evidence_excerpt=row.evidence_excerpt,
        reason_code=row.reason_code,
        reason_summary=row.reason_summary,
        before=row.before,
        after=row.after,
        created_at=row.created_at,
    )


class MemoryRepository:
    """Concrete synchronous repository backed by one SQLAlchemy session.

    Methods do not commit.  This keeps interaction, memory, and event writes in
    one caller-owned transaction and lets the scope revision guard cover the whole
    mutation batch.
    """

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    # -- scope and transaction helpers ---------------------------------

    def mutation(
        self, *, scope_id: UUID, expected_revision: int
    ) -> AbstractContextManager[ScopeRevision]:
        """Return the scope lock/assert context used around one mutation batch."""

        return scope_revision_transaction(
            self.session,
            scope_id=scope_id,
            expected_revision=expected_revision,
        )

    scope_mutation = mutation

    def create_scope(
        self,
        *,
        name: str,
        embedding_model: str | None = None,
        scope_id: UUID | None = None,
        revision: int = 0,
        created_at: datetime | None = None,
    ) -> ScopeResult:
        row = Scope(
            id=scope_id or uuid.uuid4(),
            name=name,
            revision=revision,
            embedding_model=embedding_model or self.settings.embedding_model,
            created_at=_aware(created_at) if created_at else None,
        )
        self.session.add(row)
        self.session.flush()
        return _scope_result(row)

    def get_scope(self, scope_id: UUID) -> ScopeResult | None:
        row = self.session.get(Scope, scope_id)
        return _scope_result(row) if row else None

    def require_scope(self, scope_id: UUID) -> ScopeResult:
        result = self.get_scope(scope_id)
        if result is None:
            raise ScopeNotFoundError(scope_id)
        return result

    def current_scope_revision(self, scope_id: UUID) -> int:
        scope = self.require_scope(scope_id)
        return scope.revision

    # -- interactions ---------------------------------------------------

    def insert_interaction(
        self,
        *,
        scope_id: UUID,
        text: str,
        request_hash: str | None = None,
        idempotency_key: str | None = None,
        provenance: str | None = None,
        source_ref: str | None = None,
        occurred_at: datetime | None = None,
        received_at: datetime | None = None,
        status: InteractionStatus = InteractionStatus.RECEIVED,
        mode: ExecutionMode = ExecutionMode.DEMO,
        decisions: Iterable[Any] | None = None,
        trace: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        error_details: dict[str, Any] | None = None,
        interaction_id: UUID | None = None,
    ) -> InteractionResult:
        """Insert an interaction or return the existing idempotent request.

        A caller may safely invoke this after locking the scope.  The unique
        database key still protects callers that race without the helper.
        """

        self.require_scope(scope_id)
        normalized_status = _enum_value(status, InteractionStatus)
        normalized_mode = _enum_value(mode, ExecutionMode)
        normalized_hash = request_hash or hashlib.sha256(text.encode("utf-8")).hexdigest()
        normalized_provenance = provenance if provenance is not None else source_ref

        if idempotency_key is not None:
            existing = self.session.scalar(
                select(Interaction)
                .where(
                    Interaction.scope_id == scope_id,
                    Interaction.idempotency_key == idempotency_key,
                )
                .with_for_update()
            )
            if existing is not None:
                if existing.request_hash != normalized_hash:
                    raise IdempotencyConflict(scope_id, idempotency_key)
                return _interaction_result(existing)

        row = Interaction(
            id=interaction_id or uuid.uuid4(),
            scope_id=scope_id,
            idempotency_key=idempotency_key,
            request_hash=normalized_hash,
            provenance=normalized_provenance,
            text=text,
            occurred_at=_aware(occurred_at),
            received_at=_aware(received_at),
            status=normalized_status,
            mode=normalized_mode,
            decisions=cast(list[dict[str, Any]], _jsonable(list(decisions or []))),
            trace=cast(dict[str, Any], _jsonable(trace or {})),
            metadata_json=cast(dict[str, Any], _jsonable(metadata or {})),
            error_code=error_code,
            error_message=error_message,
            error_details=cast(dict[str, Any] | None, _jsonable(error_details)),
        )
        self.session.add(row)
        try:
            self.session.flush()
        except IntegrityError:
            # A concurrent writer can win the unique key between the lookup and
            # flush.  Let the outer transaction roll back; callers can retry.
            raise
        return _interaction_result(row)

    def get_interaction(self, *, scope_id: UUID, interaction_id: UUID) -> InteractionResult | None:
        row = self.session.scalar(
            select(Interaction).where(
                Interaction.scope_id == scope_id,
                Interaction.id == interaction_id,
            )
        )
        return _interaction_result(row) if row else None

    def get_interaction_by_idempotency(
        self,
        *,
        scope_id: UUID,
        idempotency_key: str,
        request_hash: str | None = None,
    ) -> InteractionResult | None:
        row = self.session.scalar(
            select(Interaction).where(
                Interaction.scope_id == scope_id,
                Interaction.idempotency_key == idempotency_key,
            )
        )
        if row is None:
            return None
        if request_hash is not None and row.request_hash != request_hash:
            raise IdempotencyConflict(scope_id, idempotency_key)
        return _interaction_result(row)

    def update_interaction(
        self,
        *,
        scope_id: UUID,
        interaction_id: UUID,
        status: InteractionStatus | None = None,
        decisions: Iterable[Any] | None = None,
        trace: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        error_details: dict[str, Any] | None = None,
    ) -> InteractionResult | None:
        row = self.session.scalar(
            select(Interaction).where(
                Interaction.scope_id == scope_id,
                Interaction.id == interaction_id,
            )
        )
        if row is None:
            return None
        if status is not None:
            row.status = _enum_value(status, InteractionStatus)
        if decisions is not None:
            row.decisions = cast(list[dict[str, Any]], _jsonable(list(decisions)))
        if trace is not None:
            row.trace = cast(dict[str, Any], _jsonable(trace))
        if error_code is not None:
            row.error_code = error_code
        if error_message is not None:
            row.error_message = error_message
        if error_details is not None:
            row.error_details = cast(dict[str, Any], _jsonable(error_details))
        self.session.flush()
        return _interaction_result(row)

    # -- memories -------------------------------------------------------

    def insert_memory(
        self,
        *,
        scope_id: UUID,
        content: str,
        memory_type: MemoryType,
        importance: float,
        confidence: float,
        embedding: Sequence[float],
        embedding_model: str | None = None,
        status: MemoryStatus = MemoryStatus.ACTIVE,
        subject: str | None = None,
        context_key: str | None = None,
        attribute_key: str | None = None,
        lineage_id: UUID | None = None,
        version: int = 1,
        memory_id: UUID | None = None,
        reinforcement_count: int = 0,
        created_at: datetime | None = None,
        effective_at: datetime | None = None,
        last_confirmed_at: datetime | None = None,
        expires_at: datetime | None = None,
        superseded_by_id: UUID | None = None,
    ) -> StoredMemory:
        scope = self.require_scope(scope_id)
        vector = _validate_vector(embedding)
        normalized_id = memory_id or uuid.uuid4()
        row = Memory(
            id=normalized_id,
            scope_id=scope_id,
            lineage_id=lineage_id or normalized_id,
            version=version,
            content=content,
            memory_type=_enum_value(memory_type, MemoryType),
            status=_enum_value(status, MemoryStatus),
            subject=subject,
            context_key=context_key,
            attribute_key=attribute_key,
            importance=float(importance),
            confidence=float(confidence),
            reinforcement_count=reinforcement_count,
            embedding=vector,
            embedding_model=embedding_model or scope.embedding_model,
            created_at=_aware(created_at) if created_at else None,
            effective_at=_aware(effective_at) if effective_at else utc_now(),
            last_confirmed_at=(
                _aware(last_confirmed_at)
                if last_confirmed_at
                else _aware(effective_at)
                if effective_at
                else utc_now()
            ),
            expires_at=_aware(expires_at) if expires_at else None,
            superseded_by_id=superseded_by_id,
        )
        self.session.add(row)
        self.session.flush()
        return _stored_memory(row)

    insert_memory_version = insert_memory

    def get_stored_by_id(self, scope_id: UUID, memory_id: UUID) -> StoredMemory | None:
        row = self.session.scalar(
            select(Memory).where(Memory.scope_id == scope_id, Memory.id == memory_id)
        )
        return _stored_memory(row) if row else None

    def get_by_id(self, scope_id: UUID, memory_id: UUID) -> MemoryRecord | None:
        stored = self.get_stored_by_id(scope_id, memory_id)
        return stored.record if stored else None

    def set_memory_state(
        self,
        *,
        scope_id: UUID,
        memory_id: UUID,
        status: MemoryStatus | None = None,
        reinforcement_count: int | None = None,
        last_confirmed_at: datetime | None = None,
        superseded_by_id: UUID | None = None,
    ) -> StoredMemory | None:
        """Update lifecycle state while leaving immutable content untouched."""

        row = self.session.scalar(
            select(Memory)
            .where(Memory.scope_id == scope_id, Memory.id == memory_id)
            .with_for_update()
        )
        if row is None:
            return None
        if status is not None:
            row.status = _enum_value(status, MemoryStatus)
        if reinforcement_count is not None:
            row.reinforcement_count = reinforcement_count
        if last_confirmed_at is not None:
            row.last_confirmed_at = _aware(last_confirmed_at)
        if superseded_by_id is not None:
            row.superseded_by_id = superseded_by_id
        self.session.flush()
        return _stored_memory(row)

    def reinforce_memory(
        self,
        *,
        scope_id: UUID,
        memory_id: UUID,
        interaction_id: UUID,
        evidence_excerpt: str | None = None,
        reason_code: str = "reinforced",
        reason_summary: str = "Reinforced by interaction",
        provenance: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        confirmed_at: datetime | None = None,
    ) -> tuple[StoredMemory, MemoryEventContract]:
        """Increment a memory once and record its reinforcement event."""

        interaction = self.get_interaction(scope_id=scope_id, interaction_id=interaction_id)
        if interaction is None:
            raise ValueError("interaction must belong to the memory scope")
        row = self.session.scalar(
            select(Memory)
            .where(Memory.scope_id == scope_id, Memory.id == memory_id)
            .with_for_update()
        )
        if row is None:
            raise ValueError("memory must belong to the memory scope")
        existing = self.session.scalar(
            select(MemoryEvent).where(
                MemoryEvent.scope_id == scope_id,
                MemoryEvent.memory_id == memory_id,
                MemoryEvent.interaction_id == interaction_id,
                MemoryEvent.event_type == MemoryEventType.REINFORCED,
            )
        )
        if existing is not None:
            raise DuplicateReinforcement(scope_id, interaction_id, memory_id)

        confirmed = _aware(confirmed_at)
        before_payload = (
            _jsonable(before)
            if before is not None
            else {
                "reinforcement_count": row.reinforcement_count,
                "last_confirmed_at": row.last_confirmed_at.isoformat(),
            }
        )
        row.reinforcement_count += 1
        row.last_confirmed_at = confirmed
        event = MemoryEvent(
            scope_id=scope_id,
            memory_id=memory_id,
            interaction_id=interaction_id,
            event_type=MemoryEventType.REINFORCED,
            evidence_excerpt=evidence_excerpt,
            reason_code=reason_code,
            reason_summary=reason_summary,
            relation=MemoryRelation.REINFORCE,
            provenance=provenance,
            before=cast(dict[str, Any], before_payload),
            after=cast(
                dict[str, Any],
                _jsonable(after)
                if after is not None
                else {
                    "reinforcement_count": row.reinforcement_count,
                    "last_confirmed_at": confirmed.isoformat(),
                },
            ),
        )
        self.session.add(event)
        self.session.flush()
        return _stored_memory(row), _event_contract(event)

    # -- events and history --------------------------------------------

    def insert_event(
        self,
        *,
        scope_id: UUID,
        memory_id: UUID,
        event_type: MemoryEventType,
        reason_code: str,
        reason_summary: str,
        interaction_id: UUID | None = None,
        related_memory_id: UUID | None = None,
        evidence_excerpt: str | None = None,
        relation: MemoryRelation | None = None,
        provenance: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        event_id: UUID | None = None,
        created_at: datetime | None = None,
    ) -> MemoryEventContract:
        if event_type == MemoryEventType.REINFORCED and interaction_id is not None:
            existing = self.session.scalar(
                select(MemoryEvent).where(
                    MemoryEvent.scope_id == scope_id,
                    MemoryEvent.memory_id == memory_id,
                    MemoryEvent.interaction_id == interaction_id,
                    MemoryEvent.event_type == MemoryEventType.REINFORCED,
                )
            )
            if existing is not None:
                raise DuplicateReinforcement(scope_id, interaction_id, memory_id)
        event = MemoryEvent(
            id=event_id or uuid.uuid4(),
            scope_id=scope_id,
            memory_id=memory_id,
            interaction_id=interaction_id,
            event_type=_enum_value(event_type, MemoryEventType),
            related_memory_id=related_memory_id,
            evidence_excerpt=evidence_excerpt,
            reason_code=reason_code,
            reason_summary=reason_summary,
            relation=_enum_value(relation, MemoryRelation) if relation is not None else None,
            provenance=provenance,
            before=cast(dict[str, Any] | None, _jsonable(before)),
            after=cast(dict[str, Any] | None, _jsonable(after)),
            created_at=_aware(created_at) if created_at else None,
        )
        self.session.add(event)
        self.session.flush()
        return _event_contract(event)

    def get_history(self, *, scope_id: UUID, memory_id: UUID) -> MemoryHistoryResponse | None:
        selected = self.session.scalar(
            select(Memory).where(Memory.scope_id == scope_id, Memory.id == memory_id)
        )
        if selected is None:
            return None
        versions = list(
            self.session.scalars(
                select(Memory)
                .where(
                    Memory.scope_id == scope_id,
                    Memory.lineage_id == selected.lineage_id,
                )
                .order_by(Memory.version.asc(), Memory.id.asc())
            )
        )
        events = list(
            self.session.scalars(
                select(MemoryEvent)
                .where(
                    MemoryEvent.scope_id == scope_id,
                    MemoryEvent.memory_id.in_([row.id for row in versions]),
                )
                .order_by(MemoryEvent.created_at.asc(), MemoryEvent.id.asc())
            )
        )
        active = [row for row in versions if row.status == MemoryStatus.ACTIVE]
        current = max(active or versions, key=lambda row: (row.version, row.id.hex))
        return MemoryHistoryResponse(
            lineage_id=selected.lineage_id,
            versions=[
                MemoryVersion(memory=_memory_record(row), is_current=row.id == current.id)
                for row in versions
            ],
            events=[_event_contract(row) for row in events],
        )

    def list_events(self, *, scope_id: UUID, memory_id: UUID) -> list[MemoryEventContract]:
        rows = self.session.scalars(
            select(MemoryEvent)
            .where(MemoryEvent.scope_id == scope_id, MemoryEvent.memory_id == memory_id)
            .order_by(MemoryEvent.created_at.asc(), MemoryEvent.id.asc())
        )
        return [_event_contract(row) for row in rows]

    # -- listing and recall --------------------------------------------

    def list_memories(
        self,
        *,
        scope_id: UUID,
        cursor: str | None = None,
        limit: int = 25,
        memory_types: Sequence[MemoryType] | None = None,
        statuses: Sequence[MemoryStatus] | None = None,
        search: str | None = None,
    ) -> MemoryListResponse:
        if limit < 1:
            raise ValueError("limit must be positive")
        limit = min(limit, 100)
        conditions: list[Any] = [Memory.scope_id == scope_id]
        if memory_types:
            conditions.append(
                Memory.memory_type.in_([_enum_value(item, MemoryType) for item in memory_types])
            )
        if statuses:
            conditions.append(
                Memory.status.in_([_enum_value(item, MemoryStatus) for item in statuses])
            )
        if search:
            pattern = f"%{search}%"
            conditions.append(
                or_(
                    Memory.content.ilike(pattern),
                    Memory.subject.ilike(pattern),
                    Memory.context_key.ilike(pattern),
                    Memory.attribute_key.ilike(pattern),
                )
            )
        if cursor:
            created_at, memory_id = _decode_cursor(cursor)
            conditions.append(
                or_(
                    Memory.created_at < created_at,
                    and_(Memory.created_at == created_at, Memory.id < memory_id),
                )
            )
        base = select(Memory).where(*conditions)
        total = self.session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = list(
            self.session.scalars(
                base.order_by(Memory.created_at.desc(), Memory.id.desc()).limit(limit + 1)
            )
        )
        has_next = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (
            _encode_cursor(rows[-1].created_at, rows[-1].id) if has_next and rows else None
        )
        return MemoryListResponse(
            items=[MemoryListItem(**_memory_record(row).model_dump()) for row in rows],
            total=total,
            page={"next_cursor": next_cursor},
        )

    def _model_for_mode(self, mode: ExecutionMode) -> str:
        return (
            self.settings.demo_embedding_model
            if mode == ExecutionMode.DEMO
            else self.settings.embedding_model
        )

    def _recall_conditions(
        self,
        request: RecallRequest,
        *,
        as_of: datetime,
        embedding_model: str | None,
        statuses: Sequence[MemoryStatus] | None = None,
    ) -> list[Any]:
        conditions: list[Any] = [
            Memory.scope_id == request.scope_id,
            Memory.effective_at <= as_of,
            or_(Memory.expires_at.is_(None), Memory.expires_at > as_of),
        ]
        allowed = list(statuses or [MemoryStatus.ACTIVE])
        if request.include_disputed and MemoryStatus.DISPUTED not in allowed:
            allowed.append(MemoryStatus.DISPUTED)
        conditions.append(Memory.status.in_([_enum_value(item, MemoryStatus) for item in allowed]))
        if request.memory_types:
            conditions.append(
                Memory.memory_type.in_(
                    [_enum_value(item, MemoryType) for item in request.memory_types]
                )
            )
        conditions.append(
            Memory.embedding_model == (embedding_model or self._model_for_mode(request.mode))
        )
        return conditions

    def list_active_for_recall(
        self,
        request: RecallRequest,
        *,
        as_of: datetime,
        query_embedding: Sequence[float] | None = None,
        embedding_model: str | None = None,
        query_embedding_model: str | None = None,
        limit: int | None = None,
    ) -> Sequence[RecallCandidate]:
        """Return every eligible memory, optionally with exact cosine scores.

        ``request.limit`` belongs to the policy worker's final ranking.  Unless a
        caller supplies ``limit`` explicitly this method therefore returns all
        eligible rows, preserving a fair candidate set for Recall Lab comparisons.
        """

        vector = _validate_vector(query_embedding) if query_embedding is not None else None
        model = embedding_model or query_embedding_model
        conditions = self._recall_conditions(request, as_of=_aware(as_of), embedding_model=model)
        similarity = None
        if vector is not None:
            similarity = (1 - Memory.embedding.cosine_distance(vector)).label("raw_similarity")
            # ``min_similarity`` is the public normalized [0, 1] value; retain
            # the raw [-1, 1] score in the returned candidate.
            conditions.append(func.greatest(0.0, similarity) >= request.min_similarity)
        stmt: Select[Any]
        if similarity is None:
            stmt = (
                select(Memory)
                .where(*conditions)
                .order_by(Memory.last_confirmed_at.desc(), Memory.id.desc())
            )
        else:
            stmt = (
                select(Memory, similarity)
                .where(*conditions)
                .order_by(similarity.desc(), Memory.id.desc())
            )
        if limit is not None:
            stmt = stmt.limit(limit)
        results: list[RecallCandidate] = []
        if similarity is None:
            rows = self.session.scalars(stmt).all()
            scored_rows: Iterable[tuple[Memory, float | None]] = ((row, None) for row in rows)
        else:
            scored_rows = (
                (cast(Memory, row), float(raw)) for row, raw in self.session.execute(stmt).all()
            )
        for row, raw in scored_rows:
            stored = _stored_memory(row)
            results.append(
                RecallCandidate(
                    record=stored.record,
                    embedding=stored.embedding,
                    embedding_model=stored.embedding_model,
                    embedding_dimensions=stored.embedding_dimensions,
                    raw_similarity=raw,
                )
            )
        return results

    def related_candidates(
        self,
        *,
        scope_id: UUID,
        attribute_key: str | None = None,
        context_key: str | None = None,
        query_embedding: Sequence[float] | None = None,
        embedding_model: str | None = None,
        memory_type: MemoryType | None = None,
        statuses: Sequence[MemoryStatus] | None = None,
        include_disputed: bool = False,
        as_of: datetime | None = None,
        limit: int = 10,
    ) -> Sequence[RelatedCandidate]:
        """Find same-attribute/context candidates plus nearest vector candidates."""

        if limit < 1:
            return []
        vector = _validate_vector(query_embedding) if query_embedding is not None else None
        snapshot = _aware(as_of)
        conditions: list[Any] = [
            Memory.scope_id == scope_id,
            Memory.effective_at <= snapshot,
            or_(Memory.expires_at.is_(None), Memory.expires_at > snapshot),
        ]
        allowed_statuses = list(statuses or [MemoryStatus.ACTIVE])
        if include_disputed and MemoryStatus.DISPUTED not in allowed_statuses:
            allowed_statuses.append(MemoryStatus.DISPUTED)
        conditions.append(
            Memory.status.in_([_enum_value(item, MemoryStatus) for item in allowed_statuses])
        )
        if memory_type is not None:
            conditions.append(Memory.memory_type == _enum_value(memory_type, MemoryType))
        if embedding_model is not None:
            conditions.append(Memory.embedding_model == embedding_model)
        attribute_match = (
            (Memory.attribute_key == attribute_key)
            if attribute_key is not None
            else cast(Any, False)
        )
        context_match = (
            (Memory.context_key == context_key) if context_key is not None else cast(Any, False)
        )
        match_score = case((attribute_match, 2), (context_match, 1), else_=0).label("match_score")
        if vector is not None:
            similarity = (1 - Memory.embedding.cosine_distance(vector)).label("raw_similarity")
            stmt = (
                select(
                    Memory,
                    similarity,
                    attribute_match.label("attribute_match"),
                    context_match.label("context_match"),
                )
                .where(*conditions)
                .order_by(match_score.desc(), similarity.desc(), Memory.id.desc())
                .limit(limit)
            )
        else:
            stmt = (
                select(
                    Memory,
                    attribute_match.label("attribute_match"),
                    context_match.label("context_match"),
                )
                .where(*conditions)
                .order_by(match_score.desc(), Memory.last_confirmed_at.desc(), Memory.id.desc())
                .limit(limit)
            )
        results: list[RelatedCandidate] = []
        for item in self.session.execute(stmt).all():
            if vector is not None:
                row, raw, attr, context = item
                score = float(raw)
            else:
                row, attr, context = item
                score = None
            stored = _stored_memory(cast(Memory, row))
            results.append(
                RelatedCandidate(
                    record=stored.record,
                    embedding=stored.embedding,
                    embedding_model=stored.embedding_model,
                    embedding_dimensions=stored.embedding_dimensions,
                    raw_similarity=score,
                    attribute_match=bool(attr),
                    context_match=bool(context),
                )
            )
        return results


SqlAlchemyMemoryRepository = MemoryRepository


__all__ = [
    "MemoryRepository",
    "RecallCandidate",
    "RelatedCandidate",
    "ScopeMutation",
    "ScopeResult",
    "InteractionResult",
    "SqlAlchemyMemoryRepository",
    "StoredMemory",
    "VECTOR_DIMENSIONS",
]
