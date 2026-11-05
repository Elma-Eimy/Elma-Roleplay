"""运行权互斥和中断候选标记，不调用真实服务。"""
import asyncio
import subprocess
import sys
import unittest
from unittest.mock import patch, AsyncMock

from application.group_runtime import group_runtime, fail_interrupted_group_candidates
from core.models import GroupRoundCandidate, GroupContentItem
from services.conversation import group_history_service as history
from services.conversation import group_session_service as groups
from tests.conversation import test_group_session_service as fixtures


class GroupRuntimeTests(unittest.TestCase):
    setUp = fixtures.GroupSessionServiceTests.setUp

    def test_exclusive_owner_is_released_after_failure_and_rejects_expired_owner(self):
        with self.assertRaisesRegex(RuntimeError, "startup failed"):
            with group_runtime(self.engine) as owner:
                with self.assertRaisesRegex(RuntimeError, "单 Worker"):
                    with group_runtime(self.engine):
                        self.fail("second process must not own this database")
                raise RuntimeError("startup failed")
        with self.assertRaisesRegex(RuntimeError, "运行权"):
            fail_interrupted_group_candidates(owner)
        with group_runtime(self.engine) as current:
            fail_interrupted_group_candidates(current)

    def test_interruption_marks_only_generating_and_keeps_prefix_and_revision(self):
        targets = []
        for status in ("generating", "awaiting_confirmation", "failed"):
            group = asyncio.run(groups.create_group_session(self.cards, self.db))
            sid = group["session_id"]
            pid = group["members"][0]["persona_id"]
            target = asyncio.run(history.prepare_group_round(sid, "user", (pid,), self.db))
            asyncio.run(history.append_group_utterance(sid, target["candidate_id"], pid, "prefix", (), 1, self.db))
            candidate = self.db.get(GroupRoundCandidate, target["candidate_id"])
            candidate.status = status
            self.db.commit()
            targets.append(candidate.id)
        count = self.db.query(GroupContentItem).count()
        self.db.rollback()
        with group_runtime(self.engine) as owner:
            fail_interrupted_group_candidates(owner)
            fail_interrupted_group_candidates(owner)
        self.db.expire_all()
        rows = [self.db.get(GroupRoundCandidate, cid) for cid in targets]
        self.assertEqual(["failed", "awaiting_confirmation", "failed"], [row.status for row in rows])
        self.assertEqual([3, 2, 2], [row.revision for row in rows])
        self.assertEqual(["process_interrupted", None, None], [row.error_code for row in rows])
        self.assertEqual(count, self.db.query(GroupContentItem).count())

    def test_another_process_cannot_take_the_database_until_owner_exits(self):
        script = ("import sys; from sqlalchemy import create_engine; "
                  "from application.group_runtime import group_runtime; "
                  "guard=group_runtime(create_engine(sys.argv[1])); guard.__enter__(); guard.__exit__(None,None,None)")
        def attempt():
            return subprocess.run([sys.executable, "-c", script, str(self.engine.url)],
                capture_output=True, text=True, encoding="utf-8", timeout=20)
        with group_runtime(self.engine):
            denied = attempt()
            self.assertNotEqual(0, denied.returncode)
            self.assertIn("单 Worker", denied.stderr)
        released = attempt()
        self.assertEqual(0, released.returncode, released.stdout + released.stderr)

    def test_startup_takes_owner_before_migration_and_reconciliation_before_workers(self):
        from application.lifecycle import lifespan
        from fastapi import FastAPI
        from contextlib import contextmanager
        events = []
        @contextmanager
        def runtime():
            events.append("lock")
            try:
                yield "owner"
            finally:
                events.append("unlock")
        async def worker():
            events.append("worker")
            await asyncio.Event().wait()
        async def scenario():
            with patch("application.lifecycle.group_runtime", runtime), patch(
                "application.lifecycle.run_migrations", side_effect=lambda: events.append("migrate")
            ), patch("application.lifecycle.fail_interrupted_group_candidates",
                     side_effect=lambda owner: events.append("reconcile:" + owner)), patch(
                "application.lifecycle.run_outbox_worker", side_effect=worker
            ), patch("application.lifecycle.run_memory_retry_worker", side_effect=worker), patch(
                "application.lifecycle.run_charx_cleanup", side_effect=worker
            ), patch("application.lifecycle.print_startup_banner"):
                async with lifespan(FastAPI()):
                    await asyncio.sleep(0)
        asyncio.run(scenario())
        self.assertEqual(["lock", "migrate", "reconcile:owner"], events[:3])
        self.assertEqual("unlock", events[-1])
        self.assertIn("worker", events[3:-1])

    def test_worker_failure_still_stops_other_workers_before_releasing_runtime(self):
        from application.lifecycle import lifespan
        from fastapi import FastAPI
        from contextlib import contextmanager
        app = FastAPI()
        all_stopped_at_unlock = []
        def tasks():
            return (app.state.memory_retry_task, app.state.charx_cleanup_task, app.state.outbox_task)
        @contextmanager
        def runtime():
            try:
                yield "owner"
            finally:
                all_stopped_at_unlock.append(all(task.done() for task in tasks()))
        async def worker():
            await asyncio.Event().wait()
        async def broken():
            raise RuntimeError("memory worker failed")
        async def scenario():
            with patch("application.lifecycle.group_runtime", runtime), patch(
                "application.lifecycle.run_migrations"), patch("application.lifecycle.fail_interrupted_group_candidates"
            ), patch("application.lifecycle.run_outbox_worker", side_effect=worker), patch(
                "application.lifecycle.run_charx_cleanup", side_effect=worker
            ), patch("application.lifecycle.run_memory_retry_worker", side_effect=broken), patch(
                "application.lifecycle.print_startup_banner"
            ), patch("application.lifecycle.cancel_all_stream_tasks", new_callable=AsyncMock) as streams:
                try:
                    with self.assertRaisesRegex(RuntimeError, "memory worker failed"):
                        async with lifespan(app):
                            await asyncio.sleep(0)
                    self.assertEqual([True], all_stopped_at_unlock)
                    streams.assert_awaited_once()
                finally:
                    for task in tasks():
                        task.cancel()
                    await asyncio.gather(*tasks(), return_exceptions=True)
        asyncio.run(scenario())

    def test_repeated_shutdown_cancellation_keeps_runtime_until_worker_cleanup_finishes(self):
        from application.lifecycle import lifespan
        from fastapi import FastAPI
        from contextlib import contextmanager
        unlocked = []
        app = FastAPI()
        @contextmanager
        def runtime():
            try:
                yield "owner"
            finally:
                unlocked.append(app.state.memory_retry_task.done())
        async def scenario():
            started, stopping, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
            async def slow_worker():
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    stopping.set()
                    await release.wait()
                    raise
            async def worker():
                await asyncio.Event().wait()
            async def serve():
                async with lifespan(app):
                    await asyncio.Event().wait()
            with patch("application.lifecycle.group_runtime", runtime), patch(
                "application.lifecycle.run_migrations"), patch("application.lifecycle.fail_interrupted_group_candidates"
            ), patch("application.lifecycle.run_outbox_worker", side_effect=worker), patch(
                "application.lifecycle.run_charx_cleanup", side_effect=worker
            ), patch("application.lifecycle.run_memory_retry_worker", side_effect=slow_worker), patch(
                "application.lifecycle.print_startup_banner"
            ), patch("application.lifecycle.cancel_all_stream_tasks", new_callable=AsyncMock):
                serving = asyncio.create_task(serve())
                try:
                    await asyncio.wait_for(started.wait(), 1)
                    serving.cancel()
                    await asyncio.wait_for(stopping.wait(), 1)
                    serving.cancel()
                    await asyncio.sleep(0)
                    serving.cancel()
                    await asyncio.sleep(0)
                    self.assertFalse(serving.done())
                    self.assertEqual([], unlocked)
                finally:
                    release.set()
                    with self.assertRaises(asyncio.CancelledError):
                        await serving
                self.assertEqual([True], unlocked)
        asyncio.run(scenario())
