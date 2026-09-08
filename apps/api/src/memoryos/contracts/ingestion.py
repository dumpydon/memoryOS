"""Structured extraction, relationship, and interaction contracts."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator

from memoryos.contracts.common import ContractModel, TraceStep
from memoryos.domain.enums import (
    ExecutionMode,
    IngestDecisionType,
    InteractionStatus,
    MemoryRelation,
    MemoryType,
)


class IngestInteractionRequest(ContractModel):
    scope_id: UUID
    text: str = Field(min_length=1, max_length=20_000)
    source_ref: str | None = Field(default=None, max_length=512)
    occurred_at: datetime | None = None
    idempotency_key: str | None = Field(default=None, max_length=255)
    mode: ExecutionMode = ExecutionMode.DEMO
    preview: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("text must contain non-whitespace content")
        return normalized

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("occurred_at must include a timezone")
        return value


class CandidateMemory(ContractModel):
    candidate_id: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=2_000)
    memory_type: MemoryType
    subject: str | None = Field(default=None, max_length=255)
    context_key: str | None = Field(default=None, max_length=255)
    attribute_key: str | None = Field(default=None, max_length=255)
    importance: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    evidence_excerpt: str = Field(min_length=1, max_length=1_000)
    effective_at: datetime | None = None
    expires_at: datetime | None = None
    worth_remembering: bool = True
    skip_reason: str | None = Field(default=None, max_length=500)


class RelationAssessment(ContractModel):
    candidate_id: str
    related_memory_id: UUID | None = None
    relation: MemoryRelation
    confidence: float = Field(ge=0, le=1)
    evidence_excerpt: str = Field(min_length=1, max_length=1_000)
    reason_code: str = Field(min_length=1, max_length=100)
    reason_summary: str = Field(min_length=1, max_length=500)


class IngestDecision(ContractModel):
    decision_type: IngestDecisionType
    candidate_id: str | None = None
    memory_id: UUID | None = None
    related_memory_id: UUID | None = None
    reason_code: str
    reason_summary: str
    confidence: float | None = Field(default=None, ge=0, le=1)


class InteractionTrace(ContractModel):
    steps: list[TraceStep] = Field(default_factory=list)
    policy_version: str
    provider_mode: ExecutionMode


class IngestInteractionResponse(ContractModel):
    interaction_id: UUID
    scope_id: UUID
    status: InteractionStatus
    mode: ExecutionMode
    candidates: list[CandidateMemory] = Field(default_factory=list)
    decisions: list[IngestDecision] = Field(default_factory=list)
    memory_ids: list[UUID] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    trace: InteractionTrace
