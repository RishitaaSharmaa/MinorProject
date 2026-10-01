"""Pure deterministic condition and decision-review rules."""

from dataclasses import dataclass
from typing import Any, Literal

Operator = Literal["==", "!=", "<", "<=", ">", ">="]
ConditionState = Literal["valid", "invalid", "unknown"]


@dataclass(frozen=True)
class ReasonCondition:
    """A machine-checkable condition recorded as a reason for a decision."""

    entity: str
    field: str
    operator: Operator
    expected_value: Any


@dataclass(frozen=True)
class ConditionCheck:
    """Result of comparing one recorded condition with current state."""

    condition: ReasonCondition
    current_value: Any
    holds: bool | None


@dataclass(frozen=True)
class DecisionReview:
    """Deterministic review result; no language model participates in scoring."""

    condition_state: ConditionState
    estimated_regret: float
    switching_cost: float
    flagged: bool
    explanation: str


def check_condition(condition: ReasonCondition, current_value: Any) -> bool | None:
    """Evaluate a condition, returning None when the current value is unknown."""
    if current_value is None:
        return None
    comparisons = {
        "==": lambda: current_value == condition.expected_value,
        "!=": lambda: current_value != condition.expected_value,
        "<": lambda: current_value < condition.expected_value,
        "<=": lambda: current_value <= condition.expected_value,
        ">": lambda: current_value > condition.expected_value,
        ">=": lambda: current_value >= condition.expected_value,
    }
    try:
        return bool(comparisons[condition.operator]())
    except (TypeError, ValueError):
        return False


def review_decision(
    checks: list[ConditionCheck], estimated_regret: float, switching_cost: float
) -> DecisionReview:
    """Flag only broken reasons whose regret exceeds the switching cost."""
    states = [check.holds for check in checks]
    if any(state is False for state in states):
        condition_state: ConditionState = "invalid"
    elif states and all(state is True for state in states):
        condition_state = "valid"
    else:
        condition_state = "unknown"

    flagged = condition_state == "invalid" and estimated_regret > switching_cost
    if condition_state == "unknown":
        explanation = "Current state is incomplete; no decision flag was raised."
    elif condition_state == "valid":
        explanation = "Recorded conditions still hold; no decision flag was raised."
    elif flagged:
        explanation = "A recorded condition no longer holds and estimated regret exceeds switching cost."
    else:
        explanation = "A recorded condition no longer holds, but estimated regret does not exceed switching cost."

    return DecisionReview(
        condition_state=condition_state,
        estimated_regret=estimated_regret,
        switching_cost=switching_cost,
        flagged=flagged,
        explanation=explanation,
    )