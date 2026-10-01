"""Generate state changes and deterministic assumption-violation labels."""

from __future__ import annotations

from datetime import date, timedelta
import json

import numpy as np

from . import config


def _condition_field(condition: dict) -> str:
    return condition.get("field", condition["condition_name"])


def _holds(condition: dict, value) -> bool:
    op = condition["op"]
    expected = condition["value"]
    if op == "==":
        return value == expected
    try:
        left, right = float(value), float(expected)
    except (TypeError, ValueError):
        return False
    if op == ">=":
        return left >= right
    if op == "<=":
        return left <= right
    if op == "<":
        return left < right
    if op == ">":
        return left > right
    return False


def _break_value(condition: dict):
    field = _condition_field(condition)
    if field == "strike_status":
        return "open" if condition["observed_value"] != "open" else "clear"
    if condition["op"] in (">=", ">"):
        return condition["value"] - 1
    if condition["op"] in ("<=", "<"):
        return condition["value"] + 1
    return None


def _make_event(event_id: str, entity: str, field: str, old, new, when: date, event_type: str) -> dict:
    return {
        "id": event_id,
        "entity": entity,
        "field": field,
        "old_value": old,
        "new_value": new,
        "event_time": when.isoformat(),
        "event_type": event_type,
    }


def _all_conditions(decisions: list[dict]) -> list[tuple[dict, dict]]:
    result = []
    for decision in decisions:
        for name, condition in decision["structured_fields"].get("true_assumptions", {}).items():
            result.append((decision, {"condition_name": name, **condition}))
    return result


def _labels_for_event(event: dict, decisions: list[dict]) -> list[dict]:
    labels = []
    for decision in decisions:
        if decision["created_at"] >= event["event_time"]:
            continue
        for condition_name, raw in decision["structured_fields"].get("true_assumptions", {}).items():
            condition = {"condition_name": condition_name, **raw}
            if condition["entity"] != event["entity"] or _condition_field(condition) != event["field"]:
                continue
            if _holds(condition, event["old_value"]) and not _holds(condition, event["new_value"]):
                labels.append({
                    "event_id": event["id"],
                    "decision_id": decision["id"],
                    "violated_condition": condition,
                    "event_date": event["event_time"],
                })
    return labels


def generate_events(world: dict, procurement: dict, rng: np.random.Generator) -> tuple[list[dict], list[dict]]:
    decisions = procurement["decisions"]
    overrides = [decision for decision in decisions if decision["is_override"]]
    events = []
    next_id = 1

    target_count = int(round(len(overrides) * config.VIOLATION_INJECTION_RATE))
    max_broken = min(len(overrides), int(np.floor(len(overrides) * (config.VIOLATION_INJECTION_RATE + 0.05))))
    order = rng.permutation(len(overrides)).tolist() if overrides else []
    for index in order:
        existing_broken = {
            row["decision_id"] for event in events for row in _labels_for_event(event, decisions)
        }
        if len(existing_broken) >= target_count:
            break
        decision = overrides[index]
        conditions = [
            {"condition_name": name, **condition}
            for name, condition in decision["structured_fields"]["true_assumptions"].items()
            if _condition_field({"condition_name": name, **condition})
            in {"forecast_qty", "strike_status", "stock_qty", "lead_time_days"}
        ]
        if not conditions:
            continue
        condition = conditions[int(rng.integers(0, len(conditions)))]
        old_value = condition["observed_value"]
        new_value = _break_value(condition)
        if new_value is None or not _holds(condition, old_value) or _holds(condition, new_value):
            continue
        created = date.fromisoformat(decision["created_at"])
        max_offset = max(1, min(config.VIOLATION_EVENT_MAX_LAG_DAYS, (config.END_DATE - created).days))
        event_day = created + timedelta(days=int(rng.integers(1, max_offset + 1)))
        candidate = _make_event(
            f"EVT{next_id:05d}", condition["entity"], _condition_field(condition),
            old_value, new_value, event_day, "assumption_reversal",
        )
        candidate_broken = {row["decision_id"] for row in _labels_for_event(candidate, decisions)}
        if len(existing_broken | candidate_broken) <= max_broken:
            events.append(candidate)
            next_id += 1

    # Add a small mixed timeline. Candidate changes are retained only while the
    # configured override-decision violation rate remains within tolerance.
    duration_days = (config.END_DATE - config.START_DATE).days + 1
    background_count = int(round(config.BACKGROUND_EVENTS_PER_MONTH * duration_days / 30.4375))
    items = world["items"].to_dict("records")
    suppliers = world["suppliers"].to_dict("records")
    stock_by_item = {row["item_id"]: [] for row in items}
    for row in procurement["stock_snapshot"]:
        stock_by_item[row["item_id"]].append(row["qty_on_hand"])
    forecasts = world["weekly_forecasts"].to_dict("records")
    event_kinds = ["forecast_revision", "stock_correction", "supplier_risk", "lead_time", "price_break"]
    for _ in range(background_count):
        kind = event_kinds[int(rng.integers(0, len(event_kinds)))]
        when = config.START_DATE + timedelta(days=int(rng.integers(0, duration_days)))
        if kind == "forecast_revision":
            row = forecasts[int(rng.integers(0, len(forecasts)))]
            item_id, week = row["item_id"], row["week"]
            old = int(row["forecast_qty"])
            new = max(0, int(round(old * float(rng.uniform(0.72, 1.30)))))
            entity, field, event_type = f"item:{item_id}:week:{week}", "forecast_qty", kind
        elif kind == "stock_correction":
            item_id = items[int(rng.integers(0, len(items)))]["item_id"]
            values = stock_by_item[item_id]
            old = int(values[int(rng.integers(0, len(values)))]) if values else 0
            new = max(0, old + int(rng.integers(-max(1, old // 4), max(2, old // 4 + 1))))
            entity, field, event_type = f"item:{item_id}", "stock_qty", kind
        elif kind == "supplier_risk":
            supplier = suppliers[int(rng.integers(0, len(suppliers)))]
            old = "clear"
            new = "open"
            entity, field, event_type = f"supplier:{supplier['supplier_id']}", "strike_status", kind
        elif kind == "lead_time":
            supplier = suppliers[int(rng.integers(0, len(suppliers)))]
            old = int(supplier["quoted_lead_time_days"])
            new = max(1, old + int(rng.choice([-5, -3, 3, 5, 8])))
            entity, field, event_type = f"supplier:{supplier['supplier_id']}", "lead_time_days", kind
        else:
            supplier = suppliers[int(rng.integers(0, len(suppliers)))]
            old = supplier["price_break_tiers"]
            new = [dict(tier) for tier in old]
            new[-1]["discount_pct"] = round(max(0, new[-1]["discount_pct"] + float(rng.choice([-1.0, 1.0, 2.0]))), 1)
            entity, field, event_type = f"supplier:{supplier['supplier_id']}", "price_break_tiers", kind
        candidate = _make_event(f"EVT{next_id:05d}", entity, field, old, new, when, event_type)
        candidate_labels = _labels_for_event(candidate, decisions)
        existing_broken = {
            row["decision_id"] for event in events for row in _labels_for_event(event, decisions)
        }
        newly_broken = {row["decision_id"] for row in candidate_labels if row["decision_id"] not in existing_broken}
        if len(existing_broken | newly_broken) <= max_broken:
            events.append(candidate)
            next_id += 1

    events.sort(key=lambda event: (event["event_time"], event["id"]))
    violations = [label for event in events for label in _labels_for_event(event, decisions)]
    return events, violations