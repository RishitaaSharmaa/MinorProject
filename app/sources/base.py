"""Read-only ERP data sources feeding the importer.

A source reads one ERP and returns rows named exactly like the importer's canonical dataset
fields (see `app.services.importer.DATASETS`). The sync service then pushes those rows through
the same validation, reference checks, upserts and violation detection as a CSV upload, so an
ERP sync and a file import can never disagree about what a row means.
"""

from abc import ABC, abstractmethod
from typing import Any

#: Datasets a source can supply. Derived change events are produced by the sync service itself.
SYNC_DATASETS = ("suppliers", "items", "purchase_orders", "stock_levels")

Row = dict[str, Any]


class SourceError(RuntimeError):
    """The ERP could not be read (bad credentials, unreachable, rejected query)."""


class ErpSource(ABC):
    """One ERP system, read with a read-only account."""

    name: str

    def __enter__(self) -> "ErpSource":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    @abstractmethod
    def check(self) -> str:
        """Prove the credentials work with the cheapest possible call; return a short description."""

    @abstractmethod
    def fetch(self, dataset: str) -> list[Row]:
        """Return every row of one dataset in canonical field names."""
