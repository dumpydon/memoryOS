"""Memory and history response contracts."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from memoryos.contracts.common import ContractModel, PageInfo
from memoryos.domain.enums import MemoryEventType, MemoryStatus, MemoryType


class MemoryRecord(ContractModel):
    id: UUID
    scope_id: UUID
    lineage_id: UUID
    version: int = Field(ge=1)
    content: str
    memory_type: MemoryType
    status: MemoryStatus
    subject: str | None = None
    context_key: str | None = None
    attribute_key: str | None = None
    importance: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    reinforcement_count: int = Field(ge=0)
    embedding_model: str = Field(min_length=1)
    embedding_dimensions: int = Field(ge=1)
    created_at: datetime
    effective_at: datetime
    last_confirmed_at: datetime
    expires_at: datetime | None = None
    superseded_by_id: UUID | None = None


class MemoryVersion(ContractModel):
    memory: MemoryRecord
    is_current: bool = False


class MemoryEvent(ContractModel):
    id: UUID
    scope_id: UUID
    memory_id: UUID
    interaction_id: UUID | None = None
    event_type: MemoryEventType
    related_memory_id: UUID | None = None
    evidence_excerpt: str | None = None
    reason_code: str
    reason_summary: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    memory_content: str | None = None
    created_at: datetime


class MemoryListItem(MemoryRecord):
    """Explorer rows share the full public memory record shape."""


class MemoryListResponse(ContractModel):
    items: list[MemoryListItem]
    page: PageInfo = Field(default_factory=PageInfo)
    total: int = Field(ge=0)


class MemoryHistoryResponse(ContractModel):
    lineage_id: UUID
    versions: list[MemoryVersion]
    events: list[MemoryEvent]


class ForgetMemoryRequest(ContractModel):
    reason: str = Field(default="Forgotten by owner", min_length=1, max_length=500)


class ForgetMemoryResponse(ContractModel):
    lineage_id: UUID
    forgotten_memory_ids: list[UUID]
    reason: str


class ResolveMemoryRequest(ContractModel):
    selected_memory_id: UUID
    reason: str = Field(default="Resolved by owner", min_length=1, max_length=500)


class ResolveMemoryResponse(ContractModel):
    lineage_id: UUID
    selected_memory_id: UUID
    resolved_memory_ids: list[UUID]
    reason: str
