"""Supplier and item master data models."""

from typing import Any

from sqlalchemy import Float, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSON_VALUE


class Supplier(Base):
    """Supplier master record from the procurement dataset."""

    __tablename__ = "suppliers"

    id: Mapped[str] = mapped_column("supplier_id", String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    quoted_lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    lead_time_std_dev: Mapped[float] = mapped_column(Float, nullable=False)
    reliability_score: Mapped[float] = mapped_column(Float, nullable=False)
    price_break_tiers: Mapped[list[dict[str, Any]]] = mapped_column(JSON_VALUE, nullable=False)
    strike_status: Mapped[str] = mapped_column(String(32), nullable=False)


class Item(Base):
    """Inventory item and replenishment parameters."""

    __tablename__ = "items"

    id: Mapped[str] = mapped_column("item_id", String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    unit_cost: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    holding_cost_pct: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False)
    min_order_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    primary_supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.supplier_id"), nullable=False)
    avg_daily_demand: Mapped[int] = mapped_column(Integer, nullable=False)
    reorder_point_qty: Mapped[int] = mapped_column(Integer, nullable=False)