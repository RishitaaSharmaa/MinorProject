"""Acceptance test for bootstrapping a populated review workflow."""

from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models import Assumption, AssumptionProposal, Base, Decision
from scripts.load_dataset import GT_METADATA, load_dataset
from scripts.seed_review_workflow import seed_review_workflow

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data_generator" / "output"


@pytest.fixture
def session() -> Iterator[Session]:
    """Load the real generated dataset into an isolated SQLite database."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    GT_METADATA.create_all(engine)
    with Session(engine, expire_on_commit=False) as database_session:
        load_dataset(database_session, DATA_DIR)
        yield database_session
    engine.dispose()


def test_seed_confirms_structured_proposals_for_every_override(session: Session) -> None:
    """Every override decision gets confirmed, ERP-grounded assumptions."""
    override_count = session.scalar(
        select(func.count()).select_from(Decision).where(Decision.is_override.is_(True))
    )
    assert override_count > 0

    counts = seed_review_workflow(session, as_of=None)

    assert counts["override_decisions"] == override_count
    assert counts["proposals_written"] >= override_count
    assert counts["assumptions_confirmed"] == counts["proposals_written"]

    assumption_total = session.scalar(select(func.count()).select_from(Assumption))
    assert assumption_total == counts["assumptions_confirmed"]
    assert session.scalar(
        select(func.count()).select_from(Assumption).where(Assumption.confirmed_by_user.is_(False))
    ) == 0
    assert session.scalar(
        select(func.count()).select_from(AssumptionProposal).where(AssumptionProposal.review_status != "accepted")
    ) == 0


def test_seed_is_idempotent(session: Session) -> None:
    """Seeding twice must reseed cleanly, not double-confirm the same proposals."""
    from datetime import date

    first = seed_review_workflow(session, as_of=date(2025, 9, 30))
    second = seed_review_workflow(session, as_of=date(2025, 9, 30))

    assert first == second
    assert session.scalar(select(func.count()).select_from(Assumption)) == second["assumptions_confirmed"]
    assert session.scalar(
        select(func.count()).select_from(AssumptionProposal)
    ) == second["proposals_written"]
