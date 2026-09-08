"""Environment-backed application settings."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings shared by REST, MCP, and workers."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, ge=1, le=65535)
    web_origin: str = "http://localhost:3000"
    database_url: str = "postgresql+psycopg://memoryos:memoryos@localhost:5432/memoryos"
    owner_api_token: str = "memoryos-local-token"

    execution_mode: str = "demo"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=1536, ge=1)
    demo_embedding_model: str = "demo-fixture-v1"
    demo_embedding_dimensions: int = Field(default=1536, ge=1)
    provider_timeout_seconds: float = Field(default=30.0, gt=0)
    max_interaction_chars: int = Field(default=20_000, ge=100, le=100_000)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
