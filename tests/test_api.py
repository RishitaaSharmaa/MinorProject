"""Integration tests for decision persistence and connector-driven rechecks."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from decisionwatch.api import create_app
from decisionwatch.database import get_session
from decisionwatch.erp import InMemoryERPConnector
from decisionwatch.models import Base


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Provide an API client backed by an isolated in-memory database."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def test_session() -> Iterator[Session]:
        with factory() as session:
            yield session

    application = create_app(InMemoryERPConnector())
    application.dependency_overrides[get_session] = test_session
    with TestClient(application) as test_client:
        yield test_client
    application.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_event_rechecks_conditions_and_regret_rule(client: TestClient) -> None:
    """Persist a decision and only flag it after a broken condition is costly."""
    created = client.post(
        "/decisions",
        json={
            "reason": "Keep the order while stock stays below ten units.",
            "estimated_regret": 120,
            "switching_cost": 25,
            "conditions": [
                {"entity": "item:SKU1", "field": "stock", "operator": "<", "expected_value": 10}
            ],
        },
    )
    assert created.status_code == 201

    still_valid = client.post(
        "/events/recheck", json={"entity": "item:SKU1", "field": "stock", "new_value": 8}
    )
    broken = client.post(
        "/events/recheck", json={"entity": "item:SKU1", "field": "stock", "new_value": 12}
    )

    assert still_valid.json()[0]["flagged"] is False
    assert broken.json()[0]["condition_state"] == "invalid"
    assert broken.json()[0]["flagged"] is True


def test_health_endpoint(client: TestClient) -> None:
    """Expose a liveness check that does not require an ERP call."""
    assert client.get("/health").json() == {"status": "ok"}


def test_dependencies_are_traversed_recursively(client: TestClient) -> None:
    """Return downstream dependencies through the recursive SQL query."""
    decision_ids = []
    for reason in ("first", "second", "third"):
        response = client.post(
            "/decisions",
            json={
                "reason": reason,
                "estimated_regret": 1,
                "switching_cost": 1,
                "conditions": [
                    {"entity": "item:SKU1", "field": "stock", "operator": "<", "expected_value": 10}
                ],
            },
        )
        decision_ids.append(response.json()["id"])

    for source, target in zip(decision_ids, decision_ids[1:]):
        assert client.post(
            f"/decisions/{source}/dependencies", json={"target_decision_id": target}
        ).status_code == 201

    response = client.get(f"/decisions/{decision_ids[0]}/dependencies")

    assert set(response.json()) == set(decision_ids[1:])