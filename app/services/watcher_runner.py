"""Bridge the in-memory AssumptionWatcher to the operational database.

``AssumptionWatcher`` (``app.services.watcher``) is a pure, DB-free engine:
by itself it never touches a confirmed ``Assumption`` row or a recorded
``StateEvent`` row. Without this module actually running it against the
database, a confirmed assumption's status never changes when a later event
breaks it, so ``/brief`` has nothing to surface no matter what happened in
the simulated world -- this closes that gap.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Assumption, AssumptionViolation
from app.models.history import StateEvent as StateEventRow
from app.services.events import StateEvent as EventRecord
from app.services.watcher import AssumptionWatcher, ViolationRecord


@dataclass(frozen=True)
class RecheckSummary:
    """Counts from one point-in-time recheck pass."""

    as_of: date
    events_processed: int
    assumptions_rechecked: int
    violations: int
    recoveries: int


def recheck_assumptions(session: Session, as_of: date | datetime) -> RecheckSummary:
    """Replay every state event up to `as_of` and persist the resulting statuses.

    Every non-retired assumption is reset to `live` and its prior
    ``AssumptionViolation`` history is cleared before replay, so the result
    is a deterministic point-in-time snapshot for `as_of` regardless of when
    this was last run or in what order -- not an incremental patch that
    could drift from a differently-ordered history.
    """
    assumptions = list(session.scalars(select(Assumption).where(Assumption.status != "retired")))
    assumption_ids = [assumption.id for assumption in assumptions]
    if assumption_ids:
        session.execute(delete(AssumptionViolation).where(AssumptionViolation.assumption_id.in_(assumption_ids)))
    for assumption in assumptions:
        assumption.status = "live"
    session.flush()

    violations_logged = 0

    def _on_violation(record: ViolationRecord) -> None:
        nonlocal violations_logged
        if record.event_id is None:
            return
        session.add(AssumptionViolation(
            assumption_id=record.assumption_id, event_id=record.event_id, detected_at=record.reported_at,
        ))
        violations_logged += 1

    watcher = AssumptionWatcher(on_violation=_on_violation)
    for assumption in assumptions:
        watcher.watch(
            assumption.id, assumption.decision_id, assumption.condition, created_at=assumption.created_at,
        )

    cutoff = _upper_bound(as_of)
    rows = session.scalars(
        select(StateEventRow)
        .where(StateEventRow.event_time <= cutoff)
        .order_by(StateEventRow.event_time.asc(), StateEventRow.id.asc())
    )
    events_processed = 0
    recoveries = 0
    for row in rows:
        events_processed += 1
        outcome = watcher.process_event(_to_event_record(row))
        recoveries += len(outcome.recoveries)

    for assumption in assumptions:
        final_status = watcher.status_of(assumption.id)
        if final_status is not None:
            assumption.status = final_status

    session.commit()
    return RecheckSummary(
        as_of=_as_date(as_of),
        events_processed=events_processed,
        assumptions_rechecked=len(assumptions),
        violations=violations_logged,
        recoveries=recoveries,
    )


def _to_event_record(row: StateEventRow) -> EventRecord:
    """Convert a recorded state-event row into the watcher's event shape."""
    return EventRecord(
        entity=f"{row.entity_type}:{row.entity_id}",
        field=row.field,
        old_value=row.old_value,
        new_value=row.new_value,
        event_id=row.id,
        event_time=row.event_time,
    )


def _upper_bound(value: date | datetime) -> datetime:
    """Normalize a simulated cutoff to an inclusive end-of-day UTC timestamp."""
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, time.max, tzinfo=timezone.utc)


def _as_date(value: date | datetime) -> date:
    """Normalize a simulated timestamp to its calendar date."""
    return value.date() if isinstance(value, datetime) else value
