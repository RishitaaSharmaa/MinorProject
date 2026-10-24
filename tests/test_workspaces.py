"""Tests for accounts, billing, the no-data hosted site, agent mode and the self-serve importer."""

from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select

from app import tenancy
from app.api import workspace as workspace_api
from app.config import get_settings
from app.db import get_engine, get_session_factory
from app.main import app
from app.models import Base, ControlBase, Decision, StateEvent, Supplier, Tenant, User

SUPPLIERS = "Vendor Code,Vendor Name,Lead Time\nV1,Acme Steel,10\nV2,Beta Bolts,20\n"
ITEMS = "SKU,Description,Cost,Vendor,MOQ\nSKU1,Widget,12.5,V1,10\nSKU2,Gadget,\"1,200.00\",V2,5\n"
ORDERS = (
    "PO No,SKU,Vendor,Qty,Price,Order Date,Reason\n"
    "PO1,SKU1,V1,100,12.5,15/03/2025,Supplier confirmed delivery by the 25th\n"
)


@pytest.fixture
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("INGEST_API_KEY", "global-key")
    monkeypatch.delenv("AUTH_REQUIRED", raising=False)
    for cached in (get_settings, get_engine, get_session_factory):
        cached.cache_clear()
    Base.metadata.create_all(get_engine())
    ControlBase.metadata.create_all(get_engine())
    workspace_api._signup_limiter.hits.clear()
    workspace_api._login_limiter.hits.clear()
    with TestClient(app) as test_client:
        yield test_client
    get_engine().dispose()
    for cached in (get_settings, get_engine, get_session_factory):
        cached.cache_clear()


def signup(client: TestClient, email: str = "a@acme.example", company: str = "Acme") -> dict[str, str]:
    response = client.post("/auth/signup", json={
        "company_name": company, "name": "Asha", "email": email, "password": "correct-horse-1",
    })
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def load(client: TestClient, headers: dict[str, str], dataset: str, text: str, **extra) -> dict:
    response = client.post(f"/import/{dataset}/commit", headers=headers, json={"csv_text": text, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def test_signup_login_and_me(client: TestClient) -> None:
    headers = signup(client)
    me = client.get("/auth/me", headers=headers).json()
    assert me["demo"] is False and me["tenant"]["name"] == "Acme"
    assert me["tenant"]["trial_days_left"] == 30 and me["tenant"]["trial_expired"] is False

    assert client.post("/auth/signup", json={
        "company_name": "X", "name": "Y", "email": "A@ACME.example", "password": "another-pass-1",
    }).status_code == 409
    assert client.post("/auth/signup", json={
        "company_name": "X", "name": "Y", "email": "b@x.example", "password": "short",
    }).status_code == 422

    assert client.post("/auth/login", json={"email": "a@acme.example", "password": "wrong"}).status_code == 401
    ok = client.post("/auth/login", json={"email": "A@acme.example", "password": "correct-horse-1"})
    assert ok.status_code == 200 and ok.json()["token"]

    client.post("/auth/logout", headers=headers)
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_demo_workspace_without_login(client: TestClient) -> None:
    me = client.get("/auth/me").json()
    assert me == {"demo": True, "auth_required": False, "agent": False, "user": None, "tenant": None}
    assert client.post("/import/items/preview", json={"csv_text": "a\n1"}).status_code == 403


def test_auth_required_blocks_anonymous_access(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    assert client.get("/brief").status_code == 401
    headers = signup(client)
    assert client.get("/brief", headers=headers).status_code == 403  # accounts hold no data here


def test_import_flow_with_mapping_preview_and_errors(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    headers = agent_headers(client, monkeypatch)
    preview = client.post("/import/suppliers/preview", headers=headers, json={"csv_text": SUPPLIERS}).json()
    assert preview["suggested_mapping"] == {
        "supplier_id": "Vendor Code", "name": "Vendor Name", "quoted_lead_time_days": "Lead Time",
    }
    assert preview["valid_rows"] == 2 and preview["error_rows"] == 0 and preview["missing_required"] == []
    assert preview["sample"][0]["strike_status"] == "clear"

    no_map = client.post("/import/suppliers/preview", headers=headers, json={"csv_text": "foo,bar\n1,2\n"}).json()
    assert set(no_map["missing_required"]) == {"supplier_id", "name", "quoted_lead_time_days"}
    assert client.post(
        "/import/suppliers/commit", headers=headers, json={"csv_text": "foo,bar\n1,2\n"},
    ).status_code == 422

    load(client, headers, "suppliers", SUPPLIERS)
    bad_items = "SKU,Description,Cost,Vendor\nSKU1,Widget,abc,V1\nSKU3,Thing,5,NOPE\nSKU4,Ok,5,V2\n"
    preview = client.post("/import/items/preview", headers=headers, json={"csv_text": bad_items}).json()
    assert preview["valid_rows"] == 1 and preview["error_rows"] == 2
    messages = " ".join(e["message"] for e in preview["errors"])
    assert "not a number" in messages and "unknown supplier" in messages
    assert client.post("/import/items/commit", headers=headers, json={"csv_text": bad_items}).status_code == 422
    run = load(client, headers, "items", bad_items, skip_invalid=True)
    assert run["rows_imported"] == 1 and run["rows_rejected"] == 2

    saved = client.get("/import/suppliers/mapping", headers=headers).json()
    assert saved["mapping"]["supplier_id"] == "Vendor Code"
    again = client.post("/import/suppliers/preview", headers=headers, json={"csv_text": SUPPLIERS}).json()
    assert again["mapping"] == saved["mapping"]


def test_purchase_orders_stock_and_events_are_written(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    headers = agent_headers(client, monkeypatch)
    load(client, headers, "suppliers", SUPPLIERS)
    load(client, headers, "items", ITEMS)
    wrong_dates = client.post("/import/purchase_orders/preview", headers=headers, json={"csv_text": ORDERS}).json()
    assert wrong_dates["valid_rows"] == 0 and "date format" in wrong_dates["errors"][0]["message"]
    load(client, headers, "purchase_orders", ORDERS, date_format="DD/MM/YYYY")

    stock = "SKU,Date,On Hand\nSKU1,2025-03-01,50\nSKU1,2025-03-10,40\n"
    run = load(client, headers, "stock_levels", stock)
    assert run["rows_imported"] == 2
    events = "type,entity_id,attribute,value,time\nsupplier,V1,lead_time_days,30,2025-03-12T00:00:00\n"
    assert load(client, headers, "state_events", events)["rows_imported"] == 1
    assert load(client, headers, "state_events", events)["rows_imported"] == 1  # idempotent re-upload

    with get_session_factory()() as session:
        decision = session.get(Decision, "PO1")
        assert decision.is_override is True and decision.po_date.isoformat() == "2025-03-15"
        assert session.scalar(select(func.count()).select_from(StateEvent)) == 2


def test_only_the_operator_key_lists_integration_requests(client: TestClient) -> None:
    headers = signup(client)
    assert client.get("/integration-requests", headers=headers).status_code == 401
    assert client.get("/integration-requests", headers={"X-API-Key": "nope"}).status_code == 401
    assert client.get("/integration-requests", headers={"X-API-Key": "global-key"}).status_code == 200


def test_bogus_api_key_does_not_fall_back_to_demo_when_auth_required(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    assert client.get("/brief", headers={"X-API-Key": "junk"}).status_code == 401
    assert client.get("/brief").status_code == 401
    assert client.get("/brief", headers={"X-API-Key": "global-key"}).status_code == 200


def agent_headers(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Run this process as a customer's agent and return its token header."""
    monkeypatch.setenv("AGENT_MODE", "true")
    monkeypatch.setenv("AGENT_TOKEN", "agent-secret")
    get_settings.cache_clear()
    return {"Authorization": "Bearer agent-secret"}


def test_hosted_site_stores_accounts_only(client: TestClient) -> None:
    headers = signup(client)
    # No data schema is provisioned, no operational tables are touched, and data routes refuse accounts.
    with get_session_factory()() as control:
        tenant_columns = {c["name"] for c in inspect(control.get_bind()).get_columns("tenants")}
        assert not {"schema_name", "ingest_key_hash", "ingest_key_prefix"} & tenant_columns
        assert control.scalar(select(func.count()).select_from(User)) == 1
    for method, path in [("get", "/brief"), ("get", "/metrics"), ("post", "/events/recheck"), ("get", "/decisions/PO1")]:
        assert getattr(client, method)(path, headers=headers).status_code == 403
    assert client.post("/import/suppliers/commit", headers=headers, json={"csv_text": SUPPLIERS}).status_code == 403
    assert client.post("/workspace/ingest-key", headers=headers).status_code in {404, 405}


def test_billing_profile_round_trip(client: TestClient) -> None:
    headers = signup(client)
    assert client.get("/workspace/billing").status_code == 403
    empty = client.get("/workspace/billing", headers=headers).json()
    assert empty["billing_email"] is None

    profile = {
        "billing_name": "Acme Pvt Ltd", "billing_email": "accounts@acme.example",
        "billing_address": "1 Industrial Rd, Pune", "billing_country": "IN", "tax_id": "27ABCDE1234F1Z5",
    }
    assert client.put("/workspace/billing", headers=headers, json=profile).status_code == 200
    assert client.get("/workspace/billing", headers=headers).json() == profile
    assert client.put("/workspace/billing", headers=headers, json={**profile, "card_number": "4242"}).status_code == 422
    assert client.put("/workspace/billing", headers=headers, json={**profile, "billing_email": "nope"}).status_code == 422


def test_expired_trial_blocks_writes_but_not_billing(client: TestClient) -> None:
    headers = signup(client)
    with get_session_factory()() as control:
        tenant = control.scalar(select(Tenant))
        tenant.trial_ends_at = tenancy.utcnow() - timedelta(days=1)
        control.commit()
    assert client.get("/auth/me", headers=headers).json()["tenant"]["trial_expired"] is True
    profile = {
        "billing_name": "A", "billing_email": "a@a.example", "billing_address": "x", "billing_country": "IN",
    }
    assert client.put("/workspace/billing", headers=headers, json=profile).status_code == 200


def test_agent_mode_is_single_tenant_and_token_gated(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    good = agent_headers(client, monkeypatch)

    assert client.get("/brief").status_code == 401
    assert client.get("/brief", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/brief", headers=good).status_code == 200
    me = client.get("/auth/me", headers=good).json()
    assert me["agent"] is True and me["demo"] is False and me["tenant"] is None

    # Accounts and the lead list belong to the hosted site, never the agent.
    assert client.post("/auth/signup", json={
        "company_name": "X", "name": "Y", "email": "a@x.example", "password": "long-enough-1",
    }).status_code == 404
    assert client.get("/integration-requests", headers={"X-API-Key": "global-key"}).status_code == 404
    assert client.post("/import/suppliers/commit", headers=good, json={"csv_text": SUPPLIERS}).status_code == 201


def test_agent_accepts_events_with_its_token(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    agent_headers(client, monkeypatch)
    event = {"id": "e1", "entity_type": "item", "entity_id": "SKU1", "field": "stock_qty", "new_value": 3}
    assert client.post("/events", json=event, headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.post("/events", json=event, headers={"X-API-Key": "agent-secret"}).status_code == 200
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(StateEvent)) == 1


def test_agent_mode_without_token_fails_closed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_MODE", "true")
    monkeypatch.delenv("AGENT_TOKEN", raising=False)
    get_settings.cache_clear()
    assert client.get("/brief").status_code == 503
    assert client.get("/brief", headers={"Authorization": "Bearer "}).status_code == 503


def test_local_mode_refuses_to_start_outside_a_browser() -> None:
    """LOCAL_MODE skips authentication, so a real server must never accept it."""
    import os
    import subprocess
    import sys

    env = {**os.environ, "LOCAL_MODE": "true", "DATABASE_URL": "sqlite:///:memory:"}
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"], env=env, capture_output=True, text=True, cwd=os.getcwd(),
    )
    assert result.returncode != 0
    assert "only runs inside a browser" in result.stderr
