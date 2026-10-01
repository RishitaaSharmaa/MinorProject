"""Sales, stock, forecast, and world-state event models."""

from datetime import date as DateValue, datetime
from typing import Any

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSON_VALUE


class SalesHistory(Base):
    """Historical daily item sales."""

    __tablename__ = "sales_history"

    item_id: Mapped[str] = mapped_column(ForeignKey("items.item_id"), primary_key=True)
    date: Mapped[DateValue] = mapped_column(Date, primary_key=True)
    qty_sold: Mapped[int] = mapped_column(Integer, nullable=False)


class StockSnapshot(Base):
    """End-of-day inventory quantity for an item."""

    __tablename__ = "stock_snapshots"

    item_id: Mapped[str] = mapped_column(ForeignKey("items.item_id"), primary_key=True)
    date: Mapped[DateValue] = mapped_column(Date, primary_key=True)
    qty_on_hand: Mapped[int] = mapped_column(Integer, nullable=False)


class Forecast(Base):
    """Weekly forecast and realized item demand."""

    __tablename__ = "forecasts"

    item_id: Mapped[str] = mapped_column(ForeignKey("items.item_id"), primary_key=True)
    week: Mapped[DateValue] = mapped_column(Date, primary_key=True)
    forecast_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    true_demand: Mapped[int] = mapped_column(Integer, nullable=False)
    forecast_error_pct: Mapped[float] = mapped_column(Float, nullable=False)


class SupplierDelivery(Base):
    """Promised and actual dates used to calculate supplier lead-time history."""

    __tablename__ = "supplier_delivery_history"

    decision_id: Mapped[str] = mapped_column(ForeignKey("decisions.id"), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.supplier_id"), nullable=False)
    promised_delivery_date: Mapped[DateValue] = mapped_column(Date, nullable=False)
    actual_delivery_date: Mapped[DateValue] = mapped_column(Date, nullable=False)
    delay_days: Mapped[int] = mapped_column(Integer, nullable=False)
    arrived_late: Mapped[bool] = mapped_column(nullable=False)


class StateEvent(Base):
    """Recorded world-state change that can trigger assumption checks."""

    __tablename__ = "state_events"
    __table_args__ = (
        Index("ix_state_events_entity_time", "entity_type", "entity_id", "event_time"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    field: Mapped[str] = mapped_column(String(128), nullable=False)
    old_value: Mapped[Any | None] = mapped_column(JSON_VALUE, nullable=True)
    new_value: Mapped[Any | None] = mapped_column(JSON_VALUE, nullable=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)