"""Tests for authenticated, idempotent live event ingestion."""

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models import Assumption, AssumptionViolation, Base, Decision

KEY = {"X-API-Key": "test-key"}


def _event(event_id: str, new_value: int, when: str = "2025-03-10T00:00:00Z", old_value: int | None = None) -> dict:
    body = {
        "id": event_id, "entity_type": "item", "entity_id": "SKU1", "field": "stock_qty",
        "new_value": new_value, "event_time": when,
    }
    if old_value is not None:
        body["old_value"] = old_value
    return body


@pytest.fixture
def factory(monkeypatch: pytest.MonkeyPatch) -> Iterator[sessionmaker[Session]]:
    monkeypatch.setenv("INGEST_API_KEY", "test-key")
    get_settings.cache_clear()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with session_factory() as session:
        session.add(Decision(
            id="DEC1", decision_type="purchase_order",
            created_at=datetime(2025, 3, 1, tzinfo=timezone.utc), structured_fields={},
            is_override=True, status="placed",
        ))
        session.add(Assumption(
            id="ASM1", decision_id="DEC1",
            condition={"type": "stock_lt", "entity_ref": "item:SKU1", "op": "<", "value": 10},
            source="structured", confirmed_by_user=True, status="live",
            created_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
        ))
        session.commit()

    def override() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override
    yield session_factory
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    engine.dispose()


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def test_requires_api_key(client: TestClient) -> None:
    assert client.post("/events", json=_event("E0", 5)).status_code == 401
    assert client.post("/events", json=_event("E0", 5), headers={"X-API-Key": "nope"}).status_code == 401


def test_disabled_without_configured_key(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INGEST_API_KEY", "")
    get_settings.cache_clear()
    assert client.post("/events", json=_event("E0", 5), headers=KEY).status_code == 503


def test_breaking_event_flags_decision_and_is_idempotent(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    holds = client.post("/events", json=_event("E1", 5, "2025-03-05T00:00:00Z"), headers=KEY).json()
    assert holds["violated_assumption_ids"] == []
    assert holds["assumptions_evaluated"] == 1

    broke = client.post("/events", json=_event("E2", 50, "2025-03-10T00:00:00Z"), headers=KEY).json()
    assert broke["violated_assumption_ids"] == ["ASM1"]
    assert broke["violated_decision_ids"] == ["DEC1"]

    again = client.post("/events", json=_event("E2", 50, "2025-03-10T00:00:00Z"), headers=KEY).json()
    assert again["duplicate"] is True
    assert again["violated_assumption_ids"] == []

    with factory() as session:
        assert session.get(Assumption, "ASM1").status == "violated"
        assert session.scalar(select(func.count()).select_from(AssumptionViolation)) == 1


def test_recovery_returns_assumption_to_live(client: TestClient, factory: sessionmaker[Session]) -> None:
    client.post("/events", json=_event("E1", 5, "2025-03-05T00:00:00Z"), headers=KEY)
    client.post("/events", json=_event("E2", 50, "2025-03-10T00:00:00Z"), headers=KEY)
    recovered = client.post("/events", json=_event("E3", 4, "2025-03-12T00:00:00Z"), headers=KEY).json()
    assert recovered["recovered_assumption_ids"] == ["ASM1"]
    with factory() as session:
        assert session.get(Assumption, "ASM1").status == "live"


def test_late_event_triggers_full_recheck(client: TestClient, factory: sessionmaker[Session]) -> None:
    client.post("/events", json=_event("E1", 5, "2025-03-05T00:00:00Z"), headers=KEY)
    client.post("/events", json=_event("E3", 4, "2025-03-12T00:00:00Z"), headers=KEY)
    late = client.post("/events", json=_event("E2", 50, "2025-03-10T00:00:00Z"), headers=KEY).json()
    assert late["full_recheck"] is True
    with factory() as session:
        # Final replayed state is E3 (stock 4), so the assumption holds again.
        assert session.get(Assumption, "ASM1").status == "live"


def test_batch_and_validation(client: TestClient) -> None:
    ok = client.post(
        "/events/batch", headers=KEY,
        json={"events": [_event("B1", 5, "2025-03-05T00:00:00Z"), _event("B2", 50, "2025-03-10T00:00:00Z"),
                         _event("B2", 50, "2025-03-10T00:00:00Z")]},
    ).json()
    assert ok["ingested"] == 2 and ok["duplicates"] == 1
    assert ok["decisions_flagged"] == ["DEC1"]

    bad = client.post("/events", headers=KEY, json={**_event("B3", 1), "entity_type": "warehouse"})
    assert bad.status_code == 422
