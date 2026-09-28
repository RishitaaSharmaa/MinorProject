"""Deterministic reorder rule and deliberately naive event baseline."""

from __future__ import annotations

import math


def reorder_quantity(
    stock_qty: int,
    on_order_qty: int,
    reorder_point_qty: int,
    target_stock_qty: int,
    min_order_qty: int,
) -> int:
    """Return a lot-sized suggestion, or zero when inventory is sufficient."""
    inventory_position = stock_qty + on_order_qty
    if inventory_position >= reorder_point_qty:
        return 0
    raw_qty = max(min_order_qty, target_stock_qty - inventory_position)
    return int(math.ceil(raw_qty / min_order_qty) * min_order_qty)


def build_baseline_flags(events: list[dict], decisions: list[dict]) -> list[dict]:
    """Flag every prior decision touching an event's item or supplier."""
    flags = []
    for event in events:
        for decision in decisions:
            if decision["created_at"] >= event["event_time"]:
                continue
            fields = decision["structured_fields"]
            if event["entity"].startswith("item:"):
                entity_id = event["entity"].split(":", 2)[1]
                relevant = fields["item_id"] == entity_id
            elif event["entity"].startswith("supplier:"):
                entity_id = event["entity"].split(":", 1)[1]
                relevant = fields["supplier_id"] == entity_id
            else:
                relevant = False
            if relevant:
                flags.append({
                    "event_id": event["id"],
                    "decision_id": decision["id"],
                    "flag_reason": "related_item_or_supplier_changed",
                })
    return flags