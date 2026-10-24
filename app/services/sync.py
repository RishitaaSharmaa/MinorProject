"""Pull data from the configured ERP into the agent's own database.

Rows go through the same validation, reference checks and upserts as a CSV import, so ERP data and
uploaded files are interchangeable. Stock goes through the event pipeline (so a drop below a
decision's assumed level is flagged immediately), and changes to a supplier's lead time or standing
since the previous sync are recorded as state events for the same reason.
"""

import csv
import io
import logging
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ImportRun, Supplier
from app.services import importer
from app.sources import SYNC_DATASETS, ErpSource, SourceError

logger = logging.getLogger(__name__)

#: One sync at a time: a manual run and the schedule must not interleave their writes.
sync_lock = threading.Lock()

SYNC_PREFIX = "sync:"


@dataclass
class DatasetResult:
    dataset: str
    fetched: int = 0
    imported: int = 0
    rejected: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SyncSummary:
    source: str
    started_at: datetime
    finished_at: datetime | None = None
    datasets: list[DatasetResult] = field(default_factory=list)
    change_events: int = 0
    decisions_flagged: int = 0
    warnings: list[str] = field(default_factory=list)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _to_csv(dataset: str, rows: list[dict[str, Any]]) -> tuple[str, dict[str, str]]:
    """Render source rows as CSV with the importer's own field names, plus the identity mapping."""
    spec = importer.DATASETS[dataset]
    present = {key for row in rows for key in row}
    columns = [f.name for f in spec.fields if f.name in present]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_cell(row.get(column)) for column in columns])
    return buffer.getvalue(), {column: column for column in columns}


def _load(session: Session, dataset: str, rows: list[dict[str, Any]], source: str) -> tuple[DatasetResult, int]:
    result = DatasetResult(dataset=dataset, fetched=len(rows))
    flagged = 0
    limit = importer.DATASETS[dataset].max_rows
    for start in range(0, len(rows), limit):
        text, mapping = _to_csv(dataset, rows[start:start + limit])
        analysis = importer.analyze(session, dataset, text, mapping)
        run = importer.commit_import(
            session, analysis, filename=f"{SYNC_PREFIX}{source}", skip_invalid=True, remember_mapping=False,
        )
        result.imported += run.rows_imported
        result.rejected += run.rows_rejected
        result.errors += run.errors_sample[: max(0, 10 - len(result.errors))]
        flagged += run.decisions_flagged
    return result, flagged


def _supplier_state(session: Session) -> dict[str, tuple[int, str]]:
    return {
        row.id: (row.quoted_lead_time_days, row.strike_status)
        for row in session.scalars(select(Supplier))
    }


def _change_events(before: dict[str, tuple[int, str]], after: dict[str, tuple[int, str]]) -> list[dict[str, Any]]:
    """Events for suppliers that already existed and whose lead time or standing changed."""
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d%H%M%S")
    events: list[dict[str, Any]] = []
    for supplier_id, (lead, strike) in after.items():
        previous = before.get(supplier_id)
        if previous is None:
            continue
        for name, old, new in (("lead_time_days", previous[0], lead), ("strike_status", previous[1], strike)):
            if old != new:
                events.append({
                    "entity_type": "supplier", "entity_id": supplier_id, "field": name, "new_value": new,
                    "event_time": now, "event_id": f"sync-{supplier_id}-{name}-{stamp}"[:64],
                })
    return events


def sync_from_source(session: Session, source: ErpSource) -> SyncSummary:
    """Read every dataset from `source` and load it. Raises SourceError if the ERP cannot be read."""
    summary = SyncSummary(source=source.name, started_at=datetime.now(timezone.utc))
    with source:
        before = _supplier_state(session)
        for dataset in SYNC_DATASETS:
            rows = source.fetch(dataset)
            result, flagged = _load(session, dataset, rows, source.name)
            summary.datasets.append(result)
            summary.decisions_flagged += flagged
            if rows and result.imported == 0:
                summary.warnings.append(
                    f"No {dataset} rows were accepted ({result.rejected} rejected); check the first errors below."
                )
        events = _change_events(before, _supplier_state(session))
        if events:
            result, flagged = _load(session, "state_events", events, source.name)
            summary.change_events = result.imported
            summary.decisions_flagged += flagged
    summary.finished_at = datetime.now(timezone.utc)
    return summary


def run_scheduled_sync() -> None:
    """One automatic sync on its own session; failures are logged, never raised."""
    from app.db import get_session_factory
    from app.sources import get_source

    if not sync_lock.acquire(blocking=False):
        return
    try:
        source = get_source()
        if source is None:
            return
        with get_session_factory()() as session:
            summary = sync_from_source(session, source)
        logger.info(
            "scheduled %s sync: %s", summary.source,
            ", ".join(f"{d.dataset}={d.imported}" for d in summary.datasets),
        )
    except Exception:  # noqa: BLE001 - a bad ERP read must not stop the schedule
        logger.exception("scheduled ERP sync failed")
    finally:
        sync_lock.release()


def last_sync_runs(session: Session, limit: int = 8) -> list[ImportRun]:
    return list(session.scalars(
        select(ImportRun).where(ImportRun.filename.like(f"{SYNC_PREFIX}%")).order_by(ImportRun.created_at.desc()).limit(limit)
    ))


__all__ = ["SourceError", "SyncSummary", "DatasetResult", "last_sync_runs", "run_scheduled_sync", "sync_from_source", "sync_lock"]
