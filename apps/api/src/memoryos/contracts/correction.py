"""Correction input is new evidence, not an in-place memory edit."""

from uuid import UUID

from pydantic import Field

from memoryos.contracts.common import ContractModel
from memoryos.domain.enums import ExecutionMode, IngestDecisionType


class CorrectionRequest(ContractModel):
    scope_id: UUID
    text: str = Field(min_length=1, max_length=2_000)
    mode: ExecutionMode = ExecutionMode.DEMO
    preview: bool = True
    idempotency_key: str | None = Field(default=None, max_length=255)
    expected_scope_revision: int | None = Field(default=None, ge=0)
    reviewed_decisions: list[IngestDecisionType] | None = Field(default=None, max_length=5)
    reviewed_targets: list[UUID | None] | None = Field(default=None, max_length=5)
