"""Configuration-driven ERP connector factory."""

from sqlalchemy.orm import Session

from app.config import get_settings
from app.connectors.base import ERPConnector
from app.connectors.sap_b1 import SAPB1Connector
from app.connectors.synthetic import SyntheticERPConnector


def get_connector(session: Session | None = None) -> ERPConnector:
    """Build the connector selected by `ERP_CONNECTOR` configuration."""
    provider = get_settings().erp_connector.lower()
    if provider == "sap_b1":
        return SAPB1Connector()
    if provider == "synthetic":
        if session is None:
            raise ValueError("A SQLAlchemy session is required for the synthetic connector")
        return SyntheticERPConnector(session)
    raise ValueError(f"Unsupported ERP connector: {provider}")