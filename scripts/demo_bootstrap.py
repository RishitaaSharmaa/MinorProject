"""Populate an empty database with the demo dataset and a reviewed workflow.

Used by the container start-up when `DEMO_MODE=true`. Idempotent: each step is
skipped when its data is already present, so restarting the stack never
duplicates or resets rows.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import Assumption, Item, StateEvent
from scripts.load_dataset import load_dataset
from scripts.seed_review_workflow import seed_review_workflow


def bootstrap(session: Session) -> None:
    """Load the dataset and seed the review workflow where either is missing."""
    if not session.scalar(select(func.count()).select_from(Item)):
        counts = load_dataset(session)
        print(f"demo: loaded dataset ({sum(counts.values())} rows)")
    else:
        print("demo: dataset already loaded")

    if not session.scalar(select(func.count()).select_from(Assumption)):
        latest = session.scalar(select(func.max(StateEvent.event_time)))
        counts = seed_review_workflow(session, latest.date() if latest else None)
        session.commit()
        print(f"demo: seeded review workflow {counts}")
    else:
        print("demo: review workflow already seeded")


def main() -> None:
    with get_engine().begin() as connection:
        with Session(bind=connection, expire_on_commit=False) as session:
            bootstrap(session)


if __name__ == "__main__":
    main()
