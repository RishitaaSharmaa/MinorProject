"""Interface-complete SAP Business One Service Layer connector stub.

Implements the full `ERPConnector` contract so the application can be
pointed at `ERP_CONNECTOR=sap_b1` without any other code change once this
integration is built, but every method currently raises `NotImplementedError`.
Each method documents the SAP Business One Service Layer entity and table it
is intended to read or write, so implementing it later is a matter of
filling in the described OData call rather than rediscovering the mapping.
"""

from datetime import date, datetime

from app.connectors.base import AsOf, ERPConnector
from app.connectors.dto import DecisionDTO, StateEventDTO, SupplierTerms


class SAPB1Connector(ERPConnector):
    """Stub adapter documenting the intended SAP Business One field mapping."""

    def get_stock(self, item_id: str, as_of: AsOf = None) -> int:
        """Read on-hand quantity from `OITW` (Item Warehouse Info) for `item_id`.

        Service Layer: `ItemWarehouseInfoCollection` filtered by `ItemCode`,
        summed across warehouses, field `InStock`. `as_of` has no direct SAP
        equivalent (OITW reflects current state only); a point-in-time read
        would require a nightly inventory-audit report or a custom UDF log.
        """
        raise NotImplementedError("SAP B1 stock lookup is not yet implemented")

    def get_forecast(self, item_id: str, as_of: AsOf = None) -> float:
        """Read a demand forecast for `item_id`.

        SAP Business One has no native demand-forecast entity; this would
        read a custom user-defined field/table populated by the MRP wizard
        or an external forecasting job, keyed by `ItemCode` and period.
        """
        raise NotImplementedError("SAP B1 forecast lookup is not yet implemented")

    def get_supplier_terms(self, supplier_id: str, as_of: AsOf = None) -> SupplierTerms:
        """Read purchasing terms for `supplier_id` from `OCRD` (Business Partner Master).

        Service Layer: `BusinessPartners('{CardCode}')` for lead time and
        payment/price-list fields, cross-referenced with `ItemGroups`/
        `SpecialPrices` for MOQ and price-break tiers; strike/risk status
        would come from a custom UDF since SAP has no native field for it.
        """
        raise NotImplementedError("SAP B1 supplier terms lookup is not yet implemented")

    def get_supplier_actual_lead_times(self, supplier_id: str, as_of: AsOf = None) -> list[float]:
        """Compute historical lead times from `OPOR`/`POR1` (Purchase Order header/lines).

        Service Layer: `PurchaseOrders` filtered by `CardCode`, comparing
        `DocDate` on the header against `POR1.ShipDate`/goods-receipt date
        on each line for `supplier_id`'s completed orders.
        """
        raise NotImplementedError("SAP B1 lead-time history is not yet implemented")

    def list_decisions(
        self, since: date | datetime | None = None, only_overrides: bool = False
    ) -> list[DecisionDTO]:
        """List purchase decisions from `OPOR`/`POR1` (Purchase Order header/lines).

        Service Layer: `PurchaseOrders` filtered by `DocDate` >= `since`;
        `only_overrides` would filter on a custom UDF marking a manually
        adjusted quantity against the system-suggested reorder quantity.
        """
        raise NotImplementedError("SAP B1 decision listing is not yet implemented")

    def get_decision(self, decision_id: str) -> DecisionDTO:
        """Read one purchase decision from `OPOR`/`POR1` by document number.

        Service Layer: `PurchaseOrders('{DocEntry}')`, mapping `decision_id`
        to `DocEntry`/`DocNum`. Raises `LookupError` when the document does
        not exist, matching the connector contract.
        """
        raise NotImplementedError("SAP B1 decision lookup is not yet implemented")

    def list_state_events(self, since: date | datetime) -> list[StateEventDTO]:
        """List world-state changes since `since`.

        SAP Business One exposes no native change-event stream; this would
        poll `OITW`/`OCRD`/pricing tables on an interval and diff them
        against the last poll, or read SAP's change-log table (`AUD1`) where
        auditing is enabled, to synthesize entity/field/old/new events.
        """
        raise NotImplementedError("SAP B1 state-event listing is not yet implemented")

    def write_outcome(self, decision_id: str, action: str, result: str) -> None:
        """Record a planner's action and result against the source document.

        Would write to a custom UDF on the `OPOR` header (or a linked custom
        table keyed by `DocEntry`) so the recorded outcome stays visible
        alongside the purchase order inside SAP Business One itself.
        """
        raise NotImplementedError("SAP B1 outcome logging is not yet implemented")
