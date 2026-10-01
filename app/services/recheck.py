"""Deterministic assumption comparisons without LLM-based scoring."""

from datetime import date, datetime
from typing import Any

from app.connectors.base import AsOf, ERPConnector


def condition_holds(condition: dict[str, Any], current_value: Any | None) -> bool | None:
    """Compare a current value with one stored condition deterministically."""
    if current_value is None:
        return None
    operator = condition.get("op", condition.get("operator"))
    expected = condition.get("value", condition.get("expected_value"))
    try:
        comparisons = {
            "==": lambda: current_value == expected,
            "!=": lambda: current_value != expected,
            "<": lambda: current_value < expected,
            "<=": lambda: current_value <= expected,
            ">": lambda: current_value > expected,
            ">=": lambda: current_value >= expected,
        }
        return bool(comparisons[operator]())
    except (KeyError, TypeError, ValueError):
        return False


def read_condition(
    connector: ERPConnector,
    condition: dict[str, Any],
    as_of: date | datetime | None = None,
) -> bool | None:
    """Read a typed item or supplier value through the connector interface."""
    entity = str(condition.get("entity", ""))
    if ":" not in entity:
        return None
    entity_type, entity_id = entity.split(":", 1)
    if entity_type == "item":
        item_id = entity_id.split(":", 1)[0]
        field = condition.get("field", condition.get("condition_name"))
        if field == "forecast_qty":
            value = connector.get_forecast(item_id, as_of)
        elif field == "stock_qty":
            value = connector.get_stock(item_id, as_of)
        else:
            return None
    elif entity_type == "supplier":
        terms = connector.get_supplier_terms(entity_id, as_of)
        field = condition.get("field", condition.get("condition_name"))
        supplier_values = {
            "lead_time_days": terms.quoted_lead_time,
            "quoted_lead_time": terms.quoted_lead_time,
            "moq": terms.moq,
            "price_break_tiers": terms.price_break_tiers,
            "strike_status": terms.strike_status,
        }
        value = supplier_values.get(str(field))
    else:
        return None
    return condition_holds(condition, value)