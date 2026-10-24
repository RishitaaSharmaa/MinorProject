"""In-browser entry point: runs the FastAPI app inside Pyodide and calls it in-process.

The page loads this module, calls `init()` once and then `handle()` for every request the UI
would otherwise send to a server. Everything stays in the browser: the database is a SQLite
file on the in-memory filesystem, which the page snapshots into its own IndexedDB.
"""

import json
import sys
from typing import Any

DB_PATH = "/tmp/dw.db"


class _SerialExecutor:
    """Stand-in for ThreadPoolExecutor: WebAssembly has no threads."""

    def __init__(self, *_: Any, **__: Any) -> None:
        pass

    def __enter__(self) -> "_SerialExecutor":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def map(self, func, items):  # noqa: ANN001
        return [func(item) for item in items]


def _run_sync_inline() -> None:
    """Starlette runs sync endpoints in a worker thread; run them inline instead."""
    import anyio.to_thread

    async def run_sync(func, *args, **_kwargs):  # noqa: ANN001
        return func(*args)

    anyio.to_thread.run_sync = run_sync


def init() -> None:
    """Create the schema on the (possibly restored) database file and load the app."""
    assert sys.platform == "emscripten", "app.local only runs inside a browser"
    _run_sync_inline()

    from app.db import get_engine
    from app.models import Base
    from app.services import brief

    brief.ThreadPoolExecutor = _SerialExecutor
    Base.metadata.create_all(get_engine())
    import app.main  # noqa: F401 - registers every route


async def handle(method: str, target: str, body: str | None = None) -> str:
    """Call the API in-process and return `{"status": int, "body": <json or text>}` as JSON."""
    from app.main import app

    path, _, query = target.partition("?")
    payload = (body or "").encode()
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method.upper(),
        "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": query.encode(),
        "root_path": "", "client": ("127.0.0.1", 0), "server": ("local", 80),
        "headers": [(b"host", b"local"), (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode())],
    }
    sent = False
    status = 500
    chunks: list[bytes] = []

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": payload, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    await app(scope, receive, send)
    text = b"".join(chunks).decode()
    try:
        parsed: Any = json.loads(text) if text else None
    except ValueError:
        parsed = text
    return json.dumps({"status": status, "body": parsed})
