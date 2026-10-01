"""Pydantic v2 request and response schemas for the API."""

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Operator = Literal["==", "!=", "<", "<=", ">", ">="]


class ConditionInput(BaseModel):
    """A structured condition attached to a procurement decision."""

    entity: str = Field(min_length=1, max_length=255)
    field: str = Field(min_length=1, max_length=128)
    operator: Operator
    expected_value: Any


class DecisionCreate(BaseModel):
    """Fields required to record a decision and its reasons."""

    decision_type: str = Field(default="purchase_order", max_length=64)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reason: str = Field(min_length=1)
    estimated_regret: float = Field(ge=0)
    switching_cost: float = Field(ge=0)
    conditions: list[ConditionInput] = Field(min_length=1)


class ConditionOutput(ConditionInput):
    """Condition response including its persistent identifier."""

    id: str


class DecisionOutput(BaseModel):
    """Persisted decision response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    decision_type: str
    created_at: datetime
    reason: str
    estimated_regret: float
    switching_cost: float
    latest_condition_state: str
    latest_flagged: bool
    conditions: list[ConditionOutput]


class StateChangeInput(BaseModel):
    """Incoming state change from an ERP connector/event feed."""

    entity: str = Field(min_length=1, max_length=255)
    field: str = Field(min_length=1, max_length=128)
    new_value: Any
    event_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DecisionLinkInput(BaseModel):
    """Directed dependency to another recorded decision."""

    target_decision_id: str = Field(min_length=1, max_length=36)
    relationship: str = Field(default="depends_on", min_length=1, max_length=64)


class DecisionReviewOutput(BaseModel):
    """Rule-based decision review returned after a state change."""

    decision_id: str
    condition_state: Literal["valid", "invalid", "unknown"]
    estimated_regret: float
    switching_cost: float
    flagged: bool
    explanation: str


class ExtractionInput(BaseModel):
    """Text to convert into candidate machine-checkable conditions."""

    reason: str = Field(min_length=1)


class ExtractionOutput(BaseModel):
    """Conditions extracted from a decision reason."""

    conditions: list[ConditionInput]


class ExplanationOutput(BaseModel):
    """LLM-authored natural-language explanation of deterministic findings."""

    explanation: str