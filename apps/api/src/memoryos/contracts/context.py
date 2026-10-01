"""A single request answered with recalled long-term memory."""

from uuid import UUID

from pydantic import Field, field_validator

from memoryos.contracts.common import ContractModel
from memoryos.domain.enums import ExecutionMode, MemoryType


class ContextRequest(ContractModel):
    scope_id: UUID
    query: str = Field(min_length=1, max_length=2_000)
    limit: int = Field(default=3, ge=1, le=5)
    mode: ExecutionMode = ExecutionMode.DEMO

    @field_validator("query")
    @classmethod
    def meaningful_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A request is required.")
        return value.strip()


class ContextMemory(ContractModel):
    id: UUID
    content: str
    memory_type: MemoryType
    context_key: str | None = None


class ContextResponse(ContractModel):
    query: str
    answer: str
    memories_used: list[ContextMemory]
    mode: ExecutionMode
    model: str
