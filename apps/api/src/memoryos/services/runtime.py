"""Application-lifetime database and service wiring."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from memoryos.config import Settings, get_settings
from memoryos.db.session import create_db_engine, create_session_factory
from memoryos.services.query import MemoryQueryService


@dataclass(slots=True)
class AppRuntime:
    """One engine/session factory shared by REST, MCP, and worker adapters."""

    settings: Settings
    engine: Engine
    session_factory: sessionmaker[Session]
    query: MemoryQueryService

    @classmethod
    def create(cls, settings: Settings | None = None) -> AppRuntime:
        runtime_settings = settings or get_settings()
        engine = create_db_engine(runtime_settings)
        session_factory = create_session_factory(runtime_settings, engine=engine)
        query = MemoryQueryService(runtime_settings, session_factory)
        return cls(
            settings=runtime_settings,
            engine=engine,
            session_factory=session_factory,
            query=query,
        )

    def close(self) -> None:
        self.engine.dispose()


__all__ = ["AppRuntime"]
