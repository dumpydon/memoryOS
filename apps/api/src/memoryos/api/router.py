"""REST routes that delegate to the shared ingestion/query services."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request

from memoryos.api.auth import AccessContext, authorize_request
from memoryos.contracts.demo import DemoCatalogResponse
from memoryos.contracts.ingestion import IngestInteractionRequest, IngestInteractionResponse
from memoryos.contracts.memory import (
    ForgetMemoryRequest,
    ForgetMemoryResponse,
    MemoryHistoryResponse,
    MemoryListResponse,
    MemoryRecord,
    ResolveMemoryRequest,
    ResolveMemoryResponse,
)
from memoryos.contracts.overview import OverviewResponse
from memoryos.contracts.recall import RecallComparisonResponse, RecallRequest, RecallResponse
from memoryos.domain.enums import ExecutionMode, MemoryStatus, MemoryType
from memoryos.seed.catalog import get_catalog, is_allowed_demo_query, is_allowed_demo_scenario
from memoryos.services.errors import ServiceError
from memoryos.services.protocols import IngestionService
from memoryos.services.runtime import AppRuntime

router = APIRouter(prefix="/v1", tags=["v1"])


def _runtime(request: Request) -> AppRuntime:
    runtime = getattr(request.app.state, "runtime", None)
    if not isinstance(runtime, AppRuntime):
        raise ServiceError("internal_error", "Application runtime is not initialized.")
    return runtime


def _authorize_scope(
    request: Request,
    runtime: AppRuntime,
    *,
    scope_id: UUID,
    mode: ExecutionMode = ExecutionMode.DEMO,
    mutation: bool = False,
    public_demo_allowed: bool = True,
) -> AccessContext:
    return authorize_request(
        request,
        scope_id=scope_id,
        settings=runtime.settings,
        mode=mode,
        mutation=mutation,
        public_demo_allowed=public_demo_allowed,
    )


def _ingestion_service(runtime: AppRuntime) -> IngestionService:
    try:
        from memoryos.services.ingestion import MemoryIngestionService
    except ImportError as exc:  # pragma: no cover - T4 is wired in the full app
        raise ServiceError(
            "provider_unavailable",
            "The ingestion service is not available.",
            retryable=True,
        ) from exc
    return MemoryIngestionService(runtime.settings, runtime.session_factory)


@router.post("/interactions", response_model=IngestInteractionResponse)
def ingest_interaction(
    payload: IngestInteractionRequest,
    request: Request,
) -> IngestInteractionResponse:
    runtime = _runtime(request)
    access = _authorize_scope(
        request,
        runtime,
        scope_id=payload.scope_id,
        mode=payload.mode,
        mutation=not payload.preview,
    )
    if access.is_public_demo and (
        not payload.preview or not is_allowed_demo_scenario(payload.text)
    ):
        raise ServiceError(
            "demo_input_not_allowed",
            "Public demo ingestion accepts only an allowlisted preview scenario.",
        )
    return _ingestion_service(runtime).ingest(payload)


@router.get("/interactions/{interaction_id}", response_model=IngestInteractionResponse)
def get_interaction(
    interaction_id: UUID, scope_id: UUID, request: Request
) -> IngestInteractionResponse:
    runtime = _runtime(request)
    _authorize_scope(
        request,
        runtime,
        scope_id=scope_id,
        public_demo_allowed=False,
    )
    return _ingestion_service(runtime).get_interaction(
        scope_id=scope_id,
        interaction_id=interaction_id,
    )


@router.get("/memories", response_model=MemoryListResponse)
def list_memories(
    request: Request,
    scope_id: UUID,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    memory_types: Annotated[list[MemoryType] | None, Query()] = None,
    statuses: Annotated[list[MemoryStatus] | None, Query()] = None,
    search: str | None = None,
) -> MemoryListResponse:
    runtime = _runtime(request)
    _authorize_scope(request, runtime, scope_id=scope_id)
    return runtime.query.list_memories(
        scope_id=scope_id,
        cursor=cursor,
        limit=limit,
        memory_types=memory_types,
        statuses=statuses,
        search=search,
    )


@router.get("/memories/{memory_id}", response_model=MemoryRecord)
def get_memory(memory_id: UUID, scope_id: UUID, request: Request) -> MemoryRecord:
    runtime = _runtime(request)
    _authorize_scope(request, runtime, scope_id=scope_id)
    return runtime.query.get_memory(scope_id=scope_id, memory_id=memory_id)


@router.get("/memories/{memory_id}/history", response_model=MemoryHistoryResponse)
def memory_history(memory_id: UUID, scope_id: UUID, request: Request) -> MemoryHistoryResponse:
    runtime = _runtime(request)
    _authorize_scope(request, runtime, scope_id=scope_id)
    return runtime.query.history(scope_id=scope_id, memory_id=memory_id)


@router.post("/memories/{memory_id}/forget", response_model=ForgetMemoryResponse)
def forget_memory(
    memory_id: UUID,
    payload: ForgetMemoryRequest,
    scope_id: UUID,
    request: Request,
) -> ForgetMemoryResponse:
    runtime = _runtime(request)
    _authorize_scope(request, runtime, scope_id=scope_id, mutation=True)
    return runtime.query.forget(scope_id=scope_id, memory_id=memory_id, request=payload)


@router.post("/memories/{memory_id}/resolve", response_model=ResolveMemoryResponse)
def resolve_memory(
    memory_id: UUID,
    payload: ResolveMemoryRequest,
    scope_id: UUID,
    request: Request,
) -> ResolveMemoryResponse:
    runtime = _runtime(request)
    _authorize_scope(request, runtime, scope_id=scope_id, mutation=True)
    return runtime.query.resolve(scope_id=scope_id, memory_id=memory_id, request=payload)


@router.post("/recall", response_model=RecallResponse)
def recall(payload: RecallRequest, request: Request) -> RecallResponse:
    runtime = _runtime(request)
    context = authorize_request(
        request,
        scope_id=payload.scope_id,
        settings=runtime.settings,
        mode=payload.mode,
    )
    if context.is_public_demo and not is_allowed_demo_query(payload.query):
        raise ServiceError(
            "demo_input_not_allowed",
            "Public demo recall accepts only an allowlisted query.",
        )
    return runtime.query.recall(payload)


@router.post("/recall/compare", response_model=RecallComparisonResponse)
def compare_recall(payload: RecallRequest, request: Request) -> RecallComparisonResponse:
    runtime = _runtime(request)
    context = authorize_request(
        request,
        scope_id=payload.scope_id,
        settings=runtime.settings,
        mode=payload.mode,
    )
    if context.is_public_demo and not is_allowed_demo_query(payload.query):
        raise ServiceError(
            "demo_input_not_allowed",
            "Public demo recall accepts only an allowlisted query.",
        )
    return runtime.query.compare(payload)


@router.get("/overview", response_model=OverviewResponse)
def overview(scope_id: UUID, request: Request) -> OverviewResponse:
    runtime = _runtime(request)
    _authorize_scope(request, runtime, scope_id=scope_id)
    return runtime.query.get_overview(scope_id=scope_id)


@router.get("/demo/scenarios", response_model=DemoCatalogResponse)
def demo_scenarios() -> DemoCatalogResponse:
    return get_catalog()


__all__ = ["router"]
