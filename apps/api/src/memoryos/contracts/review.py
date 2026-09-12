"""Reviewable memory decisions and conservative consolidation proposals."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from memoryos.contracts.common import ContractModel
from memoryos.contracts.ingestion import CandidateMemory
from memoryos.contracts.memory import MemoryRecord
from memoryos.domain.enums import ExecutionMode, MemoryRelation

ReviewAction = Literal["keep_both", "use_new", "keep_existing", "invalid"]
ReviewStatus = Literal["pending", "resolved"]


class ReviewItem(ContractModel):
    id: UUID
    scope_id: UUID
    kind: Literal["conflict", "consolidation"]
    status: ReviewStatus
    candidate: CandidateMemory
    existing_memory: MemoryRecord | None = None
    source_memories: list[MemoryRecord] = Field(default_factory=list)
    proposed_relation: MemoryRelation
    confidence: float = Field(ge=0, le=1)
    evidence_excerpt: str
    reason_code: str
    reason_summary: str
    created_at: datetime
    resolved_at: datetime | None = None
    resolution: ReviewAction | None = None
    resolution_reason: str | None = None
    memory_id: UUID | None = None


class ReviewListResponse(ContractModel):
    items: list[ReviewItem]
    total: int = Field(ge=0)


class ResolveReviewRequest(ContractModel):
    action: ReviewAction
    reason: str = Field(default="Reviewed by owner", min_length=1, max_length=500)


class ConsolidationRequest(ContractModel):
    scope_id: UUID
    source_memory_ids: list[UUID] = Field(min_length=3, max_length=8)
    mode: ExecutionMode = ExecutionMode.DEMO

    @field_validator("source_memory_ids")
    @classmethod
    def unique_sources(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("source_memory_ids must be unique")
        return value
