"""Tests for graph.py: cycle-safe commitment walks and supplier-terms cascades."""

from collections.abc import Iterator
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Assumption, Base, Commitment, CommitmentLink, Decision
from app.services.events import StateEvent
from app.services.graph import (
    SupplierTermsCascade,
    commitments_linked_to,
    decisions_depending_on_assumption,
    sibling_impact,
)
from app.services.watcher import AssumptionWatcher


@pytest.fixture
def session() -> Iterator[Session]:
    """Provide an isolated SQLite session with operational tables."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    database = Session(engine, expire_on_commit=False)
    yield database
    database.close()
    engine.dispose()


def _decision(session: Session, decision_id: str, quantity: int = 10, unit_price: float = 1.0) -> Decision:
    """Insert a purchase decision (PO) used as a commitment owner."""
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


def _commitment(session: Session, commitment_id: str, decision_id: str, fee: float = 0.1) -> Commitment:
    """Insert cancellation economics for one decision."""
    commitment = Commitment(
        id=commitment_id,
        decision_id=decision_id,
        cancellation_fee_pct=fee,
        reversible_until=date(2025, 2, 1),
    )
    session.add(commitment)
    return commitment


def _link(
    session: Session,
    from_id: str,
    to_id: str,
    link_type: str = "freight_consolidation",
    savings_at_stake: float = 0.0,
) -> None:
    """Insert one commitment_links edge with its economics."""
    session.add(
        CommitmentLink(
            id=f"CL-{from_id}-{to_id}",
            from_commitment_id=from_id,
            to_commitment_id=to_id,
            link_type=link_type,
            savings_at_stake=savings_at_stake,
        )
    )


def _assumption(session: Session, assumption_id: str, decision_id: str, condition: dict) -> Assumption:
    """Insert a live assumption recorded against one decision."""
    assumption = Assumption(
        id=assumption_id,
        decision_id=decision_id,
        condition=condition,
        source="manual",
        status="live",
        created_at=datetime(2025, 1, 10, tzinfo=timezone.utc),
    )
    session.add(assumption)
    return assumption


def _three_po_bundle(session: Session) -> None:
    """Build PO-781/782/783 bundled by a shared freight consolidation deal."""
    for suffix, po in (("1", "PO-781"), ("2", "PO-782"), ("3", "PO-783")):
        _decision(session, po, quantity=100, unit_price=50.0)
        _commitment(session, f"COM{suffix}", po, fee=0.1)
    _link(session, "COM1", "COM2", savings_at_stake=18_000.0)
    _link(session, "COM2", "COM3", savings_at_stake=7_000.0)


def test_three_po_bundle_reports_every_sibling_decision(session: Session) -> None:
    """Every PO in the bundle is reachable from any other, cycle-free graph."""
    _three_po_bundle(session)
    _assumption(
        session,
        "ASM1",
        "PO-781",
        {"type": "supplier_risk_resolved", "entity_ref": "supplier:SUP1", "value": "resolved"},
    )
    session.commit()

    commitment_a = session.scalar(select(Commitment).where(Commitment.decision_id == "PO-781"))
    assert set(commitments_linked_to(session, commitment_a.id)) == {"COM2", "COM3"}
    assert decisions_depending_on_assumption(session, "ASM1") == ["PO-781", "PO-782", "PO-783"]


def test_three_po_bundle_sibling_impact_sums_named_savings(session: Session) -> None:
    """Cancelling one leg of the bundle forfeits every named savings in reach."""
    _three_po_bundle(session)
    session.commit()

    assert sibling_impact(session, "PO-781", "cancel") == pytest.approx(25_000.0)
    assert sibling_impact(session, "PO-782", "cancel") == pytest.approx(25_000.0)
    assert sibling_impact(session, "PO-781", "keep") == 0.0


def test_commitment_link_cycle_is_cycle_safe(session: Session) -> None:
    """A commitment_links cycle must terminate and return each commitment once."""
    for suffix in ("A", "B", "C"):
        _decision(session, f"DEC{suffix}", 10, 2.0)
        _commitment(session, f"COM{suffix}", f"DEC{suffix}", 0.1)
    _link(session, "COMA", "COMB", savings_at_stake=1_000.0)
    _link(session, "COMB", "COMC", savings_at_stake=2_000.0)
    _link(session, "COMC", "COMA", savings_at_stake=3_000.0)
    session.commit()

    related = set(commitments_linked_to(session, "COMA"))

    assert related == {"COMB", "COMC"}
    assert sibling_impact(session, "DECA", "cancel") == pytest.approx(6_000.0)


def test_decisions_depending_on_assumption_is_cycle_safe(session: Session) -> None:
    """A cycle in the commitment graph must not loop when resolving decisions."""
    for suffix in ("A", "B", "C"):
        _decision(session, f"DEC{suffix}", 10, 2.0)
        _commitment(session, f"COM{suffix}", f"DEC{suffix}", 0.1)
    _link(session, "COMA", "COMB")
    _link(session, "COMB", "COMC")
    _link(session, "COMC", "COMA")
    _assumption(
        session,
        "ASMA",
        "DECA",
        {"type": "supplier_risk_resolved", "entity_ref": "supplier:SUP1", "value": "resolved"},
    )
    session.commit()

    assert decisions_depending_on_assumption(session, "ASMA") == ["DECA", "DECB", "DECC"]


def test_watcher_reacts_to_supplier_terms_event_and_prices_the_bundle(session: Session) -> None:
    """A supplier-terms violation cascades a priced impact across the bundle."""
    _three_po_bundle(session)
    _assumption(
        session,
        "ASM1",
        "PO-781",
        {"type": "supplier_risk_resolved", "entity_ref": "supplier:SUP1", "value": "resolved"},
    )
    session.commit()

    cascade = SupplierTermsCascade(session)
    watcher = AssumptionWatcher(
        world_state={("supplier:SUP1", "strike_status"): "resolved"},
        on_violation=cascade,
    )
    watcher.watch("ASM1", "PO-781", {
        "type": "supplier_risk_resolved", "entity_ref": "supplier:SUP1", "value": "resolved",
    })

    event = StateEvent(
        entity="supplier:SUP1",
        field="strike_status",
        old_value="resolved",
        new_value="open",
        event_id="EVT1",
        event_time=datetime(2025, 3, 1, tzinfo=timezone.utc),
    )
    result = watcher.process_event(event)

    assert len(result.violations) == 1
    impacts = cascade.impacts()
    assert len(impacts) == 1
    assert impacts[0].decision_id == "PO-781"
    assert set(impacts[0].affected_decision_ids) == {"PO-782", "PO-783"}
    assert impacts[0].extra_cost == pytest.approx(25_000.0)


def test_watcher_ignores_non_supplier_terms_violations(session: Session) -> None:
    """A stock/forecast violation must not trigger a supplier-terms cascade."""
    _three_po_bundle(session)
    condition = {"condition_name": "stock_qty", "op": ">", "value": 10, "entity": "item:SKU1"}
    _assumption(session, "ASM1", "PO-781", condition)
    session.commit()

    cascade = SupplierTermsCascade(session)
    watcher = AssumptionWatcher(
        world_state={("item:SKU1", "stock_qty"): 50},
        on_violation=cascade,
    )
    watcher.watch("ASM1", "PO-781", condition)

    event = StateEvent(
        entity="item:SKU1",
        field="stock_qty",
        old_value=50,
        new_value=5,
        event_id="EVT2",
        event_time=datetime(2025, 3, 1, tzinfo=timezone.utc),
    )
    result = watcher.process_event(event)

    assert len(result.violations) == 1
    assert cascade.impacts() == ()
