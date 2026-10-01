"""Structured and LLM-assisted extraction of decision assumptions."""

import json
import logging
import statistics
from datetime import date, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.connectors.base import ERPConnector
from app.connectors.dto import DecisionDTO
from app.services.conditions import Condition, ProposedCondition
from llm.client import complete_json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Extract checkable conditions from a procurement decision reason.
Allowed condition types: forecast_gte, forecast_lte, stock_lt, stock_gt,
lead_time_lte, supplier_risk_open, supplier_risk_resolved, moq_lte,
price_break_available.
Extract ONLY what is stated or clearly implied. Never invent numbers. If a value
is not stated or grounded in the supplied structured decision context, use null
and set needs_value_from_planner=true. Handle common Hinglish and procurement
shorthand, preserving the speaker's actual meaning. Use entity_ref only from the
provided item/supplier references. Return one JSON object matching the schema."""


class _ExtractedCondition(Condition):
    """Validated model response for one free-text condition proposal."""

    confidence: float = Field(ge=0.0, le=1.0)


class _ExtractionResponse(BaseModel):
    """Validated LLM response containing candidate assumptions."""

    model_config = ConfigDict(extra="forbid")

    conditions: list[_ExtractedCondition]


def extract_assumptions(
    decision: DecisionDTO,
    connector: ERPConnector,
    as_of: date | datetime | None = None,
    include_llm: bool = True,
) -> list[ProposedCondition]:
    """Extract deterministic structured conditions and free-text proposals.

    Pass `include_llm=False` to skip the free-text LLM pass and return only
    the structured, ERP-grounded proposals -- deterministic, and usable
    without an LLM provider configured (e.g. for bulk/offline seeding).
    """
    simulated_time = as_of if as_of is not None else decision.created_at
    proposals = _structured_proposals(decision, connector, simulated_time)
    if not include_llm or not decision.free_text_reason or not decision.free_text_reason.strip():
        return proposals

    context = {
        "decision": decision.model_dump(mode="json"),
        "simulated_as_of": simulated_time.isoformat() if simulated_time else None,
    }
    try:
        extracted = complete_json(
            SYSTEM_PROMPT,
            json.dumps(context, ensure_ascii=True),
            _ExtractionResponse,
        )
    except Exception:
        # The LLM step augments the deterministic, ERP-grounded proposals above;
        # a bad response, rate limit, or outage should not discard those.
        logger.warning(
            "LLM extraction failed for decision %s; returning structured proposals only",
            decision.id, exc_info=True,
        )
        return proposals
    seen = {_condition_key(proposal) for proposal in proposals}
    for draft in extracted.conditions:
        condition = Condition(
            type=draft.type,
            entity_ref=draft.entity_ref,
            op=draft.op,
            value=draft.value,
            needs_value_from_planner=draft.needs_value_from_planner,
        )
        proposal = _proposal(
            condition,
            source="llm",
            confidence=draft.confidence,
            connector=connector,
            supplier_id=decision.supplier_id,
            as_of=simulated_time,
        )
        key = _condition_key(proposal)
        if key not in seen:
            proposals.append(proposal)
            seen.add(key)
    return proposals


def _structured_proposals(
    decision: DecisionDTO,
    connector: ERPConnector,
    as_of: date | datetime,
) -> list[ProposedCondition]:
    """Derive candidate conditions from decision facts and point-in-time ERP values."""
    fields = decision.structured_fields
    item_id = decision.item_id or _optional_string(fields.get("item_id"))
    supplier_id = decision.supplier_id or _optional_string(fields.get("supplier_id"))
    proposals: list[ProposedCondition] = []

    if item_id:
        item_ref = f"item:{item_id}"
        stock = connector.get_stock(item_id, as_of)
        if stock > 0:
            proposals.append(_proposal(
                Condition(type="stock_lt", entity_ref=item_ref, op="<", value=stock + 1),
                source="structured",
                confidence=0.85,
                connector=connector,
                supplier_id=supplier_id,
                as_of=as_of,
            ))
        forecast = connector.get_forecast(item_id, as_of)
        if forecast > 0:
            proposals.append(_proposal(
                Condition(type="forecast_gte", entity_ref=item_ref, op=">=", value=forecast),
                source="structured",
                confidence=0.9,
                connector=connector,
                supplier_id=supplier_id,
                as_of=as_of,
            ))

    if supplier_id:
        terms = connector.get_supplier_terms(supplier_id, as_of)
        supplier_ref = f"supplier:{supplier_id}"
        proposals.append(_proposal(
            Condition(
                type="lead_time_lte",
                entity_ref=supplier_ref,
                op="<=",
                value=terms.quoted_lead_time,
            ),
            source="structured",
            confidence=0.9,
            connector=connector,
            supplier_id=supplier_id,
            as_of=as_of,
        ))
        risk_condition: Condition | None = None
        if terms.strike_status.lower() in {"open", "strike", "active", "at_risk"}:
            risk_condition = Condition(
                type="supplier_risk_open", entity_ref=supplier_ref, op="==", value="open"
            )
        elif terms.strike_status.lower() in {"clear", "resolved", "none"}:
            risk_condition = Condition(
                type="supplier_risk_resolved", entity_ref=supplier_ref, op="==", value="resolved"
            )
        if risk_condition is not None:
            proposals.append(_proposal(
                risk_condition,
                source="structured",
                confidence=0.9,
                connector=connector,
                supplier_id=supplier_id,
                as_of=as_of,
            ))

        quantity = decision.quantity or _optional_int(fields.get("order_qty"))
        if quantity is not None and quantity >= terms.moq:
            proposals.append(_proposal(
                Condition(type="moq_lte", entity_ref=supplier_ref, op="<=", value=quantity),
                source="structured",
                confidence=0.95,
                connector=connector,
                supplier_id=supplier_id,
                as_of=as_of,
            ))
        if quantity is not None and any(
            quantity >= int(tier.get("min_qty", 0)) for tier in terms.price_break_tiers
        ):
            proposals.append(_proposal(
                Condition(
                    type="price_break_available",
                    entity_ref=supplier_ref,
                    op="==",
                    value=True,
                ),
                source="structured",
                confidence=0.9,
                connector=connector,
                supplier_id=supplier_id,
                as_of=as_of,
            ))
    return _deduplicate(proposals)


def _proposal(
    condition: Condition,
    source: Literal["structured", "llm"],
    confidence: float,
    connector: ERPConnector,
    supplier_id: str | None,
    as_of: date | datetime | None = None,
) -> ProposedCondition:
    """Attach identity, provenance, confidence, and a historical optimism warning."""
    warnings: list[str] = []
    if condition.type == "lead_time_lte" and supplier_id and isinstance(condition.value, (int, float)):
        historical = connector.get_supplier_actual_lead_times(supplier_id, as_of)
        if historical:
            median = statistics.median(historical)
            if float(condition.value) < median:
                warnings.append(
                    f"Stated lead time {condition.value:g} days is optimistic versus "
                    f"historical median {median:g} days ({len(historical)} deliveries)."
                )
    return ProposedCondition(
        **condition.model_dump(),
        proposal_id=str(uuid4()),
        source=source,
        confidence=confidence,
        warnings=warnings,
    )


def _condition_key(condition: ProposedCondition) -> tuple[str, str, str, str]:
    """Build a stable deduplication key for equivalent proposals."""
    return (
        condition.type,
        condition.entity_ref,
        condition.op,
        json.dumps(condition.value, sort_keys=True),
    )


def _deduplicate(proposals: list[ProposedCondition]) -> list[ProposedCondition]:
    """Keep the first deterministic occurrence of each proposal."""
    seen: set[tuple[str, str, str, str]] = set()
    unique: list[ProposedCondition] = []
    for proposal in proposals:
        key = _condition_key(proposal)
        if key not in seen:
            seen.add(key)
            unique.append(proposal)
    return unique


def _optional_string(value: Any) -> str | None:
    """Return a non-empty identifier if the structured value is string-like."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_int(value: Any) -> int | None:
    """Convert an optional numeric structured value to an integer."""
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _optional_float(value: Any) -> float | None:
    """Convert an optional numeric structured value to a float."""
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None