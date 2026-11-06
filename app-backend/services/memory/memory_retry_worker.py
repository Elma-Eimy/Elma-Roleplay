"""Retry memory candidates independently of the vector Outbox worker."""
import asyncio
import logging

from sqlalchemy.orm import Session

from core.database import SessionLocal
from services.memory.group_memory_capture import process_one_capture
from services.memory.memory_extraction_jobs import process_due_jobs


def process_memory_jobs():
    db = SessionLocal()
    try:
        process_due_jobs(db, limit=8)
    finally:
        db.close()


async def run_memory_retry_worker():
    await _poll(process_memory_jobs)


async def run_group_memory_worker(engine):
    def process():
        with Session(engine) as db:
            process_one_capture(db)
    await _poll(process)


async def _poll(process):
    while True:
        work = asyncio.create_task(asyncio.to_thread(process))
        try:
            await asyncio.shield(work)
        except asyncio.CancelledError:
            # The thread owns its session; wait for it before completing shutdown.
            try:
                await work
            except Exception as exc:
                logging.getLogger(__name__).warning("Memory retry stopped error_type=%s", type(exc).__name__)
            raise
        except Exception as exc:
            logging.getLogger(__name__).warning("Memory retry failed error_type=%s", type(exc).__name__)
        await asyncio.sleep(5)
