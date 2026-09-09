"""Small owner/public access policy shared by REST and MCP adapters."""

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from fastapi import Request

from memoryos.config import Settings
from memoryos.domain.enums import ExecutionMode
from memoryos.services.errors import ServiceError

PUBLIC_DEMO_SCOPE: Final[UUID] = UUID("00000000-0000-0000-0000-000000000001")
PRIVATE_LIVE_SCOPE: Final[UUID] = UUID("00000000-0000-0000-0000-000000000002")
PUBLIC_DEMO_QUERY_LIMIT: Final[int] = 20
DEFAULT_OWNER_TOKEN: Final[str] = "memoryos-local-token"


@dataclass(frozen=True, slots=True)
class AccessContext:
    is_owner: bool
    is_public_demo: bool


def validate_security_settings(settings: Settings) -> None:
    """Reject the development token when an app is explicitly production."""

    if settings.app_env.casefold() in {"production", "prod"} and (
        not settings.owner_api_token or settings.owner_api_token == DEFAULT_OWNER_TOKEN
    ):
        raise RuntimeError("OWNER_API_TOKEN must be configured in production")


def _bearer_token(request: Request) -> str | None:
    value = request.headers.get("authorization", "")
    scheme, _, token = value.partition(" ")
    if scheme.casefold() != "bearer" or not token:
        return None
    return token


def owner_from_request(request: Request, settings: Settings) -> bool:
    token = _bearer_token(request)
    return bool(token and settings.owner_api_token and token == settings.owner_api_token)


def owner_from_token(token: str | None, settings: Settings) -> bool:
    return bool(token and settings.owner_api_token and token == settings.owner_api_token)


def is_public_demo_scope(scope_id: UUID, mode: ExecutionMode = ExecutionMode.DEMO) -> bool:
    return scope_id == PUBLIC_DEMO_SCOPE and mode is ExecutionMode.DEMO


def authorize_request(
    request: Request,
    *,
    scope_id: UUID,
    settings: Settings,
    mode: ExecutionMode = ExecutionMode.DEMO,
    mutation: bool = False,
    public_demo_allowed: bool = True,
) -> AccessContext:
    """Authorize one scoped route without trusting a caller-supplied scope."""

    is_owner = owner_from_request(request, settings)
    if is_owner:
        return AccessContext(is_owner=True, is_public_demo=False)
    if mutation or mode is ExecutionMode.LIVE:
        raise ServiceError("auth_required", "Owner authentication is required for this operation.")
    if not public_demo_allowed or not is_public_demo_scope(scope_id, mode):
        raise ServiceError("scope_forbidden", "Public access is limited to the demo scope.")
    return AccessContext(is_owner=False, is_public_demo=True)


def authorize_token(
    *,
    token: str | None,
    scope_id: UUID,
    settings: Settings,
    mode: ExecutionMode = ExecutionMode.DEMO,
    mutation: bool = False,
) -> AccessContext:
    """Equivalent access check for MCP tools, which receive explicit token context."""

    is_owner = owner_from_token(token, settings)
    if is_owner:
        return AccessContext(is_owner=True, is_public_demo=False)
    if mutation or mode is ExecutionMode.LIVE:
        raise ServiceError("auth_required", "Owner authentication is required for this operation.")
    if not is_public_demo_scope(scope_id, mode):
        raise ServiceError("scope_forbidden", "Public access is limited to the demo scope.")
    return AccessContext(is_owner=False, is_public_demo=True)
