"""Tests for deterministic decision scoring."""

from collections.abc import Iterator
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.connectors.synthetic import SyntheticERPConnector
from app.models import (
    Assumption,
    Base,
    Commitment,
    CommitmentLink,
    Decision,
    Item,
    StockSnapshot,
    Supplier,
)
from app.services.scoring import score_decision


@pytest.fixture
def session() -> Iterator[Session]:
    """Provide an isolated SQLite session with a supplier and one catalog item."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    database = Session(engine, expire_on_commit=False)
    database.add(Supplier(
        id="SUP1", name="Supplier One", quoted_lead_time_days=5, lead_time_std_dev=1.0,
        reliability_score=0.9, price_break_tiers=[], strike_status="clear",
    ))
    database.add(Item(
        id="SKU1", name="Widget", category="Test", unit_cost=20.0, holding_cost_pct=0.2,
        min_order_qty=4, primary_supplier_id="SUP1", avg_daily_demand=5, reorder_point_qty=10,
    ))
    database.commit()
    yield database
    database.close()
    engine.dispose()


def _decision(
    session: Session, decision_id: str, quantity: int, unit_price: float,
    item_id: str | None = "SKU1", po_date: date | None = None,
) -> Decision:
    """Insert a purchase decision against the fixture's item and supplier."""
    decision = Decision(
        id=decision_id,
        decision_type="purchase_order",
        created_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
        structured_fields={},
        is_override=False,
        status="placed",
        item_id=item_id,
        supplier_id="SUP1" if item_id else None,
        quantity=quantity,
        unit_price=unit_price,
        po_date=po_date,
    )
    session.add(decision)
    return decision


def _commitment(session: Session, decision_id: str, fee_pct: float, reversible_until: date) -> Commitment:
    """Insert cancellation economics for one decision."""
    commitment = Commitment(
        id=f"COM-{decision_id}", decision_id=decision_id,
        cancellation_fee_pct=fee_pct, reversible_until=reversible_until,
    )
    session.add(commitment)
    return commitment


def _assumption(
    session: Session, assumption_id: str, decision_id: str, condition: dict,
    source: str = "structured", confirmed_by_user: bool = True,
) -> Assumption:
    """Insert a violated assumption recorded against one decision."""
    assumption = Assumption(
        id=assumption_id, decision_id=decision_id, condition=condition, source=source,
        confirmed_by_user=confirmed_by_user, status="violated",
        created_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
    )
    session.add(assumption)
    return assumption


def test_high_cancellation_fee_recommends_keep(session: Session) -> None:
    """A small exposure and a steep cancellation fee must not clear the flag bar."""
    _decision(session, "DEC1", quantity=100, unit_price=10.0)
    _commitment(session, "DEC1", fee_pct=0.9, reversible_until=date(2025, 6, 1))
    condition = {"type": "stock_gt", "entity_ref": "item:SKU1", "value": 50}
    _assumption(session, "ASM1", "DEC1", condition)
    session.add(StockSnapshot(item_id="SKU1", date=date(2025, 3, 15), qty_on_hand=45))
    session.commit()

    connector = SyntheticERPConnector(session)
    decision = session.get(Decision, "DEC1")
    assumption = session.get(Assumption, "ASM1")
    score = score_decision(session, connector, decision, assumption, date(2025, 3, 15))

    assert score.cost_keep == pytest.approx(150.0)
    assert score.best_alternative == "delay"
    assert score.regret == pytest.approx(45.0)
    assert score.switching_cost == pytest.approx(90.0)
    assert score.net_benefit < 0
    assert score.flagged is False
    assert score.recommendation == "keep"


def test_cancel_saves_money_when_fee_is_small(session: Session) -> None:
    """A large, eliminable exposure and a cheap cancellation fee must recommend cancel."""
    _decision(session, "DEC1", quantity=50, unit_price=20.0, po_date=date(2025, 3, 1))
    _decision(session, "DEC2", quantity=10, unit_price=5.0, item_id=None)
    _commitment(session, "DEC1", fee_pct=0.05, reversible_until=date(2025, 6, 1))
    commitment_2 = _commitment(session, "DEC2", fee_pct=0.05, reversible_until=date(2025, 6, 1))
    session.add(CommitmentLink(
        id="CL-DEC1-DEC2", from_commitment_id="COM-DEC1", to_commitment_id=commitment_2.id,
        link_type="freight_consolidation", savings_at_stake=50.0,
    ))
    condition = {"type": "stock_lt", "entity_ref": "item:SKU1", "value": 10}
    _assumption(session, "ASM1", "DEC1", condition)
    session.add(StockSnapshot(item_id="SKU1", date=date(2025, 3, 15), qty_on_hand=210))
    session.commit()

    connector = SyntheticERPConnector(session)
    decision = session.get(Decision, "DEC1")
    assumption = session.get(Assumption, "ASM1")
    score = score_decision(session, connector, decision, assumption, date(2025, 3, 15))

    assert score.cost_keep == pytest.approx(800.0)
    assert score.best_alternative == "cancel"
    assert score.switching_cost_breakdown == {
        "fee": pytest.approx(50.0), "in_transit": pytest.approx(150.0), "sibling_impact": pytest.approx(50.0),
    }
    assert score.switching_cost == pytest.approx(250.0)
    assert score.regret == pytest.approx(800.0)
    assert score.net_benefit == pytest.approx(550.0)
    assert score.flagged is True
    assert score.recommendation == "cancel"


def test_closed_window_suppresses_the_flag(session: Session) -> None:
    """A worthwhile switch must not be flagged once the reversal window has closed."""
    _decision(session, "DEC1", quantity=50, unit_price=20.0, po_date=date(2025, 3, 1))
    _commitment(session, "DEC1", fee_pct=0.05, reversible_until=date(2025, 3, 5))
    condition = {"type": "stock_lt", "entity_ref": "item:SKU1", "value": 10}
    _assumption(session, "ASM1", "DEC1", condition)
    session.add(StockSnapshot(item_id="SKU1", date=date(2025, 3, 15), qty_on_hand=210))
    session.commit()

    connector = SyntheticERPConnector(session)
    decision = session.get(Decision, "DEC1")
    assumption = session.get(Assumption, "ASM1")
    score = score_decision(session, connector, decision, assumption, date(2025, 3, 15))

    assert score.regret > score.switching_cost
    assert score.days_to_window == -10
    assert score.window_open is False
    assert score.flagged is False
    assert score.recommendation == "keep"


def test_confidence_downgrades_for_estimated_unconfirmed_and_credibility_flagged(session: Session) -> None:
    """Confidence steps from high to low as inputs become less trustworthy."""
    _decision(session, "DEC1", quantity=50, unit_price=20.0)
    _decision(session, "DEC2", quantity=50, unit_price=20.0)
    _decision(session, "DEC3", quantity=50, unit_price=20.0, item_id=None)
    for decision_id in ("DEC1", "DEC2", "DEC3"):
        _commitment(session, decision_id, fee_pct=0.1, reversible_until=date(2025, 6, 1))
    condition = {"type": "stock_lt", "entity_ref": "item:SKU1", "value": 10}
    _assumption(session, "ASM1", "DEC1", condition, source="structured", confirmed_by_user=True)
    _assumption(session, "ASM2", "DEC2", condition, source="structured", confirmed_by_user=False)
    _assumption(session, "ASM3", "DEC3", condition, source="llm", confirmed_by_user=False)
    session.add(StockSnapshot(item_id="SKU1", date=date(2025, 3, 15), qty_on_hand=210))
    session.commit()

    connector = SyntheticERPConnector(session)
    as_of = date(2025, 3, 15)

    high = score_decision(session, connector, session.get(Decision, "DEC1"), session.get(Assumption, "ASM1"), as_of)
    medium = score_decision(session, connector, session.get(Decision, "DEC2"), session.get(Assumption, "ASM2"), as_of)
    low = score_decision(session, connector, session.get(Decision, "DEC3"), session.get(Assumption, "ASM3"), as_of)

    assert high.confidence == "high"
    assert high.confidence_reasons == ()
    assert medium.confidence == "medium"
    assert len(medium.confidence_reasons) == 1
    assert low.confidence == "low"
    assert len(low.confidence_reasons) >= 2
    assert low.cost_keep_breakdown["estimated"] is True
