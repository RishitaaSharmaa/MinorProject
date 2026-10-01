"""Tests for per-condition evaluation, including every handler and unknown data."""

import pytest

from app.services.conditions import Condition
from app.services.evaluator import (
    CONDITION_HANDLERS,
    NormalizedCondition,
    UnsupportedConditionError,
    evaluate_condition,
    evaluate_forecast_gte,
    evaluate_forecast_lte,
    evaluate_lead_time_lte,
    evaluate_moq_lte,
    evaluate_price_break_available,
    evaluate_stock_gt,
    evaluate_stock_lt,
    evaluate_supplier_risk_open,
    evaluate_supplier_risk_resolved,
    normalize_condition,
)

PRICE_TIERS_WITH_DISCOUNT = [
    {"min_qty": 1, "discount_pct": 0.0},
    {"min_qty": 500, "discount_pct": 4.5},
]
PRICE_TIERS_WITHOUT_DISCOUNT = [{"min_qty": 1, "discount_pct": 0.0}]

LT = "<"
LTE = "<="
GTE = ">="


@pytest.mark.parametrize(
    ("handler", "expected_value", "holding_value", "violating_value"),
    [
        (evaluate_forecast_gte, 250, 250, 249),
        (evaluate_forecast_lte, 250, 250, 251),
        (evaluate_stock_lt, 500, 499, 500),
        (evaluate_stock_gt, 500, 501, 500),
        (evaluate_lead_time_lte, 14, 14, 15),
        (evaluate_moq_lte, 100, 100, 101),
        (evaluate_supplier_risk_open, "open", "open", "clear"),
        (evaluate_supplier_risk_resolved, "resolved", "clear", "open"),
        (
            evaluate_price_break_available,
            True,
            PRICE_TIERS_WITH_DISCOUNT,
            PRICE_TIERS_WITHOUT_DISCOUNT,
        ),
    ],
)
def test_each_handler_holds_and_violates(
    handler, expected_value, holding_value, violating_value
) -> None:
    """Every condition handler accepts a satisfying value and rejects a breaking one."""
    assert handler(holding_value, expected_value) is True
    assert handler(violating_value, expected_value) is False


@pytest.mark.parametrize(
    ("handler", "current_value", "expected_value"),
    [
        (evaluate_forecast_gte, "not-a-number", 500),
        (evaluate_forecast_lte, None, 500),
        (evaluate_stock_lt, True, 500),
        (evaluate_stock_gt, {"qty": 1}, 500),
        (evaluate_lead_time_lte, "abc", 14),
        (evaluate_moq_lte, ["100"], 100),
        (evaluate_supplier_risk_open, "on_hold", "open"),
        (evaluate_supplier_risk_resolved, 7, "resolved"),
        (evaluate_price_break_available, 12, True),
    ],
)
def test_handlers_return_none_when_values_cannot_be_compared(
    handler, current_value, expected_value
) -> None:
    """A handler reports None rather than guessing when its value is unusable."""
    assert handler(current_value, expected_value) is None


def test_every_canonical_type_has_a_handler() -> None:
    """The handler registry covers each canonical condition type exactly once."""
    canonical = {
        "forecast_gte",
        "forecast_lte",
        "stock_lt",
        "stock_gt",
        "lead_time_lte",
        "moq_lte",
        "supplier_risk_open",
        "supplier_risk_resolved",
        "price_break_available",
    }
    assert set(CONDITION_HANDLERS) == canonical


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        (
            {"type": "stock_lt", "entity_ref": "item:SKU1", "op": LT, "value": 500},
            ("stock_lt", "item:SKU1", "stock_qty", LT),
        ),
        (
            {
                "type": "supplier_risk_resolved",
                "entity_ref": "supplier:SUP1",
                "op": "==",
                "value": "resolved",
            },
            ("supplier_risk_resolved", "supplier:SUP1", "strike_status", "=="),
        ),
        (
            {"condition_name": "stock_qty", "entity": "item:SKU1", "op": LT, "value": 500},
            ("stock_lt", "item:SKU1", "stock_qty", LT),
        ),
        (
            {
                "condition_name": "forecast_qty",
                "entity": "item:SKU1:week:2025-01-06",
                "op": GTE,
                "value": 100,
            },
            ("forecast_gte", "item:SKU1:week:2025-01-06", "forecast_qty", GTE),
        ),
        (
            {"condition_name": "forecast_qty", "entity": "item:SKU1", "op": LTE, "value": 100},
            ("forecast_lte", "item:SKU1", "forecast_qty", LTE),
        ),
        (
            {"condition_name": "lead_time_days", "entity": "supplier:SUP1", "op": LTE, "value": 9},
            ("lead_time_lte", "supplier:SUP1", "lead_time_days", LTE),
        ),
        (
            {"condition_name": "moq", "entity": "supplier:SUP1", "op": LTE, "value": 50},
            ("moq_lte", "supplier:SUP1", "moq", LTE),
        ),
        (
            {"condition_name": "price_break", "entity": "supplier:SUP1", "op": "=="},
            ("price_break_available", "supplier:SUP1", "price_break_tiers", "=="),
        ),
        (
            {
                "condition_name": "supplier_risk",
                "entity": "supplier:SUP1",
                "field": "strike_status",
                "op": "==",
                "value": "clear",
            },
            ("supplier_risk_resolved", "supplier:SUP1", "strike_status", "=="),
        ),
        (
            {
                "condition_name": "supplier_risk",
                "entity": "supplier:SUP1",
                "field": "strike_status",
                "op": "==",
                "value": "open",
            },
            ("supplier_risk_open", "supplier:SUP1", "strike_status", "=="),
        ),
    ],
)
def test_normalize_condition_accepts_both_recorded_shapes(condition, expected) -> None:
    """Closed-vocabulary and generator conditions normalize to the same key fields."""
    normalized = normalize_condition(condition)
    assert (
        normalized.condition_type,
        normalized.entity,
        normalized.field,
        normalized.operator,
    ) == expected


def test_normalize_condition_rejects_unsupported_input() -> None:
    """An unknown condition shape raises instead of being silently coerced."""
    with pytest.raises(UnsupportedConditionError):
        normalize_condition({"condition_name": "defects", "op": LT, "value": 3})
    with pytest.raises(UnsupportedConditionError):
        normalize_condition({"condition_name": "stock_qty", "op": "!=", "value": 3})
    with pytest.raises(UnsupportedConditionError):
        normalize_condition({"unrelated": True})


def test_evaluate_condition_uses_the_matching_world_value() -> None:
    """A recorded condition resolves against the value at its own entity and field."""
    world = {("item:SKU1", "stock_qty"): 120}
    condition = {"condition_name": "stock_qty", "entity": "item:SKU1", "op": LT, "value": 500}

    assert evaluate_condition(condition, world) == "holds"
    assert evaluate_condition(condition, {("item:SKU1", "stock_qty"): 600}) == "violated"
    assert evaluate_condition(condition, {("item:SKU2", "stock_qty"): 120}) == "unknown"


def test_evaluate_condition_accepts_the_closed_condition_model() -> None:
    """The validated extraction model can be evaluated without conversion."""
    condition = Condition(type="stock_lt", entity_ref="item:SKU1", op=LT, value=500)

    assert evaluate_condition(condition, {("item:SKU1", "stock_qty"): 120}) == "holds"


@pytest.mark.parametrize(
    ("condition", "world"),
    [
        ({"condition_name": "stock_qty", "entity": "item:SKU1", "op": LT, "value": 500}, {}),
        (
            {"condition_name": "stock_qty", "entity": "item:SKU1", "op": LT, "value": 500},
            {("item:SKU1", "stock_qty"): None},
        ),
        (
            {"condition_name": "stock_qty", "entity": "item:SKU1", "op": LT, "value": None},
            {("item:SKU1", "stock_qty"): 120},
        ),
        (
            {"condition_name": "stock_qty", "entity": "item:SKU1", "op": LT, "value": 500},
            {("item:SKU1", "stock_qty"): "many"},
        ),
        (
            {"condition_name": "stock_qty", "op": LT, "value": 500},
            {("item:SKU1", "stock_qty"): 120},
        ),
        (
            {"type": "unknown_type", "entity_ref": "item:SKU1", "op": LT, "value": 500},
            {("item:SKU1", "stock_qty"): 120},
        ),
        (
            {"condition_name": "defects", "entity": "item:SKU1", "op": LT, "value": 3},
            {("item:SKU1", "defects"): 1},
        ),
    ],
)
def test_evaluate_condition_reports_unknown_instead_of_guessing(condition, world) -> None:
    """Missing entities, values, thresholds, or comparable data always yield unknown."""
    assert evaluate_condition(condition, world) == "unknown"


def test_evaluate_condition_accepts_an_already_normalized_condition() -> None:
    """A normalized condition evaluates directly against world state."""
    normalized = NormalizedCondition(
        condition_type="stock_lt",
        entity="item:SKU1",
        field="stock_qty",
        operator=LT,
        expected_value=500,
    )

    assert evaluate_condition(normalized, {("item:SKU1", "stock_qty"): 120}) == "holds"
    assert evaluate_condition(normalized, {("item:SKU1", "stock_qty"): 900}) == "violated"


def test_evaluate_condition_never_raises_on_a_non_mapping() -> None:
    """A condition object that is not a mapping is unknown, not an exception."""
    assert evaluate_condition(object(), {}) == "unknown"
