"""The memory retry thread owns its session until cancellation has drained it."""
import asyncio
import threading
import unittest
from unittest.mock import patch
from services.memory.memory_retry_worker import run_memory_retry_worker


class MemoryWorkerShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_waits_for_running_work(self):
        await self.check_shutdown(False)

    async def test_shutdown_drains_failed_work_without_masking_cancellation(self):
        await self.check_shutdown(True)

    async def check_shutdown(self, fail):
        started = asyncio.Event()
        release = threading.Event()
        finished = threading.Event()
        loop = asyncio.get_running_loop()

        def work():
            loop.call_soon_threadsafe(started.set)
            try:
                release.wait(2)
            finally:
                finished.set()
            if fail:
                raise RuntimeError("simulated worker error")

        with patch("services.memory.memory_retry_worker.process_memory_jobs", side_effect=work):
            task = asyncio.create_task(run_memory_retry_worker())
            await asyncio.wait_for(started.wait(), 1)
            task.cancel()
            await asyncio.sleep(.01)
            self.assertFalse(task.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(finished.is_set())
