"""Tests for the ranked, deterministic morning brief."""

from collections.abc import Iterator
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.connectors.synthetic import SyntheticERPConnector
from app.models import Assumption, Base, Commitment, Decision, Item, StockSnapshot, Supplier
from app.services.brief import generate_brief

AS_OF = date(2025, 3, 15)


@pytest.fixture
def session() -> Iterator[Session]:
    """Provide an isolated SQLite session with a supplier and two catalog items."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    database = Session(engine, expire_on_commit=False)
    database.add(Supplier(
        id="SUP1", name="Supplier One", quoted_lead_time_days=5, lead_time_std_dev=1.0,
        reliability_score=0.9, price_break_tiers=[], strike_status="open",
    ))
    for item_id in ("SKU1", "SKU3"):
        database.add(Item(
            id=item_id, name=item_id, category="Test", unit_cost=20.0, holding_cost_pct=0.2,
            min_order_qty=4, primary_supplier_id="SUP1", avg_daily_demand=5, reorder_point_qty=10,
        ))
    database.commit()
    yield database
    database.close()
    engine.dispose()


def _decision(
    session: Session, decision_id: str, item_id: str | None, is_override: bool, fee_pct: float = 0.05,
) -> Decision:
    """Insert a purchase decision with a round, easy-to-hand-check order value."""
    decision = Decision(
        id=decision_id,
        decision_type="purchase_order",
        created_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
        structured_fields={},
        is_override=is_override,
        status="placed",
        item_id=item_id,
        supplier_id="SUP1",
        quantity=40,
        unit_price=25.0,
    )
    session.add(decision)
    session.add(Commitment(
        id=f"COM-{decision_id}", decision_id=decision_id,
        cancellation_fee_pct=fee_pct, reversible_until=date(2025, 6, 1),
    ))
    return decision


def _assumption(session: Session, decision_id: str, condition: dict) -> None:
    """Insert a violated assumption recorded against one decision."""
    session.add(Assumption(
        id=f"ASM-{decision_id}", decision_id=decision_id, condition=condition, source="structured",
        confirmed_by_user=True, status="violated", created_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
    ))


def test_brief_covers_all_three_demo_archetypes(session: Session) -> None:
    """A fixed-date brief surfaces both worthwhile flags and hides the one that isn't.

    Three archetypes: (1) an ordinary ERP-visible stock breach any MRP system,
    SAP included, would also flag; (2) a broken assumption behind a planner's
    override -- a supplier-risk judgment call raw SAP fields cannot see; and
    (3) a decision whose only broken assumption is real but too cheap to act
    on once the cancellation fee is priced in.
    """
    _decision(session, "DEC-SAP", item_id="SKU1", is_override=False)
    _assumption(session, "DEC-SAP", {"type": "stock_gt", "entity_ref": "item:SKU1", "value": 100})
    session.add(StockSnapshot(item_id="SKU1", date=AS_OF, qty_on_hand=10))

    _decision(session, "DEC-OVERRIDE", item_id="SKU1", is_override=True)
    _assumption(session, "DEC-OVERRIDE", {"type": "supplier_risk_open", "entity_ref": "supplier:SUP1", "value": "open"})

    _decision(session, "DEC-KEEP", item_id="SKU3", is_override=False, fee_pct=0.9)
    _assumption(session, "DEC-KEEP", {"type": "stock_gt", "entity_ref": "item:SKU3", "value": 50})
    session.add(StockSnapshot(item_id="SKU3", date=AS_OF, qty_on_hand=45))
    session.commit()

    connector = SyntheticERPConnector(session)
    brief = generate_brief(session, connector, AS_OF, limit=10)

    assert brief.as_of == AS_OF
    assert brief.reviewed_and_kept == 1

    flagged_ids = [card.score.decision_id for card in brief.cards]
    assert set(flagged_ids) == {"DEC-SAP", "DEC-OVERRIDE"}
    assert "DEC-KEEP" not in flagged_ids

    by_id = {card.score.decision_id: card.score for card in brief.cards}
    assert by_id["DEC-SAP"].recommendation == "cancel"
    assert by_id["DEC-OVERRIDE"].recommendation == "cancel"

    # Ranked by net benefit descending: the large, obvious SAP-visible breach
    # dwarfs the smaller, override-only supplier-risk exposure.
    assert flagged_ids == ["DEC-SAP", "DEC-OVERRIDE"]
    assert by_id["DEC-SAP"].net_benefit > by_id["DEC-OVERRIDE"].net_benefit > 0

    decisions = {decision.id: decision for decision in session.query(Decision).all()}
    assert decisions["DEC-SAP"].is_override is False
    assert decisions["DEC-OVERRIDE"].is_override is True


def test_explanations_are_generated_per_card_and_cached(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """With explain on, every card gets a grounded explanation; repeat calls reuse the cache."""
    from app.services import brief as brief_module

    brief_module._explanation_cache.clear()
    _decision(session, "DEC-A", item_id="SKU1", is_override=False)
    _assumption(session, "DEC-A", {"type": "stock_gt", "entity_ref": "item:SKU1", "value": 100})
    session.add(StockSnapshot(item_id="SKU1", date=AS_OF, qty_on_hand=10))
    session.commit()
    calls: list[str] = []

    def fake_complete(system: str, user: str, schema: type) -> object:
        calls.append(user)
        return schema.model_validate({"explanation": "Flagged because stock fell. Cancel is recommended."})

    monkeypatch.setattr("app.services.brief.complete_json", fake_complete)
    connector = SyntheticERPConnector(session)

    first = generate_brief(session, connector, AS_OF, explain=True)
    second = generate_brief(session, connector, AS_OF, explain=True)

    assert first.cards[0].explanation == "Flagged because stock fell. Cancel is recommended."
    assert second.cards[0].explanation == first.cards[0].explanation
    assert len(calls) == 1
