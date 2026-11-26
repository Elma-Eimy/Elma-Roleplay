"""单聊维护线程的应用归属、关闭等待和入口登记回归。"""

import asyncio
from contextlib import contextmanager
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import BackgroundTasks, FastAPI

from application import chat_maintenance as maintenance
from application.lifecycle import lifespan
from core.locking import GroupRuntimeOwner, get_session_lock
from routers import chat
from schemas import ChatRequest


class ChatMaintenanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runtime_patch = patch.object(maintenance, "_runtime", None)
        self.runtime_patch.start()
        self.addCleanup(self.runtime_patch.stop)

    async def asyncTearDown(self):
        if maintenance._runtime:
            await maintenance._runtime.stop()

    async def test_shutdown_waits_for_model_and_database_close_despite_repeated_cancellation(self):
        started, release = threading.Event(), threading.Event()
        unlocked = []
        app = FastAPI()
        db = MagicMock()

        def model(*args):
            started.set()
            if not release.wait(5):
                raise RuntimeError("test did not release model")
            return "认知结果"

        @contextmanager
        def runtime():
            try:
                yield GroupRuntimeOwner(object())
            finally:
                unlocked.append((db.close.call_count, not app.state.chat_maintenance.tasks))

        async def worker(*args):
            await asyncio.Event().wait()

        async def serve():
            async with lifespan(app):
                maintenance.schedule_post_turn_maintenance(10, 20)
                await asyncio.Event().wait()

        turn = maintenance.chat_turn_service
        with (patch("application.lifecycle.group_runtime", runtime),
              patch("application.lifecycle.run_migrations"),
              patch("application.lifecycle.fail_interrupted_group_candidates"),
              patch("application.lifecycle.run_outbox_worker", side_effect=worker),
              patch("application.lifecycle.run_charx_cleanup", side_effect=worker),
              patch("application.lifecycle.run_memory_retry_worker", side_effect=worker),
              patch("application.lifecycle.run_group_memory_worker", side_effect=worker),
              patch("application.lifecycle.print_startup_banner"),
              patch.object(turn, "SessionLocal", return_value=db),
              patch.object(turn.memory_extraction_service, "get_unsummarized_count", return_value=0),
              patch.object(turn.cognition_service, "get_cognition_unseen_count", return_value=1),
              patch.object(turn.settings, "APP_COGNITION_UPDATE_INTERVAL", 1),
              patch.object(turn.cognition_service, "update_cognition_state", side_effect=model)):
            serving = asyncio.create_task(serve())
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 2))
                serving.cancel()
                for _ in range(100):
                    if not app.state.chat_maintenance.accepting:
                        break
                    await asyncio.sleep(0.001)
                serving.cancel()
                await asyncio.sleep(0)
                serving.cancel()
                await asyncio.sleep(0)
                self.assertFalse(serving.done())
                self.assertEqual([], unlocked)
                db.close.assert_not_called()
                self.assertIsNone(maintenance.schedule_post_turn_maintenance(10, 20))
            finally:
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await serving
            self.assertEqual([(1, True)], unlocked)

    async def test_task_cancellation_waits_for_thread_failure_and_releases_registration(self):
        runtime = maintenance.start_chat_maintenance()
        started, release, closed = threading.Event(), threading.Event(), threading.Event()

        def work(*args):
            started.set()
            try:
                if not release.wait(5):
                    raise RuntimeError("test did not release work")
                raise RuntimeError("maintenance failed")
            finally:
                closed.set()

        with patch.object(maintenance.chat_turn_service, "run_post_turn_maintenance", side_effect=work):
            task = maintenance.schedule_post_turn_maintenance(10, 20)
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 2))
                task.cancel()
                await asyncio.sleep(0)
                task.cancel()
                await asyncio.sleep(0)
                self.assertFalse(task.done())
            finally:
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertTrue(closed.is_set())
            self.assertEqual(set(), runtime.tasks)

    async def test_stop_rejects_new_tasks_and_next_lifespan_gets_fresh_registry(self):
        first = maintenance.start_chat_maintenance()
        with self.assertRaisesRegex(RuntimeError, "生命周期"):
            maintenance.start_chat_maintenance()
        await first.stop()
        self.assertIsNone(maintenance.schedule_post_turn_maintenance(1, 2))
        second = maintenance.start_chat_maintenance()
        self.assertIsNot(first, second)
        with patch.object(maintenance.chat_turn_service, "run_post_turn_maintenance") as work:
            task = maintenance.schedule_post_turn_maintenance(3, 4)
            await task
            work.assert_called_once_with(3, 4)
            self.assertEqual(set(), second.tasks)

    async def test_nonstream_success_registers_maintenance_after_persistence(self):
        turn = SimpleNamespace(character=object(), persona=SimpleNamespace(id=20),
                               user_message=SimpleNamespace(id=30))
        completed = SimpleNamespace(affection_score=1, assistant_message_id=40, candidates=[])
        events = []

        async def complete(*args):
            events.append("saved")
            return completed

        with (patch.object(chat, "_prepare_turn_and_messages", new_callable=AsyncMock, return_value=(turn, [])),
              patch.object(chat.chat_engine, "generate_reply", new_callable=AsyncMock, return_value={"reply": "回复"}),
              patch.object(chat, "_complete_turn", side_effect=complete),
              patch.object(chat, "schedule_post_turn_maintenance", side_effect=lambda *args: events.append(args))):
            response = await chat.chat(ChatRequest(session_id=10, user_message="输入"), BackgroundTasks(), MagicMock())
        self.assertEqual(["saved", (10, 20)], events)
        self.assertEqual(40, response["assistant_message_id"])
        self.assertFalse(get_session_lock(10).locked())
