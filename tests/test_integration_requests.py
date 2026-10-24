"""Tests for the enterprise ERP integration request endpoints."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import get_control_db
from app.main import app
from app.models import ControlBase

PAYLOAD = {
    "company_name": "Acme Industries", "contact_name": "Asha Rao", "contact_email": "asha@acme.example",
    "erp_system": "sap_s4hana", "deployment": "cloud", "integration_method": "rest_api",
    "monthly_po_volume": 1200, "consent": True,
}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("INGEST_API_KEY", "test-key")
    get_settings.cache_clear()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    ControlBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_control_db] = override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    engine.dispose()


def test_submit_stores_request_with_thirty_day_trial(client: TestClient) -> None:
    response = client.post("/integration-requests", json=PAYLOAD)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "new"
    assert body["trial_ends_at"][:10] > body["created_at"][:10]
    listing = client.get("/integration-requests", headers={"X-API-Key": "test-key"})
    assert [row["id"] for row in listing.json()] == [body["id"]]


def test_listing_requires_api_key(client: TestClient) -> None:
    client.post("/integration-requests", json=PAYLOAD)
    assert client.get("/integration-requests").status_code == 401


def test_rejects_missing_consent_bad_email_and_unknown_erp(client: TestClient) -> None:
    assert client.post("/integration-requests", json={**PAYLOAD, "consent": False}).status_code == 422
    assert client.post("/integration-requests", json={**PAYLOAD, "contact_email": "nope"}).status_code == 422
    assert client.post("/integration-requests", json={**PAYLOAD, "erp_system": "unknown"}).status_code == 422
