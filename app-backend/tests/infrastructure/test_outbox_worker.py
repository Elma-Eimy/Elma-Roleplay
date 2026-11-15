"""用临时 SQLite 验证 Outbox 锁等待、线程归属及取消后的持久结果。"""

import asyncio
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from core.models import Base, OutboxJob, OutboxJobStatus
from services.infrastructure import outbox_worker as worker


class OutboxWorkerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.engine = create_engine("sqlite:///" + str(Path(temporary.name) / "outbox.db"),
                                    connect_args={"check_same_thread": False, "timeout": 2})
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.db = self.sessions()
        self.addCleanup(self.db.close)

    def add_job(self, **values):
        job = OutboxJob(task_type="test", payload="{}", **values)
        self.db.add(job)
        self.db.commit()
        job_id = job.id
        self.db.rollback()
        return job_id

    def test_database_execution_and_session_close_share_one_worker_thread(self):
        self.add_job()
        created, closed, executed, sql = [], [], [], []
        main_thread = threading.get_ident()

        def factory():
            created.append(threading.get_ident())
            db = self.sessions()
            close = db.close

            def tracked_close():
                closed.append(threading.get_ident())
                close()

            db.close = tracked_close
            return db

        @event.listens_for(self.engine, "before_cursor_execute")
        def track_sql(*args):
            sql.append(threading.get_ident())

        with patch.object(worker, "SessionLocal", side_effect=factory), patch.object(
            worker, "execute_task", side_effect=lambda *args: executed.append(threading.get_ident()),
        ):
            asyncio.run(worker.process_pending_jobs())
        self.assertEqual(1, len(created))
        self.assertNotEqual(main_thread, created[0])
        self.assertEqual({created[0]}, set(created + closed + executed + sql))
        self.assertEqual(created, closed)

    def test_sqlite_write_lock_does_not_block_event_loop_heartbeat(self):
        self.add_job()
        locked, release = threading.Event(), threading.Event()

        def hold_write_lock():
            with self.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                locked.set()
                release.wait(0.8)
                connection.rollback()

        holder = threading.Thread(target=hold_write_lock)
        holder.start()
        self.assertTrue(locked.wait(2))

        async def scenario():
            started = time.monotonic()
            task = asyncio.create_task(worker.process_pending_jobs())
            try:
                await asyncio.sleep(0.02)
                delay = time.monotonic() - started
                self.assertLess(delay, 0.3, f"event loop blocked for {delay:.3f}s")
            finally:
                release.set()
                await task

        try:
            with patch.object(worker, "SessionLocal", self.sessions), patch.object(worker, "execute_task"):
                asyncio.run(scenario())
        finally:
            release.set()
            holder.join(2)
        self.assertFalse(holder.is_alive())

    def test_repeated_cancellation_waits_for_current_job_and_leaves_next_pending(self):
        first, second = self.add_job(), self.add_job()
        started, release, finished = threading.Event(), threading.Event(), threading.Event()

        def execute(*args):
            started.set()
            try:
                if not release.wait(3):
                    raise RuntimeError("test did not release executor")
            finally:
                finished.set()

        async def scenario():
            task = asyncio.create_task(worker.process_pending_jobs())
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
            self.assertTrue(finished.is_set())

        with patch.object(worker, "SessionLocal", self.sessions), patch.object(worker, "execute_task", side_effect=execute) as executor:
            asyncio.run(scenario())
        executor.assert_called_once()
        self.assertIsNone(self.db.get(OutboxJob, first))
        self.assertEqual(OutboxJobStatus.pending, self.db.get(OutboxJob, second).status)

    def test_failure_during_cancellation_is_saved_before_worker_exits(self):
        job_id = self.add_job()
        started, release = threading.Event(), threading.Event()

        def fail(*args):
            started.set()
            if not release.wait(3):
                raise RuntimeError("test did not release executor")
            raise ValueError("external failure")

        async def scenario():
            task = asyncio.create_task(worker.process_pending_jobs())
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 2))
                task.cancel()
                await asyncio.sleep(0)
            finally:
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task

        with patch.object(worker, "SessionLocal", self.sessions), patch.object(worker, "execute_task", side_effect=fail):
            asyncio.run(scenario())
        job = self.db.get(OutboxJob, job_id)
        self.assertEqual(OutboxJobStatus.failed, job.status)
        self.assertEqual(1, job.attempts)
        self.assertIn("ValueError", job.last_error)
        self.assertGreater(job.run_after, datetime.now())

    def test_expired_processing_lease_is_retried_but_live_lease_is_not(self):
        expired = self.add_job(status=OutboxJobStatus.processing, run_after=datetime.now() - timedelta(seconds=1))
        live = self.add_job(status=OutboxJobStatus.processing, run_after=datetime.now() + timedelta(minutes=5))
        with patch.object(worker, "SessionLocal", self.sessions), patch.object(worker, "execute_task") as executor:
            asyncio.run(worker.process_pending_jobs())
        executor.assert_called_once()
        self.assertIsNone(self.db.get(OutboxJob, expired))
        self.assertEqual(OutboxJobStatus.processing, self.db.get(OutboxJob, live).status)

    def test_exhausted_retry_burst_keeps_job_with_cooldown(self):
        job_id = self.add_job(attempts=2, max_attempts=3)
        with patch.object(worker, "SessionLocal", self.sessions), patch.object(worker, "execute_task", side_effect=ValueError("offline")):
            asyncio.run(worker.process_pending_jobs())
        job = self.db.get(OutboxJob, job_id)
        self.assertEqual(OutboxJobStatus.failed, job.status)
        self.assertEqual(0, job.attempts)
        self.assertGreater(job.run_after, datetime.now() + timedelta(minutes=59))

    def test_cancellation_during_sqlite_lock_wait_keeps_loop_live_and_waits_for_cleanup(self):
        first, second = self.add_job(), self.add_job()
        locked, claiming, release = threading.Event(), threading.Event(), threading.Event()

        def hold_lock():
            with self.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                locked.set()
                release.wait(2)
                connection.rollback()

        @event.listens_for(self.engine, "before_cursor_execute")
        def detect_claim(connection, cursor, statement, parameters, context, executemany):
            if statement.startswith("UPDATE outbox_jobs"):
                claiming.set()

        holder = threading.Thread(target=hold_lock)
        holder.start()
        self.assertTrue(locked.wait(2))

        async def scenario():
            task = asyncio.create_task(worker.process_pending_jobs())
            try:
                self.assertTrue(await asyncio.to_thread(claiming.wait, 1))
                task.cancel()
                started = time.monotonic()
                await asyncio.sleep(0.02)
                self.assertLess(time.monotonic() - started, 0.3)
                self.assertFalse(task.done())
            finally:
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task

        try:
            with patch.object(worker, "SessionLocal", self.sessions), patch.object(worker, "execute_task") as executor:
                asyncio.run(scenario())
        finally:
            release.set()
            holder.join(2)
        executor.assert_called_once()
        self.assertFalse(holder.is_alive())
        self.assertIsNone(self.db.get(OutboxJob, first))
        self.assertEqual(OutboxJobStatus.pending, self.db.get(OutboxJob, second).status)
