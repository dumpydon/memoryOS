"""Small shared response contracts."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_schema_serialization_defaults_required=True,
    )


class ScopeRef(ContractModel):
    scope_id: UUID


class AuthContext(ContractModel):
    """Resolved by transport middleware; never accepted from request JSON."""

    authenticated: bool = False
    is_owner: bool = False
    principal: str | None = None


class ErrorResponse(ContractModel):
    code: str
    message: str
    request_id: str
    retryable: bool = False


class PageInfo(ContractModel):
    next_cursor: str | None = None


class TraceStep(ContractModel):
    node: str
    duration_ms: float = Field(ge=0)
    status: str = "completed"


class ApiHealth(ContractModel):
    status: str
    service: str = "memoryos-api"
    checked_at: datetime
    details: dict[str, Any] = Field(default_factory=dict)
