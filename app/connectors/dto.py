"""Pydantic data-transfer objects returned by ERP connectors."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class SupplierTerms(BaseModel):
    """Supplier terms normalized across synthetic and SAP B1 systems."""

    model_config = ConfigDict(frozen=True)

    supplier_id: str
    as_of: date | datetime | None = None
    quoted_lead_time: float
    moq: int
    price_break_tiers: list[dict[str, Any]]
    strike_status: str
    lead_time_std_dev: float = 0.0
    reliability_score: float = 0.0


class DecisionDTO(BaseModel):
    """Detached decision data; callers never receive ORM entities."""

    model_config = ConfigDict(frozen=True)

    id: str
    type: str
    created_at: datetime
    structured_fields: dict[str, Any]
    free_text_reason: str | None = None
    is_override: bool
    status: str
    item_id: str | None = None
    supplier_id: str | None = None
    quantity: int | None = None
    unit_price: float | None = None
    po_date: date | None = None
    expected_delivery: date | None = None


class StateEventDTO(BaseModel):
    """Detached state-change event data."""

    model_config = ConfigDict(frozen=True)

    id: str
    entity_type: str
    entity_id: str
    field: str
    old_value: Any | None = None
    new_value: Any | None = None
    event_time: datetime