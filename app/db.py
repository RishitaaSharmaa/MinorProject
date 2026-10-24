"""SQLAlchemy engine, session factory, and FastAPI session dependency."""

from collections.abc import Iterator
from functools import lru_cache

from fastapi import HTTPException, Request
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


def get_control_db() -> Iterator[Session]:
    """Yield a session on the shared control-plane tables (tenants, users, leads)."""
    with get_session_factory()() as session:
        yield session


def get_db(request: Request) -> Iterator[Session]:
    """Yield a session on the operational tables (the demo, or a customer's own agent).

    A hosted account never has operational data on this server, so it is refused here.
    """
    from app.tenancy import resolve_workspace

    with get_session_factory()() as control:
        workspace = resolve_workspace(request, control)
    if workspace.tenant is not None:
        raise HTTPException(
            status_code=403,
            detail="Your data is not stored on the hosted site. Connect your DecisionWatch agent to use it.",
        )
    with get_session_factory()() as session:
        yield session
