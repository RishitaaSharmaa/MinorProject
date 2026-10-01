"""LLM-written, advisory suggestion for what to do about one flagged decision.

The deterministic score (``app.services.scoring``) remains the source of truth
for whether a decision is flagged and which action is recommended. The LLM
only reads that score and the surrounding context, then proposes one of the
four valid actions with a rationale. Output is constrained to those actions
and is discarded if it cites any figure absent from the score's own breakdown.
"""

import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import Decision, StateEvent
from app.services.brief import _only_uses_grounded_numbers, numbers_in
from app.services.scoring import DecisionScore
from llm.client import complete_json

ACTIONS = ("keep", "reduce", "delay", "cancel")
_MAX_TIMELINE_EVENTS = 8
_MAX_ATTEMPTS = 3

_SYSTEM_PROMPT = (
    "You are a procurement advisor assisting a planner. A purchasing decision rested on an "
    "assumption that has now broken. Suggest which one action the planner should take: keep, "
    "reduce, delay, or cancel. Treat the supplied total_cost of each action as the main evidence "
    "(lower is better) and weigh the reversal deadline, sibling impact, confidence reasons and the "
    "recent state changes. You may disagree with the deterministic recommendation, but only for a "
    "reason you state. Write plain sentences. State only monetary amounts and day counts that appear "
    "in the supplied data, exactly as given. Never mention dates, never number your points, and never "
    "introduce any other figure. Use only facts present in the supplied data; do not assume anything "
    "else about the supplier, stock or market. The planner makes the final call."
)


@dataclass(frozen=True)
class Suggestion:
    """A validated, advisory action suggestion for one decision."""

    decision_id: str
    suggested_action: str
    model_recommendation: str
    headline: str
    rationale: str
    risks: tuple[str, ...]
    next_steps: tuple[str, ...]

    @property
    def agrees_with_model(self) -> bool:
        """Whether the LLM's pick matches the deterministic recommendation."""
        return self.suggested_action == self.model_recommendation


class SuggestionUnavailable(RuntimeError):
    """Raised when the LLM is unreachable or never produced a grounded suggestion."""


class _LLMSuggestion(BaseModel):
    """Schema the LLM must return."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["keep", "reduce", "delay", "cancel"]
    headline: str = Field(min_length=1, max_length=160)
    rationale: str = Field(min_length=1, max_length=700)
    risks: list[str] = Field(default_factory=list, max_length=3)
    next_steps: list[str] = Field(default_factory=list, max_length=3)


def suggest_action(
    decision: Decision,
    score: DecisionScore,
    timeline: list[StateEvent],
) -> Suggestion:
    """Ask the LLM what to do about a flagged decision, retrying if it cites ungrounded numbers."""
    payload = json.dumps(_build_payload(decision, score, timeline), default=str)
    supplied_numbers = numbers_in(payload)
    last_error = "The LLM cited figures that are not in this decision's data."
    for _ in range(_MAX_ATTEMPTS):
        try:
            result = complete_json(_SYSTEM_PROMPT, payload, _LLMSuggestion)
        except Exception as exc:  # transient provider errors are retried
            last_error = f"LLM suggestion failed: {exc}"
            continue
        text = " ".join([result.headline, result.rationale, *result.risks, *result.next_steps])
        if _only_uses_grounded_numbers(text, score, supplied_numbers):
            return Suggestion(
                decision_id=score.decision_id,
                suggested_action=result.action,
                model_recommendation=score.recommendation,
                headline=result.headline,
                rationale=result.rationale,
                risks=tuple(result.risks),
                next_steps=tuple(result.next_steps),
            )
        last_error = "The LLM cited figures that are not in this decision's data."
    raise SuggestionUnavailable(last_error)


def _build_payload(decision: Decision, score: DecisionScore, timeline: list[StateEvent]) -> dict:
    """Assemble the grounded context the LLM may draw on."""
    return {
        "decision": {
            "id": decision.id,
            "type": decision.decision_type,
            "is_override": decision.is_override,
            "planner_reason": decision.free_text_reason,
            "quantity": decision.quantity,
        },
        "broken_assumption": score.assumptions_used,
        "current_value_of_broken_field": score.cost_keep_breakdown.get("current_value"),
        "deterministic_recommendation": score.recommendation,
        "confidence": score.confidence,
        "confidence_reasons": list(score.confidence_reasons),
        "days_to_window": score.days_to_window,
        "order_value": round(score.order_value, 2),
        "cost_keep": round(score.cost_keep, 2),
        "regret": round(score.regret, 2),
        "net_benefit": round(score.net_benefit, 2),
        "actions": {
            name: {
                "residual_cost": round(cost.residual_cost, 2),
                "fee": round(cost.fee, 2),
                "in_transit": round(cost.in_transit, 2),
                "sibling_impact": round(cost.sibling_impact, 2),
                "switching_cost": round(cost.switching_cost, 2),
                "total_cost": round(cost.total_cost, 2),
            }
            for name, cost in score.actions.items()
        },
        "recent_state_changes": [
            {"entity": f"{event.entity_type}:{event.entity_id}", "field": event.field,
             "from": event.old_value, "to": event.new_value}
            for event in timeline[-_MAX_TIMELINE_EVENTS:]
        ],
    }
