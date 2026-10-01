"""Contract and simulated-clock tests for ERP connector implementations."""

from datetime import date, datetime, time, timezone
from inspect import isabstract
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.connectors.base import ERPConnector
from app.connectors.dto import DecisionDTO, SupplierTerms
from app.connectors.factory import get_connector
from app.connectors.sap_b1 import SAPB1Connector
from app.connectors.synthetic import SyntheticERPConnector
from app.models import (
    Base,
    Decision,
    Forecast,
    Item,
    StateEvent,
    StockSnapshot,
    Supplier,
    SupplierDelivery,
)


@pytest.fixture
def session() -> Session:
    """Create a populated SQLite session with adjacent simulated dates."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    database = Session(engine, expire_on_commit=False)
    database.add(Supplier(
        id="SUP1",
        name="Supplier",
        quoted_lead_time_days=5,
        lead_time_std_dev=1.0,
        reliability_score=0.9,
        price_break_tiers=[{"min_qty": 1, "discount_pct": 0}],
        strike_status="clear",
    ))
    database.add(Item(
        id="SKU1",
        name="Item",
        category="Test",
        unit_cost=12.5,
        holding_cost_pct=0.1,
        min_order_qty=4,
        primary_supplier_id="SUP1",
        avg_daily_demand=2,
        reorder_point_qty=10,
    ))
    database.add_all([
        StockSnapshot(item_id="SKU1", date=date(2025, 1, 10), qty_on_hand=10),
        StockSnapshot(item_id="SKU1", date=date(2025, 1, 11), qty_on_hand=99),
        Forecast(item_id="SKU1", week=date(2025, 1, 10), forecast_qty=3, true_demand=3, forecast_error_pct=0),
        Forecast(item_id="SKU1", week=date(2025, 1, 11), forecast_qty=12, true_demand=12, forecast_error_pct=0),
        StateEvent(
            id="EV1",
            entity_type="supplier",
            entity_id="SUP1",
            field="lead_time_days",
            old_value=5,
            new_value=14,
            event_time=datetime.combine(date(2025, 1, 11), time.min, tzinfo=timezone.utc),
        ),
    ])
    database.commit()
    yield database
    database.close()
    engine.dispose()


def test_synthetic_connector_honors_as_of_cutoff(session: Session) -> None:
    """Historical stock and forecast queries must exclude next-day rows."""
    connector = SyntheticERPConnector(session)

    assert connector.get_stock("SKU1", date(2025, 1, 10)) == 10
    assert connector.get_stock("SKU1", date(2025, 1, 11)) == 99
    assert connector.get_forecast("SKU1", date(2025, 1, 10)) == 3.0
    assert connector.get_forecast("SKU1", date(2025, 1, 11)) == 12.0
    assert connector.get_supplier_terms("SUP1", date(2025, 1, 10)).quoted_lead_time == 5.0
    assert connector.get_supplier_terms("SUP1", date(2025, 1, 11)).quoted_lead_time == 14.0


def test_connectors_fully_implement_abstract_contract(session: Session) -> None:
    """Both adapters implement every abstract method and return DTO types."""
    assert not isabstract(SyntheticERPConnector)
    assert not isabstract(SAPB1Connector)
    assert isinstance(SyntheticERPConnector(session).get_supplier_terms("SUP1"), SupplierTerms)

    decision = Decision(
        id="DEC1",
        decision_type="purchase_order",
        created_at=datetime(2025, 1, 10, tzinfo=timezone.utc),
        structured_fields={"order_qty": 2},
        is_override=False,
        status="placed",
    )
    session.add(decision)
    session.add(SupplierDelivery(
        decision_id="DEC1",
        supplier_id="SUP1",
        promised_delivery_date=date(2025, 1, 14),
        actual_delivery_date=date(2025, 1, 15),
        delay_days=1,
        arrived_late=True,
    ))
    session.commit()
    connector = SyntheticERPConnector(session)
    assert isinstance(connector.get_decision("DEC1"), DecisionDTO)
    assert len(connector.list_decisions()) == 1
    assert connector.get_supplier_actual_lead_times("SUP1") == [5.0]
    assert connector.get_supplier_actual_lead_times("SUP1", date(2025, 1, 14)) == []
    assert connector.get_supplier_actual_lead_times("SUP1", date(2025, 1, 15)) == [5.0]
    assert len(connector.list_state_events(date(2025, 1, 11))) == 1
    connector.write_outcome("DEC1", "keep", "on_time")


def test_sap_stub_methods_are_explicitly_unimplemented() -> None:
    """The SAP adapter satisfies the interface while clearly remaining a stub."""
    connector = SAPB1Connector()
    method_calls = [
        lambda: connector.get_stock("SKU1"),
        lambda: connector.get_forecast("SKU1"),
        lambda: connector.get_supplier_terms("SUP1"),
        lambda: connector.get_supplier_actual_lead_times("SUP1"),
        lambda: connector.list_decisions(),
        lambda: connector.get_decision("DEC1"),
        lambda: connector.list_state_events(date(2025, 1, 1)),
        lambda: connector.write_outcome("DEC1", "keep", "ok"),
    ]
    for call in method_calls:
        with pytest.raises(NotImplementedError):
            call()


def test_factory_selects_adapter_from_settings(monkeypatch: pytest.MonkeyPatch, session: Session) -> None:
    """Choose the configured connector without exposing model instances."""
    monkeypatch.setattr("app.connectors.factory.get_settings", lambda: SimpleNamespace(erp_connector="sap_b1"))
    assert isinstance(get_connector(), SAPB1Connector)

    monkeypatch.setattr("app.connectors.factory.get_settings", lambda: SimpleNamespace(erp_connector="synthetic"))
    assert isinstance(get_connector(session), SyntheticERPConnector)