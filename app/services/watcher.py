"""Event-driven assumption watching with an entity/field index.

Recording thousands of assumptions and rechecking all of them for every state
event does not scale and is unnecessary: an event can only change the value of
one ``(entity, field)`` pair, so only assumptions recorded against that exact
pair can change outcome. The watcher keeps an index from ``(entity, field)`` to
the assumptions watching it and evaluates only that bucket.

Semantics:

* An assumption is registered with the status ``live``.
* On an event, every indexed assumption is evaluated twice: against the value
  the event reports as ``old_value`` and against the value it reports as
  ``new_value``. A condition that moved from ``holds`` to ``violated`` is a
  violation; a condition that moved from ``violated`` to ``holds`` has recovered
  and its status is reversed back to ``live``.
* A condition that cannot be judged on either side (``unknown``) changes no
  status and is reported as unevaluated data, never as a violation.
* Retired assumptions are removed from the index and never looked up again.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from app.services.evaluator import (
    NormalizedCondition,
    WorldState,
    evaluate_condition,
    normalize_condition,
)
from app.services.events import StateEvent, to_state_event

AssumptionStatus = Literal["live", "violated", "retired"]

WorldKey = tuple[str, str]


class _WorldView(Mapping):
    """A read-only world state with one entity/field value overridden.

    Overlaying avoids copying the whole world state for every event, which keeps
    per-event work proportional to the affected bucket rather than to the total
    number of tracked fields.
    """

    def __init__(self, base: Mapping[WorldKey, Any], key: WorldKey, value: Any) -> None:
        self._base = base
        self._key = key
        self._value = value

    def __getitem__(self, key: WorldKey) -> Any:
        if key == self._key:
            return self._value
        return self._base[key]

    def __contains__(self, key: object) -> bool:
        return key == self._key or key in self._base

    def __iter__(self):
        return iter({*self._base, self._key})

    def __len__(self) -> int:
        return len({*self._base, self._key})


@dataclass
class WatchedAssumption:
    """One recorded assumption under watch, with its current status."""

    assumption_id: str
    decision_id: str
    condition: NormalizedCondition
    created_at: datetime | date | None = None
    status: AssumptionStatus = "live"

    @property
    def key(self) -> WorldKey:
        """Return the entity/field pair this assumption watches."""
        return (self.condition.entity, self.condition.field)


@dataclass(frozen=True)
class ViolationRecord:
    """One recorded violation linking an assumption to the event that broke it."""

    assumption_id: str
    decision_id: str
    event_id: str | None
    reported_at: datetime | date | None
    entity: str
    field: str


@dataclass(frozen=True)
class EventProcessingResult:
    """Outcome of processing a single state event."""

    event_id: str | None
    evaluated: int
    violations: tuple[ViolationRecord, ...]
    recoveries: tuple[str, ...]
    unknown: tuple[str, ...]


class AssumptionWatcher:
    """Index recorded assumptions and recheck only those an event can affect."""

    def __init__(
        self,
        world_state: Mapping[WorldKey, Any] | None = None,
        on_violation: Callable[[ViolationRecord], None] | None = None,
    ) -> None:
        """Create a watcher, optionally seeded with known world state."""
        self._index: dict[WorldKey, list[str]] = {}
        self._assumptions: dict[str, WatchedAssumption] = {}
        self._world_state: dict[WorldKey, Any] = dict(world_state or {})
        self._violations: list[ViolationRecord] = []
        self._on_violation = on_violation
        self.evaluations = 0

    def watch(
        self,
        assumption_id: str,
        decision_id: str,
        condition: Mapping[str, Any],
        created_at: datetime | date | None = None,
        status: AssumptionStatus = "live",
    ) -> WatchedAssumption:
        """Normalize, index, and start watching one recorded assumption."""
        assumption = WatchedAssumption(
            assumption_id=assumption_id,
            decision_id=decision_id,
            condition=normalize_condition(condition),
            created_at=created_at,
            status=status,
        )
        self.register_assumption(assumption)
        return assumption

    def watch_many(self, assumptions: Iterable[WatchedAssumption]) -> None:
        """Register a batch of already-normalized assumptions."""
        for assumption in assumptions:
            self.register_assumption(assumption)

    def register_assumption(self, assumption: WatchedAssumption) -> None:
        """Add or replace one assumption in the index and the status registry."""
        existing = self._assumptions.get(assumption.assumption_id)
        if existing is not None:
            self._unindex(existing)
        self._assumptions[assumption.assumption_id] = assumption
        self._index.setdefault(assumption.key, []).append(assumption.assumption_id)

    def retire(self, assumption_id: str) -> None:
        """Stop watching an assumption and drop it from the index."""
        assumption = self._assumptions.get(assumption_id)
        if assumption is None:
            return
        self._unindex(assumption)
        assumption.status = "retired"

    def process_event(self, event: Any) -> EventProcessingResult:
        """Recheck the indexed assumptions affected by one state event."""
        state_event = to_state_event(event)
        candidates = tuple(self._index.get(state_event.key, ()))
        before = _WorldView(self._world_state, state_event.key, state_event.old_value)
        after = _WorldView(self._world_state, state_event.key, state_event.new_value)

        violations: list[ViolationRecord] = []
        recoveries: list[str] = []
        unknown: list[str] = []

        for assumption_id in candidates:
            assumption = self._assumptions[assumption_id]
            self.evaluations += 1
            before_outcome = evaluate_condition(assumption.condition, before)
            after_outcome = evaluate_condition(assumption.condition, after)

            if "unknown" in (before_outcome, after_outcome):
                unknown.append(assumption_id)
            elif before_outcome == "holds" and after_outcome == "violated":
                violations.append(self._record_violation(assumption, state_event))
            elif before_outcome == "violated" and after_outcome == "holds":
                if assumption.status == "violated":
                    assumption.status = "live"
                    recoveries.append(assumption_id)

        self._world_state[state_event.key] = state_event.new_value
        return EventProcessingResult(
            event_id=state_event.event_id,
            evaluated=len(candidates),
            violations=tuple(violations),
            recoveries=tuple(recoveries),
            unknown=tuple(unknown),
        )

    def status_of(self, assumption_id: str) -> AssumptionStatus | None:
        """Return the tracked status of one assumption, or None if unwatched."""
        assumption = self._assumptions.get(assumption_id)
        return None if assumption is None else assumption.status

    def watched_assumption(self, assumption_id: str) -> WatchedAssumption | None:
        """Return the watched assumption record for one identifier."""
        return self._assumptions.get(assumption_id)

    def indexed_keys(self) -> tuple[WorldKey, ...]:
        """Return the entity/field pairs currently present in the index."""
        return tuple(self._index)

    def active_assumption_ids(self) -> tuple[str, ...]:
        """Return the identifiers of every non-retired assumption."""
        return tuple(
            assumption_id
            for assumption_id, assumption in self._assumptions.items()
            if assumption.status != "retired"
        )

    def active_assumption_count(self) -> int:
        """Return how many non-retired assumptions a full recheck would visit."""
        return sum(1 for assumption in self._assumptions.values() if assumption.status != "retired")

    def violations(self) -> tuple[ViolationRecord, ...]:
        """Return every violation recorded so far, in detection order."""
        return tuple(self._violations)

    def _record_violation(
        self, assumption: WatchedAssumption, event: StateEvent
    ) -> ViolationRecord:
        """Mark an assumption violated and record the breaking event."""
        record = ViolationRecord(
            assumption_id=assumption.assumption_id,
            decision_id=assumption.decision_id,
            event_id=event.event_id,
            reported_at=event.event_time,
            entity=event.entity,
            field=event.field,
        )
        assumption.status = "violated"
        self._violations.append(record)
        if self._on_violation is not None:
            self._on_violation(record)
        return record

    def _unindex(self, assumption: WatchedAssumption) -> None:
        """Remove one assumption identifier from its entity/field bucket."""
        bucket = self._index.get(assumption.key)
        if bucket and assumption.assumption_id in bucket:
            bucket.remove(assumption.assumption_id)
        if bucket is not None and not bucket:
            del self._index[assumption.key]

    def world_state(self) -> dict[WorldKey, Any]:
        """Return a copy of the tracked world state."""
        return dict(self._world_state)
