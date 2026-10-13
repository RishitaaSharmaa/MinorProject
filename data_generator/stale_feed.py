"""Stale-ERP scenario: some stock feeds sync on a cadence, then go silent.

A healthy item reports a `feed_sync` stock event every `SYNC_CADENCE_DAYS`
through the end of the horizon. A silent item stops syncing partway through,
so assumptions watching its stock look "live" only because nothing has been
reported since. Sync events confirm the value unchanged (old == new), so they
can never flip a condition: ground-truth violations and the violation rate are
unaffected, and they are excluded from the naive baseline (not real changes).

The scenario uses its own random stream so adding it leaves every other
generated table byte-for-byte unchanged.
"""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from . import config

EVENT_TYPE = "feed_sync"
SYNC_CADENCE_DAYS = 7
SILENT_FEEDS = 5
HEALTHY_FEEDS = 3
#: A silent feed's last sync falls in this window, so it is 6+ weeks quiet at the horizon.
LAST_SYNC_EARLIEST = date(2025, 7, 1)
LAST_SYNC_LATEST = date(2025, 8, 15)
LF = chr(10)
SCENARIO_COLUMNS = ["entity", "field", "status", "cadence_days", "first_sync", "last_sync", "silent_days_at_end"]


def generate_stale_feed(
    stock_entities: dict[str, int],
    first_event_id: int,
    rng: np.random.Generator | None = None,
) -> tuple[list[dict], list[dict]]:
    """Return `(sync_events, scenario_rows)` for the given `{entity: stock_qty}` map.

    `stock_entities` should only hold items that decisions assume stock
    conditions on, so the silent feeds have assumptions to leave unverified.
    """
    rng = rng or np.random.default_rng(config.RANDOM_SEED + 1)
    entities = sorted(stock_entities)
    wanted = SILENT_FEEDS + HEALTHY_FEEDS
    chosen = [entities[i] for i in sorted(rng.permutation(len(entities))[:wanted].tolist())]
    rng.shuffle(chosen)

    events: list[dict] = []
    scenario: list[dict] = []
    next_id = first_event_id
    window_days = (LAST_SYNC_LATEST - LAST_SYNC_EARLIEST).days
    for index, entity in enumerate(chosen):
        silent = index < SILENT_FEEDS
        first = config.START_DATE + timedelta(days=int(rng.integers(0, SYNC_CADENCE_DAYS)))
        stop = (
            LAST_SYNC_EARLIEST + timedelta(days=int(rng.integers(0, window_days + 1)))
            if silent else config.END_DATE
        )
        value = int(stock_entities[entity])
        last = first
        day = first
        while day <= stop:
            events.append({
                "id": f"EVT{next_id:05d}", "entity": entity, "field": "stock_qty",
                "old_value": value, "new_value": value,
                "event_time": day.isoformat(), "event_type": EVENT_TYPE,
            })
            next_id += 1
            last = day
            day += timedelta(days=SYNC_CADENCE_DAYS)
        scenario.append({
            "entity": entity, "field": "stock_qty",
            "status": "silent" if silent else "healthy",
            "cadence_days": SYNC_CADENCE_DAYS,
            "first_sync": first.isoformat(), "last_sync": last.isoformat(),
            "silent_days_at_end": (config.END_DATE - last).days if silent else 0,
        })
    return events, scenario


def stock_entities_from_decisions(
    decisions: list[dict],
    stock_by_item: dict[str, int],
    exclude: set[str] | frozenset[str] = frozenset(),
) -> dict[str, int]:
    """Map each item that an override decision assumes stock on to a reference qty.

    `exclude` lists entities that already have real stock events; they are
    skipped so a silent feed stays silent and the answer key stays exact.
    """
    result: dict[str, int] = {}
    for decision in decisions:
        if not decision["is_override"]:
            continue
        condition = decision["structured_fields"].get("true_assumptions", {}).get("stock_qty")
        if not condition:
            continue
        entity = condition["entity"]
        item_id = entity.split(":", 1)[1]
        if item_id in stock_by_item and entity not in exclude:
            result[entity] = int(stock_by_item[item_id])
    return result


def apply_to_output(output_dir: Path | None = None) -> int:
    """Add the scenario to an already generated dataset without regenerating it.

    Idempotent: previous `feed_sync` rows are replaced. Returns the number of
    sync events written.
    """
    directory = output_dir or Path(__file__).resolve().parent / config.OUTPUT_DIR_NAME
    events_path = directory / "state_events.csv"
    with events_path.open("r", encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row["event_type"] != EVENT_TYPE]
    fieldnames = ["id", "entity", "field", "old_value", "new_value", "event_time", "event_type"]

    with (directory / "decisions.csv").open("r", encoding="utf-8", newline="") as handle:
        decisions = [
            {
                "is_override": row["is_override"] == "True",
                "structured_fields": json.loads(row["structured_fields"]),
            }
            for row in csv.DictReader(handle)
        ]
    stock_by_item: dict[str, int] = {}
    with (directory / "stock_snapshot.csv").open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            stock_by_item.setdefault(row["item_id"], int(row["qty_on_hand"]))

    next_id = 1 + max(int(row["id"].removeprefix("EVT")) for row in rows)
    sync_events, scenario = generate_stale_feed(
        stock_entities_from_decisions(
            decisions, stock_by_item,
            exclude={row["entity"] for row in rows if row["field"] == "stock_qty"},
        ),
        next_id,
    )
    rows.extend({**event, "old_value": json.dumps(event["old_value"]), "new_value": json.dumps(event["new_value"])}
                for event in sync_events)
    rows.sort(key=lambda row: (row["event_time"], row["id"]))
    with events_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator=LF)
        writer.writeheader()
        writer.writerows(rows)
    write_scenario_csv(directory, scenario)
    return len(sync_events)


def write_scenario_csv(directory: Path, scenario: list[dict]) -> None:
    """Write the answer key describing which feeds were made silent."""
    with (directory / "stale_feed_scenarios.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCENARIO_COLUMNS, lineterminator=LF)
        writer.writeheader()
        writer.writerows(scenario)


if __name__ == "__main__":
    count = apply_to_output()
    print(f"Wrote {count} feed_sync events and stale_feed_scenarios.csv")
