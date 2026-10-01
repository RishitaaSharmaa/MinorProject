"""Deterministic one-condition evaluation with explicit unknown outcomes.

A recorded condition plus a snapshot of world state always resolves to exactly
one of three outcomes:

``holds``     the current value satisfies the recorded condition,
``violated``  the current value contradicts the recorded condition,
``unknown``   the condition cannot be judged because data is missing.

Missing data never resolves to ``holds`` or ``violated``. A condition whose
entity, field, threshold, or current value is absent, whose type has no
registered handler, or whose values cannot be compared returns ``unknown``
instead of a guess.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

ConditionOutcome = Literal["holds", "violated", "unknown"]

WorldKey = tuple[str, str]
WorldState = Mapping[WorldKey, Any]

ConditionHandler = Callable[[Any, Any], bool | None]

RISK_OPEN_VALUES = frozenset(
    {"open", "strike", "at_risk", "active", "unresolved", "ongoing", "yes", "true"}
)
RISK_RESOLVED_VALUES = frozenset(
    {
        "resolved",
        "clear",
        "cleared",
        "none",
        "normal",
        "no strike",
        "closed",
        "inactive",
        "safe",
        "no risk",
        "not at risk",
        "not_at_risk",
        "false",
    }
)

#: Field name the ERP and event stream use for each canonical condition type.
FIELD_FOR_TYPE: dict[str, str] = {
    "forecast_gte": "forecast_qty",
    "forecast_lte": "forecast_qty",
    "stock_lt": "stock_qty",
    "stock_gt": "stock_qty",
    "lead_time_lte": "lead_time_days",
    "moq_lte": "moq",
    "supplier_risk_open": "strike_status",
    "supplier_risk_resolved": "strike_status",
    "price_break_available": "price_break_tiers",
}

#: Comparison operator each canonical condition type encodes.
OPERATOR_FOR_TYPE: dict[str, str] = {
    "forecast_gte": ">=",
    "forecast_lte": "<=",
    "stock_lt": "<",
    "stock_gt": ">",
    "lead_time_lte": "<=",
    "moq_lte": "<=",
    "supplier_risk_open": "==",
    "supplier_risk_resolved": "==",
    "price_break_available": "==",
}

#: Generator-and-dataset condition names mapped onto the canonical vocabulary.
RAW_TYPE_FOR_NAME_AND_OPERATOR: dict[tuple[str, str], str] = {
    ("stock_qty", "<"): "stock_lt",
    ("stock_qty", ">"): "stock_gt",
    ("forecast_qty", ">="): "forecast_gte",
    ("forecast_qty", "<="): "forecast_lte",
    ("lead_time_days", "<="): "lead_time_lte",
    ("moq", "<="): "moq_lte",
    ("price_break", "=="): "price_break_available",
}

#: Raw condition names whose event field differs from the condition name.
RAW_FIELD_OVERRIDE: dict[str, str] = {"supplier_risk": "strike_status"}


class UnsupportedConditionError(ValueError):
    """Raised when a condition cannot be mapped onto the supported vocabulary."""


@dataclass(frozen=True)
class NormalizedCondition:
    """A recorded condition expressed in the canonical checkable vocabulary."""

    condition_type: str
    entity: str
    field: str
    operator: str
    expected_value: Any


def normalize_condition(condition: Mapping[str, Any] | Any) -> NormalizedCondition:
    """Map a closed-vocabulary or generator condition onto a canonical condition.

    Raises:
        UnsupportedConditionError: when the condition uses an unknown type,
            operator, or lacks an entity to address.
    """
    values = _as_mapping(condition)
    canonical_type = values.get("type")
    if isinstance(canonical_type, str) and canonical_type in FIELD_FOR_TYPE:
        entity = values.get("entity_ref") or values.get("entity") or ""
        return NormalizedCondition(
            condition_type=canonical_type,
            entity=str(entity),
            field=FIELD_FOR_TYPE[canonical_type],
            operator=OPERATOR_FOR_TYPE[canonical_type],
            expected_value=_canonical_expected_value(canonical_type, values.get("value")),
        )

    condition_name = values.get("condition_name")
    if not isinstance(condition_name, str):
        raise UnsupportedConditionError(f"Condition has no supported type: {values!r}")

    operator = str(values.get("op") or "")
    if condition_name == "supplier_risk":
        condition_type = (
            "supplier_risk_open"
            if _risk_status(values.get("value")) == "open"
            else "supplier_risk_resolved"
        )
    else:
        condition_type = RAW_TYPE_FOR_NAME_AND_OPERATOR.get((condition_name, operator), "")
    if not condition_type:
        raise UnsupportedConditionError(
            f"Unsupported condition name/operator pair: {condition_name!r}/{operator!r}"
        )

    field = (
        values.get("field")
        or RAW_FIELD_OVERRIDE.get(condition_name)
        or FIELD_FOR_TYPE[condition_type]
    )
    entity = values.get("entity") or values.get("entity_ref") or ""
    return NormalizedCondition(
        condition_type=condition_type,
        entity=str(entity),
        field=str(field),
        operator=OPERATOR_FOR_TYPE[condition_type],
        expected_value=_canonical_expected_value(condition_type, values.get("value")),
    )


def evaluate_forecast_gte(current_value: Any, expected_value: Any) -> bool | None:
    """Check that the current forecast meets the recorded minimum."""
    return _numeric_compare(current_value, expected_value, ">=")


def evaluate_forecast_lte(current_value: Any, expected_value: Any) -> bool | None:
    """Check that the current forecast stays at or below the recorded maximum."""
    return _numeric_compare(current_value, expected_value, "<=")


def evaluate_stock_lt(current_value: Any, expected_value: Any) -> bool | None:
    """Check that current stock is below the recorded ceiling."""
    return _numeric_compare(current_value, expected_value, "<")


def evaluate_stock_gt(current_value: Any, expected_value: Any) -> bool | None:
    """Check that current stock is above the recorded floor."""
    return _numeric_compare(current_value, expected_value, ">")


def evaluate_lead_time_lte(current_value: Any, expected_value: Any) -> bool | None:
    """Check that the current lead time stays within the recorded bound."""
    return _numeric_compare(current_value, expected_value, "<=")


def evaluate_moq_lte(current_value: Any, expected_value: Any) -> bool | None:
    """Check that the effective minimum order quantity stays within the bound."""
    return _numeric_compare(current_value, expected_value, "<=")


def evaluate_supplier_risk_open(current_value: Any, expected_value: Any) -> bool | None:
    """Check that the supplier risk status is still reported as open."""
    status = _risk_status(current_value)
    if status is None:
        return None
    return status == "open"


def evaluate_supplier_risk_resolved(current_value: Any, expected_value: Any) -> bool | None:
    """Check that the supplier risk status is still reported as resolved."""
    status = _risk_status(current_value)
    if status is None:
        return None
    return status == "resolved"


def evaluate_price_break_available(current_value: Any, expected_value: Any) -> bool | None:
    """Check that a usable price break is still available."""
    if isinstance(current_value, bool):
        return current_value
    if isinstance(current_value, (list, tuple)):
        return any(_tier_gives_discount(tier) for tier in current_value)
    return None


#: One handler per canonical condition type; keyed by the type stored on a condition.
CONDITION_HANDLERS: dict[str, ConditionHandler] = {
    "forecast_gte": evaluate_forecast_gte,
    "forecast_lte": evaluate_forecast_lte,
    "stock_lt": evaluate_stock_lt,
    "stock_gt": evaluate_stock_gt,
    "lead_time_lte": evaluate_lead_time_lte,
    "moq_lte": evaluate_moq_lte,
    "supplier_risk_open": evaluate_supplier_risk_open,
    "supplier_risk_resolved": evaluate_supplier_risk_resolved,
    "price_break_available": evaluate_price_break_available,
}


def evaluate_condition(
    condition: Mapping[str, Any] | NormalizedCondition,
    world_state: WorldState,
) -> ConditionOutcome:
    """Evaluate one recorded condition against a world-state snapshot.

    Returns ``holds`` or ``violated`` only when every input needed for the
    comparison is present and comparable; otherwise returns ``unknown``.
    """
    try:
        normalized = (
            condition
            if isinstance(condition, NormalizedCondition)
            else normalize_condition(condition)
        )
    except UnsupportedConditionError:
        return "unknown"

    if not normalized.entity or not normalized.field:
        return "unknown"
    if normalized.expected_value is None:
        return "unknown"

    handler = CONDITION_HANDLERS.get(normalized.condition_type)
    if handler is None:
        return "unknown"

    key: WorldKey = (normalized.entity, normalized.field)
    if key not in world_state:
        return "unknown"
    current_value = world_state[key]
    if current_value is None:
        return "unknown"

    try:
        result = handler(current_value, normalized.expected_value)
    except (TypeError, ValueError):
        return "unknown"
    if result is None:
        return "unknown"
    return "holds" if result else "violated"


def _as_mapping(condition: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Return a plain mapping for dicts, pydantic models, and ORM-like objects."""
    if isinstance(condition, Mapping):
        return dict(condition)
    model_dump = getattr(condition, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump(mode="json"))
    raise UnsupportedConditionError(f"Condition is not a mapping: {condition!r}")


def _canonical_expected_value(condition_type: str, raw_value: Any) -> Any:
    """Normalize the recorded threshold into the form the handler expects."""
    if condition_type == "supplier_risk_open":
        return "open"
    if condition_type == "supplier_risk_resolved":
        return "resolved"
    if condition_type == "price_break_available":
        return True if raw_value is None else raw_value
    return raw_value


def _numeric_compare(current_value: Any, expected_value: Any, operator: str) -> bool | None:
    """Compare two values numerically, returning None when they are not comparable."""
    if isinstance(current_value, bool) or isinstance(expected_value, bool):
        return None
    try:
        left = float(current_value)
        right = float(expected_value)
    except (TypeError, ValueError):
        return None
    if operator == ">=":
        return left >= right
    if operator == "<=":
        return left <= right
    if operator == "<":
        return left < right
    if operator == ">":
        return left > right
    return None


def _risk_status(value: Any) -> str | None:
    """Map a stated supplier-risk status onto ``open``, ``resolved``, or None."""
    if isinstance(value, bool):
        return "open" if value else "resolved"
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in RISK_OPEN_VALUES:
        return "open"
    if normalized in RISK_RESOLVED_VALUES:
        return "resolved"
    return None


def _tier_gives_discount(tier: Any) -> bool:
    """Return whether one price-break tier carries an actual volume discount."""
    if not isinstance(tier, Mapping):
        return False
    discount = tier.get("discount_pct")
    try:
        return float(discount) > 0
    except (TypeError, ValueError):
        return False
