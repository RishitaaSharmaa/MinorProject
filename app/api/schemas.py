"""Pydantic request and response schemas for the decision review API."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.conditions import Condition


class ProposalEdit(BaseModel):
    """Accepted planner condition linked to its original extraction proposal."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=1, max_length=36)
    condition: Condition


class ConfirmAssumptionsRequest(BaseModel):
    """Accepted or edited proposals and proposal identifiers rejected by planner."""

    model_config = ConfigDict(extra="forbid")

    accepted: list[ProposalEdit] = Field(default_factory=list)
    rejected_proposal_ids: list[str] = Field(default_factory=list)


class ConfirmAssumptionsResponse(BaseModel):
    """Confirmation counts and persisted assumption identifiers."""

    accepted_count: int
    edited_count: int
    rejected_count: int
    assumption_ids: list[str]


class ActionCostOut(BaseModel):
    """One alternative action's priced mitigation and switching cost."""

    action: str
    residual_cost: float
    fee: float
    in_transit: float
    sibling_impact: float
    switching_cost: float
    total_cost: float


class DecisionScoreOut(BaseModel):
    """Full deterministic scoring breakdown for one decision and its broken assumption."""

    decision_id: str
    assumption_id: str
    order_value: float
    cost_keep: float
    cost_keep_breakdown: dict[str, Any]
    actions: dict[str, ActionCostOut]
    best_alternative: str
    regret: float
    switching_cost: float
    switching_cost_breakdown: dict[str, float]
    net_benefit: float
    days_to_window: int | None
    window_open: bool
    flagged: bool
    recommendation: str
    confidence: str
    confidence_reasons: list[str]
    assumptions_used: dict[str, Any]


class BriefCardOut(BaseModel):
    """One flagged decision on the brief, with its score and optional explanation."""

    score: DecisionScoreOut
    explanation: str | None


class BriefResponse(BaseModel):
    """A ranked, deterministic morning brief for one simulated date."""

    as_of: date
    cards: list[BriefCardOut]
    reviewed_and_kept: int


class DecisionActionRequest(BaseModel):
    """A planner's disposition of one flagged decision."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["keep", "reduce", "delay", "cancel"]
    note: str = Field(default="", max_length=2000)


class DecisionActionResponse(BaseModel):
    """Confirmation that a decision's outcome was logged."""

    decision_id: str
    action: str
    note: str


class AssumptionOut(BaseModel):
    """One recorded assumption's condition and review state."""

    id: str
    condition: dict[str, Any]
    source: str
    status: str
    confirmed_by_user: bool
    created_at: datetime


class TimelineEventOut(BaseModel):
    """One recorded state change affecting a decision's item or supplier."""

    id: str
    entity_type: str
    entity_id: str
    field: str
    old_value: Any
    new_value: Any
    event_time: datetime


class DecisionDetailResponse(BaseModel):
    """One decision's facts, assumptions, timeline, and current score."""

    id: str
    decision_type: str
    created_at: datetime
    item_id: str | None
    supplier_id: str | None
    quantity: int | None
    unit_price: float | None
    po_date: date | None
    expected_delivery: date | None
    free_text_reason: str | None
    is_override: bool
    status: str
    assumptions: list[AssumptionOut]
    timeline: list[TimelineEventOut]
    score: DecisionScoreOut | None


class MetricsResponse(BaseModel):
    """Operational review metrics."""

    flags_per_week: dict[str, int]
    action_rate: float
    extraction_correction_rate: float


class RecheckResponse(BaseModel):
    """Counts from one point-in-time assumption recheck pass."""

    as_of: date
    events_processed: int
    assumptions_rechecked: int
    violations: int
    recoveries: int