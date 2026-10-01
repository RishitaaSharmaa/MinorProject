"""SQLAlchemy declarative base and PostgreSQL JSONB type helper."""

from typing import Any

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeEngine


class Base(DeclarativeBase):
    """Base class for operational SQLAlchemy models."""


JSON_VALUE: TypeEngine[Any] = JSON().with_variant(JSONB, "postgresql")