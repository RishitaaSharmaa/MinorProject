"""Application services coordinating persistence, ERP access, and rule checks."""

from sqlalchemy.orm import Session

from decisionwatch.domain import ConditionCheck, ReasonCondition, check_condition, review_decision
from decisionwatch.erp import ERPConnector
from decisionwatch.models import DecisionRecord
from decisionwatch.schemas import DecisionReviewOutput


def review_record(decision: DecisionRecord, connector: ERPConnector) -> DecisionReviewOutput:
    """Read condition values through the ERP interface and apply pure rules."""
    checks = []
    for record in decision.conditions:
        condition = ReasonCondition(
            entity=record.entity,
            field=record.field,
            operator=record.operator,
            expected_value=record.expected_value,
        )
        current_value = connector.get_current_value(condition.entity, condition.field)
        checks.append(ConditionCheck(condition, current_value, check_condition(condition, current_value)))

    result = review_decision(checks, decision.estimated_regret, decision.switching_cost)
    decision.latest_condition_state = result.condition_state
    decision.latest_flagged = result.flagged
    return DecisionReviewOutput(decision_id=decision.id, **result.__dict__)


def persist_review(session: Session, decision: DecisionRecord, connector: ERPConnector) -> DecisionReviewOutput:
    """Evaluate and persist the latest deterministic state for a decision."""
    result = review_record(decision, connector)
    session.add(decision)
    return result