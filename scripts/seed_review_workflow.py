"""Bootstrap a populated review workflow on top of a freshly loaded dataset.

`scripts.load_dataset` intentionally never writes operational `Assumption`
rows: those come only from a planner extracting and confirming proposals, so
the app never silently trusts the generator's hidden answer key. That means
a freshly loaded database has an empty `/brief` no matter how rich the
underlying dataset is, until someone works through extract-then-confirm one
decision at a time.

This script does exactly that extraction-and-confirmation for every override
decision, in bulk, using only the deterministic, ERP-grounded structured
proposals (`include_llm=False` -- no LLM provider required, fully
repeatable), and persists them through the same `AssumptionProposal` ->
`Assumption` path the real API routes use. It then runs one recheck pass
across the whole simulated calendar so `Assumption.status` and
`AssumptionViolation` history are populated too. Run it once after
`load_dataset` to see the full review workflow -- confirmed assumptions,
violations, and a non-empty morning brief -- in the UI immediately.
"""

import argparse
from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.connectors.factory import get_connector
from app.db import get_engine
from app.models import Assumption, AssumptionProposal, AssumptionViolation, Decision
from app.services.extraction import extract_assumptions
from app.services.watcher_runner import recheck_assumptions


def seed_review_workflow(session: Session, as_of: date | None = None) -> dict[str, int]:
    """Confirm every structured proposal for every override decision, then recheck.

    Safe to rerun: any proposals/assumptions this script previously wrote for
    an override decision are cleared first (explicitly, in FK-safe order, not
    relying on ON DELETE CASCADE so this also works against SQLite), so a
    second run reseeds cleanly instead of duplicating everything.
    """
    connector = get_connector(session)
    decisions = list(session.scalars(
        select(Decision).where(Decision.is_override.is_(True)).order_by(Decision.id)
    ))
    decision_ids = [decision.id for decision in decisions]
    if decision_ids:
        prior_assumption_ids = session.scalars(
            select(Assumption.id).where(Assumption.decision_id.in_(decision_ids))
        ).all()
        if prior_assumption_ids:
            session.execute(
                delete(AssumptionViolation).where(AssumptionViolation.assumption_id.in_(prior_assumption_ids))
            )
        session.execute(delete(Assumption).where(Assumption.decision_id.in_(decision_ids)))
        session.execute(delete(AssumptionProposal).where(AssumptionProposal.decision_id.in_(decision_ids)))
        session.flush()

    now = datetime.now(timezone.utc)
    proposals_written = 0
    assumptions_confirmed = 0
    for decision in decisions:
        decision_dto = connector.get_decision(decision.id)
        proposals = extract_assumptions(decision_dto, connector, as_of=decision.created_at, include_llm=False)
        for proposal in proposals:
            condition = proposal.model_dump(
                include={"type", "entity_ref", "op", "value", "needs_value_from_planner"}, mode="json",
            )
            session.add(AssumptionProposal(
                id=proposal.proposal_id, decision_id=decision.id, condition=condition,
                source=proposal.source, confidence=proposal.confidence, warnings=proposal.warnings,
                review_status="accepted", final_condition=condition, created_at=now, reviewed_at=now,
            ))
            proposals_written += 1
            session.add(Assumption(
                id=str(uuid4()), decision_id=decision.id, condition=condition,
                source=proposal.source, confirmed_by_user=True, status="live", created_at=now,
            ))
            assumptions_confirmed += 1
    session.commit()

    summary = recheck_assumptions(session, as_of or date.today())
    return {
        "override_decisions": len(decisions),
        "proposals_written": proposals_written,
        "assumptions_confirmed": assumptions_confirmed,
        "events_processed": summary.events_processed,
        "violations": summary.violations,
    }


def main() -> None:
    """Seed the review workflow for every override decision in the current database."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of", type=date.fromisoformat, default=None,
        help="Recheck point-in-time cutoff (YYYY-MM-DD); defaults to today.",
    )
    args = parser.parse_args()
    with get_engine().begin() as connection:
        with Session(bind=connection, expire_on_commit=False) as session:
            counts = seed_review_workflow(session, args.as_of)
    for key, value in counts.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
