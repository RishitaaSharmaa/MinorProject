"""SAP Business One reader over the Service Layer (OData REST).

Read-only: it logs in, pages through `BusinessPartners`, `Items`, `ItemGroups` and
`PurchaseOrders`, and logs out. Use a dedicated SAP user with read authorisation only.

Mapping (entity -> importer dataset):
  BusinessPartners (CardType = supplier) -> suppliers      CardCode, CardName, Frozen/Valid
  Items + ItemGroups                     -> items          ItemCode, ItemName, MainSupplier, AvgStdPrice, MinInventory
  Items.QuantityOnStock                  -> stock_levels   total on hand across warehouses, dated today
  PurchaseOrders.DocumentLines           -> purchase_orders one decision per line, Comments/FreeText as the planner's note

SAP has no standard supplier lead-time or strike fields. Point `SAP_B1_LEAD_TIME_FIELD` and
`SAP_B1_STRIKE_FIELD` at your own user-defined fields (for example `U_LeadTimeDays`); otherwise
`DEFAULT_LEAD_TIME_DAYS` is used and a frozen or invalid business partner counts as a strike.
"""

import logging
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.config import Settings
from app.sources.base import ErpSource, Row, SourceError

logger = logging.getLogger(__name__)

_PAGE_SIZE = 500
_ITEM_SELECT = "ItemCode,ItemName,ItemsGroupCode,MainSupplier,AvgStdPrice,MinInventory,QuantityOnStock"


def _first(row: dict[str, Any], *names: str) -> Any:
    """First non-empty value among candidate field names (property names differ across B1 versions)."""
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def _day(value: Any) -> str | None:
    return str(value)[:10] if value else None


class SapB1Source(ErpSource):
    name = "sap_b1"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        if not (settings.sap_b1_url and settings.sap_b1_company_db and settings.sap_b1_username):
            raise SourceError("SAP Business One is not configured: set SAP_B1_URL, SAP_B1_COMPANY_DB and SAP_B1_USERNAME")
        self.settings = settings
        base = settings.sap_b1_url.rstrip("/") + "/"
        parts = urlsplit(base)
        self._origin = f"{parts.scheme}://{parts.netloc}"
        verify: bool | str = settings.sap_b1_ca_bundle or settings.sap_b1_verify_tls
        self.client = httpx.Client(base_url=base, verify=verify, timeout=60.0, transport=transport)
        self._logged_in = False
        self._items_cache: list[dict[str, Any]] | None = None

    # -- session -------------------------------------------------------------------------
    def __enter__(self) -> "SapB1Source":
        self._login()
        return self

    def __exit__(self, *_exc: object) -> None:
        try:
            if self._logged_in:
                self.client.post("Logout")
        except httpx.HTTPError:
            logger.debug("SAP logout failed", exc_info=True)
        finally:
            self._logged_in = False
            self.client.close()

    def _login(self) -> None:
        settings = self.settings
        try:
            response = self.client.post("Login", json={
                "CompanyDB": settings.sap_b1_company_db,
                "UserName": settings.sap_b1_username,
                "Password": settings.sap_b1_password.get_secret_value(),
            })
        except httpx.HTTPError as exc:
            raise SourceError(f"Could not reach SAP Business One at {self._origin}: {exc}") from exc
        if response.status_code in (400, 401, 403):
            raise SourceError(f"SAP Business One rejected the login ({response.status_code}): {_error_text(response)}")
        if response.status_code >= 400:
            raise SourceError(f"SAP Business One login failed ({response.status_code}): {_error_text(response)}")
        self._logged_in = True

    def check(self) -> str:
        if not self._logged_in:
            self._login()
        response = self._send("POST", "CompanyService_GetCompanyInfo", None, post=True)
        info = response.json() if response.status_code == 200 else {}
        return f"Connected to SAP Business One company {info.get('CompanyName') or self.settings.sap_b1_company_db}"

    # -- paging --------------------------------------------------------------------------
    def _send(self, method: str, target: str, params: dict[str, Any] | None, *, post: bool = False) -> httpx.Response:
        headers = {"Prefer": f"odata.maxpagesize={_PAGE_SIZE}"}
        for attempt in (1, 2):
            try:
                if post:
                    response = self.client.post(target, headers=headers)
                else:
                    response = self.client.request(method, target, params=params, headers=headers)
            except httpx.HTTPError as exc:
                raise SourceError(f"SAP Business One request failed: {exc}") from exc
            if response.status_code == 401 and attempt == 1:
                self._login()  # the Service Layer session times out after ~30 minutes
                continue
            return response
        return response

    def _pages(self, entity: str, params: dict[str, Any]) -> Iterator[dict[str, Any]]:
        target: str = entity
        query: dict[str, Any] | None = params
        while True:
            response = self._send("GET", target, query)
            if response.status_code >= 400:
                raise SourceError(f"SAP Business One {entity} query failed ({response.status_code}): {_error_text(response)}")
            data = response.json()
            yield from data.get("value", [])
            link = data.get("odata.nextLink") or data.get("@odata.nextLink")
            if not link:
                return
            target = f"{self._origin}{link}" if link.startswith("/") else link
            query = None  # the next link already carries the paging parameters

    def _all(self, entity: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            return list(self._pages(entity, params))
        except SourceError as exc:
            # A property name this B1 version does not know makes the whole $select fail; read it unfiltered.
            if "$select" in params and "(400)" in str(exc):
                logger.warning("SAP %s: $select rejected, retrying without it", entity)
                return list(self._pages(entity, {k: v for k, v in params.items() if k != "$select"}))
            raise

    # -- datasets ------------------------------------------------------------------------
    def fetch(self, dataset: str) -> list[Row]:
        handler = {
            "suppliers": self._suppliers, "items": self._items_rows,
            "purchase_orders": self._purchase_orders, "stock_levels": self._stock,
        }.get(dataset)
        if handler is None:
            raise SourceError(f"SAP Business One has no mapping for dataset {dataset!r}")
        return handler()

    def _suppliers(self) -> list[Row]:
        settings = self.settings
        extra = [f for f in (settings.sap_b1_lead_time_field, settings.sap_b1_strike_field) if f]
        select = ",".join(["CardCode", "CardName", "Valid", "Frozen", *extra])
        rows: list[Row] = []
        for bp in self._all("BusinessPartners", {"$filter": "CardType eq 'cSupplier'", "$select": select, "$orderby": "CardCode"}):
            lead = bp.get(settings.sap_b1_lead_time_field) if settings.sap_b1_lead_time_field else None
            try:
                lead_days = int(float(lead)) if lead not in (None, "") else settings.default_lead_time_days
            except (TypeError, ValueError):
                lead_days = settings.default_lead_time_days
            if settings.sap_b1_strike_field and bp.get(settings.sap_b1_strike_field):
                strike = str(bp[settings.sap_b1_strike_field])
            else:
                strike = "strike" if bp.get("Frozen") == "tYES" or bp.get("Valid") == "tNO" else "clear"
            rows.append({
                "supplier_id": bp["CardCode"], "name": bp.get("CardName") or bp["CardCode"],
                "quoted_lead_time_days": lead_days, "strike_status": strike,
            })
        return rows

    def _item_records(self) -> list[dict[str, Any]]:
        if self._items_cache is None:
            self._items_cache = self._all("Items", {"$select": _ITEM_SELECT, "$orderby": "ItemCode"})
        return self._items_cache

    def _groups(self) -> dict[Any, str]:
        try:
            return {g["Number"]: g.get("GroupName") for g in self._all("ItemGroups", {"$select": "Number,GroupName"})}
        except SourceError:
            return {}

    def _items_rows(self) -> list[Row]:
        groups = self._groups()
        rows: list[Row] = []
        for item in self._item_records():
            code = item.get("ItemCode")
            if not code:
                continue
            group = item.get("ItemsGroupCode")
            rows.append({
                "item_id": code, "name": item.get("ItemName") or code,
                "category": groups.get(group) or (str(group) if group is not None else None),
                "unit_cost": _first(item, "AvgStdPrice", "LastPurchasePrice"),
                "primary_supplier_id": _first(item, "MainSupplier", "Mainsupplier"),
                "min_order_qty": _first(item, "MinOrderQuantity", "MinOrdrQty"),
                "reorder_point_qty": _first(item, "MinInventory"),
            })
        return rows

    def _stock(self) -> list[Row]:
        today = datetime.now(timezone.utc).date().isoformat()
        return [
            {"item_id": item["ItemCode"], "date": today, "qty_on_hand": item.get("QuantityOnStock") or 0}
            for item in self._item_records() if item.get("ItemCode")
        ]

    def _purchase_orders(self) -> list[Row]:
        since = (date.today() - timedelta(days=self.settings.sync_lookback_days)).isoformat()
        rows: list[Row] = []
        for doc in self._all("PurchaseOrders", {"$filter": f"DocDate ge '{since}'", "$orderby": "DocEntry"}):
            if doc.get("Cancelled") == "tYES":
                continue  # a cancelled order is no longer a decision whose assumptions matter
            status = "placed" if doc.get("DocumentStatus") == "bost_Open" else "received"
            for line in doc.get("DocumentLines") or []:
                if not line.get("ItemCode"):
                    continue
                note = " | ".join(t.strip() for t in (doc.get("Comments"), line.get("FreeText")) if t and t.strip())
                rows.append({
                    "po_id": f"{doc.get('DocNum')}-{line.get('LineNum')}"[:64],
                    "item_id": line["ItemCode"], "supplier_id": doc.get("CardCode"),
                    "quantity": line.get("Quantity"), "unit_price": _first(line, "UnitPrice", "Price"),
                    "po_date": _day(doc.get("DocDate")),
                    "expected_delivery": _day(_first(line, "ShipDate") or doc.get("DocDueDate")),
                    "free_text_reason": note or None, "status": status,
                })
        return rows


def _error_text(response: httpx.Response) -> str:
    try:
        error = response.json().get("error", {})
        message = error.get("message")
        return (message.get("value") if isinstance(message, dict) else message) or response.text[:200]
    except (ValueError, AttributeError):
        return response.text[:200]
