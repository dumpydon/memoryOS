"""Dashboard overview contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from memoryos.contracts.common import ContractModel
from memoryos.contracts.memory import MemoryEvent
from memoryos.domain.enums import MemoryType


class MemoryTypeCount(ContractModel):
    memory_type: MemoryType
    count: int = Field(ge=0)


class OverviewResponse(ContractModel):
    scope_id: UUID
    active_memories: int = Field(ge=0)
    disputed_memories: int = Field(ge=0)
    reinforced_last_30_days: int = Field(ge=0)
    interactions_last_30_days: int = Field(ge=0)
    type_counts: list[MemoryTypeCount]
    recent_event_count: int = Field(ge=0)
    recent_events: list[MemoryEvent] = Field(default_factory=list)
    generated_at: datetime
