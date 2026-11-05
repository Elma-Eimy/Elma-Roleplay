"""Own migrations and the lifetime of this application's Outbox task."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from application.banner import print_startup_banner
from application.group_runtime import group_runtime, fail_interrupted_group_candidates
from core.database import run_migrations
from services.infrastructure.outbox_worker import run_outbox_worker
from services.memory.memory_retry_worker import run_memory_retry_worker
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
    with group_runtime() as owner:
        async with _owned_lifespan(app, owner):
            yield


@asynccontextmanager
async def _owned_lifespan(app: FastAPI, owner):
    run_migrations()
    fail_interrupted_group_candidates(owner)
    task = asyncio.create_task(run_outbox_worker(), name="outbox-worker")
    app.state.outbox_task = task
    cleanup_task = asyncio.create_task(run_charx_cleanup(), name="charx-cleanup")
    app.state.charx_cleanup_task = cleanup_task
    memory_task = asyncio.create_task(run_memory_retry_worker(), name="memory-retry")
    app.state.memory_retry_task = memory_task
    try:
        print_startup_banner()
        yield
    finally:
        shutdown = asyncio.create_task(_stop_workers(memory_task, cleanup_task, task), name="application-shutdown")
        cancelled = False
        while True:
            try:
                errors = await asyncio.shield(shutdown)
                break
            except asyncio.CancelledError:
                if shutdown.cancelled():
                    raise
                cancelled = True
        # 所有任务结束后再传播失败或取消，外层此时才可以释放数据库运行权。
        if cancelled:
            raise asyncio.CancelledError
        if errors:
            raise errors[0]


async def _stop_workers(*tasks):
    for task in tasks:
        task.cancel()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    print("[SHUTDOWN] Stopped background outbox worker.")
    await cancel_all_stream_tasks()
    print("[SHUTDOWN] Cleaned up active chat stream workers.")
    return [result for result in results if isinstance(result, Exception)]
