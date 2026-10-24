"""FastAPI application entrypoint."""

import asyncio
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.workspace import router as workspace_router
from app.config import get_settings

if get_settings().local_mode and sys.platform != "emscripten":
    # Local mode skips authentication because the only caller is the page hosting the engine.
    # On a real server that would be an open door, so refuse to start.
    raise RuntimeError("LOCAL_MODE only runs inside a browser (Pyodide); never enable it on a server")


async def _sync_forever(minutes: int) -> None:
    from app.services.sync import run_scheduled_sync

    while True:
        await asyncio.to_thread(run_scheduled_sync)
        await asyncio.sleep(minutes * 60)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    task = None
    if settings.agent_mode and not settings.local_mode and settings.erp_source and settings.sync_interval_minutes > 0:
        task = asyncio.create_task(_sync_forever(settings.sync_interval_minutes))
    yield
    if task is not None:
        task.cancel()


app = FastAPI(title="DecisionWatch API", version="0.1.0", lifespan=lifespan)

# In agent mode the hosted site's browser code calls this API directly, so allow its origin.
_origins = [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]
if _origins:
    app.add_middleware(
        CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"], max_age=600,
    )

app.include_router(router)
app.include_router(workspace_router)
