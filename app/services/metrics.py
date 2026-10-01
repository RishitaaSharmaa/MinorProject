"""Operational metrics for the review workflow."""

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.base import ERPConnector
from app.models import Assumption, AssumptionProposal, AssumptionViolation, Decision, Outcome
from app.services.scoring import score_decision


@dataclass(frozen=True)
class Metrics:
    """Operational counters surfaced on the metrics dashboard."""

    flags_per_week: dict[str, int]
    action_rate: float
    extraction_correction_rate: float


def compute_metrics(session: Session, connector: ERPConnector, as_of: date | datetime) -> Metrics:
    """Compute deterministic operational metrics as of one simulated date."""
    return Metrics(
        flags_per_week=_flags_per_week(session, connector, as_of),
        action_rate=_action_rate(session),
        extraction_correction_rate=_extraction_correction_rate(session),
    )


def _flags_per_week(session: Session, connector: ERPConnector, as_of: date | datetime) -> dict[str, int]:
    """Count, per ISO week of detection, violations whose decision is still flag-worthy."""
    rows = session.execute(
        select(AssumptionViolation, Assumption, Decision)
        .join(Assumption, Assumption.id == AssumptionViolation.assumption_id)
        .join(Decision, Decision.id == Assumption.decision_id)
        .where(Assumption.status == "violated")
    )
    counts: Counter[str] = Counter()
    for violation, assumption, decision in rows:
        score = score_decision(session, connector, decision, assumption, as_of)
        if score.flagged:
            iso_week = violation.detected_at.isocalendar()
            counts[f"{iso_week.year}-W{iso_week.week:02d}"] += 1
    return dict(sorted(counts.items()))


def _action_rate(session: Session) -> float:
    """Fraction of decisions with a currently violated assumption that have a logged outcome."""
    exposed = set(session.scalars(
        select(Assumption.decision_id).where(Assumption.status == "violated").distinct()
    ))
    if not exposed:
        return 0.0
    acted = set(session.scalars(select(Outcome.decision_id).where(Outcome.decision_id.in_(exposed))))
    return len(acted) / len(exposed)


def _extraction_correction_rate(session: Session) -> float:
    """Fraction of reviewed extraction proposals a planner had to edit or reject."""
    reviewed = list(session.scalars(
        select(AssumptionProposal.review_status).where(AssumptionProposal.review_status != "pending")
    ))
    if not reviewed:
        return 0.0
    corrected = sum(1 for status in reviewed if status in {"edited", "rejected"})
    return corrected / len(reviewed)
