"""Deterministic, config-driven scoring for decisions with a broken assumption.

No LLM participates in scoring. Every number in a ``DecisionScore`` is either
grounded in connector-returned point-in-time data (current stock, forecast,
or supplier terms) and catalog facts (unit cost, holding cost), or is an
explicitly config-driven, clearly-marked estimate. That marking feeds
confidence: a score is downgraded when its cost_keep fell back to an
estimate, when the underlying assumption was never confirmed by a planner,
or when the assumption came from an unverified source (an LLM extraction).

The economics:

* ``cost_keep`` prices the exposure of leaving the decision unchanged given
  its broken condition (excess stock, a stockout risk, a forced MOQ top-up,
  supplier risk, or a lost price break).
* For each alternative action (``reduce``, ``delay``, ``cancel``), a
  ``residual_cost`` (the exposure the action leaves behind) and a
  ``switching_cost`` (the fee, in-transit, and commitment-bundle cost of
  taking the action, via ``app.services.graph.sibling_impact``) are priced.
* ``best_alternative`` minimizes ``residual_cost + switching_cost``.
* ``regret`` is the exposure a decision-maker avoids by acting rather than
  keeping (``cost_keep - residual_cost``), independent of what acting costs.
* ``net_benefit = regret - switching_cost`` is what acting is worth after
  paying for it, and a decision is flagged only when that is positive
  (``regret > switching_cost``) and the commitment's reversal window is
  still open.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.connectors.base import AsOf, ERPConnector
from app.models import Assumption, Commitment, Decision, Item
from app.services import graph
from app.services.evaluator import NormalizedCondition, normalize_condition

#: Actions a planner can take instead of keeping a decision unchanged.
ALTERNATIVE_ACTIONS: tuple[str, ...] = ("reduce", "delay", "cancel")
#: Confidence ladder; one step down per triggered downgrade reason.
_CONFIDENCE_LEVELS: tuple[str, ...] = ("high", "medium", "low")


@dataclass(frozen=True)
class ActionCost:
    """One alternative action's priced mitigation and switching cost."""

    action: str
    residual_cost: float
    fee: float
    in_transit: float
    sibling_impact: float

    @property
    def switching_cost(self) -> float:
        """Return the total cost of taking this action."""
        return self.fee + self.in_transit + self.sibling_impact

    @property
    def total_cost(self) -> float:
        """Return the leftover exposure plus the cost of acting."""
        return self.residual_cost + self.switching_cost


@dataclass(frozen=True)
class DecisionScore:
    """Full deterministic scoring breakdown for one decision and its broken assumption."""

    decision_id: str
    assumption_id: str
    order_value: float
    cost_keep: float
    cost_keep_breakdown: dict[str, Any]
    actions: dict[str, ActionCost]
    best_alternative: str
    regret: float
    switching_cost: float
    switching_cost_breakdown: dict[str, float]
    net_benefit: float
    days_to_window: int | None
    window_open: bool
    flagged: bool
    recommendation: str
    confidence: str
    confidence_reasons: tuple[str, ...]
    assumptions_used: dict[str, Any]


def score_violated_decisions(
    session: Session,
    connector: ERPConnector,
    as_of: date | datetime,
    settings: Settings | None = None,
) -> list[DecisionScore]:
    """Score every (decision, assumption) pair with a currently violated assumption."""
    settings = settings or get_settings()
    rows = session.execute(
        select(Decision, Assumption)
        .join(Assumption, Assumption.decision_id == Decision.id)
        .where(Assumption.status == "violated")
        .order_by(Decision.id.asc(), Assumption.id.asc())
    )
    return [
        score_decision(session, connector, decision, assumption, as_of, settings)
        for decision, assumption in rows
    ]


def score_decision(
    session: Session,
    connector: ERPConnector,
    decision: Decision,
    assumption: Assumption,
    as_of: date | datetime,
    settings: Settings | None = None,
) -> DecisionScore:
    """Price cost_keep, every alternative action, and the recommendation for one decision."""
    settings = settings or get_settings()
    order_value = _order_value(decision)
    normalized = normalize_condition(assumption.condition)
    cost_keep, cost_keep_breakdown = _cost_keep(session, connector, decision, normalized, order_value, as_of, settings)

    commitment = session.scalar(select(Commitment).where(Commitment.decision_id == decision.id))
    days_to_window, window_open = _window(commitment, as_of)

    actions = {
        action: _action_cost(session, decision, action, cost_keep, commitment, order_value, as_of, settings)
        for action in ALTERNATIVE_ACTIONS
    }
    best_alternative = min(actions, key=lambda name: actions[name].total_cost)
    best = actions[best_alternative]

    regret = cost_keep - best.residual_cost
    switching_cost = best.switching_cost
    net_benefit = regret - switching_cost
    flagged = regret > switching_cost and window_open
    recommendation = best_alternative if flagged else "keep"
    confidence, confidence_reasons = _confidence(cost_keep_breakdown, assumption)

    return DecisionScore(
        decision_id=decision.id,
        assumption_id=assumption.id,
        order_value=order_value,
        cost_keep=cost_keep,
        cost_keep_breakdown=cost_keep_breakdown,
        actions=actions,
        best_alternative=best_alternative,
        regret=regret,
        switching_cost=switching_cost,
        switching_cost_breakdown={
            "fee": best.fee, "in_transit": best.in_transit, "sibling_impact": best.sibling_impact,
        },
        net_benefit=net_benefit,
        days_to_window=days_to_window,
        window_open=window_open,
        flagged=flagged,
        recommendation=recommendation,
        confidence=confidence,
        confidence_reasons=confidence_reasons,
        assumptions_used={
            "condition": assumption.condition,
            "normalized_type": normalized.condition_type,
            "entity": normalized.entity,
            "field": normalized.field,
            "operator": normalized.operator,
            "expected_value": normalized.expected_value,
            "confirmed_by_user": assumption.confirmed_by_user,
            "source": assumption.source,
        },
    )


def _cost_keep(
    session: Session,
    connector: ERPConnector,
    decision: Decision,
    normalized: NormalizedCondition,
    order_value: float,
    as_of: date | datetime,
    settings: Settings,
) -> tuple[float, dict[str, Any]]:
    """Price the exposure of leaving `decision` unchanged given its broken condition."""
    item = session.get(Item, decision.item_id) if decision.item_id else None
    current_value = _current_field_value(connector, normalized.entity, normalized.field, as_of)
    expected_value = normalized.expected_value
    condition_type = normalized.condition_type

    def fallback(reason: str) -> tuple[float, dict[str, Any]]:
        cost = order_value * settings.scoring_default_exposure_pct
        return cost, {
            "method": "default_exposure_pct",
            "estimated": True,
            "reason": reason,
            "order_value": order_value,
            "exposure_pct": settings.scoring_default_exposure_pct,
        }

    #: These two condition types are inherently status-based (a risk state or the
    #: presence of a discount tier), so they are always priced as a flat exposure
    #: rather than from a numeric severity, independent of whether a current value
    #: was available.
    if condition_type in {"supplier_risk_open", "supplier_risk_resolved"}:
        cost = order_value * settings.scoring_supplier_risk_exposure_pct
        return cost, {
            "method": condition_type,
            "estimated": False,
            "order_value": order_value,
            "exposure_pct": settings.scoring_supplier_risk_exposure_pct,
        }
    if condition_type == "price_break_available":
        cost = order_value * settings.scoring_price_break_loss_pct
        return cost, {
            "method": condition_type,
            "estimated": False,
            "order_value": order_value,
            "exposure_pct": settings.scoring_price_break_loss_pct,
        }

    if current_value is None:
        return fallback("current value unavailable from the connector")

    if item is None:
        return fallback(f"no catalog item to price {condition_type!r} against")

    if condition_type in {"stock_lt", "forecast_gte"}:
        excess = float(current_value) - float(expected_value)
        if excess <= 0:
            return fallback(f"{condition_type} violated without a measurable excess")
        cost = excess * float(item.unit_cost) * float(item.holding_cost_pct)
        return cost, {
            "method": condition_type, "estimated": False,
            "current_value": current_value, "expected_value": expected_value,
            "excess_units": excess, "unit_cost": float(item.unit_cost),
            "holding_cost_pct": float(item.holding_cost_pct),
        }

    if condition_type in {"stock_gt", "forecast_lte"}:
        shortfall = float(expected_value) - float(current_value)
        if shortfall <= 0:
            return fallback(f"{condition_type} violated without a measurable shortfall")
        cost = shortfall * float(item.unit_cost) * settings.scoring_stockout_multiplier
        return cost, {
            "method": condition_type, "estimated": False,
            "current_value": current_value, "expected_value": expected_value,
            "shortfall_units": shortfall, "unit_cost": float(item.unit_cost),
            "stockout_multiplier": settings.scoring_stockout_multiplier,
        }

    if condition_type == "lead_time_lte":
        extra_days = float(current_value) - float(expected_value)
        if extra_days <= 0:
            return fallback("lead_time_lte violated without a measurable delay")
        cost = extra_days * float(item.avg_daily_demand) * float(item.unit_cost) * settings.scoring_stockout_multiplier
        return cost, {
            "method": condition_type, "estimated": False,
            "current_value": current_value, "expected_value": expected_value,
            "extra_days": extra_days, "avg_daily_demand": item.avg_daily_demand,
            "unit_cost": float(item.unit_cost), "stockout_multiplier": settings.scoring_stockout_multiplier,
        }

    if condition_type == "moq_lte" and decision.quantity is not None:
        shortfall = float(current_value) - float(decision.quantity)
        if shortfall <= 0:
            return fallback("moq_lte violated without a measurable top-up requirement")
        cost = shortfall * float(item.unit_cost) * settings.scoring_topup_penalty_pct
        return cost, {
            "method": condition_type, "estimated": False,
            "current_moq": current_value, "order_quantity": decision.quantity,
            "shortfall_units": shortfall, "unit_cost": float(item.unit_cost),
            "topup_penalty_pct": settings.scoring_topup_penalty_pct,
        }

    return fallback(f"no grounded cost model for condition type {condition_type!r}")


def _current_field_value(connector: ERPConnector, entity: str, field: str, as_of: AsOf) -> Any:
    """Read the current value the connector reports for one (entity, field) pair."""
    if ":" not in entity:
        return None
    entity_type, entity_id = entity.split(":", 1)
    if entity_type == "item":
        if field == "stock_qty":
            return connector.get_stock(entity_id, as_of)
        if field == "forecast_qty":
            return connector.get_forecast(entity_id, as_of)
        return None
    if entity_type == "supplier":
        terms = connector.get_supplier_terms(entity_id, as_of)
        return {
            "lead_time_days": terms.quoted_lead_time,
            "quoted_lead_time": terms.quoted_lead_time,
            "moq": terms.moq,
            "price_break_tiers": terms.price_break_tiers,
            "strike_status": terms.strike_status,
        }.get(field)
    return None


def _action_cost(
    session: Session,
    decision: Decision,
    action: str,
    cost_keep: float,
    commitment: Commitment | None,
    order_value: float,
    as_of: date | datetime,
    settings: Settings,
) -> ActionCost:
    """Price one alternative action's residual exposure and switching cost.

    Each action has its own mitigation fraction (how much of cost_keep it
    removes) and its own fee/in-transit fraction (how much of the
    commitment's cancellation fee and in-transit cost it triggers): cancel
    removes all the exposure and pays the full fee; reduce removes and pays
    a config-driven fraction of both; delay removes a separate mitigation
    fraction but, since it never stops or shrinks the shipment, only pays a
    small rebooking-style fraction of the fee and no in-transit cost.
    """
    in_transit = decision.po_date is not None and _as_date(as_of) >= decision.po_date
    fee_pct = commitment.cancellation_fee_pct if commitment is not None else 0.0

    if action == "cancel":
        mitigation, fee_fraction, in_transit_fraction = 1.0, 1.0, 1.0
    elif action == "reduce":
        mitigation = fee_fraction = in_transit_fraction = settings.scoring_reduce_fraction
    elif action == "delay":
        mitigation = settings.scoring_delay_mitigation
        fee_fraction = settings.scoring_delay_fee_fraction
        in_transit_fraction = 0.0
    else:
        raise ValueError(f"Unsupported alternative action: {action!r}")

    fee = order_value * fee_fraction * fee_pct
    in_transit_cost = order_value * in_transit_fraction * settings.scoring_in_transit_cost_pct if in_transit else 0.0
    sibling_impact = graph.sibling_impact(session, decision.id, action)
    residual_cost = cost_keep * (1.0 - mitigation)
    return ActionCost(
        action=action, residual_cost=residual_cost, fee=fee,
        in_transit=in_transit_cost, sibling_impact=sibling_impact,
    )


def _confidence(cost_keep_breakdown: dict[str, Any], assumption: Assumption) -> tuple[str, tuple[str, ...]]:
    """Downgrade confidence once per estimated, unconfirmed, or credibility-flagged input."""
    reasons: list[str] = []
    if cost_keep_breakdown.get("estimated"):
        reasons.append("cost_keep used a default exposure estimate, not grounded ERP data")
    if not assumption.confirmed_by_user:
        reasons.append("assumption was never confirmed by a planner")
    if assumption.source == "llm":
        reasons.append("assumption was extracted by an LLM and is credibility-flagged")
    level = _CONFIDENCE_LEVELS[min(len(reasons), len(_CONFIDENCE_LEVELS) - 1)]
    return level, tuple(reasons)


def _window(commitment: Commitment | None, as_of: date | datetime) -> tuple[int | None, bool]:
    """Return days remaining before the commitment's reversal window closes, and whether it's open."""
    if commitment is None:
        return None, True
    days = (commitment.reversible_until - _as_date(as_of)).days
    return days, days >= 0


def _order_value(decision: Decision) -> float:
    """Compute PO value from recorded quantity and unit price without inventing zeros."""
    if decision.quantity is None or decision.unit_price is None:
        return 0.0
    return float(decision.quantity) * float(decision.unit_price)


def _as_date(value: date | datetime) -> date:
    """Normalize a simulated timestamp to its calendar date."""
    return value.date() if isinstance(value, datetime) else value
