"""Detect assumptions whose watched ERP data has gone silent.

The watcher only reacts to events, so a feed that stops delivering updates for
an entity/field makes every assumption watching it look healthy ("live") when
it is really just unverified. This module reports those assumptions so a
planner can tell "still true" apart from "nobody has checked for a while".

An assumption is stale when the most recent state event for its watched
``(entity, field)`` pair -- or, if none exists, the assumption's own creation
time -- is older than the threshold as of the reference time.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Assumption
from app.models.history import StateEvent as StateEventRow
from app.services.evaluator import UnsupportedConditionError, normalize_condition

DEFAULT_STALE_AFTER_DAYS = 14


@dataclass(frozen=True)
class StaleAssumption:
    """One assumption whose watched ERP field has not been refreshed recently."""

    assumption_id: str
    decision_id: str
    entity: str
    field: str
    status: str
    last_event_time: datetime | None
    reference_time: datetime
    age_days: float
    never_updated: bool


def find_stale_assumptions(
    session: Session,
    as_of: date | datetime | None = None,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
) -> list[StaleAssumption]:
    """Return live assumptions whose watched field is older than the threshold.

    Results are ordered stalest first. Assumptions whose condition cannot be
    mapped to an entity/field are skipped: they are never evaluated, so there
    is no feed to be stale. Violated assumptions are left out: they are
    already surfaced, and a retired one is no longer watched.
    """
    now = _as_datetime(as_of)
    latest_by_key = _latest_event_times(session, now)

    stale: list[StaleAssumption] = []
    for assumption in session.scalars(select(Assumption).where(Assumption.status == "live")):
        try:
            condition = normalize_condition(assumption.condition)
        except UnsupportedConditionError:
            continue
        if not condition.entity or not condition.field:
            continue

        last_event = latest_by_key.get((condition.entity, condition.field))
        created_at = _aware(assumption.created_at)
        if created_at > now:
            continue  # assumption did not exist yet at the reference time
        reference = last_event or created_at
        age_days = (now - reference).total_seconds() / 86400
        if age_days < stale_after_days:
            continue
        stale.append(StaleAssumption(
            assumption_id=assumption.id,
            decision_id=assumption.decision_id,
            entity=condition.entity,
            field=condition.field,
            status=assumption.status,
            last_event_time=last_event,
            reference_time=reference,
            age_days=round(age_days, 1),
            never_updated=last_event is None,
        ))
    return sorted(stale, key=lambda item: item.age_days, reverse=True)


def _latest_event_times(session: Session, cutoff: datetime) -> dict[tuple[str, str], datetime]:
    """Map ``("type:id", field)`` to its newest event time at or before `cutoff`."""
    rows = session.execute(
        select(
            StateEventRow.entity_type,
            StateEventRow.entity_id,
            StateEventRow.field,
            func.max(StateEventRow.event_time),
        )
        .where(StateEventRow.event_time <= cutoff)
        .group_by(StateEventRow.entity_type, StateEventRow.entity_id, StateEventRow.field)
    )
    return {
        (f"{entity_type}:{entity_id}", field): _aware(latest)
        for entity_type, entity_id, field, latest in rows
    }


def _as_datetime(value: date | datetime | None) -> datetime:
    """Normalize the reference time to an aware datetime (end of day for dates)."""
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return _aware(value)
    return datetime.combine(value, time.max, tzinfo=timezone.utc)


def _aware(value: datetime) -> datetime:
    """Treat naive timestamps (e.g. from SQLite) as UTC."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
