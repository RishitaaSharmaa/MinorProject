"""Deterministic, plain-language reasoning for one scored decision.

Built purely from the score's own numbers, so every decision can always show
why it was (or was not) flagged without an LLM call.
"""

from app.services.scoring import DecisionScore


def explain_score(score: DecisionScore) -> list[str]:
    """Return ordered sentences explaining the flag and the recommendation."""
    used = score.assumptions_used
    breakdown = score.cost_keep_breakdown
    lines = [
        f"The assumption behind this order no longer holds: {used['normalized_type']} on "
        f"{used['entity']} (expected {used['field']} {used['operator']} {used['expected_value']})."
    ]
    if "current_value" in breakdown:
        lines.append(f"The current {used['field']} is {breakdown['current_value']}, against an expected {breakdown['expected_value']}.")

    estimate_note = " This is a default estimate, as no precise exposure could be measured." if breakdown.get("estimated") else ""
    lines.append(
        f"Keeping the order unchanged is expected to cost {_inr(score.cost_keep)}. Moving to "
        f"'{score.best_alternative}' would avoid {_inr(score.regret)} of that (regret) at a switching cost of "
        f"{_inr(score.switching_cost)}.{estimate_note}"
    )

    if score.flagged:
        lines.append(
            f"Regret exceeds switching cost by {_inr(score.net_benefit)}, so acting is worth it. "
            f"Recommended action: {score.recommendation}."
        )
    elif not score.window_open:
        lines.append("The window to reverse this commitment has closed, so the recommendation is to keep it.")
    else:
        lines.append(
            f"Switching costs {_inr(-score.net_benefit)} more than it saves, so the recommendation is to keep the order."
        )

    if score.window_open and score.days_to_window is not None:
        lines.append(f"There are {score.days_to_window} days left to reverse this commitment.")
    elif score.window_open:
        lines.append("There is no deadline to reverse this commitment.")

    sibling = score.switching_cost_breakdown.get("sibling_impact", 0)
    if sibling:
        lines.append(f"Acting would forfeit {_inr(sibling)} in savings on linked orders.")

    confidence = f"Confidence is {score.confidence}."
    if score.confidence_reasons:
        confidence += " Reduced because: " + "; ".join(score.confidence_reasons) + "."
    lines.append(confidence)
    return lines


def _inr(value: float) -> str:
    """Format an amount as rounded rupees."""
    return f"₹{value:,.0f}"
