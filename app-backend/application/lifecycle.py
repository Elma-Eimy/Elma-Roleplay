"""Own migrations and the lifetime of this application's Outbox task."""

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from application.banner import print_startup_banner
from core.database import run_migrations
from services.infrastructure.outbox_worker import run_outbox_worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    task = asyncio.create_task(run_outbox_worker(), name="outbox-worker")
    app.state.outbox_task = task
    try:
        print_startup_banner()
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        print("[SHUTDOWN] Stopped background outbox worker.")
