"""Generate the catalog, supplier master, demand, and weekly forecasts."""

from __future__ import annotations

from datetime import date, timedelta
import math

import numpy as np
import pandas as pd
from faker import Faker

from . import config


CATEGORIES = ("Electrical", "Fasteners", "Packaging", "Pumps", "Bearings")


def _calendar_dates() -> list[date]:
    return [value.date() for value in pd.date_range(config.START_DATE, config.END_DATE, freq="D")]


def _festival_multiplier(day: date) -> float:
    multiplier = 1.0
    for month, start_day, duration, spike, _label in config.FESTIVAL_SPIKES:
        try:
            start = date(day.year, month, start_day)
        except ValueError:
            continue
        if 0 <= (day - start).days < duration:
            multiplier *= spike
    return multiplier


def generate_world(rng: np.random.Generator, fake: Faker) -> dict[str, pd.DataFrame | dict]:
    """Create all exogenous world data; inventory is replayed with POs later."""
    supplier_rows = []
    for index in range(1, config.NUM_SUPPLIERS + 1):
        lead_time = int(rng.integers(5, 22))
        supplier_rows.append({
            "supplier_id": f"SUP{index:03d}",
            "name": fake.company(),
            "quoted_lead_time_days": lead_time,
            "lead_time_std_dev": round(float(rng.uniform(1.2, 4.5)), 2),
            "reliability_score": round(float(rng.uniform(0.72, 0.98)), 3),
            "price_break_tiers": [
                {"min_qty": 1, "discount_pct": 0.0},
                {"min_qty": 100, "discount_pct": 2.0},
                {"min_qty": 500, "discount_pct": 4.5},
            ],
            "strike_status": "clear",
        })
    suppliers = pd.DataFrame(supplier_rows)

    item_rows = []
    initial_stock = {}
    for index in range(1, config.NUM_ITEMS + 1):
        category = CATEGORIES[(index - 1) % len(CATEGORIES)]
        supplier = supplier_rows[int(rng.integers(0, len(supplier_rows)))]
        avg_daily = int(rng.integers(config.AVG_DAILY_DEMAND_MIN, config.AVG_DAILY_DEMAND_MAX + 1))
        lead_days = supplier["quoted_lead_time_days"]
        reorder_point = int(avg_daily * (lead_days + config.SAFETY_STOCK_DAYS))
        min_order = int(rng.integers(config.MIN_ORDER_QTY_MIN, config.MIN_ORDER_QTY_MAX + 1))
        item_id = f"SKU{index:03d}"
        item_rows.append({
            "item_id": item_id,
            "name": f"{fake.unique.word().title()} {category[:-1] if category.endswith('s') else category}",
            "category": category,
            "unit_cost": round(float(rng.uniform(config.UNIT_COST_MIN, config.UNIT_COST_MAX)), 2),
            "holding_cost_pct": round(float(rng.uniform(config.HOLDING_COST_PCT_MIN, config.HOLDING_COST_PCT_MAX)), 3),
            "min_order_qty": min_order,
            "primary_supplier_id": supplier["supplier_id"],
            "avg_daily_demand": avg_daily,
            "reorder_point_qty": reorder_point,
        })
        initial_stock[item_id] = int(avg_daily * rng.uniform(20, 42))
    items = pd.DataFrame(item_rows)

    dates = _calendar_dates()
    sales_rows = []
    item_daily_demand: dict[str, dict[date, int]] = {}
    for item in item_rows:
        baseline = item["avg_daily_demand"]
        demand_by_day = {}
        for day in dates:
            weekday_factor = config.WEEKDAY_DEMAND_MULTIPLIERS[day.weekday()]
            annual_factor = 1.0 + 0.10 * math.sin(2 * math.pi * (day.timetuple().tm_yday - 100) / 365.25)
            expected = baseline * weekday_factor * annual_factor * _festival_multiplier(day)
            noisy = expected + float(rng.normal(0.0, max(1.0, baseline * config.SALES_NOISE_STD_DEV_PCT)))
            quantity = max(0, int(round(noisy)))
            demand_by_day[day] = quantity
            sales_rows.append({"item_id": item["item_id"], "date": day.isoformat(), "qty_sold": quantity})
        item_daily_demand[item["item_id"]] = demand_by_day
    sales_history = pd.DataFrame(sales_rows)

    forecast_rows = []
    forecast_lookup = {}
    range_start = config.START_DATE
    first_monday = range_start - timedelta(days=range_start.weekday())
    week_starts = []
    week = first_monday
    while week <= config.END_DATE:
        week_starts.append(week)
        week += timedelta(days=7)
    for item_id, demand_by_day in item_daily_demand.items():
        for week_start in week_starts:
            true_demand = sum(
                quantity for day, quantity in demand_by_day.items()
                if week_start <= day < week_start + timedelta(days=7)
            )
            error_pct = float(rng.normal(config.FORECAST_ERROR_MEAN, config.FORECAST_ERROR_STD_DEV))
            forecast_qty = max(0, int(round(true_demand * (1.0 + error_pct))))
            row = {
                "item_id": item_id,
                "week": week_start.isoformat(),
                "forecast_qty": forecast_qty,
                "true_demand": true_demand,
                "forecast_error_pct": round(error_pct, 5),
            }
            forecast_rows.append(row)
            forecast_lookup[(item_id, week_start.isoformat())] = row
    weekly_forecasts = pd.DataFrame(forecast_rows)

    return {
        "items": items,
        "suppliers": suppliers,
        "sales_history": sales_history,
        "weekly_forecasts": weekly_forecasts,
        "forecast_lookup": forecast_lookup,
        "item_daily_demand": item_daily_demand,
        "initial_stock": initial_stock,
        "dates": dates,
    }