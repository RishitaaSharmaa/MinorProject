"""Tests for persisting AssumptionWatcher detections against the database."""

from collections.abc import Iterator
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models import Assumption, AssumptionViolation, Base, Decision, StateEvent
from app.services.watcher_runner import recheck_assumptions


@pytest.fixture
def session() -> Iterator[Session]:
    """Provide an isolated SQLite session with one confirmed assumption."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    database = Session(engine, expire_on_commit=False)
    database.add(Decision(
        id="DEC1", decision_type="purchase_order",
        created_at=datetime(2025, 3, 1, tzinfo=timezone.utc), structured_fields={},
        is_override=True, status="placed",
    ))
    database.add(Assumption(
        id="ASM1", decision_id="DEC1",
        condition={"type": "supplier_risk_resolved", "entity_ref": "supplier:SUP1", "value": "resolved"},
        source="structured", confirmed_by_user=True, status="live",
        created_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
    ))
    database.add(StateEvent(
        id="EVT1", entity_type="supplier", entity_id="SUP1", field="strike_status",
        old_value="resolved", new_value="open",
        event_time=datetime(2025, 3, 10, tzinfo=timezone.utc),
    ))
    database.commit()
    yield database
    database.close()
    engine.dispose()


def test_recheck_flags_an_assumption_broken_by_a_later_event(session: Session) -> None:
    """A confirmed assumption becomes violated once its breaking event is replayed."""
    summary = recheck_assumptions(session, date(2025, 3, 15))

    assert summary.events_processed == 1
    assert summary.violations == 1
    session.expire_all()
    assumption = session.get(Assumption, "ASM1")
    assert assumption.status == "violated"
    violation = session.scalar(select(AssumptionViolation).where(AssumptionViolation.assumption_id == "ASM1"))
    assert violation is not None
    assert violation.event_id == "EVT1"


def test_recheck_before_the_breaking_event_leaves_the_assumption_live(session: Session) -> None:
    """A point-in-time recheck before the event must not see it yet."""
    summary = recheck_assumptions(session, date(2025, 3, 5))

    assert summary.events_processed == 0
    assert summary.violations == 0
    session.expire_all()
    assert session.get(Assumption, "ASM1").status == "live"


def test_recheck_is_idempotent_and_time_travels_correctly(session: Session) -> None:
    """Rechecking at an earlier date after a later one must un-flag and not duplicate rows."""
    recheck_assumptions(session, date(2025, 3, 15))
    session.expire_all()
    assert session.get(Assumption, "ASM1").status == "violated"

    recheck_assumptions(session, date(2025, 3, 5))
    session.expire_all()
    assert session.get(Assumption, "ASM1").status == "live"
    assert session.scalar(select(func.count()).select_from(AssumptionViolation)) == 0

    recheck_assumptions(session, date(2025, 3, 15))
    recheck_assumptions(session, date(2025, 3, 15))
    session.expire_all()
    assert session.get(Assumption, "ASM1").status == "violated"
    assert session.scalar(select(func.count()).select_from(AssumptionViolation)) == 1
