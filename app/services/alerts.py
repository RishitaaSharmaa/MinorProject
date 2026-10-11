"""Best-effort outbound notification when an ingested event breaks assumptions."""

import json
import logging
import urllib.request

from app.config import get_settings
from app.services.ingest import IngestResult

logger = logging.getLogger(__name__)


def notify_violations(result: IngestResult, entity: str, field_name: str) -> None:
    """POST a summary to `ALERT_WEBHOOK_URL`; failures are logged, never raised."""
    url = get_settings().alert_webhook_url
    if not url or not result.violated_assumption_ids:
        return
    payload = {
        "text": (
            f"DecisionWatch: {entity} {field_name} change invalidated assumptions on "
            f"{len(result.violated_decision_ids)} decision(s): {', '.join(result.violated_decision_ids)}"
        ),
        "event_id": result.event_id,
        "decision_ids": list(result.violated_decision_ids),
        "assumption_ids": list(result.violated_assumption_ids),
    }
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=5).close()
    except Exception:  # noqa: BLE001 - alerting must never break ingestion
        logger.warning("alert webhook delivery failed", exc_info=True)
