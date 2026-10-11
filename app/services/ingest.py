"""Idempotent live ingestion of state events with incremental assumption rechecks.

Unlike `recheck_assumptions`, which resets every assumption and replays all
history, ingestion persists one new event and evaluates only the assumptions
indexed on that event's entity/field. A late-arriving event (older than one
already stored for the same entity/field) cannot be applied incrementally
without risking a wrong transition, so it triggers a full replay instead.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Assumption, AssumptionViolation
from app.models.history import StateEvent as StateEventRow
from app.services.events import StateEvent as EventRecord
from app.services.watcher import AssumptionWatcher
from app.services.watcher_runner import recheck_assumptions

ENTITY_TYPES = frozenset({"item", "supplier"})


@dataclass(frozen=True)
class IngestResult:
    """Outcome of ingesting one event."""

    event_id: str
    duplicate: bool = False
    assumptions_evaluated: int = 0
    violated_assumption_ids: tuple[str, ...] = ()
    violated_decision_ids: tuple[str, ...] = ()
    recovered_assumption_ids: tuple[str, ...] = ()
    full_recheck: bool = False


def ingest_event(
    session: Session,
    *,
    entity_type: str,
    entity_id: str,
    field_name: str,
    new_value: Any,
    old_value: Any = None,
    event_time: datetime | None = None,
    event_id: str | None = None,
) -> IngestResult:
    """Persist one event (idempotent on `event_id`) and recheck what it touches."""
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"entity_type must be one of {sorted(ENTITY_TYPES)}, got {entity_type!r}")
    event_id = event_id or str(uuid4())
    if session.get(StateEventRow, event_id) is not None:
        return IngestResult(event_id=event_id, duplicate=True)

    when = _aware(event_time or datetime.now(timezone.utc))

    latest = session.scalar(
        select(StateEventRow)
        .where(
            StateEventRow.entity_type == entity_type,
            StateEventRow.entity_id == entity_id,
            StateEventRow.field == field_name,
        )
        .order_by(StateEventRow.event_time.desc(), StateEventRow.id.desc())
        .limit(1)
    )
    is_late = latest is not None and _aware(latest.event_time) > when
    if old_value is None and latest is not None and not is_late:
        old_value = latest.new_value

    session.add(StateEventRow(
        id=event_id, entity_type=entity_type, entity_id=entity_id, field=field_name,
        old_value=old_value, new_value=new_value, event_time=when,
    ))
    session.flush()

    if is_late:
        before = _violated_ids(session)
        recheck_assumptions(session, datetime.now(timezone.utc))
        after = _violated_ids(session)
        newly = after - before
        return IngestResult(
            event_id=event_id,
            violated_assumption_ids=tuple(sorted(newly)),
            violated_decision_ids=tuple(sorted(_decision_ids(session, newly))),
            recovered_assumption_ids=tuple(sorted(before - after)),
            full_recheck=True,
        )

    assumptions = list(session.scalars(select(Assumption).where(Assumption.status != "retired")))
    by_id = {assumption.id: assumption for assumption in assumptions}
    watcher = AssumptionWatcher()
    for assumption in assumptions:
        watcher.watch(
            assumption.id, assumption.decision_id, assumption.condition,
            created_at=assumption.created_at, status=assumption.status,
        )
    outcome = watcher.process_event(EventRecord(
        entity=f"{entity_type}:{entity_id}", field=field_name,
        old_value=old_value, new_value=new_value, event_id=event_id, event_time=when,
    ))

    for violation in outcome.violations:
        session.add(AssumptionViolation(
            assumption_id=violation.assumption_id, event_id=event_id, detected_at=when,
        ))
        by_id[violation.assumption_id].status = "violated"
    for assumption_id in outcome.recoveries:
        by_id[assumption_id].status = "live"
    session.commit()

    return IngestResult(
        event_id=event_id,
        assumptions_evaluated=outcome.evaluated,
        violated_assumption_ids=tuple(v.assumption_id for v in outcome.violations),
        violated_decision_ids=tuple(sorted({v.decision_id for v in outcome.violations})),
        recovered_assumption_ids=tuple(outcome.recoveries),
    )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _violated_ids(session: Session) -> set[str]:
    return set(session.scalars(select(Assumption.id).where(Assumption.status == "violated")))


def _decision_ids(session: Session, assumption_ids: set[str]) -> set[str]:
    if not assumption_ids:
        return set()
    return set(session.scalars(
        select(Assumption.decision_id).where(Assumption.id.in_(assumption_ids))
    ))
