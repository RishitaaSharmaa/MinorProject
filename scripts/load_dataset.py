"""Idempotently load generated CSV data into operational and GT tables."""

import argparse
import csv
import json
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, Column, Date, Integer, MetaData, String, Table, delete, insert, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.models import (
    Assumption,
    AssumptionProposal,
    AssumptionViolation,
    Base,
    Commitment,
    CommitmentLink,
    Decision,
    Forecast,
    Item,
    Outcome,
    SalesHistory,
    StateEvent,
    StockSnapshot,
    Supplier,
    SupplierDelivery,
)
from app.models.base import JSON_VALUE

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data_generator" / "output"
GT_METADATA = MetaData()
GT_ASSUMPTIONS = Table(
    "gt_assumptions",
    GT_METADATA,
    Column("id", String(64), primary_key=True),
    Column("decision_id", String(64), nullable=False),
    Column("condition", JSON_VALUE, nullable=False),
    Column("confirmed_by_user", Boolean, nullable=False),
)
GT_VIOLATIONS = Table(
    "gt_assumption_violations",
    GT_METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_id", String(64), nullable=False),
    Column("decision_id", String(64), nullable=False),
    Column("violated_condition", JSON_VALUE, nullable=False),
    Column("event_date", Date, nullable=False),
)


def _csv_rows(data_dir: Path, filename: str) -> list[dict[str, str]]:
    """Read one CSV file as dictionaries, preserving the source headers."""
    with (data_dir / filename).open("r", encoding="utf-8-sig", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def _boolean(value: str) -> bool:
    """Parse CSV boolean spellings emitted by pandas and Python."""
    return value.strip().lower() in {"true", "1", "yes"}


def _json(value: str) -> Any:
    """Decode a JSON-valued CSV cell, returning None for empty cells."""
    return json.loads(value) if value else None


def _date(value: str) -> date:
    """Parse an ISO date from a CSV cell."""
    return date.fromisoformat(value)


def _timestamp(day: date) -> datetime:
    """Convert a source date to a stable UTC midnight timestamp."""
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


def _clear_dataset(session: Session) -> None:
    """Delete loaded rows in foreign-key-safe order before each full reload."""
    session.execute(update(Commitment).values(linked_commitment_id=None))
    for table in (
        GT_VIOLATIONS,
        GT_ASSUMPTIONS,
        AssumptionViolation.__table__,
        AssumptionProposal.__table__,
        Assumption.__table__,
        CommitmentLink.__table__,
        Commitment.__table__,
        Outcome.__table__,
        SupplierDelivery.__table__,
        StateEvent.__table__,
        Decision.__table__,
        Forecast.__table__,
        StockSnapshot.__table__,
        SalesHistory.__table__,
        Item.__table__,
        Supplier.__table__,
    ):
        session.execute(delete(table))


def _insert_rows(session: Session, model: Any, rows: list[dict[str, Any]]) -> int:
    """Bulk insert model rows and return the inserted row count."""
    if rows:
        session.execute(insert(model), rows)
    return len(rows)


def load_dataset(session: Session, data_dir: Path = DEFAULT_DATA_DIR) -> dict[str, int]:
    """Truncate and reload all generator CSVs, isolating answer-key rows."""
    _clear_dataset(session)
    counts: dict[str, int] = {}

    suppliers = [
        {
            "id": row["supplier_id"],
            "name": row["name"],
            "quoted_lead_time_days": int(row["quoted_lead_time_days"]),
            "lead_time_std_dev": float(row["lead_time_std_dev"]),
            "reliability_score": float(row["reliability_score"]),
            "price_break_tiers": _json(row["price_break_tiers"]),
            "strike_status": row["strike_status"],
        }
        for row in _csv_rows(data_dir, "suppliers.csv")
    ]
    counts["suppliers"] = _insert_rows(session, Supplier, suppliers)

    items = [
        {
            "id": row["item_id"],
            "name": row["name"],
            "category": row["category"],
            "unit_cost": float(row["unit_cost"]),
            "holding_cost_pct": float(row["holding_cost_pct"]),
            "min_order_qty": int(row["min_order_qty"]),
            "primary_supplier_id": row["primary_supplier_id"],
            "avg_daily_demand": int(row["avg_daily_demand"]),
            "reorder_point_qty": int(row["reorder_point_qty"]),
        }
        for row in _csv_rows(data_dir, "items.csv")
    ]
    counts["items"] = _insert_rows(session, Item, items)

    sales = [
        {"item_id": row["item_id"], "date": _date(row["date"]), "qty_sold": int(row["qty_sold"])}
        for row in _csv_rows(data_dir, "sales_history.csv")
    ]
    counts["sales_history"] = _insert_rows(session, SalesHistory, sales)

    snapshots = [
        {"item_id": row["item_id"], "date": _date(row["date"]), "qty_on_hand": int(row["qty_on_hand"])}
        for row in _csv_rows(data_dir, "stock_snapshot.csv")
    ]
    counts["stock_snapshots"] = _insert_rows(session, StockSnapshot, snapshots)

    forecasts = [
        {
            "item_id": row["item_id"],
            "week": _date(row["week"]),
            "forecast_qty": int(row["forecast_qty"]),
            "true_demand": int(row["true_demand"]),
            "forecast_error_pct": float(row["forecast_error_pct"]),
        }
        for row in _csv_rows(data_dir, "weekly_forecasts.csv")
    ]
    counts["forecasts"] = _insert_rows(session, Forecast, forecasts)

    deliveries = {
        row["decision_id"]: _date(row["promised_delivery_date"])
        for row in _csv_rows(data_dir, "supplier_delivery_history.csv")
    }
    decisions: list[dict[str, Any]] = []
    decision_dates: dict[str, date] = {}
    for row in _csv_rows(data_dir, "decisions.csv"):
        source_fields = _json(row["structured_fields"]) or {}
        fields = {key: value for key, value in source_fields.items() if key != "true_assumptions"}
        po_day = _date(row["created_at"])
        decision_dates[row["id"]] = po_day
        decisions.append({
            "id": row["id"],
            "decision_type": row["type"],
            "created_at": _timestamp(po_day),
            "structured_fields": fields,
            "free_text_reason": row["free_text_reason"] or None,
            "is_override": _boolean(row["is_override"]),
            "status": row["status"],
            "item_id": fields.get("item_id"),
            "supplier_id": fields.get("supplier_id"),
            "quantity": fields.get("order_qty"),
            "unit_price": fields.get("unit_cost"),
            "po_date": po_day,
            "expected_delivery": deliveries.get(row["id"]),
        })
    counts["decisions"] = _insert_rows(session, Decision, decisions)

    delivery_rows = [
        {
            "decision_id": row["decision_id"],
            "supplier_id": row["supplier_id"],
            "promised_delivery_date": _date(row["promised_delivery_date"]),
            "actual_delivery_date": _date(row["actual_delivery_date"]),
            "delay_days": int(row["delay_days"]),
            "arrived_late": _boolean(row["arrived_late"]),
        }
        for row in _csv_rows(data_dir, "supplier_delivery_history.csv")
    ]
    counts["supplier_delivery_history"] = _insert_rows(session, SupplierDelivery, delivery_rows)

    operational_assumptions: list[dict[str, Any]] = []
    gt_assumptions: list[dict[str, Any]] = []
    for row in _csv_rows(data_dir, "assumptions.csv"):
        condition = _json(row["condition"])
        if _boolean(row["is_ground_truth"]):
            gt_assumptions.append({
                "id": row["id"],
                "decision_id": row["decision_id"],
                "condition": condition,
                "confirmed_by_user": _boolean(row["confirmed_by_user"]),
            })
        else:
            operational_assumptions.append({
                "id": row["id"],
                "decision_id": row["decision_id"],
                "condition": condition,
                "source": "structured",
                "confirmed_by_user": _boolean(row["confirmed_by_user"]),
                "status": "live",
                "created_at": _timestamp(decision_dates[row["decision_id"]]),
            })
    counts["assumptions"] = _insert_rows(session, Assumption, operational_assumptions)
    if gt_assumptions:
        session.execute(insert(GT_ASSUMPTIONS), gt_assumptions)
    counts["gt_assumptions"] = len(gt_assumptions)

    events: list[dict[str, Any]] = []
    for row in _csv_rows(data_dir, "state_events.csv"):
        entity_type, _, entity_id = row["entity"].partition(":")
        event_day = _date(row["event_time"])
        events.append({
            "id": row["id"],
            "entity_type": entity_type,
            "entity_id": entity_id,
            "field": row["field"],
            "old_value": _json(row["old_value"]),
            "new_value": _json(row["new_value"]),
            "event_time": _timestamp(event_day),
        })
    counts["state_events"] = _insert_rows(session, StateEvent, events)

    ground_truth_violations = [
        {
            "event_id": row["event_id"],
            "decision_id": row["decision_id"],
            "violated_condition": _json(row["violated_condition"]),
            "event_date": _date(row["event_date"]),
        }
        for row in _csv_rows(data_dir, "ground_truth_violations.csv")
    ]
    if ground_truth_violations:
        session.execute(insert(GT_VIOLATIONS), ground_truth_violations)
    counts["gt_assumption_violations"] = len(ground_truth_violations)

    commitments = [
        {
            "id": row["id"],
            "decision_id": row["decision_id"],
            "cancellation_fee_pct": float(row["cancellation_fee_pct"]),
            "reversible_until": _date(row["reversible_until_date"]),
            "linked_commitment_id": row["linked_commitment_id"] or None,
        }
        for row in _csv_rows(data_dir, "commitments.csv")
    ]
    counts["commitments"] = _insert_rows(session, Commitment, commitments)
    commitment_links = [
        {
            "id": f"CL-{row['id']}-{row['linked_commitment_id']}",
            "from_commitment_id": row["id"],
            "to_commitment_id": row["linked_commitment_id"],
        }
        for row in _csv_rows(data_dir, "commitments.csv")
        if row.get("linked_commitment_id")
    ]
    counts["commitment_links"] = _insert_rows(session, CommitmentLink, commitment_links)

    outcomes = [
        {
            "id": row["id"],
            "decision_id": row["decision_id"],
            "recommended_action": row["recommended_action"],
            "actual_action": row["actual_action"],
            "actual_result": row["actual_result"],
            "logged_at": _timestamp(decision_dates[row["decision_id"]]),
        }
        for row in _csv_rows(data_dir, "outcomes.csv")
    ]
    counts["outcomes"] = _insert_rows(session, Outcome, outcomes)

    session.commit()
    return counts


def main() -> None:
    """Load CSVs from the default generator output directory or a supplied path."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args()
    with get_engine().begin() as connection:
        with Session(bind=connection, expire_on_commit=False) as session:
            counts = load_dataset(session, args.data_dir)
    for table_name, count in sorted(counts.items()):
        print(f"{table_name}: {count}")


if __name__ == "__main__":
    main()