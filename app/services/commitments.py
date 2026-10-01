"""Cycle-safe commitment graph walks and sibling cancellation economics.

The cycle-safe recursive walk itself lives in ``app.services.graph``, which
also prices the named ``savings_at_stake`` a commitment bundle can forfeit.
This module keeps the older, decision-object-based fee estimate: a sibling's
own ``cancellation_fee_pct`` charged against its order value.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from app.models import Commitment, Decision
from app.services.graph import COSTLY_ACTIONS, commitments_linked_to


def sibling_impact(decision: Decision, action: str) -> float:
    """Return extra cost imposed on linked orders for a planned action."""
    session = object_session(decision)
    if session is None:
        raise RuntimeError("sibling_impact requires a persistent Decision bound to a session")
    if action not in COSTLY_ACTIONS:
        return 0.0

    commitment = session.scalar(select(Commitment).where(Commitment.decision_id == decision.id))
    if commitment is None:
        return 0.0

    sibling_ids = commitments_linked_to(session, commitment.id)
    if not sibling_ids:
        return 0.0

    extra_cost = 0.0
    rows = session.execute(
        select(Commitment, Decision)
        .join(Decision, Decision.id == Commitment.decision_id)
        .where(Commitment.id.in_(sibling_ids))
    )
    for sibling, sibling_decision in rows:
        extra_cost += _order_value(sibling_decision) * float(sibling.cancellation_fee_pct)
    return extra_cost


def linked_commitment_ids(session: Session, commitment_id: str) -> list[str]:
    """Return distinct related commitment IDs via a cycle-safe recursive CTE."""
    return commitments_linked_to(session, commitment_id)


def _order_value(decision: Decision) -> float:
    """Compute PO value from recorded quantity and unit price without inventing zeros."""
    if decision.quantity is None or decision.unit_price is None:
        return 0.0
    return float(decision.quantity) * float(decision.unit_price)
