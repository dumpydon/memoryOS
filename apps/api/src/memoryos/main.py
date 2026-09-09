"""FastAPI application entry point and app-lifetime wiring."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.responses import Response

from memoryos.api.auth import validate_security_settings
from memoryos.api.router import router as v1_router
from memoryos.config import Settings, get_settings
from memoryos.contracts.common import ApiHealth, ErrorResponse
from memoryos.mcp.server import create_http_app
from memoryos.services.errors import ERROR_HTTP_STATUS, ServiceError
from memoryos.services.runtime import AppRuntime

MIGRATION_HEAD = "0001_initial_persistence"


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    if isinstance(value, str):
        return value
    value = request.headers.get("x-request-id") or str(uuid4())
    request.state.request_id = value
    return value


def _status_for_error(code: str) -> int:
    if code in {"auth_required", "unauthorized"}:
        return 401
    if code in {"scope_forbidden", "forbidden"}:
        return 403
    if code in {"database_unavailable", "provider_unavailable"}:
        return 503
    if code == "provider_timeout":
        return 504
    if code == "provider_output_invalid":
        return 502
    if code in {"demo_input_not_allowed", "unsupported_demo_input"}:
        return 422
    return ERROR_HTTP_STATUS.get(code, 500)


def _error_response(request: Request, error: ServiceError) -> JSONResponse:
    body = ErrorResponse(
        code=error.code,
        message=error.message,
        request_id=_request_id(request),
        retryable=error.retryable,
    )
    return JSONResponse(status_code=_status_for_error(error.code), content=body.model_dump())


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or get_settings()
    validate_security_settings(runtime_settings)
    runtime = AppRuntime.create(runtime_settings)
    mcp_app = create_http_app(runtime=runtime)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with mcp_app.router.lifespan_context(mcp_app):
            try:
                yield
            finally:
                runtime.close()

    app = FastAPI(
        title="MemoryOS API",
        version="0.1.0",
        description="Explainable long-term memory infrastructure for AI agents.",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    app.state.runtime = runtime
    app.state.mcp_server = getattr(mcp_app.state, "mcp_server", None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[runtime_settings.web_origin, "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.request_id = request.headers.get("x-request-id") or str(uuid4())
        response = await call_next(request)
        response.headers["x-request-id"] = request.state.request_id
        return response

    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
        return _error_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        _: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(
            request,
            ServiceError("invalid_request", "Request validation failed."),
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, _: Exception) -> JSONResponse:
        return _error_response(
            request,
            ServiceError("internal_error", "The request could not be completed."),
        )

    @app.get("/health/live", response_model=ApiHealth, tags=["health"])
    def live_health() -> ApiHealth:
        return ApiHealth(status="ok", checked_at=datetime.now(UTC))

    @app.get("/health/ready", response_model=ApiHealth, tags=["health"])
    def ready_health() -> ApiHealth:
        try:
            with runtime.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                version = connection.execute(
                    text(
                        "SELECT version_num FROM alembic_version ORDER BY version_num DESC LIMIT 1"
                    )
                ).scalar_one_or_none()
        except Exception as exc:  # pragma: no cover - infrastructure dependent
            raise ServiceError(
                "database_unavailable",
                "The memory database is not ready.",
                retryable=True,
            ) from exc
        if version != MIGRATION_HEAD:
            raise ServiceError(
                "database_unavailable",
                "The memory database migration is not at the expected version.",
                retryable=True,
            )
        return ApiHealth(
            status="ok",
            checked_at=datetime.now(UTC),
            details={"execution_mode": runtime_settings.execution_mode},
        )

    app.include_router(v1_router)
    app.mount("/mcp", mcp_app, name="mcp")
    return app


app = create_app()


__all__ = ["app", "create_app"]
