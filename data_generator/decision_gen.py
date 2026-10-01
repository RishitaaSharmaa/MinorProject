"""Replay daily inventory, generate PO decisions, assumptions, and notes."""

from __future__ import annotations
from datetime import date, timedelta
import json
import os
import random

import numpy as np
import pandas as pd
from faker import Faker

from . import config
from .baseline_mrp import reorder_quantity
from decisionwatch.llm.client import LLMClient


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _condition_set(
    item_id: str,
    supplier_id: str,
    created_day: date,
    stock_qty: int,
    forecast_qty: int,
    lead_time: int,
    strike_status: str,
    rng: np.random.Generator,
) -> dict:
    possible = {
        "forecast_qty": {
            "op": ">=", "value": max(0, int(forecast_qty * rng.uniform(0.62, 0.90))),
            "observed_value": int(forecast_qty), "entity": f"item:{item_id}:week:{_week_start(created_day).isoformat()}",
        },
        "supplier_risk": {
            "field": "strike_status", "op": "==", "value": strike_status,
            "observed_value": strike_status, "entity": f"supplier:{supplier_id}",
        },
        "stock_qty": {
            "op": "<", "value": stock_qty + int(rng.integers(1, max(3, stock_qty // 5 + 2))),
            "observed_value": int(stock_qty), "entity": f"item:{item_id}",
        },
        "lead_time_days": {
            "op": "<=", "value": lead_time + int(rng.integers(1, 6)),
            "observed_value": int(lead_time), "entity": f"supplier:{supplier_id}",
        },
    }
    keys = list(possible)
    selected = rng.choice(keys, size=2, replace=False).tolist()
    return {key: possible[key] for key in selected}


def _template_note(assumptions: dict, supplier_name: str, rng: np.random.Generator) -> str:
    styles = []
    for key, condition in assumptions.items():
        if key == "forecast_qty":
            styles.append(f"forecast around {condition['value']}+ units")
        elif key == "supplier_risk":
            styles.append(f"strike status is {condition['value']}")
        elif key == "stock_qty":
            styles.append(f"stock below {condition['value']}")
        else:
            styles.append(f"lead time stays under {condition['value']} days")
    templates = [
        "Please keep this PO open; " + " and ".join(styles) + f". {supplier_name} said they'll manage.",
        "Need this covered: " + " / ".join(styles) + ". Pls check again next week.",
        "Stock tight hai, " + "; ".join(styles) + f". {supplier_name} se baat hui.",
        "OK to proceed for now. " + " + ".join(styles),
        "Urgent, don't hold it up. " + " and ".join(styles[:1]) + ".",
    ]
    return templates[int(rng.integers(0, len(templates)))]


def _llm_notes(cases: list[dict]) -> list[str]:
    provider = config.NOTE_LLM_PROVIDER
    if provider == config.EXTRACTION_PROVIDER and config.NOTE_LLM_MODEL == config.EXTRACTION_MODEL:
        raise ValueError("Note generation and extraction must not use the same provider and model")
    if provider == "groq":
        content = LLMClient().complete(
            "synthetic_notes",
            system_prompt=(
                "Write one short, realistic, slightly messy purchase-order note per case as a busy "
                "Indian SME buyer. Vary terse phrasing and occasional Hinglish. Some notes may omit "
                "one assumption. Return only a JSON array of strings in the same order."
            ),
            user_prompt=json.dumps(cases, ensure_ascii=True),
        )
    else:
        raise ValueError("NOTE_LLM_PROVIDER must be 'template' or 'groq'")

    try:
        notes = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM note response was not a JSON array") from exc
    if not isinstance(notes, list) or len(notes) != len(cases) or not all(isinstance(note, str) for note in notes):
        raise ValueError("LLM must return one string note per case")
    return notes


def generate_decisions(world: dict, rng: np.random.Generator, fake: Faker) -> dict[str, list[dict]]:
    items = world["items"].set_index("item_id").to_dict("index")
    suppliers = world["suppliers"].set_index("supplier_id").to_dict("index")
    inventory = dict(world["initial_stock"])
    arrivals: dict[date, list[tuple[str, int]]] = {}
    on_order = {item_id: 0 for item_id in items}
    decisions = []
    deliveries = []
    stock_rows = []
    commitments = []
    commitment_by_decision = {}
    supplier_last_commitment = {}
    notes_cases = []
    decisions_by_id = {}

    for day in world["dates"]:
        for item_id, quantity in arrivals.pop(day, []):
            inventory[item_id] += quantity
            on_order[item_id] -= quantity
        for item_id in items:
            sold = world["item_daily_demand"][item_id][day]
            inventory[item_id] = max(0, inventory[item_id] - sold)
            stock_rows.append({"item_id": item_id, "date": day.isoformat(), "qty_on_hand": inventory[item_id]})

            item = items[item_id]
            supplier = suppliers[item["primary_supplier_id"]]
            target_stock = item["avg_daily_demand"] * config.TARGET_STOCK_DAYS
            suggestion = reorder_quantity(
                inventory[item_id], on_order[item_id], item["reorder_point_qty"],
                target_stock, item["min_order_qty"],
            )
            if not suggestion:
                continue

            decision_id = f"DEC{len(decisions) + 1:06d}"
            is_override = bool(rng.random() < config.OVERRIDE_RATE)
            order_qty = suggestion
            if is_override:
                order_qty = max(item["min_order_qty"], int(round(suggestion * float(rng.choice([0.65, 0.8, 1.2, 1.5])))))
                order_qty = int(np.ceil(order_qty / item["min_order_qty"]) * item["min_order_qty"])
            lead_time = int(supplier["quoted_lead_time_days"])
            delay_late = bool(rng.random() < config.DELIVERIES_LATE_RATE)
            if delay_late:
                delay_days = max(1, min(
                    config.LATE_DAYS_MAX + 2,
                    int(round(abs(rng.normal(0.0, supplier["lead_time_std_dev"] * 0.55)))),
                ))
            else:
                delay_days = min(
                    0,
                    max(config.EARLY_DAYS_MIN - 1, int(round(rng.normal(-0.8, supplier["lead_time_std_dev"] * 0.2)))),
                )
            promised = day + timedelta(days=lead_time)
            actual = promised + timedelta(days=delay_days)
            decision = {
                "id": decision_id,
                "type": "purchase_order",
                "created_at": day.isoformat(),
                "structured_fields": {
                    "item_id": item_id,
                    "supplier_id": item["primary_supplier_id"],
                    "order_qty": order_qty,
                    "unit_cost": item["unit_cost"],
                    "system_suggestion_qty": suggestion,
                    "deviation_qty": order_qty - suggestion,
                },
                "free_text_reason": None,
                "is_override": is_override,
                "status": "placed",
            }
            if is_override:
                week_key = _week_start(day).isoformat()
                forecast = world["forecast_lookup"].get((item_id, week_key), {"forecast_qty": item["avg_daily_demand"] * 7})
                assumptions = _condition_set(
                    item_id, item["primary_supplier_id"], day, inventory[item_id],
                    forecast["forecast_qty"], lead_time, supplier["strike_status"], rng,
                )
                decision["structured_fields"]["true_assumptions"] = assumptions
                notes_cases.append({
                    "decision_id": decision_id,
                    "supplier_name": supplier["name"],
                    "assumptions": assumptions,
                })
            decisions.append(decision)
            decisions_by_id[decision_id] = decision

            actual_iso = actual.isoformat()
            deliveries.append({
                "decision_id": decision_id,
                "supplier_id": item["primary_supplier_id"],
                "promised_delivery_date": promised.isoformat(),
                "actual_delivery_date": actual_iso,
                "delay_days": delay_days,
                "arrived_late": delay_days > 0,
            })
            if actual <= config.END_DATE:
                arrivals.setdefault(actual, []).append((item_id, order_qty))
            on_order[item_id] += order_qty

            commitment_id = f"COM{len(commitments) + 1:06d}"
            prior_id = supplier_last_commitment.get(item["primary_supplier_id"])
            linked_id = None
            if prior_id and rng.random() < 0.18:
                prior = commitment_by_decision[prior_id]
                linked_id = prior["id"]
            commitment = {
                "id": commitment_id,
                "decision_id": decision_id,
                "cancellation_fee_pct": round(float(rng.uniform(0, 0.25)), 3),
                "reversible_until_date": (day + timedelta(days=max(7, lead_time))).isoformat(),
                "linked_commitment_id": linked_id,
            }
            commitments.append(commitment)
            commitment_by_decision[decision_id] = commitment
            supplier_last_commitment[item["primary_supplier_id"]] = decision_id

    if config.NOTE_LLM_PROVIDER == "template":
        fake.seed_instance(config.RANDOM_SEED + 1)
        note_rng = rng
        notes = [
            _template_note(case["assumptions"], case["supplier_name"], note_rng)
            for case in notes_cases
        ]
    else:
        notes = []
        for start in range(0, len(notes_cases), config.NOTES_BATCH_SIZE):
            batch = notes_cases[start:start + config.NOTES_BATCH_SIZE]
            notes.extend(_llm_notes(batch))
    assumptions_rows = []
    for case, note in zip(notes_cases, notes):
        decision = decisions_by_id[case["decision_id"]]
        decision["free_text_reason"] = note
        for condition_name, condition in case["assumptions"].items():
            assumptions_rows.append({
                "id": f"ASM{len(assumptions_rows) + 1:06d}",
                "decision_id": case["decision_id"],
                "condition": {"condition_name": condition_name, **condition},
                "is_ground_truth": True,
                "confirmed_by_user": False,
            })

    return {
        "decisions": decisions,
        "assumptions": assumptions_rows,
        "supplier_delivery_history": deliveries,
        "stock_snapshot": stock_rows,
        "commitments": commitments,
    }