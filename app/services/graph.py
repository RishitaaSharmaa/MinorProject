"""Cycle-safe recursive walks across assumptions, commitments, and decisions.

A supplier-terms break (a changed lead time, MOQ, price break, or strike
status) can invalidate more than the one decision an assumption was recorded
against: procurement often consolidates several purchase orders into one
commitment bundle (shared freight, a volume discount, a pooled MOQ), so
cancelling or switching one order can also forfeit the ``savings_at_stake``
recorded on the ``commitment_links`` edges tying it to the rest of the
bundle. These walks answer "how far does that reach" without assuming the
graph is acyclic.
"""

from dataclasses import dataclass

from sqlalchemy import String, case, cast, func, literal, or_, select
from sqlalchemy.orm import Session

from app.models import Assumption, Commitment, CommitmentLink
from app.services.watcher import ViolationRecord

#: Actions that can trigger sibling cancellation/switching economics.
COSTLY_ACTIONS = frozenset({"cancel", "switch"})

#: Supplier fields whose change constitutes a "supplier-terms" event.
SUPPLIER_TERMS_FIELDS = frozenset(
    {"quoted_lead_time", "lead_time_days", "moq", "price_break_tiers", "strike_status"}
)


def commitments_linked_to(session: Session, commitment_id: str) -> list[str]:
    """Return every commitment reachable from one via commitment_links edges.

    Edges are walked in both directions (a link only records a from/to pair
    for uniqueness, not a real direction), and a cycle-safe visited token
    stops the walk from revisiting a commitment, so a cycle terminates and
    every related commitment is returned exactly once.

    The recursive term is a single SELECT that picks "the other end" of
    whichever edge matched via a CASE expression, rather than two separate
    SELECTs (one per direction) combined with UNION ALL: PostgreSQL rejects
    a recursive CTE whose self-reference appears in more than one branch of
    that union ("recursive reference ... must not appear within its
    non-recursive term"), even though SQLite tolerates it.
    """
    start_visited = f",{commitment_id},"
    walk = select(
        literal(commitment_id).label("commitment_id"),
        literal(start_visited).label("visited"),
    ).cte("graph_commitment_walk", recursive=True)
    other_end = case(
        (CommitmentLink.from_commitment_id == walk.c.commitment_id, CommitmentLink.to_commitment_id),
        else_=CommitmentLink.from_commitment_id,
    )
    step = select(
        other_end.label("commitment_id"),
        (walk.c.visited + other_end + literal(",")).label("visited"),
    ).where(
        or_(
            CommitmentLink.from_commitment_id == walk.c.commitment_id,
            CommitmentLink.to_commitment_id == walk.c.commitment_id,
        ),
        ~walk.c.visited.contains(_visited_token(other_end)),
    )
    walk = walk.union_all(step)
    return list(
        session.scalars(
            select(cast(walk.c.commitment_id, String))
            .where(walk.c.commitment_id != commitment_id)
            .distinct()
        )
    )


def decisions_depending_on_assumption(session: Session, assumption_id: str) -> list[str]:
    """Return every decision whose economics depend on one assumption.

    A decision depends on an assumption directly when the assumption was
    recorded against it, and transitively when its commitment sits in the
    same commitment-link bundle (reached by any chain of edges, cycle-safe)
    as the commitment of the decision the assumption was recorded against.
    """
    assumption = session.get(Assumption, assumption_id)
    if assumption is None:
        return []

    decision_ids = {assumption.decision_id}
    commitment = session.scalar(
        select(Commitment).where(Commitment.decision_id == assumption.decision_id)
    )
    if commitment is not None:
        linked_ids = commitments_linked_to(session, commitment.id)
        if linked_ids:
            decision_ids.update(
                session.scalars(select(Commitment.decision_id).where(Commitment.id.in_(linked_ids)))
            )
    return sorted(decision_ids)


def sibling_impact(session: Session, decision_id: str, action: str) -> float:
    """Return the named savings a bundle forfeits if ``action`` is taken on one decision.

    Unlike ``app.services.commitments.sibling_impact`` (which prices a
    sibling's own cancellation fee), this sums ``commitment_links.savings_at_stake``
    across every edge inside the reachable commitment bundle -- the concrete,
    named economics a buyer was promised (e.g. "cancel PO-781 loses freight
    discount on PO-782, +INR 18k") rather than a fee-based estimate.
    """
    if action not in COSTLY_ACTIONS:
        return 0.0

    commitment = session.scalar(select(Commitment).where(Commitment.decision_id == decision_id))
    if commitment is None:
        return 0.0

    reachable = commitments_linked_to(session, commitment.id)
    if not reachable:
        return 0.0

    bundle = {commitment.id, *reachable}
    savings = session.scalar(
        select(func.coalesce(func.sum(CommitmentLink.savings_at_stake), 0.0)).where(
            CommitmentLink.from_commitment_id.in_(bundle),
            CommitmentLink.to_commitment_id.in_(bundle),
        )
    )
    return float(savings or 0.0)


def is_supplier_terms_event(entity: str, field: str) -> bool:
    """Return whether an (entity, field) pair reports a supplier-terms change."""
    return entity.startswith("supplier:") and field in SUPPLIER_TERMS_FIELDS


@dataclass(frozen=True)
class SupplierTermsImpact:
    """Priced blast radius of one supplier-terms violation across the commitment graph."""

    decision_id: str
    affected_decision_ids: tuple[str, ...]
    extra_cost: float


class SupplierTermsCascade:
    """Price the linked-order cost of every supplier-terms violation a watcher reports.

    Pass an instance as ``on_violation`` to ``AssumptionWatcher`` to react to
    supplier-terms breaks (lead time, MOQ, price break, strike) by pricing
    their reach across the commitment graph as each violation is detected,
    without coupling the in-memory watcher engine itself to persistence.
    Violations from non-supplier-terms events (forecast, stock, ...) are
    ignored, since only a supplier-terms change implicates a shared
    commitment bundle.
    """

    def __init__(self, session: Session, action: str = "cancel") -> None:
        self._session = session
        self._action = action
        self._impacts: list[SupplierTermsImpact] = []

    def __call__(self, violation: ViolationRecord) -> None:
        """Price and record one violation's cascade, if it came from a supplier-terms event."""
        if not is_supplier_terms_event(violation.entity, violation.field):
            return
        affected = tuple(
            decision_id
            for decision_id in decisions_depending_on_assumption(self._session, violation.assumption_id)
            if decision_id != violation.decision_id
        )
        if not affected:
            return
        extra_cost = sibling_impact(self._session, violation.decision_id, self._action)
        self._impacts.append(
            SupplierTermsImpact(
                decision_id=violation.decision_id,
                affected_decision_ids=affected,
                extra_cost=extra_cost,
            )
        )

    def impacts(self) -> tuple[SupplierTermsImpact, ...]:
        """Return every priced supplier-terms cascade recorded so far."""
        return tuple(self._impacts)


def _visited_token(column):
    """Wrap an identifier so substring collisions cannot look like a visit."""
    return literal(",") + column + literal(",")
