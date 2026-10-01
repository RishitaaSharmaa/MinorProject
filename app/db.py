"""SQLAlchemy engine, session factory, and FastAPI session dependency."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache(maxsize=1)
def get_engine():
    """Create the configured SQLAlchemy engine once per process."""
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Return the process-wide SQLAlchemy session factory."""
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """Yield a request-scoped database session."""
    with get_session_factory()() as session:
        yield session