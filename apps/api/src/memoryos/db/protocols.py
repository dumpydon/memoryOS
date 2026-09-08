"""Repository protocols consumed by policy and service workers.

The concrete implementation lives in :mod:`memoryos.db.repositories`; these
protocols keep service workers independent of SQLAlchemy while retaining the
embedding that policy ranking needs.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from memoryos.contracts.memory import MemoryEvent, MemoryHistoryResponse, MemoryRecord
from memoryos.contracts.recall import RecallRequest
from memoryos.domain.enums import MemoryEventType, MemoryRelation, MemoryStatus, MemoryType


class StoredMemory(Protocol):
    """Internal repository projection with the vector needed for ranking."""

    record: MemoryRecord
    embedding: Sequence[float]
    embedding_model: str
    embedding_dimensions: int


class RecallCandidate(StoredMemory, Protocol):
    raw_similarity: float | None


class RelatedCandidate(RecallCandidate, Protocol):
    attribute_match: bool
    context_match: bool


class MemoryRepository(Protocol):
    """Persistence boundary consumed by policy and service workers."""

    def get_by_id(self, scope_id: UUID, memory_id: UUID) -> MemoryRecord | None: ...

    def list_active_for_recall(
        self,
        request: RecallRequest,
        *,
        as_of: datetime,
        query_embedding: Sequence[float] | None = None,
        embedding_model: str | None = None,
        query_embedding_model: str | None = None,
        limit: int | None = None,
    ) -> Sequence[RecallCandidate]: ...

    def get_stored_by_id(self, scope_id: UUID, memory_id: UUID) -> StoredMemory | None: ...

    def list_memories(
        self,
        *,
        scope_id: UUID,
        cursor: str | None = None,
        limit: int = 25,
        memory_types: Sequence[MemoryType] | None = None,
        statuses: Sequence[MemoryStatus] | None = None,
        search: str | None = None,
    ) -> Any: ...

    def get_history(self, *, scope_id: UUID, memory_id: UUID) -> MemoryHistoryResponse | None: ...

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
    ) -> Sequence[RelatedCandidate]: ...

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
    ) -> MemoryEvent: ...
