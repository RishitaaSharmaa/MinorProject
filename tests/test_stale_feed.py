"""Tests for the generated stale-ERP scenario and its detection end to end."""

import csv
from datetime import date
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base
from data_generator import config
from data_generator.stale_feed import (
    EVENT_TYPE,
    HEALTHY_FEEDS,
    SILENT_FEEDS,
    SYNC_CADENCE_DAYS,
    generate_stale_feed,
)
from scripts.load_dataset import GT_METADATA, load_dataset
from scripts.seed_review_workflow import seed_review_workflow
from app.services.staleness import find_stale_assumptions

DATA_DIR = Path(__file__).resolve().parents[1] / "data_generator" / "output"


def test_generation_is_deterministic_and_never_changes_a_value() -> None:
    entities = {f"item:SKU{n:03d}": 100 + n for n in range(1, 20)}

    first, scenario = generate_stale_feed(entities, first_event_id=1)
    second, _ = generate_stale_feed(entities, first_event_id=1)

    assert first == second
    assert all(event["old_value"] == event["new_value"] for event in first)
    assert all(event["event_type"] == EVENT_TYPE for event in first)
    assert [row["status"] for row in scenario].count("silent") == SILENT_FEEDS
    assert [row["status"] for row in scenario].count("healthy") == HEALTHY_FEEDS
    for row in scenario:
        if row["status"] == "silent":
            assert row["silent_days_at_end"] >= 6 * 7
        else:
            assert (config.END_DATE - date.fromisoformat(row["last_sync"])).days < SYNC_CADENCE_DAYS


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    GT_METADATA.create_all(engine)
    with Session(engine, expire_on_commit=False) as database_session:
        load_dataset(database_session, DATA_DIR)
        yield database_session
    engine.dispose()


def test_silent_feeds_are_detected_and_healthy_feeds_are_not(session: Session) -> None:
    with (DATA_DIR / "stale_feed_scenarios.csv").open(encoding="utf-8", newline="") as handle:
        scenario = list(csv.DictReader(handle))
    silent = {row["entity"] for row in scenario if row["status"] == "silent"}
    healthy = {row["entity"] for row in scenario if row["status"] == "healthy"}

    seed_review_workflow(session, as_of=config.END_DATE)
    stale = find_stale_assumptions(session, config.END_DATE, stale_after_days=14)

    flagged = {item.entity for item in stale if not item.never_updated and item.field == "stock_qty"}
    assert silent <= flagged  # real events on other fields may add genuine extras
    assert not healthy & {item.entity for item in stale if item.field == "stock_qty"}
