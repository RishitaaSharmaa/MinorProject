"""Rank violated decisions into a daily, deterministic action brief.

Ranking and flagging are entirely deterministic (``app.services.scoring``);
the only optional LLM involvement is a short, grounded explanation attached
to each card, which is discarded whenever it states a number that does not
appear in that card's own arithmetic breakdown.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.connectors.base import ERPConnector
from app.services.scoring import DecisionScore, score_violated_decisions
from llm.client import complete_json

_EXPLANATION_SYSTEM_PROMPT = (
    "Explain in exactly two short sentences why this procurement decision was flagged "
    "and what is recommended. A decision is flagged when the regret of keeping it exceeds the "
    "switching cost of the recommended action; net_benefit is regret minus switching_cost. "
    "State only numbers that already appear in the supplied data, exactly as given. "
    "Never invent, round, or introduce any other figure."
)
_NUMBER_PATTERN = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_EXPLANATION_WORKERS = 5
_EXPLANATION_ATTEMPTS = 3
_CACHE_LIMIT = 512
#: Successful explanations keyed by their exact LLM input, so revisiting a date is instant.
_explanation_cache: dict[str, str] = {}


@dataclass(frozen=True)
class BriefCard:
    """One flagged decision, with its full score and an optional grounded explanation."""

    score: DecisionScore
    explanation: str | None


@dataclass(frozen=True)
class Brief:
    """A ranked, deterministic morning brief for one simulated date."""

    as_of: date
    cards: tuple[BriefCard, ...]
    reviewed_and_kept: int


class _Explanation(BaseModel):
    """Validated two-sentence explanation returned by the LLM."""

    model_config = ConfigDict(extra="forbid")

    explanation: str = Field(min_length=1, max_length=400)


def generate_brief(
    session: Session,
    connector: ERPConnector,
    as_of: date | datetime,
    limit: int = 10,
    explain: bool = False,
    settings: Settings | None = None,
) -> Brief:
    """Score every violated decision and rank the actionable ones for review.

    Only decisions worth acting on are returned (``flagged``); everything
    else is folded into ``reviewed_and_kept`` so a clean brief never hides
    that the rest of the portfolio was checked and needed nothing.
    """
    settings = settings or get_settings()
    scores = score_violated_decisions(session, connector, as_of, settings)
    best_per_decision = _best_score_per_decision(scores)

    flagged = sorted((score for score in best_per_decision.values() if score.flagged), key=_rank_key)
    reviewed_and_kept = sum(1 for score in best_per_decision.values() if not score.flagged)

    shown = flagged[:limit]
    if explain and shown:
        with ThreadPoolExecutor(max_workers=_EXPLANATION_WORKERS) as pool:
            explanations = list(pool.map(_explain, shown))
    else:
        explanations = [None] * len(shown)
    cards = tuple(BriefCard(score=score, explanation=text) for score, text in zip(shown, explanations))
    return Brief(as_of=_as_date(as_of), cards=cards, reviewed_and_kept=reviewed_and_kept)


def _best_score_per_decision(scores: list[DecisionScore]) -> dict[str, DecisionScore]:
    """Keep the highest-net-benefit broken assumption per decision."""
    best: dict[str, DecisionScore] = {}
    for score in scores:
        current = best.get(score.decision_id)
        if current is None or score.net_benefit > current.net_benefit:
            best[score.decision_id] = score
    return best


def _rank_key(score: DecisionScore) -> tuple[float, int]:
    """Rank by net benefit descending, tie-broken by the earliest reversal deadline."""
    deadline = score.days_to_window if score.days_to_window is not None else 10**9
    return (-score.net_benefit, deadline)


def _explain(score: DecisionScore) -> str | None:
    """Generate a two-sentence explanation, discarding it if it cites an ungrounded number."""
    user_payload = {
        "decision_id": score.decision_id,
        "recommendation": score.recommendation,
        "regret": round(score.regret, 2),
        "switching_cost": round(score.switching_cost, 2),
        "net_benefit": round(score.net_benefit, 2),
        "days_to_window": score.days_to_window,
        "assumptions_used": score.assumptions_used,
    }
    key = json.dumps(user_payload, default=str, sort_keys=True)
    if key in _explanation_cache:
        return _explanation_cache[key]
    supplied = numbers_in(key)
    for _ in range(_EXPLANATION_ATTEMPTS):
        try:
            result = complete_json(_EXPLANATION_SYSTEM_PROMPT, key, _Explanation)
        except Exception:
            continue
        if not _only_uses_grounded_numbers(result.explanation, score, supplied):
            continue
        if len(_explanation_cache) >= _CACHE_LIMIT:
            _explanation_cache.clear()
        _explanation_cache[key] = result.explanation
        return result.explanation
    return None


def numbers_in(payload: str) -> set[float]:
    """Collect every number an LLM was actually shown, so citing them back is allowed."""
    return {float(match.replace(",", "")) for match in _NUMBER_PATTERN.findall(payload)}


def _only_uses_grounded_numbers(text: str, score: DecisionScore, extra_allowed: set[float] | None = None) -> bool:
    """Reject text that states any number absent from the score's breakdown (or `extra_allowed`)."""
    allowed = _grounded_numbers(score) | (extra_allowed or set())
    for match in _NUMBER_PATTERN.findall(text):
        stated = float(match.replace(",", ""))
        if not any(abs(stated - value) <= max(0.5, abs(value) * 0.01) for value in allowed):
            return False
    return True


def _grounded_numbers(score: DecisionScore) -> set[float]:
    """Collect every number that legitimately appears in one decision's breakdown."""
    values = {
        score.order_value, score.cost_keep, score.regret,
        score.switching_cost, score.net_benefit,
    }
    if score.days_to_window is not None:
        values.add(float(score.days_to_window))
    for action_cost in score.actions.values():
        values.update({
            action_cost.residual_cost, action_cost.fee, action_cost.in_transit,
            action_cost.sibling_impact, action_cost.switching_cost, action_cost.total_cost,
        })
    return {round(value, 2) for value in values}


def _as_date(value: date | datetime) -> date:
    """Normalize a simulated timestamp to its calendar date."""
    return value.date() if isinstance(value, datetime) else value
