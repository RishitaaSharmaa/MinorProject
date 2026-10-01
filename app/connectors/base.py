"""Abstract DTO-only ERP connector contract shared by all adapters."""

from abc import ABC, abstractmethod
from datetime import date, datetime

from app.connectors.dto import DecisionDTO, StateEventDTO, SupplierTerms

AsOf = date | datetime | None


class ERPConnector(ABC):
    """Stable application boundary implemented by all ERP adapters."""

    @abstractmethod
    def get_stock(self, item_id: str, as_of: AsOf = None) -> int:
        """Return latest known stock quantity at or before the simulated date."""

    @abstractmethod
    def get_forecast(self, item_id: str, as_of: AsOf = None) -> float:
        """Return the latest known forecast at or before the simulated date."""

    @abstractmethod
    def get_supplier_terms(self, supplier_id: str, as_of: AsOf = None) -> SupplierTerms:
        """Return supplier purchasing terms as a connector DTO."""

    @abstractmethod
    def get_supplier_actual_lead_times(self, supplier_id: str, as_of: AsOf = None) -> list[float]:
        """Return observed supplier lead times known at or before `as_of`."""

    @abstractmethod
    def list_decisions(
        self, since: date | datetime | None = None, only_overrides: bool = False
    ) -> list[DecisionDTO]:
        """List decisions created since an optional timestamp."""

    @abstractmethod
    def get_decision(self, decision_id: str) -> DecisionDTO:
        """Return one decision DTO or raise LookupError when it does not exist."""

    @abstractmethod
    def list_state_events(self, since: date | datetime) -> list[StateEventDTO]:
        """List state events at or after the supplied timestamp."""

    @abstractmethod
    def write_outcome(self, decision_id: str, action: str, result: str) -> None:
        """Record the observed action and result for a decision."""