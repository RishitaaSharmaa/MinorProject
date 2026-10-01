"""Tests for typed connector usage in deterministic assumption rechecks."""

from datetime import date
from unittest.mock import create_autospec

from app.connectors.base import ERPConnector
from app.connectors.dto import SupplierTerms
from app.services.recheck import read_condition


def test_item_condition_uses_typed_connector_and_as_of() -> None:
    """Route stock checks through the connector with the harness clock."""
    connector = create_autospec(ERPConnector, instance=True)
    connector.get_stock.return_value = 8

    is_holding = read_condition(
        connector,
        {"entity": "item:SKU1", "condition_name": "stock_qty", "op": "<", "value": 10},
        date(2025, 1, 10),
    )

    assert is_holding is True
    connector.get_stock.assert_called_once_with("SKU1", date(2025, 1, 10))


def test_supplier_condition_uses_terms_dto() -> None:
    """Read supplier risk from normalized terms rather than ORM fields."""
    connector = create_autospec(ERPConnector, instance=True)
    connector.get_supplier_terms.return_value = SupplierTerms(
        supplier_id="SUP1",
        quoted_lead_time=5,
        moq=10,
        price_break_tiers=[],
        strike_status="clear",
    )

    is_clear = read_condition(
        connector,
        {
            "entity": "supplier:SUP1",
            "condition_name": "supplier_risk",
            "field": "strike_status",
            "op": "==",
            "value": "clear",
        },
        date(2025, 1, 10),
    )

    assert is_clear is True
    connector.get_supplier_terms.assert_called_once_with("SUP1", date(2025, 1, 10))