"""Own migrations and the lifetime of this application's Outbox task."""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from application.banner import print_startup_banner
from core.database import run_migrations
from services.infrastructure.outbox_worker import run_outbox_worker
from routers.chat import cancel_all_stream_tasks
from services.media.charx_import import cleanup_previews


async def run_charx_cleanup():
    while True:
        try:
            await asyncio.to_thread(cleanup_previews)
        except OSError:
            logging.getLogger(__name__).warning('CHARX 临时资源清理失败，将在下一周期重试', exc_info=True)
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    task = asyncio.create_task(run_outbox_worker(), name="outbox-worker")
    app.state.outbox_task = task
    cleanup_task = asyncio.create_task(run_charx_cleanup(), name="charx-cleanup")
    app.state.charx_cleanup_task = cleanup_task
    try:
        print_startup_banner()
        yield
    finally:
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        print("[SHUTDOWN] Stopped background outbox worker.")
        # 服务关闭或重载时，清理所有正在运行的后台流式 Worker，确保事务安全回滚
        await cancel_all_stream_tasks()
        print("[SHUTDOWN] Cleaned up active chat stream workers.")
