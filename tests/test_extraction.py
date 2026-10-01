"""Mocked tests for structured and LLM-based assumption extraction."""

from datetime import datetime, timezone
from unittest.mock import create_autospec

import pytest
from pydantic import BaseModel

from app.connectors.base import ERPConnector
from app.connectors.dto import DecisionDTO, SupplierTerms
from app.services.extraction import (
    _ExtractedCondition,
    _ExtractionResponse,
    extract_assumptions,
)


@pytest.fixture
def decision() -> DecisionDTO:
    """Return an override decision with structured PO context and rationale."""
    return DecisionDTO(
        id="DEC1",
        type="purchase_order",
        created_at=datetime(2025, 1, 10, tzinfo=timezone.utc),
        structured_fields={"order_qty": 20, "unit_cost": 5.5, "system_suggestion_qty": 10},
        free_text_reason="Lead time bas 3 din, stock tight hai; supplier clear hai.",
        is_override=True,
        status="placed",
        item_id="SKU1",
        supplier_id="SUP1",
        quantity=20,
        unit_price=5.5,
    )


def _connector() -> ERPConnector:
    """Return a mock connector with deterministic point-in-time values."""
    connector = create_autospec(ERPConnector, instance=True)
    connector.get_stock.return_value = 8
    connector.get_forecast.return_value = 12.0
    connector.get_supplier_terms.return_value = SupplierTerms(
        supplier_id="SUP1",
        quoted_lead_time=5,
        moq=10,
        price_break_tiers=[{"min_qty": 15, "discount_pct": 2}],
        strike_status="clear",
    )
    connector.get_supplier_actual_lead_times.return_value = [4.0, 6.0, 8.0]
    return connector


def test_extraction_combines_structured_and_text_proposals(
    decision: DecisionDTO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Use no LLM for structured facts and attach text warnings and confidence."""
    connector = _connector()
    captured: dict[str, object] = {}

    def fake_complete(system: str, user: str, schema: type[BaseModel]) -> _ExtractionResponse:
        captured["system"] = system
        captured["user"] = user
        captured["schema"] = schema
        return _ExtractionResponse(conditions=[
            _ExtractedCondition(
                type="lead_time_lte",
                entity_ref="supplier:SUP1",
                op="<=",
                value=3,
                confidence=0.78,
            ),
            _ExtractedCondition(
                type="moq_lte",
                entity_ref="supplier:SUP1",
                op="<=",
                value=None,
                needs_value_from_planner=True,
                confidence=0.55,
            ),
        ])

    monkeypatch.setattr("app.services.extraction.complete_json", fake_complete)

    proposals = extract_assumptions(decision, connector)

    connector.get_stock.assert_called_once_with("SKU1", decision.created_at)
    connector.get_forecast.assert_called_once_with("SKU1", decision.created_at)
    connector.get_supplier_terms.assert_called_once_with("SUP1", decision.created_at)
    connector.get_supplier_actual_lead_times.assert_called_with("SUP1", decision.created_at)
    assert "Hinglish" in str(captured["system"])
    assert "Never invent numbers" in str(captured["system"])
    assert "Lead time bas 3 din" in str(captured["user"])
    assert any(item.source == "structured" and item.type == "stock_lt" for item in proposals)
    assert any(item.source == "structured" and item.type == "forecast_gte" for item in proposals)

    free_text_lead_time = next(
        item for item in proposals if item.source == "llm" and item.type == "lead_time_lte"
    )
    assert free_text_lead_time.confidence == 0.78
    assert "optimistic" in free_text_lead_time.warnings[0]
    planner_value = next(item for item in proposals if item.needs_value_from_planner)
    assert planner_value.value is None


def test_no_free_text_skips_llm(decision: DecisionDTO, monkeypatch: pytest.MonkeyPatch) -> None:
    """Return structured proposals directly when a decision has no reason text."""
    decision_without_text = decision.model_copy(update={"free_text_reason": None})
    monkeypatch.setattr(
        "app.services.extraction.complete_json",
        lambda *args: pytest.fail("LLM must not run without free text"),
    )

    proposals = extract_assumptions(decision_without_text, _connector())

    assert proposals
    assert all(item.source == "structured" for item in proposals)