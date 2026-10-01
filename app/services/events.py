"""Canonical normalization of state-change events from connectors and files."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

DateLike = datetime | date

WorldKey = tuple[str, str]


@dataclass(frozen=True)
class StateEvent:
    """One state change: what changed, from what, to what, and when."""

    entity: str
    field: str
    old_value: Any = None
    new_value: Any = None
    event_id: str | None = None
    event_time: DateLike | None = None

    @property
    def key(self) -> WorldKey:
        """Return the entity/field pair this event touches."""
        return (self.entity, self.field)


def to_state_event(event: Any) -> StateEvent:
    """Normalize a mapping, DTO, or existing ``StateEvent`` into a ``StateEvent``.

    Connector DTOs split the entity into ``entity_type`` and ``entity_id``;
    dataset rows and mappings carry a combined ``entity`` such as
    ``item:SKU017``. Both shapes normalize to the same combined entity so the
    watcher index keys line up regardless of source.
    """
    if isinstance(event, StateEvent):
        return event

    model_dump = getattr(event, "model_dump", None)
    if callable(model_dump):
        values: Mapping[str, Any] = model_dump(mode="json")
    elif isinstance(event, Mapping):
        values = event
    else:
        raise TypeError(f"Unsupported event object: {event!r}")

    entity = values.get("entity") or _combined_entity(values)
    if not entity:
        raise ValueError(f"Event carries no entity: {dict(values)!r}")
    field = values.get("field")
    if not field:
        raise ValueError(f"Event carries no field: {dict(values)!r}")

    return StateEvent(
        entity=str(entity),
        field=str(field),
        old_value=values.get("old_value"),
        new_value=values.get("new_value"),
        event_id=_optional_str(values.get("id") or values.get("event_id")),
        event_time=values.get("event_time"),
    )


def _combined_entity(values: Mapping[str, Any]) -> str | None:
    """Rebuild a combined entity from separate entity_type/entity_id columns."""
    entity_type = values.get("entity_type")
    entity_id = values.get("entity_id")
    if entity_type and entity_id:
        return f"{entity_type}:{entity_id}"
    return entity_id or None


def _optional_str(value: Any) -> str | None:
    """Return a string identifier or None when the source value is absent."""
    return None if value is None else str(value)
