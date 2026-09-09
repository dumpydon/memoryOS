"""Service protocols freeze the seam between transports and business logic."""

from typing import Protocol
from uuid import UUID

from memoryos.contracts.ingestion import IngestInteractionRequest, IngestInteractionResponse
from memoryos.contracts.memory import (
    ForgetMemoryRequest,
    ForgetMemoryResponse,
    MemoryHistoryResponse,
    MemoryListResponse,
    MemoryRecord,
    ResolveMemoryRequest,
    ResolveMemoryResponse,
)
from memoryos.contracts.overview import OverviewResponse
from memoryos.contracts.recall import (
    RecallComparisonResponse,
    RecallRequest,
    RecallResponse,
)
from memoryos.domain.enums import MemoryStatus, MemoryType


class IngestionService(Protocol):
    def ingest(self, request: IngestInteractionRequest) -> IngestInteractionResponse: ...

    def get_interaction(
        self,
        *,
        scope_id: UUID,
        interaction_id: UUID,
    ) -> IngestInteractionResponse: ...


class RecallService(Protocol):
    def recall(self, request: RecallRequest) -> RecallResponse: ...

    def compare(self, request: RecallRequest) -> RecallComparisonResponse: ...


class MemoryQueryService(Protocol):
    def list_memories(
        self,
        *,
        scope_id: UUID,
        cursor: str | None = None,
        limit: int = 25,
        memory_types: list[MemoryType] | None = None,
        statuses: list[MemoryStatus] | None = None,
        search: str | None = None,
    ) -> MemoryListResponse: ...

    def get_memory(self, *, scope_id: UUID, memory_id: UUID) -> MemoryRecord: ...

    def history(self, *, scope_id: UUID, memory_id: UUID) -> MemoryHistoryResponse: ...


class MemoryMutationService(Protocol):
    def forget(
        self,
        *,
        scope_id: UUID,
        memory_id: UUID,
        request: ForgetMemoryRequest,
    ) -> ForgetMemoryResponse: ...

    def resolve(
        self,
        *,
        scope_id: UUID,
        memory_id: UUID,
        request: ResolveMemoryRequest,
    ) -> ResolveMemoryResponse: ...


class OverviewService(Protocol):
    def get_overview(self, *, scope_id: UUID) -> OverviewResponse: ...
