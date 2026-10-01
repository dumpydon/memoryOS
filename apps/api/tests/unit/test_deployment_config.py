"""Deployment boundaries without network access or provider calls."""

import pytest
from fastapi.testclient import TestClient

from memoryos.api.auth import validate_security_settings
from memoryos.config import Settings
from memoryos.db.session import create_db_engine
from memoryos.main import create_app


@pytest.mark.parametrize("scheme", ["postgresql", "postgres", "postgresql+psycopg"])
def test_hosted_postgres_url_uses_installed_driver_and_preserves_tls(scheme: str) -> None:
    suffix = (
        "test-user:p%40ss%25word@ep-example.neon.tech/test-db"
        "?sslmode=require&channel_binding=require"
    )
    settings = Settings(database_url=f"{scheme}://{suffix}", _env_file=None)
    assert settings.database_url == f"postgresql+psycopg://{suffix}"
    engine = create_db_engine(settings)
    try:
        assert engine.dialect.driver == "psycopg"
        assert engine.url.query["sslmode"] == "require"
        assert engine.url.query["channel_binding"] == "require"
        assert engine.url.password == "p@ss%word"
    finally:
        engine.dispose()


@pytest.mark.parametrize("token", ["", "   ", "memoryos-local-token", " memoryos-local-token "])
def test_production_rejects_development_or_empty_owner_token(token: str) -> None:
    with pytest.raises(RuntimeError, match="OWNER_API_TOKEN"):
        validate_security_settings(Settings(app_env="production", owner_api_token=token))


def test_production_cors_allows_only_configured_frontend() -> None:
    settings = Settings(
        app_env="production",
        owner_api_token="deployment-test-owner",
        web_origin="https://frontend.example.test",
        _env_file=None,
    )
    with TestClient(create_app(settings)) as client:
        for origin, allowed in (
            (settings.web_origin, True),
            ("http://127.0.0.1:3000", False),
            ("https://unrelated.example.test", False),
        ):
            response = client.options(
                "/v1/interactions",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization,content-type",
                },
            )
            assert (response.status_code == 200) is allowed
            assert response.headers.get("access-control-allow-origin") == (
                origin if allowed else None
            )
        assert client.get("/health/live").status_code == 200


def test_local_loopback_alias_remains_allowed() -> None:
    with TestClient(create_app(Settings(app_env="development", _env_file=None))) as client:
        response = client.options(
            "/v1/interactions",
            headers={
                "Origin": "http://127.0.0.1:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"


@pytest.mark.parametrize("origin_setting", ["api_public_origin", "render_external_url"])
def test_external_mcp_host_is_configured_without_disabling_rebinding_protection(
    origin_setting: str,
) -> None:
    settings = Settings(
        app_env="production",
        owner_api_token="deployment-test-owner",
        web_origin="https://frontend.example.test",
        _env_file=None,
    )
    setattr(settings, origin_setting, "https://api.example.test")
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "deployment-check", "version": "1.0"},
        },
    }
    with TestClient(create_app(settings), base_url="https://api.example.test") as client:
        headers = {"Accept": "application/json, text/event-stream", "Origin": settings.web_origin}
        assert client.post("/mcp/", headers=headers, json=body).status_code == 200
        assert (
            client.post(
                "/mcp/", headers={**headers, "Host": "unrelated.example.test"}, json=body
            ).status_code
            == 421
        )
        assert (
            client.post(
                "/mcp/", headers={**headers, "Origin": "https://unrelated.example.test"}, json=body
            ).status_code
            == 403
        )
