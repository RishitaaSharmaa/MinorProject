"""Unit tests for CSV parsing, mapping suggestion and cell conversion in the importer."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.services import importer
from app.services.importer import DATASETS, ImportFailure, _convert, _number, parse_csv, suggest_mapping


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


@pytest.mark.parametrize("raw, expected", [
    ("1,234.50", 1234.5), ("₹ 1,20,000", 120000), ("1.234,56", 1234.56), ("12,5", 12.5),
    ("(12)", -12), ("16%", 0.16), ("INR 99", 99),
])
def test_number_formats(raw: str, expected: float) -> None:
    assert _number(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", ["abc", "12abc34", "1,2,3", ""])
def test_number_rejects_garbage(raw: str) -> None:
    with pytest.raises(ValueError):
        _number(raw)


def test_parse_csv_detects_delimiter_and_skips_blank_lines() -> None:
    headers, rows = parse_csv("﻿SKU;Name\nA;One\n\n;;\nB;Two\n")
    assert headers == ["SKU", "Name"]
    assert [(line, row["SKU"]) for line, row in rows] == [(2, "A"), (5, "B")]


@pytest.mark.parametrize("text", ["", "   \n", "a,,b\n1,2,3\n", "a,A\n1,2\n"])
def test_parse_csv_rejects_unusable_files(text: str) -> None:
    with pytest.raises(ImportFailure):
        parse_csv(text)


def test_suggest_mapping_uses_synonyms_and_never_reuses_a_column() -> None:
    mapping = suggest_mapping(DATASETS["purchase_orders"], ["PO Number", "Material", "Vendor", "Qty", "Net Price", "Created On"])
    assert mapping == {
        "po_id": "PO Number", "item_id": "Material", "supplier_id": "Vendor",
        "quantity": "Qty", "unit_price": "Net Price", "po_date": "Created On",
    }


def test_conversions() -> None:
    spec = DATASETS["purchase_orders"]
    assert _convert(spec.field("po_date"), "2025-03-01T10:00:00", None) == date(2025, 3, 1)
    assert _convert(spec.field("po_date"), "01-Mar-2025", "%d-%b-%Y") == date(2025, 3, 1)
    assert _convert(spec.field("po_date"), "03/04/2025", "%m/%d/%Y") == date(2025, 3, 4)
    with pytest.raises(ValueError, match="date format"):
        _convert(spec.field("po_date"), "03/04/2025", None)
    assert _convert(spec.field("quantity"), "1,000", None) == 1000
    with pytest.raises(ValueError, match="whole number"):
        _convert(spec.field("quantity"), "10.5", None)
    assert _convert(spec.field("cancellation_fee_pct"), "12", None) == pytest.approx(0.12)
    assert _convert(spec.field("is_override"), "Yes", None) is True
    assert _convert(DATASETS["state_events"].field("new_value"), "clear", None) == "clear"
    assert _convert(DATASETS["state_events"].field("new_value"), "4", None) == 4


def test_analyze_flags_duplicates_and_partial_cancellation_terms(session: Session) -> None:
    csv_text = "id,name,lead\nV1,A,5\nV1,B,6\nV2,C,x\n"
    analysis = importer.analyze(session, "suppliers", csv_text, {
        "supplier_id": "id", "name": "name", "quoted_lead_time_days": "lead",
    })
    assert len(analysis.rows) == 1
    assert {e.message for e in analysis.errors} == {"duplicate of row 2", "'x' is not a number"}


def test_analyze_rejects_unknown_dataset_mapping_and_oversized_event_files(session: Session) -> None:
    with pytest.raises(ImportFailure, match="Unknown dataset"):
        importer.analyze(session, "nope", "a\n1")
    with pytest.raises(ImportFailure, match="not in the file"):
        importer.analyze(session, "suppliers", "a\n1", {"name": "missing"})
    with pytest.raises(ImportFailure, match="Unknown field"):
        importer.analyze(session, "suppliers", "a\n1", {"bogus": "a"})
    big = "entity_type,entity_id,field,new_value\n" + "item,A,stock_qty,1\n" * (importer.MAX_EVENT_ROWS + 1)
    with pytest.raises(ImportFailure, match="Too many rows"):
        importer.analyze(session, "state_events", big)
