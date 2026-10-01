"""Compatibility import for the former in-memory connector name."""

from app.connectors.synthetic import SyntheticERPConnector

InMemoryERPConnector = SyntheticERPConnector