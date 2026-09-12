"""Explainable recall and ranking comparison contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from memoryos.contracts.common import ContractModel
from memoryos.contracts.memory import MemoryRecord
from memoryos.domain.enums import ExecutionMode, MemoryType


class RecallRequest(ContractModel):
    scope_id: UUID
    query: str = Field(min_length=1, max_length=2_000)
    limit: int = Field(default=5, ge=1, le=20)
    min_similarity: float = Field(default=0.25, ge=0, le=1)
    memory_types: list[MemoryType] | None = None
    include_disputed: bool = False
    as_of: datetime | None = None
    mode: ExecutionMode = ExecutionMode.DEMO


class RecallScoreBreakdown(ContractModel):
    policy_version: str
    raw_similarity: float = Field(ge=-1, le=1)
    similarity: float = Field(ge=0, le=1)
    importance: float = Field(ge=0, le=1)
    recency: float = Field(ge=0, le=1)
    reinforcement: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    weighted_similarity: float = Field(ge=0, le=1)
    weighted_importance: float = Field(ge=0, le=1)
    weighted_recency: float = Field(ge=0, le=1)
    weighted_reinforcement: float = Field(ge=0, le=1)
    weighted_confidence: float = Field(ge=0, le=1)
    total: float = Field(ge=0, le=1)
    days_since_confirmation: float = Field(ge=0)
    half_life_days: int = Field(ge=1)


class RecallItem(ContractModel):
    rank: int = Field(ge=1)
    memory: MemoryRecord
    score: RecallScoreBreakdown
    explanation: str


class RecallResponse(ContractModel):
    scope_id: UUID
    query: str
    evaluated_at: datetime
    policy_version: str
    candidate_count: int = Field(ge=0)
    items: list[RecallItem]


class RecallComparisonItem(ContractModel):
    memory: MemoryRecord
    naive_rank: int | None = Field(default=None, ge=1)
    memoryos_rank: int | None = Field(default=None, ge=1)
    naive_similarity: float = Field(ge=0, le=1)
    memoryos_score: RecallScoreBreakdown
    rank_delta: int | None = None
    explanation: str = ""


class RecallComparisonResponse(ContractModel):
    scope_id: UUID
    query: str
    evaluated_at: datetime
    policy_version: str
    naive: list[RecallComparisonItem]
    memoryos: list[RecallComparisonItem]
    candidate_count: int = Field(ge=0)
