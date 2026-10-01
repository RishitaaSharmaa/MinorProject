"""Tests for deterministic DecisionWatch condition and regret rules."""

from decisionwatch.domain import ConditionCheck, ReasonCondition, check_condition, review_decision


def test_condition_comparisons_and_unknown_state() -> None:
    """Support relational checks and represent missing values as unknown."""
    condition = ReasonCondition("item:1", "stock", "<", 10)

    assert check_condition(condition, 8) is True
    assert check_condition(condition, 12) is False
    assert check_condition(condition, None) is None


def test_flags_only_when_regret_exceeds_switching_cost() -> None:
    """Use a strict greater-than threshold for intervention flags."""
    condition = ReasonCondition("item:1", "stock", "<", 10)
    broken = ConditionCheck(condition, 12, False)

    assert review_decision([broken], 101, 100).flagged is True
    assert review_decision([broken], 100, 100).flagged is False


def test_missing_values_do_not_create_a_flag() -> None:
    """Do not flag decisions when the ERP connector lacks current state."""
    condition = ReasonCondition("item:1", "stock", "<", 10)
    unknown = ConditionCheck(condition, None, None)

    review = review_decision([unknown], 1000, 1)

    assert review.condition_state == "unknown"
    assert review.flagged is False