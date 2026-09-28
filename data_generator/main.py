"""Run the full deterministic Sharma Industries data-generation pipeline."""

from __future__ import annotations

import json
from pathlib import Path
import random

import numpy as np
import pandas as pd
from faker import Faker

from . import config
from .baseline_mrp import build_baseline_flags
from .decision_gen import generate_decisions
from .event_gen import generate_events
from .world_gen import generate_world


def _serialize_table(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in result.columns:
        if column in {"old_value", "new_value"}:
            result[column] = result[column].map(
                lambda value: json.dumps(value, ensure_ascii=True)
                if value is not None and (isinstance(value, (dict, list)) or not pd.isna(value))
                else None
            )
        elif result[column].map(lambda value: isinstance(value, (dict, list))).any():
            result[column] = result[column].map(
                lambda value: json.dumps(value, ensure_ascii=True) if isinstance(value, (dict, list)) else value
            )
    return result


def run(output_dir: Path | None = None) -> dict[str, pd.DataFrame]:
    random.seed(config.RANDOM_SEED)
    rng = np.random.default_rng(config.RANDOM_SEED)
    fake = Faker("en_IN")
    fake.seed_instance(config.RANDOM_SEED)

    world = generate_world(rng, fake)
    procurement = generate_decisions(world, rng, fake)
    events, violations = generate_events(world, procurement, rng)
    baseline_flags = build_baseline_flags(events, procurement["decisions"])

    violation_decisions = {row["decision_id"] for row in violations}
    baseline_decisions = {row["decision_id"] for row in baseline_flags}
    outcomes = []
    for decision in procurement["decisions"]:
        decision_id = decision["id"]
        broken = decision_id in violation_decisions
        outcomes.append({
            "id": f"OUT{len(outcomes) + 1:06d}",
            "decision_id": decision_id,
            "recommended_action": "review" if decision_id in baseline_decisions else "no_action",
            "actual_action": "revisited" if broken else "unchanged",
            "actual_result": "assumption_broken" if broken else (
                "assumptions_hold_at_horizon" if decision["is_override"] else "not_applicable"
            ),
        })

    tables = {
        "items": world["items"],
        "suppliers": world["suppliers"],
        "sales_history": world["sales_history"],
        "stock_snapshot": pd.DataFrame(procurement["stock_snapshot"]),
        "weekly_forecasts": world["weekly_forecasts"],
        "decisions": pd.DataFrame([
            {
                "id": row["id"], "type": row["type"], "created_at": row["created_at"],
                "structured_fields": row["structured_fields"], "free_text_reason": row["free_text_reason"],
                "is_override": row["is_override"], "status": row["status"],
            }
            for row in procurement["decisions"]
        ]),
        "assumptions": pd.DataFrame(procurement["assumptions"]),
        "supplier_delivery_history": pd.DataFrame(procurement["supplier_delivery_history"]),
        "state_events": pd.DataFrame(events),
        "ground_truth_violations": pd.DataFrame(violations, columns=["event_id", "decision_id", "violated_condition", "event_date"]),
        "commitments": pd.DataFrame(procurement["commitments"]),
        "outcomes": pd.DataFrame(outcomes),
        "baseline_event_flags": pd.DataFrame(baseline_flags, columns=["event_id", "decision_id", "flag_reason"]),
    }

    destination = output_dir or Path(__file__).resolve().parent / config.OUTPUT_DIR_NAME
    destination.mkdir(parents=True, exist_ok=True)
    for table_name, frame in tables.items():
        _serialize_table(frame).to_csv(destination / f"{table_name}.csv", index=False)

    overrides = sum(row["is_override"] for row in procurement["decisions"])
    broken_rate = len(violation_decisions) / overrides if overrides else 0.0
    late_rate = sum(row["arrived_late"] for row in procurement["supplier_delivery_history"]) / max(1, len(procurement["supplier_delivery_history"]))
    print(f"Wrote {len(tables)} CSV tables to {destination}")
    print(f"POs: {len(procurement['decisions'])}; overrides: {overrides}; override violation rate: {broken_rate:.1%}")
    print(f"Supplier deliveries late: {late_rate:.1%}; events: {len(events)}; labeled violations: {len(violations)}")
    return tables


if __name__ == "__main__":
    run()