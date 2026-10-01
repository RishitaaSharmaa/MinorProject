"""Evaluate assumption extraction against isolated GT and optional gold examples.

Gold-set JSONL records use `{ "decision": {DecisionDTO fields}, "conditions": [...] }`.
Each condition uses the closed `/app` condition schema.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.factory import get_connector
from app.connectors.dto import DecisionDTO
from app.db import get_session_factory
from app.services.conditions import Condition
from app.services.extraction import extract_assumptions
from scripts.load_dataset import GT_ASSUMPTIONS

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLD_SET = ROOT / "data_generator" / "gold_set"
ConditionMatch = tuple[str, str, str, str, str]


def _normalize_entity(entity_ref: str) -> str:
    """Normalize synthetic forecast week suffixes from item entity references."""
    if entity_ref.startswith("item:"):
        return entity_ref.split(":week:", 1)[0]
    return entity_ref


def _ground_truth_condition(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Map generator assumption labels into the closed extraction vocabulary."""
    if raw.get("type") in {
        "forecast_gte", "forecast_lte", "stock_lt", "stock_gt", "lead_time_lte",
        "supplier_risk_open", "supplier_risk_resolved", "moq_lte", "price_break_available",
    }:
        condition = Condition.model_validate({
            "type": raw["type"],
            "entity_ref": _normalize_entity(str(raw.get("entity_ref", raw.get("entity", "")))),
            "op": raw.get("op"),
            "value": raw.get("value"),
            "needs_value_from_planner": raw.get("needs_value_from_planner", False),
        })
        return condition.model_dump(mode="json")

    condition_name = raw.get("condition_name")
    entity_ref = _normalize_entity(str(raw.get("entity", "")))
    operator = raw.get("op")
    value = raw.get("value")
    if condition_name == "forecast_qty" and operator in {">=", "<="}:
        condition_type = "forecast_gte" if operator == ">=" else "forecast_lte"
    elif condition_name == "stock_qty" and operator in {"<", ">"}:
        condition_type = "stock_lt" if operator == "<" else "stock_gt"
    elif condition_name == "lead_time_days" and operator == "<=":
        condition_type, operator = "lead_time_lte", "<="
    elif condition_name == "moq" and operator == "<=":
        condition_type, operator = "moq_lte", "<="
    elif condition_name == "price_break":
        condition_type, operator, value = "price_break_available", "==", True
    elif condition_name == "supplier_risk":
        risk_value = str(value).lower()
        if risk_value in {"strike", "open", "at_risk", "active"}:
            condition_type, operator, value = "supplier_risk_open", "==", "open"
        else:
            condition_type, operator, value = "supplier_risk_resolved", "==", "resolved"
    else:
        return None
    return {
        "type": condition_type,
        "entity_ref": entity_ref,
        "op": operator,
        "value": value,
        "needs_value_from_planner": False,
    }


def _condition_key(
    decision_id: str, condition: dict[str, Any] | Condition
) -> ConditionMatch:
    """Create comparable keys from validated condition objects or mappings."""
    values = condition.model_dump(mode="json") if isinstance(condition, Condition) else condition
    value = values.get("value")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = float(value)
    return (
        decision_id,
        str(values["type"]),
        _normalize_entity(str(values["entity_ref"])),
        str(values["op"]),
        json.dumps(value, sort_keys=True),
    )


def _condition_type_metrics(
    predictions: set[ConditionMatch],
    expected: set[ConditionMatch],
) -> dict[str, tuple[float, float, float, int, int, int]]:
    """Calculate precision, recall, F1, and counts independently by type."""
    types = sorted({row[1] for row in predictions | expected})
    results: dict[str, tuple[float, float, float, int, int, int]] = {}
    for condition_type in types:
        predicted_type = {row for row in predictions if row[1] == condition_type}
        expected_type = {row for row in expected if row[1] == condition_type}
        true_positive = len(predicted_type & expected_type)
        false_positive = len(predicted_type - expected_type)
        false_negative = len(expected_type - predicted_type)
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        results[condition_type] = (
            precision,
            recall,
            f1,
            true_positive,
            false_positive,
            false_negative,
        )
    return results


def _print_report(title: str, predictions: set[ConditionMatch], expected: set[ConditionMatch]) -> None:
    """Print per-condition-type and micro-aggregate extraction metrics."""
    print(f"\n{title}")
    print(f"{'condition_type':<26} {'precision':>9} {'recall':>9} {'f1':>9} {'tp':>6} {'fp':>6} {'fn':>6}")
    print("-" * 80)
    metrics = _condition_type_metrics(predictions, expected)
    for condition_type, (precision, recall, f1, tp, fp, fn) in metrics.items():
        print(f"{condition_type:<26} {precision:>9.3f} {recall:>9.3f} {f1:>9.3f} {tp:>6} {fp:>6} {fn:>6}")
    tp = sum(result[3] for result in metrics.values())
    fp = sum(result[4] for result in metrics.values())
    fn = sum(result[5] for result in metrics.values())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    print(f"{'MICRO':<26} {precision:>9.3f} {recall:>9.3f} {f1:>9.3f} {tp:>6} {fp:>6} {fn:>6}")


def _load_gold_examples(gold_dir: Path) -> list[dict[str, Any]]:
    """Load hand-authored JSONL examples from a gold-set directory."""
    examples: list[dict[str, Any]] = []
    for path in sorted(gold_dir.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as jsonl_file:
            examples.extend(json.loads(line) for line in jsonl_file if line.strip())
    for path in sorted(gold_dir.glob("*.json")):
        with path.open("r", encoding="utf-8") as json_file:
            loaded = json.load(json_file)
        examples.extend(loaded if isinstance(loaded, list) else [loaded])
    return examples


def evaluate(database: Session, gold_dir: Path = DEFAULT_GOLD_SET) -> None:
    """Run override extraction against GT and optional hand-authored labels."""
    connector = get_connector(database)
    ground_truth: dict[str, set[ConditionMatch]] = defaultdict(set)
    for decision_id, condition in database.execute(
        select(GT_ASSUMPTIONS.c.decision_id, GT_ASSUMPTIONS.c.condition)
    ):
        normalized = _ground_truth_condition(condition)
        if normalized is not None:
            ground_truth[decision_id].add(_condition_key(decision_id, normalized))

    predictions: set[ConditionMatch] = set()
    llm_predictions: set[ConditionMatch] = set()
    expected: set[ConditionMatch] = set()
    decisions = connector.list_decisions(only_overrides=True)
    extraction_failures = 0
    for decision in decisions:
        expected.update(ground_truth.get(decision.id, set()))
        try:
            proposals = extract_assumptions(decision, connector, as_of=decision.created_at)
        except Exception as error:
            extraction_failures += 1
            print(f"WARNING {decision.id}: extraction failed ({type(error).__name__})", file=sys.stderr)
            continue
        predictions.update(_condition_key(decision.id, proposal) for proposal in proposals)
        llm_predictions.update(
            _condition_key(decision.id, proposal)
            for proposal in proposals
            if proposal.source == "llm"
        )
    _print_report("Synthetic override evaluation (LLM free-text vs GT)", llm_predictions, expected)
    _print_report("Synthetic override evaluation (structured + LLM vs GT)", predictions, expected)
    print(f"Evaluated override decisions: {len(decisions)}")
    print(f"Extraction failures: {extraction_failures}")

    examples = _load_gold_examples(gold_dir)
    if not examples:
        print("\nHand-authored gold_set: no JSON/JSONL examples found.")
        return
    gold_predictions: set[ConditionMatch] = set()
    gold_expected: set[ConditionMatch] = set()
    gold_failures = 0
    for index, example in enumerate(examples):
        decision_data = example.get("decision", {})
        decision_data.setdefault("id", f"GOLD{index + 1:04d}")
        decision_data.setdefault("type", "purchase_order")
        decision_data.setdefault("created_at", datetime_now())
        decision_data.setdefault("structured_fields", {})
        decision_data.setdefault("is_override", True)
        decision_data.setdefault("status", "placed")
        decision_data.setdefault("free_text_reason", example.get("reason"))
        decision = DecisionDTO.model_validate(decision_data)
        try:
            extracted = extract_assumptions(decision, connector)
        except Exception as error:
            gold_failures += 1
            print(f"WARNING {decision.id}: gold extraction failed ({type(error).__name__})", file=sys.stderr)
            extracted = []
        gold_predictions.update(_condition_key(decision.id, item) for item in extracted)
        for raw_condition in example.get("conditions", []):
            gold_expected.add(_condition_key(decision.id, Condition.model_validate(raw_condition)))
    _print_report("Hand-authored gold_set evaluation", gold_predictions, gold_expected)
    print(f"Evaluated gold examples: {len(examples)}")
    print(f"Gold extraction failures: {gold_failures}")


def datetime_now() -> str:
    """Return a current UTC ISO timestamp for gold rows without a date."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    """Parse options, connect to PostgreSQL, and print extraction metrics."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-set", type=Path, default=DEFAULT_GOLD_SET)
    args = parser.parse_args()
    with get_session_factory()() as session:
        evaluate(session, args.gold_set)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Evaluation failed: {error}", file=sys.stderr)
        raise