"""Integration tests for the brief, decision detail, action, and metrics routes."""

from collections.abc import Iterator
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Assumption, Base, Commitment, Decision, Item, Outcome, StockSnapshot, Supplier

AS_OF = "2025-03-15"


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Provide the API with a shared SQLite session pre-loaded with one flagged decision."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def test_db() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = test_db
    with factory() as session:
        session.add(Supplier(
            id="SUP1", name="Supplier One", quoted_lead_time_days=5, lead_time_std_dev=1.0,
            reliability_score=0.9, price_break_tiers=[], strike_status="clear",
        ))
        session.add(Item(
            id="SKU1", name="Widget", category="Test", unit_cost=20.0, holding_cost_pct=0.2,
            min_order_qty=4, primary_supplier_id="SUP1", avg_daily_demand=5, reorder_point_qty=10,
        ))
        session.add(Decision(
            id="DEC1", decision_type="purchase_order",
            created_at=datetime(2025, 3, 1, tzinfo=timezone.utc), structured_fields={},
            is_override=False, status="placed", item_id="SKU1", supplier_id="SUP1",
            quantity=40, unit_price=25.0,
        ))
        session.add(Commitment(
            id="COM1", decision_id="DEC1", cancellation_fee_pct=0.05, reversible_until=date(2025, 6, 1),
        ))
        session.add(Assumption(
            id="ASM1", decision_id="DEC1", condition={"type": "stock_gt", "entity_ref": "item:SKU1", "value": 100},
            source="structured", confirmed_by_user=True, status="violated",
            created_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
        ))
        session.add(StockSnapshot(item_id="SKU1", date=date(2025, 3, 15), qty_on_hand=10))
        session.commit()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_brief_returns_the_flagged_decision(client: TestClient) -> None:
    """The brief endpoint ranks and returns the seeded flagged decision."""
    response = client.get("/brief", params={"as_of": AS_OF})

    assert response.status_code == 200
    body = response.json()
    assert body["as_of"] == AS_OF
    assert body["reviewed_and_kept"] == 0
    assert len(body["cards"]) == 1
    card = body["cards"][0]
    assert card["score"]["decision_id"] == "DEC1"
    assert card["score"]["flagged"] is True
    assert card["score"]["recommendation"] == "cancel"
    assert card["explanation"] is None


def test_decision_detail_includes_score_and_assumptions(client: TestClient) -> None:
    """Decision detail surfaces the recorded assumption and its current score."""
    response = client.get("/decisions/DEC1", params={"as_of": AS_OF})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "DEC1"
    assert len(body["assumptions"]) == 1
    assert body["assumptions"][0]["status"] == "violated"
    assert body["score"] is not None
    assert body["score"]["flagged"] is True


def test_decision_detail_404_for_unknown_decision(client: TestClient) -> None:
    """A decision that does not exist returns 404, not a scoring error."""
    response = client.get("/decisions/NOPE")

    assert response.status_code == 404


def test_action_route_logs_outcome_via_connector(client: TestClient) -> None:
    """Posting an action persists an outcome row with the planner's note."""
    response = client.post("/decisions/DEC1/action", json={"action": "cancel", "note": "Cancelled per buyer"})

    assert response.status_code == 200
    assert response.json() == {"decision_id": "DEC1", "action": "cancel", "note": "Cancelled per buyer"}
    with next(app.dependency_overrides[get_db]()) as session:
        outcome = session.scalar(select(Outcome).where(Outcome.decision_id == "DEC1"))
        assert outcome is not None
        assert outcome.actual_action == "cancel"
        assert outcome.actual_result == "Cancelled per buyer"


def test_metrics_route_reports_extraction_and_action_rates(client: TestClient) -> None:
    """Metrics respond with the expected shape even with a minimal dataset."""
    response = client.get("/metrics", params={"as_of": AS_OF})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"flags_per_week", "action_rate", "extraction_correction_rate"}
    assert body["action_rate"] == 0.0
    assert body["extraction_correction_rate"] == 0.0


def _fake_llm(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> list[str]:
    """Patch the suggestion LLM call, returning the list of prompts it received."""
    prompts: list[str] = []

    def fake_complete(system: str, user: str, schema: type) -> object:
        prompts.append(user)
        fields = {
            "action": "cancel",
            "headline": "Cancel this order now.",
            "rationale": "Stock is far below the level this order assumed, so keeping it costs more than cancelling.",
            "risks": ["The supplier may dispute the cancellation."],
            "next_steps": ["Notify the supplier before the window closes."],
        }
        fields.update(overrides)
        return schema.model_validate(fields)

    monkeypatch.setattr("app.services.suggestion.complete_json", fake_complete)
    return prompts


def test_suggestion_returns_llm_action_and_agreement(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A grounded LLM suggestion is returned and compared with the deterministic recommendation."""
    prompts = _fake_llm(monkeypatch)
    client.get("/decisions/DEC1", params={"as_of": AS_OF})

    response = client.post("/decisions/DEC1/suggestion", params={"as_of": AS_OF})

    assert response.status_code == 200
    body = response.json()
    assert body["suggested_action"] == "cancel"
    assert body["model_recommendation"] == "cancel"
    assert body["agrees_with_model"] is True
    assert body["risks"] and body["next_steps"]
    assert "total_cost" in prompts[0]


def test_suggestion_flags_disagreement_with_deterministic_model(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the LLM picks a different action, the response says so."""
    _fake_llm(monkeypatch, action="delay")

    body = client.post("/decisions/DEC1/suggestion", params={"as_of": AS_OF}).json()

    assert body["suggested_action"] == "delay"
    assert body["agrees_with_model"] is False


def test_suggestion_rejects_ungrounded_numbers(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A suggestion that states a figure absent from the breakdown is refused, not shown."""
    _fake_llm(monkeypatch, rationale="Cancelling saves about 987654 rupees.")

    response = client.post("/decisions/DEC1/suggestion", params={"as_of": AS_OF})

    assert response.status_code == 503


def test_suggestion_unavailable_when_llm_fails(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """An LLM outage surfaces as 503 rather than a 500."""
    def broken(system: str, user: str, schema: type) -> object:
        raise RuntimeError("GROQ_API_KEY is required for LLM requests")

    monkeypatch.setattr("app.services.suggestion.complete_json", broken)

    assert client.post("/decisions/DEC1/suggestion", params={"as_of": AS_OF}).status_code == 503


def test_suggestion_404_for_unknown_decision(client: TestClient) -> None:
    """An unknown decision returns 404."""
    assert client.post("/decisions/NOPE/suggestion").status_code == 404


def test_every_score_carries_deterministic_reasoning(client: TestClient) -> None:
    """Brief cards and decision detail always include reasoning, with no LLM involved."""
    card = client.get("/brief", params={"as_of": AS_OF}).json()["cards"][0]["score"]
    detail = client.get("/decisions/DEC1", params={"as_of": AS_OF}).json()["score"]

    for score in (card, detail):
        reasoning = " ".join(score["reasoning"])
        assert "no longer holds" in reasoning
        assert "Recommended action: cancel" in reasoning
        assert "Confidence is" in reasoning
