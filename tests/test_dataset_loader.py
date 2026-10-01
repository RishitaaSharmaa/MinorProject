"""Acceptance tests for CSV row loading and answer-key isolation."""

import csv
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models import Assumption, Base, Decision, Item
from scripts.load_dataset import GT_ASSUMPTIONS, GT_METADATA, GT_VIOLATIONS, load_dataset

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data_generator" / "output"


@pytest.fixture
def session() -> Iterator[Session]:
    """Create operational and GT tables in an isolated SQLite database."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    GT_METADATA.create_all(engine)
    with Session(engine, expire_on_commit=False) as database_session:
        yield database_session
    engine.dispose()


def _csv_count(name: str) -> int:
    """Count source data records excluding a CSV header."""
    with (DATA_DIR / name).open("r", encoding="utf-8-sig", newline="") as csv_file:
        return sum(1 for _ in csv.DictReader(csv_file))


def test_loader_counts_and_idempotence(session: Session) -> None:
    """Load expected operational counts and replace data cleanly on rerun."""
    counts = load_dataset(session, DATA_DIR)
    repeated_counts = load_dataset(session, DATA_DIR)

    assert counts == repeated_counts
    assert counts["items"] == _csv_count("items.csv")
    assert counts["decisions"] == _csv_count("decisions.csv")
    assert counts["supplier_delivery_history"] == _csv_count("supplier_delivery_history.csv")
    assert counts["sales_history"] == _csv_count("sales_history.csv")
    assert counts["assumptions"] == 0
    assert counts["gt_assumptions"] == _csv_count("assumptions.csv")
    assert counts["gt_assumption_violations"] == _csv_count("ground_truth_violations.csv")
    with (DATA_DIR / "commitments.csv").open("r", encoding="utf-8-sig", newline="") as csv_file:
        linked_rows = sum(1 for row in csv.DictReader(csv_file) if row.get("linked_commitment_id"))
    assert counts["commitment_links"] == linked_rows
    assert session.scalar(select(func.count()).select_from(Item)) == counts["items"]
    assert session.scalar(select(func.count()).select_from(Decision)) == counts["decisions"]
    assert session.scalar(select(func.count()).select_from(Assumption)) == 0
    assert session.scalar(select(func.count()).select_from(GT_ASSUMPTIONS)) > 0
    assert session.scalar(select(func.count()).select_from(GT_VIOLATIONS)) > 0
    override = session.scalar(select(Decision).where(Decision.is_override.is_(True)).limit(1))
    assert override is not None
    assert "true_assumptions" not in override.structured_fields


def test_gt_tables_are_not_referenced_under_app() -> None:
    """Keep answer-key table names and access code outside the application package."""
    app_root = ROOT / "app"
    references = [
        path.relative_to(app_root).as_posix()
        for path in app_root.rglob("*.py")
        if "gt_" in path.read_text(encoding="utf-8")
    ]

    assert references == []