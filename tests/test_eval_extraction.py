"""Tests for evaluation-label mapping and per-condition metrics."""

from scripts.eval_extraction import _condition_type_metrics, _ground_truth_condition


def test_ground_truth_conditions_map_to_closed_vocabulary() -> None:
    """Normalize the generator's historical assumption names and entity refs."""
    mapped = _ground_truth_condition({
        "condition_name": "stock_qty",
        "entity": "item:SKU1",
        "op": "<",
        "value": 20,
    })

    assert mapped == {
        "type": "stock_lt",
        "entity_ref": "item:SKU1",
        "op": "<",
        "value": 20,
        "needs_value_from_planner": False,
    }

    forecast = _ground_truth_condition({
        "condition_name": "forecast_qty",
        "entity": "item:SKU1:week:2025-04-07",
        "op": ">=",
        "value": 186,
    })
    assert forecast is not None
    assert forecast["type"] == "forecast_gte"
    assert forecast["entity_ref"] == "item:SKU1"


def test_condition_metrics_are_reported_per_type() -> None:
    """Count exact condition matches and compute zero-safe precision/recall/F1."""
    expected = {
        ("DEC1", "stock_lt", "item:SKU1", "<", "10.0"),
        ("DEC1", "lead_time_lte", "supplier:SUP1", "<=", "5.0"),
    }
    predicted = {
        ("DEC1", "stock_lt", "item:SKU1", "<", "10.0"),
        ("DEC2", "forecast_gte", "item:SKU1", ">=", "12.0"),
    }

    report = _condition_type_metrics(predicted, expected)

    assert report["stock_lt"] == (1.0, 1.0, 1.0, 1, 0, 0)
    assert report["lead_time_lte"] == (0.0, 0.0, 0.0, 0, 0, 1)
    assert report["forecast_gte"] == (0.0, 0.0, 0.0, 0, 1, 0)