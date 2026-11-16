"""任务关联编号、异步隔离和运行日志故障隔离。"""

import asyncio
import inspect
import logging
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from services.infrastructure.logging_context import current_task_id, diagnostic_task, log_event


class LoggingContextTests(unittest.TestCase):
    def test_nested_calls_share_id_and_signature_and_restore_context(self):
        @diagnostic_task("inner")
        def inner(message_id=None):
            return current_task_id()

        @diagnostic_task("outer")
        def outer(message_id=None):
            return current_task_id(), inner(message_id)

        with self.assertLogs(__name__, level="INFO") as captured:
            outer_id, inner_id = outer(message_id=42)
        self.assertEqual(outer_id, inner_id)
        self.assertIn("message_id=42", " ".join(captured.output))
        self.assertIsNone(current_task_id())
        self.assertEqual(["message_id"], list(inspect.signature(outer).parameters))

    def test_parallel_async_tasks_keep_distinct_ids(self):
        @diagnostic_task("async")
        async def operation():
            before = current_task_id()
            await asyncio.sleep(0)
            self.assertEqual(before, current_task_id())
            return before

        async def scenario():
            return await asyncio.gather(operation(), operation())

        first, second = asyncio.run(scenario())
        self.assertNotEqual(first, second)
        self.assertIsNone(current_task_id())

    def test_cancelled_task_restores_context_and_preserves_cancellation(self):
        @diagnostic_task("cancelled")
        async def operation():
            raise asyncio.CancelledError

        async def scenario():
            with self.assertRaises(asyncio.CancelledError):
                await operation()
            self.assertIsNone(current_task_id())

        asyncio.run(scenario())

    def test_host_handler_failure_does_not_escape_log_event(self):
        logger = Mock()
        logger.log.side_effect = OSError("handler failed")
        log_event(logger, logging.ERROR, "test_event", job_id=7)
        logger.log.assert_called_once()

    def test_chat_request_logs_session_id_without_serializing_request(self):
        @diagnostic_task("chat")
        def operation(request):
            return "ok"

        request = SimpleNamespace(session_id=12, user_message="private-content")
        with self.assertLogs(__name__, level="INFO") as captured:
            self.assertEqual("ok", operation(request))
        self.assertIn("session_id=12", " ".join(captured.output))
        self.assertNotIn("private-content", " ".join(captured.output))
