"""Abstract ERP access and an event-fed in-memory connector for demos/tests."""

from typing import Any, Protocol


class ERPConnector(Protocol):
    """Business logic reads current ERP values only through this interface."""

    def get_current_value(self, entity: str, field: str) -> Any | None:
        """Return a current ERP field value, or None when it is unavailable."""

    def ingest_event(self, entity: str, field: str, value: Any) -> None:
        """Update the connector's event-backed view of current ERP state."""


class InMemoryERPConnector:
    """Minimal connector implementation for local demos and isolated tests."""

    def __init__(self) -> None:
        """Create an empty entity/field state snapshot."""
        self._state: dict[tuple[str, str], Any] = {}

    def get_current_value(self, entity: str, field: str) -> Any | None:
        """Read one value from the connector's current state snapshot."""
        return self._state.get((entity, field))

    def ingest_event(self, entity: str, field: str, value: Any) -> None:
        """Apply an incoming ERP state-change event to the local snapshot."""
        self._state[(entity, field)] = value