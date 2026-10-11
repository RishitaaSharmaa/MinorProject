"""MCP server exposing DecisionWatch to AI agents (stdio by default).

It is a thin client over the REST API and never touches the database, so the
deterministic flagging rules stay in one place. Tools are read-only plus
`suggest_action` (advisory) and `ingest_event`; recording a decision's outcome
is only registered when `DECISIONWATCH_MCP_ALLOW_WRITES=true`.

Environment:
    DECISIONWATCH_API_URL   default http://localhost:8000
    INGEST_API_KEY          required for `ingest_event`
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP

API_URL = os.environ.get("DECISIONWATCH_API_URL", "http://localhost:8000").rstrip("/")
INGEST_KEY = os.environ.get("INGEST_API_KEY", "")
ALLOW_WRITES = os.environ.get("DECISIONWATCH_MCP_ALLOW_WRITES", "").lower() == "true"

mcp = FastMCP("decisionwatch")


def _call(method: str, path: str, params: dict[str, Any] | None = None,
          body: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Any:
    """Call the REST API and return parsed JSON, or raise with the API's detail."""
    query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
    request = urllib.request.Request(
        f"{API_URL}{path}{'?' + query if query else ''}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise RuntimeError(f"DecisionWatch API {error.code}: {detail}") from error


@mcp.tool()
def get_morning_brief(as_of: str | None = None, limit: int = 10) -> Any:
    """Ranked purchase decisions whose recorded assumptions have broken and whose
    estimated regret exceeds the cost of switching. `as_of` is YYYY-MM-DD (default today)."""
    if as_of:
        _call("POST", "/events/recheck", {"as_of": as_of})
    return _call("GET", "/brief", {"as_of": as_of, "limit": limit})


@mcp.tool()
def get_decision(decision_id: str, as_of: str | None = None) -> Any:
    """Full detail for one decision: assumptions and status, cost breakdown, event timeline."""
    return _call("GET", f"/decisions/{urllib.parse.quote(decision_id)}", {"as_of": as_of})


@mcp.tool()
def suggest_action(decision_id: str, as_of: str | None = None) -> Any:
    """Advisory LLM suggestion (keep/reduce/delay/cancel) for a decision with a broken
    assumption. It never changes flagging or ranking."""
    return _call("POST", f"/decisions/{urllib.parse.quote(decision_id)}/suggestion", {"as_of": as_of})


@mcp.tool()
def ingest_event(entity_type: str, entity_id: str, field: str, new_value: Any,
                 old_value: Any = None, event_time: str | None = None,
                 event_id: str | None = None) -> Any:
    """Report a real-world change (e.g. entity_type='item', entity_id='SKU001',
    field='stock_qty', new_value=12). Returns which decisions it just invalidated.
    Pass a stable `event_id` to make retries safe."""
    if not INGEST_KEY:
        raise RuntimeError("INGEST_API_KEY is not set for the MCP server")
    return _call("POST", "/events", headers={"X-API-Key": INGEST_KEY}, body={
        "id": event_id, "entity_type": entity_type, "entity_id": entity_id, "field": field,
        "new_value": new_value, "old_value": old_value, "event_time": event_time,
    })


@mcp.tool()
def get_metrics(as_of: str | None = None) -> Any:
    """Aggregate precision, regret and savings metrics."""
    return _call("GET", "/metrics", {"as_of": as_of})


if ALLOW_WRITES:

    @mcp.tool()
    def record_action(decision_id: str, action: str, note: str = "") -> Any:
        """Record the chosen disposition (keep|reduce|delay|cancel) for a decision.
        Registered only when DECISIONWATCH_MCP_ALLOW_WRITES=true."""
        return _call("POST", f"/decisions/{urllib.parse.quote(decision_id)}/action",
                     body={"action": action, "note": note})


def main() -> None:
    """Serve over stdio, or HTTP when `--http` is passed."""
    import sys

    if "--http" in sys.argv:
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
