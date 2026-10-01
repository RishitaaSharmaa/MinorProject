"""Tests for cycle-safe commitment walks and sibling extra cost."""

from collections.abc import Iterator
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Commitment, CommitmentLink, Decision
from app.services.commitments import linked_commitment_ids, sibling_impact


@pytest.fixture
def session() -> Iterator[Session]:
    """Provide an isolated SQLite session with operational tables."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    database = Session(engine, expire_on_commit=False)
    yield database
    database.close()
    engine.dispose()


def _decision(session: Session, decision_id: str, quantity: int, unit_price: float) -> Decision:
    """Insert a purchase decision used as a commitment owner."""
    decision = Decision(
        id=decision_id,
        decision_type="purchase_order",
        created_at=datetime(2025, 1, 10, tzinfo=timezone.utc),
        structured_fields={},
        is_override=False,
        status="placed",
        quantity=quantity,
        unit_price=unit_price,
    )
    session.add(decision)
    return decision


def _commitment(
    session: Session, commitment_id: str, decision_id: str, fee: float
) -> Commitment:
    """Insert cancellation economics for one decision."""
    commitment = Commitment(
        id=commitment_id,
        decision_id=decision_id,
        cancellation_fee_pct=fee,
        reversible_until=date(2025, 2, 1),
    )
    session.add(commitment)
    return commitment


def _link(session: Session, from_id: str, to_id: str) -> None:
    """Insert one directed commitment edge."""
    session.add(CommitmentLink(
        id=f"CL-{from_id}-{to_id}",
        from_commitment_id=from_id,
        to_commitment_id=to_id,
    ))


def test_linked_commitment_walk_is_cycle_safe(session: Session) -> None:
    """A cycle must terminate and return each related commitment once."""
    for suffix in ("A", "B", "C"):
        _decision(session, f"DEC{suffix}", 10, 2.0)
        _commitment(session, f"COM{suffix}", f"DEC{suffix}", 0.1)
    _link(session, "COMA", "COMB")
    _link(session, "COMB", "COMC")
    _link(session, "COMC", "COMA")
    session.commit()

    related = set(linked_commitment_ids(session, "COMA"))

    assert related == {"COMB", "COMC"}


def test_diamond_graph_does_not_double_count(session: Session) -> None:
    """Shared descendants reached by two paths appear once."""
    for suffix in ("A", "B", "C", "D"):
        _decision(session, f"DEC{suffix}", 1, 1.0)
        _commitment(session, f"COM{suffix}", f"DEC{suffix}", 0.1)
    _link(session, "COMA", "COMB")
    _link(session, "COMA", "COMC")
    _link(session, "COMB", "COMD")
    _link(session, "COMC", "COMD")
    session.commit()

    related = linked_commitment_ids(session, "COMA")

    assert sorted(related) == ["COMB", "COMC", "COMD"]


def test_sibling_impact_charges_linked_orders_for_cancel(session: Session) -> None:
    """Cancel extra cost is sibling order value times each sibling fee."""
    primary = _decision(session, "DEC1", 10, 5.0)
    sibling = _decision(session, "DEC2", 20, 4.0)
    _commitment(session, "COM1", "DEC1", 0.5)
    _commitment(session, "COM2", "DEC2", 0.25)
    _link(session, "COM1", "COM2")
    session.commit()

    assert sibling_impact(primary, "cancel") == pytest.approx(20 * 4.0 * 0.25)
    assert sibling_impact(sibling, "switch") == pytest.approx(10 * 5.0 * 0.5)
    assert sibling_impact(primary, "keep") == 0.0


def test_sibling_impact_is_zero_without_links_or_commitment(session: Session) -> None:
    """Unlinked and uncommitted decisions impose no sibling extra cost."""
    unlinked = _decision(session, "DEC1", 8, 3.0)
    _commitment(session, "COM1", "DEC1", 0.2)
    orphan = _decision(session, "DEC2", 8, 3.0)
    session.commit()

    assert sibling_impact(unlinked, "cancel") == 0.0
    assert sibling_impact(orphan, "cancel") == 0.0
