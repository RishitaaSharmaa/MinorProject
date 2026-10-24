"""ERP data sources: read-only readers that feed the importer."""

from app.config import Settings, get_settings
from app.sources.base import SYNC_DATASETS, ErpSource, SourceError


def get_source(settings: Settings | None = None) -> ErpSource | None:
    """Build the ERP source selected by `ERP_SOURCE`, or None when only CSV/event input is used."""
    settings = settings or get_settings()
    name = settings.erp_source.strip().lower()
    if not name:
        return None
    if name == "sap_b1":
        from app.sources.sap_b1 import SapB1Source

        return SapB1Source(settings)
    if name == "netsuite":
        from app.sources.netsuite import NetSuiteSource

        return NetSuiteSource(settings)
    raise SourceError(f"Unsupported ERP_SOURCE {name!r}; use sap_b1 or netsuite")


__all__ = ["SYNC_DATASETS", "ErpSource", "SourceError", "get_source"]
