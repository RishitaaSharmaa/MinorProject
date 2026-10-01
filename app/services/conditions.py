"""Closed Pydantic vocabulary for machine-checkable decision conditions."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ConditionType = Literal[
    "forecast_gte",
    "forecast_lte",
    "stock_lt",
    "stock_gt",
    "lead_time_lte",
    "supplier_risk_open",
    "supplier_risk_resolved",
    "moq_lte",
    "price_break_available",
]
ConditionOperator = Literal["==", "!=", "<", "<=", ">", ">="]
ConditionValue = str | float | int | bool | None

_REQUIRED_OPERATOR: dict[str, str] = {
    "forecast_gte": ">=",
    "forecast_lte": "<=",
    "stock_lt": "<",
    "stock_gt": ">",
    "lead_time_lte": "<=",
    "supplier_risk_open": "==",
    "supplier_risk_resolved": "==",
    "moq_lte": "<=",
    "price_break_available": "==",
}


class Condition(BaseModel):
    """One checkable condition constrained to the supported type/operator set."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: ConditionType
    entity_ref: str = Field(min_length=1, max_length=255)
    op: ConditionOperator
    value: ConditionValue
    needs_value_from_planner: bool = False

    @model_validator(mode="before")
    @classmethod
    def normalize_supplier_risk_value(cls, values: object) -> object:
        """Normalize common stated supplier-risk statuses into canonical values."""
        if not isinstance(values, dict):
            return values
        condition_data = values.copy()
        condition_type = condition_data.get("type")
        risk_value = condition_data.get("value")
        normalized = risk_value.strip().lower() if isinstance(risk_value, str) else risk_value
        open_values = {"open", "strike", "at_risk", "active", "unresolved", "ongoing", "yes", "true"}
        resolved_values = {
            "resolved", "clear", "cleared", "none", "normal", "no strike", "closed",
            "inactive", "safe", "no risk", "not at risk", "not_at_risk", "false",
        }
        if condition_type == "supplier_risk_open" and (normalized in open_values or normalized is True):
            condition_data["value"] = "open"
        elif condition_type == "supplier_risk_resolved" and (
            normalized in resolved_values or normalized is False
        ):
            condition_data["value"] = "resolved"
        return condition_data

    @model_validator(mode="after")
    def validate_condition_shape(self) -> "Condition":
        """Require a type-appropriate operator and explicit missing-value marker."""
        if self.op != _REQUIRED_OPERATOR[self.type]:
            raise ValueError(f"Condition type {self.type} requires operator {_REQUIRED_OPERATOR[self.type]}")
        if self.value is None and not self.needs_value_from_planner:
            raise ValueError("A null value must set needs_value_from_planner=true")
        if self.type == "supplier_risk_open" and self.value not in {None, "open"}:
            raise ValueError("supplier_risk_open value must be 'open' or null")
        if self.type == "supplier_risk_resolved" and self.value not in {None, "resolved"}:
            raise ValueError("supplier_risk_resolved value must be 'resolved' or null")
        if self.type == "price_break_available" and self.value not in {None, True}:
            raise ValueError("price_break_available value must be true or null")
        return self


class ProposedCondition(Condition):
    """Condition proposal with provenance, confidence, and review warnings."""

    proposal_id: str
    source: Literal["structured", "llm"]
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)