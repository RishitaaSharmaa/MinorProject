"""Per-tenant import configuration and audit log."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSON_VALUE


class ImportMapping(Base):
    """Saved column mapping for one canonical dataset, reused on the next upload."""

    __tablename__ = "import_mappings"

    dataset: Mapped[str] = mapped_column(String(32), primary_key=True)
    mapping: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, nullable=False)
    date_format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ImportRun(Base):
    """Audit row for one committed import."""

    __tablename__ = "import_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset: Mapped[str] = mapped_column(String(32), nullable=False)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rows_total: Mapped[int] = mapped_column(Integer, nullable=False)
    rows_imported: Mapped[int] = mapped_column(Integer, nullable=False)
    rows_rejected: Mapped[int] = mapped_column(Integer, nullable=False)
    decisions_flagged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors_sample: Mapped[list[Any]] = mapped_column(JSON_VALUE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
