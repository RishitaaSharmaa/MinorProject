"""Database engine and request-scoped SQLAlchemy session dependencies."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from decisionwatch.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create the configured SQLAlchemy engine once per process."""
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def create_session_factory(database_url: str) -> sessionmaker[Session]:
    """Create an isolated session factory, primarily for tests and tooling."""
    engine = create_engine(database_url, pool_pre_ping=True)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """Yield and close a database session for one API request."""
    factory = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    with factory() as session:
        yield session