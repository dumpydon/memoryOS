"""SQLAlchemy engine/session factory shared by service workers."""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from memoryos.config import Settings, get_settings


def create_db_engine(settings: Settings | None = None) -> Engine:
    """Create a synchronous engine suitable for short API transactions."""

    runtime = settings or get_settings()
    return create_engine(
        runtime.database_url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=1,
        future=True,
    )


def create_session_factory(
    settings: Settings | None = None,
    *,
    engine: Engine | None = None,
) -> sessionmaker[Session]:
    return sessionmaker(
        bind=engine or create_db_engine(settings),
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )


@contextmanager
def session_scope(
    settings: Settings | None = None,
    *,
    session_factory: sessionmaker[Session] | None = None,
) -> Generator[Session, None, None]:
    """Yield a transaction-scoped session for a request or worker operation."""

    owns_factory = session_factory is None
    factory = session_factory or create_session_factory(settings)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        if owns_factory:
            engine = factory.kw.get("bind")
            if isinstance(engine, Engine):
                engine.dispose()
