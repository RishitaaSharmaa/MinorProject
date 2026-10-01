"""Read generator CSVs into the typed inputs a replay run needs.

The replay harness is deliberately offline: it reads the same CSV files the
dataset loader writes so a replay can be run and scored without a database,
while still reproducing the exact order and timestamps the loader would use.
"""

import csv
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

from app.services.events import StateEvent

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data_generator" / "output"


@dataclass(frozen=True)
class RecordedAssumption:
    """One assumption recorded against a decision, with its recording time."""

    assumption_id: str
    decision_id: str
    condition: dict[str, Any]
    recorded_at: datetime


@dataclass(frozen=True)
class GroundTruthViolation:
    """One answer-key violation: this event broke this condition for this decision."""

    event_id: str
    decision_id: str
    event_date: date


def read_csv_rows(data_dir: Path, filename: str) -> list[dict[str, str]]:
    """Read one generator CSV as dictionaries, preserving source headers."""
    with (data_dir / filename).open("r", encoding="utf-8-sig", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def load_decision_dates(data_dir: Path = DEFAULT_DATA_DIR) -> dict[str, datetime]:
    """Map every decision identifier to its creation timestamp."""
    return {
        row["id"]: timestamp(date.fromisoformat(row["created_at"]))
        for row in read_csv_rows(data_dir, "decisions.csv")
    }


def load_recorded_assumptions(
    data_dir: Path = DEFAULT_DATA_DIR,
    decision_dates: dict[str, datetime] | None = None,
) -> list[RecordedAssumption]:
    """Load recorded assumptions, ordered by when their decision was made."""
    dates = decision_dates if decision_dates is not None else load_decision_dates(data_dir)
    assumptions: list[RecordedAssumption] = []
    for row in read_csv_rows(data_dir, "assumptions.csv"):
        condition = decode_json(row["condition"])
        if not isinstance(condition, dict):
            continue
        recorded_at = dates.get(row["decision_id"])
        if recorded_at is None:
            continue
        assumptions.append(
            RecordedAssumption(
                assumption_id=row["id"],
                decision_id=row["decision_id"],
                condition=condition,
                recorded_at=recorded_at,
            )
        )
    assumptions.sort(key=lambda item: (item.recorded_at, item.assumption_id))
    return assumptions


def load_state_events(data_dir: Path = DEFAULT_DATA_DIR) -> list[StateEvent]:
    """Load state events in the time order a replay must process them."""
    events = [
        StateEvent(
            entity=row["entity"],
            field=row["field"],
            old_value=decode_json(row["old_value"]),
            new_value=decode_json(row["new_value"]),
            event_id=row["id"],
            event_time=timestamp(date.fromisoformat(row["event_time"])),
        )
        for row in read_csv_rows(data_dir, "state_events.csv")
    ]
    events.sort(key=lambda event: (event.event_time, event.event_id or ""))
    return events


def load_ground_truth(data_dir: Path = DEFAULT_DATA_DIR) -> list[GroundTruthViolation]:
    """Load the answer-key violations the replay is scored against."""
    return [
        GroundTruthViolation(
            event_id=row["event_id"],
            decision_id=row["decision_id"],
            event_date=date.fromisoformat(row["event_date"]),
        )
        for row in read_csv_rows(data_dir, "ground_truth_violations.csv")
    ]


def decode_json(value: str | None) -> Any:
    """Decode a JSON-valued CSV cell, returning None for empty cells."""
    return json.loads(value) if value else None


def timestamp(day: date) -> datetime:
    """Convert a source date to the same stable UTC midnight used by the loader."""
    return datetime.combine(day, time.min, tzinfo=timezone.utc)
