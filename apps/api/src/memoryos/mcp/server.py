"""MCP tools backed by the same services used by REST."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Any
from uuid import UUID

from mcp.server.mcpserver import Context

from memoryos.api.auth import authorize_token
from memoryos.config import Settings, get_settings
from memoryos.contracts.ingestion import IngestInteractionRequest, IngestInteractionResponse
from memoryos.contracts.memory import (
    ForgetMemoryRequest,
    ForgetMemoryResponse,
    MemoryListResponse,
)
from memoryos.contracts.recall import RecallRequest, RecallResponse
from memoryos.domain.enums import ExecutionMode, MemoryStatus, MemoryType
from memoryos.seed.catalog import is_allowed_demo_query, is_allowed_demo_scenario
from memoryos.services.errors import ServiceError
from memoryos.services.protocols import IngestionService
from memoryos.services.runtime import AppRuntime


def _ingestion(runtime: AppRuntime) -> IngestionService:
    try:
        from memoryos.services.ingestion import MemoryIngestionService
    except ImportError as exc:  # pragma: no cover - T4 is wired in the full app
        raise ServiceError(
            "provider_unavailable",
            "The ingestion service is not available.",
            retryable=True,
        ) from exc
    return MemoryIngestionService(runtime.settings, runtime.session_factory)


def _context_token(ctx: Context[Any, Any]) -> str | None:
    """Read owner auth from the transport context, never tool arguments."""

    request = ctx.request_context.request
    headers = getattr(request, "headers", None)
    if headers is not None:
        value = headers.get("authorization", "")
        if isinstance(value, str):
            scheme, _, token = value.partition(" ")
            if scheme.casefold() == "bearer" and token:
                return token
    # Stdio has no HTTP headers. A locally configured environment token is the
    # explicit owner context for that transport and never appears in tool input.
    return os.environ.get("MEMORYOS_MCP_OWNER_TOKEN")


def create_server(
    settings: Settings | None = None,
    *,
    runtime: AppRuntime | None = None,
) -> Any:
    """Create an MCP v2 server with four thin service adapters."""

    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError as exc:  # pragma: no cover - dependency is declared in pyproject
        raise RuntimeError("mcp is required to start the MemoryOS MCP server") from exc

    owned_runtime = runtime or AppRuntime.create(settings or get_settings())
    server = MCPServer(
        name="MemoryOS",
        version="0.1.0",
        description="Explainable long-term memory tools for AI agents.",
    )

    @server.tool(
        name="remember",
        description="Ingest one interaction through the MemoryOS ingestion service.",
        structured_output=True,
    )
    def remember(
        scope_id: UUID,
        text: str,
        source_ref: str | None = None,
        occurred_at: datetime | None = None,
        idempotency_key: str | None = None,
        mode: ExecutionMode = ExecutionMode.DEMO,
        preview: bool = False,
        metadata: dict[str, Any] | None = None,
        *,
        ctx: Context[Any, Any],
    ) -> IngestInteractionResponse:
        access = authorize_token(
            token=_context_token(ctx),
            scope_id=scope_id,
            settings=owned_runtime.settings,
            mode=mode,
            mutation=not preview,
        )
        if access.is_public_demo and (not preview or not is_allowed_demo_scenario(text)):
            raise ServiceError(
                "demo_input_not_allowed",
                "Public demo ingestion accepts only an allowlisted preview scenario.",
            )
        return _ingestion(owned_runtime).ingest(
            IngestInteractionRequest(
                scope_id=scope_id,
                text=text,
                source_ref=source_ref,
                occurred_at=occurred_at,
                idempotency_key=idempotency_key,
                mode=mode,
                preview=preview,
                metadata=metadata or {},
            )
        )

    @server.tool(
        name="recall",
        description="Recall scoped memories with explainable MemoryOS ranking.",
        structured_output=True,
    )
    def recall(
        scope_id: UUID,
        query: str,
        limit: int = 5,
        min_similarity: float = 0.25,
        memory_types: list[MemoryType] | None = None,
        include_disputed: bool = False,
        as_of: datetime | None = None,
        mode: ExecutionMode = ExecutionMode.DEMO,
        *,
        ctx: Context[Any, Any],
    ) -> RecallResponse:
        access = authorize_token(
            token=_context_token(ctx),
            scope_id=scope_id,
            settings=owned_runtime.settings,
            mode=mode,
        )
        if access.is_public_demo and not is_allowed_demo_query(query):
            raise ServiceError(
                "demo_input_not_allowed",
                "Public demo recall accepts only an allowlisted query.",
            )
        return owned_runtime.query.recall(
            RecallRequest(
                scope_id=scope_id,
                query=query,
                limit=limit,
                min_similarity=min_similarity,
                memory_types=memory_types,
                include_disputed=include_disputed,
                as_of=as_of,
                mode=mode,
            )
        )

    @server.tool(
        name="forget",
        description="Forget every version in a memory lineage.",
        structured_output=True,
    )
    def forget(
        scope_id: UUID,
        memory_id: UUID,
        reason: str = "Forgotten by owner",
        *,
        ctx: Context[Any, Any],
    ) -> ForgetMemoryResponse:
        authorize_token(
            token=_context_token(ctx),
            scope_id=scope_id,
            settings=owned_runtime.settings,
            mutation=True,
        )
        return owned_runtime.query.forget(
            scope_id=scope_id,
            memory_id=memory_id,
            request=ForgetMemoryRequest(reason=reason),
        )

    @server.tool(
        name="list_memories",
        description="List scoped memories with type/status/search filters.",
        structured_output=True,
    )
    def list_memories(
        scope_id: UUID,
        cursor: str | None = None,
        limit: int = 25,
        memory_types: list[MemoryType] | None = None,
        statuses: list[MemoryStatus] | None = None,
        search: str | None = None,
        *,
        ctx: Context[Any, Any],
    ) -> MemoryListResponse:
        authorize_token(
            token=_context_token(ctx),
            scope_id=scope_id,
            settings=owned_runtime.settings,
        )
        return owned_runtime.query.list_memories(
            scope_id=scope_id,
            cursor=cursor,
            limit=limit,
            memory_types=memory_types,
            statuses=statuses,
            search=search,
        )

    return server


def create_http_app(
    settings: Settings | None = None,
    *,
    runtime: AppRuntime | None = None,
) -> Any:
    """Return the stateless JSON streamable HTTP ASGI app for mounting at /mcp."""

    server = create_server(settings, runtime=runtime)
    from mcp.server.transport_security import TransportSecuritySettings

    app = server.streamable_http_app(
        streamable_http_path="/",
        json_response=True,
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[
                "127.0.0.1",
                "127.0.0.1:*",
                "localhost",
                "localhost:*",
                "testserver",
                "testserver:*",
            ],
            allowed_origins=[
                "http://127.0.0.1",
                "http://127.0.0.1:*",
                "http://localhost",
                "http://localhost:*",
                "http://testserver",
                "http://testserver:*",
            ],
        ),
    )
    app.state.mcp_server = server
    app.state.memoryos_runtime = runtime
    return app


def main() -> None:
    runtime = AppRuntime.create(get_settings())
    server = create_server(runtime=runtime)
    try:
        asyncio.run(server.run_stdio_async())
    finally:
        runtime.close()


__all__ = ["create_http_app", "create_server", "main"]
