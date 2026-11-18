"""Application wiring and lifecycle ownership regressions."""

import asyncio
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI

from application.factory import create_app
from application.lifecycle import lifespan


class ApplicationFactoryTests(unittest.TestCase):
    def test_existing_http_contract_is_preserved(self):
        app = create_app()
        actual = {
            (method, route.path)
            for route in app.routes
            if getattr(route, "path", "") not in ("/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json")
            for method in getattr(route, "methods", ())
        }
        fixture = Path(__file__).resolve().parents[1] / "fixtures" / "http_routes.json"
        expected = {tuple(item) for item in json.loads(fixture.read_text())}
        self.assertEqual(expected, actual)

    def test_creating_apps_does_not_start_migrations_or_workers(self):
        with patch("application.lifecycle.run_migrations") as migrations, patch(
            "application.lifecycle.run_outbox_worker", new_callable=AsyncMock
        ) as worker, patch("application.lifecycle.settings.persist_normalized") as save:
            first = create_app()
            second = create_app()
        self.assertIsNot(first, second)
        self.assertIsNot(first.state, second.state)
        migrations.assert_not_called()
        worker.assert_not_called()
        save.assert_not_called()


class ApplicationLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_configuration_is_saved_after_ownership_and_before_migrations(self):
        events = []
        with patch("application.lifecycle.group_runtime") as runtime, patch(
            "application.lifecycle.settings.persist_normalized", side_effect=lambda: events.append("save"),
        ), patch("application.lifecycle.run_migrations", side_effect=RuntimeError("stop after save")) as migrate:
            runtime.return_value.__enter__.side_effect = lambda: events.append("lock")
            runtime.return_value.__exit__.side_effect = lambda *args: events.append("unlock")
            with self.assertRaisesRegex(RuntimeError, "stop after save"):
                async with lifespan(FastAPI()):
                    self.fail("startup must stop at the injected migration failure")
            migrate.assert_called_once()
        self.assertEqual(["lock", "save", "unlock"], events)

    async def test_failed_configuration_save_releases_ownership_without_migrations_or_workers(self):
        with patch("application.lifecycle.group_runtime") as runtime, patch(
            "application.lifecycle.settings.persist_normalized", side_effect=OSError("configuration save failed"),
        ), patch("application.lifecycle.run_migrations") as migrate, patch(
            "application.lifecycle.run_outbox_worker", new_callable=AsyncMock,
        ) as worker:
            with self.assertRaisesRegex(OSError, "configuration save failed"):
                async with lifespan(FastAPI()):
                    self.fail("startup must fail before serving requests")
            migrate.assert_not_called()
            worker.assert_not_called()
            runtime.return_value.__exit__.assert_called_once()

    async def test_worker_is_owned_and_awaited_on_each_lifespan(self):
        started = asyncio.Event()
        stopped = asyncio.Event()

        async def worker():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        with patch("application.lifecycle.run_migrations") as migrations, patch(
            "application.lifecycle.run_outbox_worker", side_effect=worker
        ), patch("application.lifecycle.print_startup_banner"):
            app = FastAPI()
            tasks = []
            for _ in range(2):
                started.clear()
                stopped.clear()
                async with lifespan(app):
                    await asyncio.wait_for(started.wait(), timeout=1)
                    task = app.state.outbox_task
                    tasks.append(task)
                    self.assertFalse(task.done())
                self.assertTrue(stopped.is_set())
                self.assertTrue(task.cancelled())
            self.assertIsNot(tasks[0], tasks[1])
            self.assertEqual(2, migrations.call_count)

    async def test_failed_migration_does_not_launch_worker(self):
        with patch("application.lifecycle.run_migrations", side_effect=RuntimeError("migration failed")), patch(
            "application.lifecycle.run_outbox_worker", new_callable=AsyncMock
        ) as worker:
            with self.assertRaisesRegex(RuntimeError, "migration failed"):
                async with lifespan(FastAPI()):
                    self.fail("Startup must fail before serving requests")
            worker.assert_not_called()
