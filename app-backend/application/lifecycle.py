"""Own migrations and the lifetime of this application's Outbox task."""

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from application.banner import print_startup_banner
from core.database import run_migrations
from services.infrastructure.outbox_worker import run_outbox_worker
from routers.chat import cancel_all_stream_tasks


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
        # 服务关闭或重载时，清理所有正在运行的后台流式 Worker，确保事务安全回滚
        await cancel_all_stream_tasks()
        print("[SHUTDOWN] Cleaned up active chat stream workers.")
