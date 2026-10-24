"""SAP Business One and NetSuite readers and the sync service, against mocked ERP HTTP APIs.

These prove the request shapes, paging, authentication signing, row mapping and that synced data
behaves exactly like imported data. They do not prove compatibility with a specific customer's
ERP version or custom fields; that needs a sandbox account.
"""

import base64
import hashlib
import hmac
import json
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db import get_engine, get_session_factory
from app.main import app
from app.models import Base, ControlBase, Decision, ImportMapping, Item, StateEvent, StockSnapshot, Supplier
from app.services.sync import sync_from_source
from app.sources import SourceError, get_source
from app.sources.netsuite import NetSuiteSource, oauth_header
from app.sources.sap_b1 import SapB1Source


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def settings(**overrides) -> Settings:
    base = dict(
        erp_source="sap_b1", sap_b1_url="https://sap.example:50000/b1s/v1", sap_b1_company_db="PROD",
        sap_b1_username="reader", sap_b1_password="pw", sap_b1_lead_time_field="U_LeadTimeDays",
        netsuite_account_id="1234567_SB1", netsuite_consumer_key="ck", netsuite_consumer_secret="cs",
        netsuite_token_id="tk", netsuite_token_secret="ts", default_lead_time_days=14,
    )
    return Settings(_env_file=None, **{**base, **overrides})


# --- SAP Business One ------------------------------------------------------------------------


class FakeSap:
    """Just enough of the Service Layer: login, paging, a $select the server may reject, logout."""

    def __init__(self, *, lead_time: int = 10, reject_select_on: str | None = None, fail_login: bool = False) -> None:
        self.lead_time = lead_time
        self.reject_select_on = reject_select_on
        self.fail_login = fail_login
        self.calls: list[tuple[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/b1s/v1/")
        query = parse_qs(request.url.query.decode())
        self.calls.append((request.method, path + ("?" + request.url.query.decode() if request.url.query else "")))
        if path == "Login":
            if self.fail_login:
                return httpx.Response(401, json={"error": {"code": -1, "message": {"value": "Invalid password"}}})
            body = json.loads(request.content)
            assert body == {"CompanyDB": "PROD", "UserName": "reader", "Password": "pw"}
            return httpx.Response(200, json={"SessionId": "abc"}, headers={"Set-Cookie": "B1SESSION=abc; Path=/"})
        assert request.headers.get("cookie", "").startswith("B1SESSION=abc"), "must send the session cookie"
        if path == "Logout":
            return httpx.Response(204)
        if path == "CompanyService_GetCompanyInfo":
            return httpx.Response(200, json={"CompanyName": "Acme Ltd"})
        if path == "BusinessPartners":
            skip = query.get("$skip", ["0"])[0]
            if skip == "0":
                assert query["$filter"] == ["CardType eq 'cSupplier'"]  # the next link carries its own paging options
                assert "U_LeadTimeDays" in query["$select"][0]
                return httpx.Response(200, json={
                    "value": [{"CardCode": "V1", "CardName": "Acme Steel", "Valid": "tYES", "Frozen": "tNO", "U_LeadTimeDays": self.lead_time}],
                    "odata.nextLink": "BusinessPartners?$filter=CardType eq 'cSupplier'&$select=CardCode,CardName,Valid,Frozen,U_LeadTimeDays&$skip=1",
                })
            return httpx.Response(200, json={"value": [
                {"CardCode": "V2", "CardName": "Beta Bolts", "Valid": "tYES", "Frozen": "tYES", "U_LeadTimeDays": None},
            ]})
        if path == "ItemGroups":
            return httpx.Response(200, json={"value": [{"Number": 100, "GroupName": "Fasteners"}]})
        if path == "Items":
            if "$select" in query and self.reject_select_on == "Items":
                return httpx.Response(400, json={"error": {"message": {"value": "Property 'AvgStdPrice' of 'Item' is invalid"}}})
            return httpx.Response(200, json={"value": [
                {"ItemCode": "SKU1", "ItemName": "Widget", "ItemsGroupCode": 100, "MainSupplier": "V1",
                 "AvgStdPrice": 12.5, "MinInventory": 20, "QuantityOnStock": 40},
                {"ItemCode": "SKU2", "ItemName": "No supplier", "ItemsGroupCode": 100, "MainSupplier": None,
                 "AvgStdPrice": 3.0, "QuantityOnStock": 5},
            ]})
        if path == "PurchaseOrders":
            return httpx.Response(200, json={"value": [{
                "DocNum": 1001, "CardCode": "V1", "DocDate": "2026-09-01", "DocDueDate": "2026-09-20",
                "DocumentStatus": "bost_Open", "Cancelled": "tNO", "Comments": "Rush: supplier promised 10 days",
                "DocumentLines": [{"LineNum": 0, "ItemCode": "SKU1", "Quantity": 100, "UnitPrice": 12.5, "ShipDate": "2026-09-18", "FreeText": None}],
            }, {
                "DocNum": 1002, "CardCode": "V1", "DocDate": "2026-09-02", "DocumentStatus": "bost_Open", "Cancelled": "tYES",
                "DocumentLines": [{"LineNum": 0, "ItemCode": "SKU1", "Quantity": 1, "UnitPrice": 1}],
            }]})
        return httpx.Response(404, json={"error": {"message": f"unexpected {path}"}})


def sap_source(fake: FakeSap) -> SapB1Source:
    return SapB1Source(settings(), transport=httpx.MockTransport(fake))


def test_sap_reads_and_maps_every_dataset() -> None:
    fake = FakeSap()
    with sap_source(fake) as source:
        suppliers = source.fetch("suppliers")
        items = source.fetch("items")
        stock = source.fetch("stock_levels")
        orders = source.fetch("purchase_orders")

    assert [(s["supplier_id"], s["quoted_lead_time_days"], s["strike_status"]) for s in suppliers] == [
        ("V1", 10, "clear"), ("V2", 14, "strike"),  # paged; missing UDF -> default; frozen -> strike
    ]
    assert items[0] == {
        "item_id": "SKU1", "name": "Widget", "category": "Fasteners", "unit_cost": 12.5,
        "primary_supplier_id": "V1", "min_order_qty": None, "reorder_point_qty": 20,
    }
    assert {r["item_id"]: r["qty_on_hand"] for r in stock} == {"SKU1": 40, "SKU2": 5}
    assert len(orders) == 1, "cancelled documents are skipped"
    assert orders[0]["po_id"] == "1001-0" and orders[0]["supplier_id"] == "V1" and orders[0]["quantity"] == 100
    assert orders[0]["expected_delivery"] == "2026-09-18" and orders[0]["free_text_reason"] == "Rush: supplier promised 10 days"
    # Logged in once, logged out at the end, and Items were fetched only once for items + stock.
    assert fake.calls[0] == ("POST", "Login") and fake.calls[-1] == ("POST", "Logout")
    assert sum(1 for _, p in fake.calls if p.startswith("Items")) == 1


def test_sap_retries_items_without_select_when_a_property_is_unknown() -> None:
    fake = FakeSap(reject_select_on="Items")
    with sap_source(fake) as source:
        assert len(source.fetch("items")) == 2
    item_calls = [p for _, p in fake.calls if p.startswith("Items")]
    assert "select" in item_calls[0].lower() and "select" not in item_calls[1].lower()


def test_sap_bad_login_and_missing_config_are_clear_errors() -> None:
    with pytest.raises(SourceError, match="rejected the login.*Invalid password"):
        with sap_source(FakeSap(fail_login=True)):
            pass
    with pytest.raises(SourceError, match="SAP_B1_URL"):
        SapB1Source(settings(sap_b1_url=""))


def test_sap_check_reports_the_company() -> None:
    with sap_source(FakeSap()) as source:
        assert "Acme Ltd" in source.check()


# --- NetSuite --------------------------------------------------------------------------------


def test_oauth_signature_matches_a_hand_built_base_string() -> None:
    url = "https://1234567-sb1.suitetalk.api.netsuite.com/services/rest/query/v1/suiteql?limit=1000&offset=0"
    header = oauth_header("POST", url, settings(), nonce="NONCE", timestamp="1700000000")

    normalized = (
        "limit=1000&oauth_consumer_key=ck&oauth_nonce=NONCE&oauth_signature_method=HMAC-SHA256"
        "&oauth_timestamp=1700000000&oauth_token=tk&oauth_version=1.0&offset=0"
    )
    base = "&".join([
        "POST",
        "https%3A%2F%2F1234567-sb1.suitetalk.api.netsuite.com%2Fservices%2Frest%2Fquery%2Fv1%2Fsuiteql",
        normalized.replace("&", "%26").replace("=", "%3D"),
    ])
    expected = base64.b64encode(hmac.new(b"cs&ts", base.encode(), hashlib.sha256).digest()).decode()

    assert header.startswith('OAuth realm="1234567_SB1", ')
    assert 'oauth_signature_method="HMAC-SHA256"' in header
    assert f'oauth_signature="{expected.replace("+", "%2B").replace("/", "%2F").replace("=", "%3D")}"' in header


class FakeNetSuite:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.host == "1234567-sb1.suitetalk.api.netsuite.com"
        assert request.headers["authorization"].startswith("OAuth realm=")
        assert request.headers["prefer"] == "transient"
        sql = json.loads(request.content)["q"]
        offset = int(parse_qs(request.url.query.decode())["offset"][0])
        link = [{"rel": "self", "href": "x"}]
        if "FROM vendor v" in sql:
            return httpx.Response(200, json={"hasMore": False, "items": [
                {"links": link, "supplier_id": "V1", "name": "Acme", "quoted_lead_time_days": 14, "strike_status": "clear"},
            ]})
        if "FROM item i" in sql:
            return httpx.Response(200, json={"hasMore": False, "items": [
                {"links": link, "item_id": "SKU1", "name": "Widget", "unit_cost": "12.5", "primary_supplier_id": "V1"},
            ]})
        if "FROM transaction t" in sql:
            assert "TO_DATE('" in sql and "{since}" not in sql
            if offset == 0:
                return httpx.Response(200, json={"hasMore": True, "items": [
                    {"po_id": "PO9-1", "item_id": "SKU1", "supplier_id": "V1", "quantity": "50", "unit_price": "12.5",
                     "po_date": "2026-09-01", "memo": None},
                ]})
            return httpx.Response(200, json={"hasMore": False, "items": [
                {"po_id": "PO9-2", "item_id": "SKU1", "supplier_id": "V1", "quantity": "5", "unit_price": "12.5", "po_date": "2026-09-02"},
            ]})
        if "FROM inventorybalance" in sql:
            return httpx.Response(200, json={"hasMore": False, "items": [{"item_id": "SKU1", "date": "2026-10-23", "qty_on_hand": "40"}]})
        if sql.strip().startswith("SELECT id FROM vendor"):
            return httpx.Response(200, json={"hasMore": True, "items": [{"id": "1"}]})
        return httpx.Response(400, json={"o:errorDetails": [{"detail": "Invalid or unsupported search"}]})


def netsuite_source(fake: FakeNetSuite, **overrides) -> NetSuiteSource:
    return NetSuiteSource(settings(erp_source="netsuite", **overrides), transport=httpx.MockTransport(fake))


def test_netsuite_runs_default_queries_and_pages() -> None:
    fake = FakeNetSuite()
    with netsuite_source(fake) as source:
        suppliers = source.fetch("suppliers")
        orders = source.fetch("purchase_orders")
        assert "1 vendor sampled" in source.check()

    assert suppliers == [{"supplier_id": "V1", "name": "Acme", "quoted_lead_time_days": 14, "strike_status": "clear"}]
    assert [o["po_id"] for o in orders] == ["PO9-1", "PO9-2"], "follows hasMore/offset"
    assert all("memo" not in o for o in orders), "null columns are dropped"
    offsets = [parse_qs(r.url.query.decode())["offset"][0] for r in fake.requests if "transaction" in json.loads(r.content)["q"]]
    assert offsets == ["0", "1000"]


def test_netsuite_query_can_be_overridden_and_errors_are_readable() -> None:
    fake = FakeNetSuite()
    with netsuite_source(fake, netsuite_query_suppliers="SELECT 1 AS supplier_id FROM nothing") as source:
        with pytest.raises(SourceError, match="Invalid or unsupported search"):
            source.fetch("suppliers")
    with pytest.raises(SourceError, match="NETSUITE_TOKEN_SECRET"):
        NetSuiteSource(settings(erp_source="netsuite", netsuite_token_secret=""))


def test_get_source_selects_by_configuration() -> None:
    assert get_source(settings(erp_source="")) is None
    assert isinstance(get_source(settings(erp_source="sap_b1")), SapB1Source)
    assert isinstance(get_source(settings(erp_source="NetSuite")), NetSuiteSource)
    with pytest.raises(SourceError, match="Unsupported"):
        get_source(settings(erp_source="oracle"))


# --- sync into the database ------------------------------------------------------------------


def test_sync_loads_data_like_an_import_and_records_changes(session: Session) -> None:
    with sap_source(FakeSap(lead_time=10)) as _:
        pass  # constructing/closing must not leave state behind
    summary = sync_from_source(session, sap_source(FakeSap(lead_time=10)))

    by_dataset = {d.dataset: d for d in summary.datasets}
    assert by_dataset["suppliers"].imported == 2
    assert by_dataset["items"].imported == 1 and by_dataset["items"].rejected == 1, "an item with no supplier is rejected, not guessed"
    assert by_dataset["purchase_orders"].imported == 1
    assert by_dataset["stock_levels"].imported == 1, "stock for the rejected item is skipped because the item is unknown"
    assert session.get(Decision, "1001-0").free_text_reason == "Rush: supplier promised 10 days"
    assert session.get(Item, "SKU1").category == "Fasteners"
    assert session.scalar(select(func.count()).select_from(StockSnapshot)) == 1
    assert session.get(ImportMapping, "suppliers") is None, "an ERP sync must not overwrite the user's saved CSV mapping"
    assert summary.change_events == 0, "the first sync has nothing to compare against"

    # The ERP now quotes a longer lead time: that is a state change that can break a decision's assumption.
    again = sync_from_source(session, sap_source(FakeSap(lead_time=25)))
    assert again.change_events == 1
    event = session.scalars(select(StateEvent).where(StateEvent.entity_id == "V1")).one()
    assert (event.field, event.new_value) == ("lead_time_days", 25)
    assert session.get(Supplier, "V1").quoted_lead_time_days == 25

    quiet = sync_from_source(session, sap_source(FakeSap(lead_time=25)))
    assert quiet.change_events == 0, "no change, no event"


def test_sync_endpoints_on_an_agent(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'agent.db'}")
    monkeypatch.setenv("AGENT_MODE", "true")
    monkeypatch.setenv("AGENT_TOKEN", "agent-secret")
    monkeypatch.delenv("ERP_SOURCE", raising=False)
    for cached in (get_settings, get_engine, get_session_factory):
        cached.cache_clear()
    Base.metadata.create_all(get_engine())
    ControlBase.metadata.create_all(get_engine())
    good = {"Authorization": "Bearer agent-secret"}
    try:
        with TestClient(app) as client:
            assert client.get("/sync/status").status_code == 401
            status = client.get("/sync/status", headers=good).json()
            assert status["configured"] is False and status["runs"] == []
            assert client.post("/sync", headers=good).status_code == 409

            monkeypatch.setenv("ERP_SOURCE", "sap_b1")
            monkeypatch.setenv("SAP_B1_URL", "https://sap.example:50000/b1s/v1")
            monkeypatch.setenv("SAP_B1_COMPANY_DB", "PROD")
            monkeypatch.setenv("SAP_B1_USERNAME", "reader")
            monkeypatch.setenv("SAP_B1_PASSWORD", "pw")
            monkeypatch.setenv("SAP_B1_LEAD_TIME_FIELD", "U_LeadTimeDays")
            get_settings.cache_clear()
            transport = httpx.MockTransport(FakeSap())
            real_init = SapB1Source.__init__
            monkeypatch.setattr(
                SapB1Source, "__init__", lambda self, s, transport_=transport: real_init(self, s, transport=transport_),
            )

            test = client.post("/sync/test", headers=good)
            assert test.status_code == 200 and "Acme Ltd" in test.json()["message"]
            run = client.post("/sync", headers=good)
            assert run.status_code == 200, run.text
            body = run.json()
            assert {d["dataset"]: d["imported"] for d in body["datasets"]}["suppliers"] == 2
            status = client.get("/sync/status", headers=good).json()
            assert status["configured"] and status["source"] == "sap_b1"
            assert {r["dataset"] for r in status["runs"]} >= {"suppliers", "items"}
            assert all(r["filename"] == "sync:sap_b1" for r in status["runs"])
    finally:
        get_engine().dispose()
        for cached in (get_settings, get_engine, get_session_factory):
            cached.cache_clear()


def test_hosted_accounts_cannot_trigger_a_sync(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'hosted.db'}")
    monkeypatch.delenv("AGENT_MODE", raising=False)
    for cached in (get_settings, get_engine, get_session_factory):
        cached.cache_clear()
    Base.metadata.create_all(get_engine())
    ControlBase.metadata.create_all(get_engine())
    try:
        with TestClient(app) as client:
            assert client.post("/sync").status_code == 403
            assert client.get("/sync/status").status_code == 403
    finally:
        get_engine().dispose()
        for cached in (get_settings, get_engine, get_session_factory):
            cached.cache_clear()
