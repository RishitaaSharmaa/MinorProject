"""Tests for detecting assumptions whose watched ERP data has gone silent."""

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Assumption, Base, Decision
from app.models.history import StateEvent
from app.services.staleness import find_stale_assumptions

CREATED = datetime(2025, 3, 1, tzinfo=timezone.utc)
NOW = datetime(2025, 4, 1, tzinfo=timezone.utc)


def _assumption(assumption_id: str, entity: str, condition_type: str = "stock_lt", status: str = "live") -> Assumption:
    return Assumption(
        id=assumption_id, decision_id="DEC1",
        condition={"type": condition_type, "entity_ref": entity, "op": "<", "value": 10},
        source="structured", confirmed_by_user=True, status=status, created_at=CREATED,
    )


@pytest.fixture
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        session.add(Decision(
            id="DEC1", decision_type="purchase_order", created_at=CREATED,
            structured_fields={}, is_override=True, status="placed",
        ))
        session.commit()
    yield factory
    engine.dispose()


def test_flags_silent_field_and_ignores_fresh_and_retired(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        session.add_all([
            _assumption("STALE", "item:SKU1"),
            _assumption("FRESH", "item:SKU2"),
            _assumption("NEVER", "item:SKU3"),
            _assumption("GONE", "item:SKU4", status="retired"),
        ])
        session.flush()
        session.add_all([
            StateEvent(id="E1", entity_type="item", entity_id="SKU1", field="stock_qty",
                       new_value=5, event_time=datetime(2025, 3, 5, tzinfo=timezone.utc)),
            StateEvent(id="E2", entity_type="item", entity_id="SKU2", field="stock_qty",
                       new_value=5, event_time=datetime(2025, 3, 30, tzinfo=timezone.utc)),
        ])
        session.commit()

        stale = find_stale_assumptions(session, NOW, stale_after_days=14)

    by_id = {item.assumption_id: item for item in stale}
    assert set(by_id) == {"STALE", "NEVER"}
    assert by_id["NEVER"].never_updated is True
    assert by_id["STALE"].never_updated is False
    assert by_id["STALE"].age_days == pytest.approx(26, abs=1)
    assert stale[0].assumption_id == "NEVER"  # stalest first


def test_other_field_updates_do_not_refresh_assumption(session_factory: sessionmaker[Session]) -> None:
    """A fresh forecast event must not make a stock assumption look verified."""
    with session_factory() as session:
        session.add(_assumption("A", "item:SKU1"))
        session.flush()
        session.add(StateEvent(
            id="E1", entity_type="item", entity_id="SKU1", field="forecast_qty",
            new_value=90, event_time=datetime(2025, 3, 31, tzinfo=timezone.utc),
        ))
        session.commit()

        assert [s.assumption_id for s in find_stale_assumptions(session, NOW, 14)] == ["A"]


def test_staleness_endpoint(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        session.add_all([_assumption("A", "item:SKU1"), _assumption("B", "item:SKU2")])
        session.flush()
        session.add(StateEvent(
            id="E1", entity_type="item", entity_id="SKU2", field="stock_qty",
            new_value=5, event_time=datetime(2025, 3, 2, tzinfo=timezone.utc),
        ))
        session.commit()

    def override() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            body = client.get("/staleness", params={"as_of": "2025-04-01", "stale_after_days": 7}).json()
            fresh = client.get("/staleness", params={"as_of": "2025-04-01", "stale_after_days": 60}).json()
    finally:
        app.dependency_overrides.clear()

    assert body["stale_count"] == 1
    assert body["decisions_affected"] == ["DEC1"]
    assert body["stale"][0]["assumption_id"] == "B"
    assert body["never_reported_count"] == 1
    assert body["never_reported"][0]["never_updated"] is True
    assert fresh["never_reported_count"] == 0
