"""Integration tests for extraction proposal review endpoints."""

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Assumption, AssumptionProposal, Base, Decision
from app.services.conditions import ProposedCondition


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Provide the API with a shared SQLite session for each test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def test_db() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = test_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _create_decision(client: TestClient) -> None:
    """Insert a minimal decision that can own extraction proposals."""
    with next(app.dependency_overrides[get_db]()) as session:
        session.add(Decision(
            id="DEC1",
            decision_type="purchase_order",
            created_at=datetime(2025, 1, 10, tzinfo=timezone.utc),
            structured_fields={},
            free_text_reason="Stock is tight",
            is_override=True,
            status="placed",
        ))
        session.commit()


def test_extract_then_confirm_records_edits_and_rejections(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Persist original proposals, confirmed assumptions, and correction dispositions."""
    _create_decision(client)
    proposals = [
        ProposedCondition(
            type="stock_lt",
            entity_ref="item:SKU1",
            op="<",
            value=10,
            proposal_id="proposal-1",
            source="structured",
            confidence=0.9,
        ),
        ProposedCondition(
            type="lead_time_lte",
            entity_ref="supplier:SUP1",
            op="<=",
            value=4,
            proposal_id="proposal-2",
            source="llm",
            confidence=0.7,
        ),
    ]
    monkeypatch.setattr("app.api.routes.extract_assumptions", lambda decision, connector: proposals)

    extracted = client.post("/decisions/DEC1/extract")
    assert extracted.status_code == 200
    assert len(extracted.json()) == 2

    confirmed = client.post(
        "/decisions/DEC1/assumptions/confirm",
        json={
            "accepted": [{
                "proposal_id": "proposal-1",
                "condition": {
                    "type": "stock_lt",
                    "entity_ref": "item:SKU1",
                    "op": "<",
                    "value": 12,
                },
            }],
            "rejected_proposal_ids": ["proposal-2"],
        },
    )

    assert confirmed.status_code == 200
    assert confirmed.json()["accepted_count"] == 1
    assert confirmed.json()["edited_count"] == 1
    assert confirmed.json()["rejected_count"] == 1
    with next(app.dependency_overrides[get_db]()) as session:
        assumption = session.scalar(select(Assumption))
        assert assumption is not None
        assert assumption.confirmed_by_user is True
        assert assumption.condition["value"] == 12
        dispositions = dict(session.execute(select(
            AssumptionProposal.id, AssumptionProposal.review_status
        )).all())
        assert dispositions == {"proposal-1": "edited", "proposal-2": "rejected"}
        edited = session.get(AssumptionProposal, "proposal-1")
        rejected = session.get(AssumptionProposal, "proposal-2")
        assert edited is not None and rejected is not None
        assert edited.condition["value"] == 10
        assert edited.final_condition["value"] == 12
        assert rejected.condition["value"] == 4
        assert rejected.final_condition is None
        assert session.scalar(select(func.count()).select_from(AssumptionProposal)) == 2


def test_confirmation_rejects_duplicate_proposal_review(client: TestClient) -> None:
    """Reject a proposal identifier submitted as both accepted and rejected."""
    _create_decision(client)
    response = client.post(
        "/decisions/DEC1/assumptions/confirm",
        json={
            "accepted": [{
                "proposal_id": "same",
                "condition": {
                    "type": "stock_lt",
                    "entity_ref": "item:SKU1",
                    "op": "<",
                    "value": 2,
                },
            }],
            "rejected_proposal_ids": ["same"],
        },
    )

    assert response.status_code == 422