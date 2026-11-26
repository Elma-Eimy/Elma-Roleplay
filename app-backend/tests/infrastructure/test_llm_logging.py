"""模型日志的故障隔离、保留预算、脱敏和流语义回归。"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from services.infrastructure import llm_logger as logs
from services.infrastructure.logging_context import task_context


def chunk(content="", reasoning=""):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content, reasoning_content=reasoning))])


class LLMLoggingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "logs" / "debug.log"
        self.config = patch.multiple(logs.settings, LOG_LLM_DEBUG_ENABLED=True,
            LOG_LLM_DEBUG_PATH=str(self.path), LOG_LLM_DEBUG_MAX_BYTES=4096,
            LOG_LLM_DEBUG_BACKUP_COUNT=2, LOG_LLM_DEBUG_EXCERPT_BYTES=4096,
            CHAT_API_KEY="private-chat-token", EMBEDDING_API_KEY="private-embedding-token",
            MIMO_API_KEY="private-mimo-token", ACCESS_API_KEY="private-access-token")
        self.config.start()
        self.addCleanup(self.config.stop)
        self.addCleanup(logs.close_debug_log)
        self.messages = [{"role": "user", "content": "测试输入"}]

    def read_records(self):
        logs.close_debug_log()
        return [json.loads(line) for path in self.path.parent.glob("debug.log*")
                for line in path.read_text(encoding="utf-8").splitlines()]

    def test_disabled_log_does_not_inspect_messages_or_chunks_or_create_files(self):
        class Unreadable:
            @property
            def choices(self):
                raise AssertionError("disabled logging inspected chunk")

        with patch.object(logs.settings, "LOG_LLM_DEBUG_ENABLED", False):
            original = Unreadable()
            result = list(logs.log_llm_stream_wrapper(iter([original]), "test", None))
        self.assertEqual([original], result)
        self.assertFalse(self.path.parent.exists())

    def test_sync_write_failure_keeps_chunks_unchanged(self):
        original = [chunk("回复"), chunk(reasoning="思考")]
        with patch.object(logs, "_write_record", side_effect=OSError("private-chat-token")):
            with self.assertLogs(logs.logger, level="WARNING") as captured:
                result = list(logs.log_llm_stream_wrapper(iter(original), "test", self.messages))
        self.assertEqual(original, result)
        self.assertNotIn("private-chat-token", " ".join(captured.output))
        self.assertIn("task_id=llm-", " ".join(captured.output))

    def test_async_write_failure_keeps_stream_success(self):
        original = [chunk("正文"), chunk(reasoning="思考")]

        async def stream():
            for value in original:
                yield value

        async def consume():
            return [value async for value in logs.log_llm_stream_wrapper_async(stream(), "test", self.messages)]

        with patch.object(logs, "_write_record", side_effect=PermissionError("disk unavailable")):
            self.assertEqual(original, asyncio.run(consume()))

    def test_stream_error_is_preserved_without_logging_exception_text(self):
        original = RuntimeError("private-chat-token confidential body")

        async def stream():
            yield chunk("部分回复")
            raise original

        async def consume():
            return [value async for value in logs.log_llm_stream_wrapper_async(stream(), "test", self.messages)]

        with patch.object(logs, "_write_record", side_effect=OSError("disk failed")), self.assertLogs(logs.logger, level="WARNING") as captured:
            with self.assertRaises(RuntimeError) as raised:
                asyncio.run(consume())
        self.assertIs(original, raised.exception)
        output = " ".join(captured.output)
        self.assertIn("RuntimeError", output)
        self.assertNotIn("private-chat-token", output)
        self.assertNotIn("confidential body", output)

    def test_cancelled_stream_stays_cancelled_when_debug_write_fails(self):
        async def stream():
            yield chunk("部分回复")
            raise asyncio.CancelledError

        async def consume():
            return [value async for value in logs.log_llm_stream_wrapper_async(stream(), "test", self.messages)]

        with patch.object(logs, "_write_record", side_effect=OSError("disk failed")):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(consume())

    def test_malformed_diagnostic_chunk_is_still_yielded(self):
        original = SimpleNamespace(choices=[object()])
        self.assertEqual([original], list(logs.log_llm_stream_wrapper(iter([original]), "test", self.messages)))

    def test_debug_redacts_all_configured_credentials_including_split_chunks(self):
        messages = [{"role": "user", "content": "private-embedding-token private-access-token"}]
        values = [chunk("private-chat-"), chunk("token", "private-mimo-token")]
        list(logs.log_llm_stream_wrapper(iter(values), "private-chat-token", messages))
        record = self.read_records()[0]
        serialized = json.dumps(record)
        for secret in ("private-chat-token", "private-embedding-token", "private-mimo-token", "private-access-token"):
            self.assertNotIn(secret, serialized)
        self.assertEqual("[REDACTED]", record["content"])
        self.assertEqual("[REDACTED]", record["reasoning"])

    def test_oversized_concurrent_records_keep_rotated_files_within_byte_budget(self):
        def write(index):
            values = [chunk("汉字\n" * 10000, "思考" * 10000)]
            list(logs.log_llm_stream_wrapper(iter(values), "test", [{"role": "user", "content": "输入" * 10000}]))

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(write, range(30)))
        logs.close_debug_log()
        files = list(self.path.parent.glob("debug.log*"))
        self.assertGreater(len(files), 1)
        self.assertLessEqual(len(files), 3)
        self.assertTrue(all(path.stat().st_size <= 4096 for path in files))
        self.assertTrue(all(record["truncated"] for record in self.read_records()))

    def test_capture_buffers_stay_bounded_after_many_chunks(self):
        audit = logs._Audit("test", self.messages)
        for _ in range(1000):
            audit.capture("汉字" * 100, "思考" * 100)
        self.assertLessEqual(len(audit.content.encode("utf-8")), audit.budget + audit.reserve)
        self.assertLessEqual(len(audit.reasoning.encode("utf-8")), audit.budget + audit.reserve)

    def test_async_wrapper_freezes_task_id_before_context_exits(self):
        async def stream():
            yield chunk("回复")

        async def consume():
            with task_context("chat-fixed-id"):
                wrapped = logs.log_llm_stream_wrapper_async(stream(), "test", self.messages)
            return [value async for value in wrapped]

        asyncio.run(consume())
        self.assertEqual("chat-fixed-id", self.read_records()[0]["task_id"])

    def test_handler_failure_does_not_print_record_or_raise(self):
        with patch.object(logs._DebugHandler, "doRollover", side_effect=OSError("private-chat-token")):
            with patch.object(logs._DebugHandler, "shouldRollover", return_value=True):
                with self.assertLogs(logs.logger, level="WARNING") as captured:
                    list(logs.log_llm_stream_wrapper(iter([chunk("正文")]), "test", self.messages))
        self.assertNotIn("private-chat-token", " ".join(captured.output))

    def test_nonstream_compatibility_entry_does_not_record_headers(self):
        completion = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="回复", reasoning_content="思考"))])
        response = SimpleNamespace(parse=lambda: completion, headers={"Authorization": "unknown-header-secret"})
        logs.log_llm_non_stream("test", self.messages, response, 0.5)
        records = self.read_records()
        self.assertNotIn("unknown-header-secret", json.dumps(records))
        self.assertGreaterEqual(records[0]["elapsed_ms"], 500)

    def test_nonstream_slow_debug_write_keeps_event_loop_responsive(self):
        from services.conversation import chat_engine
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="<reply>回复</reply>", reasoning_content=""))])
        provider = SimpleNamespace(generate_async=AsyncMock(return_value=response))
        release = threading.Event()

        async def scenario():
            started = time.monotonic()
            task = asyncio.create_task(chat_engine.generate_reply(SimpleNamespace(extensions=None), self.messages))
            try:
                await asyncio.sleep(0.02)
                self.assertLess(time.monotonic() - started, 0.3)
            finally:
                release.set()
                result = await task
            self.assertEqual("回复", result["reply"])

        with patch.object(logs, "_write_record", side_effect=lambda *args: release.wait(0.7)), patch(
            "services.infrastructure.llm_provider.get_llm_provider", return_value=provider,
        ):
            asyncio.run(scenario())

    def test_async_stream_slow_debug_write_keeps_event_loop_responsive(self):
        release = threading.Event()
        original = chunk("回复")

        async def stream():
            yield original

        async def consume():
            return [value async for value in logs.log_llm_stream_wrapper_async(stream(), "test", self.messages)]

        async def scenario():
            started = time.monotonic()
            task = asyncio.create_task(consume())
            try:
                await asyncio.sleep(0.02)
                self.assertLess(time.monotonic() - started, 0.3)
            finally:
                release.set()
                result = await task
            self.assertEqual([original], result)

        with patch.object(logs, "_write_record", side_effect=lambda *args: release.wait(0.7)):
            asyncio.run(scenario())

    def test_repeated_cancellation_waits_for_debug_writer_failure_without_losing_cancel(self):
        started, release, finished = threading.Event(), threading.Event(), threading.Event()

        def write(*args):
            started.set()
            try:
                if not release.wait(3):
                    raise RuntimeError("test did not release writer")
                raise OSError("disk failed")
            finally:
                finished.set()

        async def stream():
            yield chunk("回复")

        async def consume():
            return [value async for value in logs.log_llm_stream_wrapper_async(stream(), "test", self.messages)]

        async def scenario():
            task = asyncio.create_task(consume())
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

        with patch.object(logs, "_write_record", side_effect=write):
            asyncio.run(scenario())

    def test_lifespan_debug_close_keeps_event_loop_live_until_handle_is_closed(self):
        from application.lifecycle import _stop_workers
        list(logs.log_llm_stream_wrapper(iter([chunk("回复")]), "test", self.messages))
        handler = logs._handler
        original_close = handler.close
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        threads = []

        def close():
            threads.append(threading.get_ident())
            started.set()
            try:
                release.wait(0.7)
                original_close()
            finally:
                finished.set()

        async def scenario():
            before = time.monotonic()
            task = asyncio.create_task(_stop_workers())
            try:
                await asyncio.sleep(0.02)
                self.assertLess(time.monotonic() - before, 0.3)
                self.assertTrue(await asyncio.to_thread(started.wait, 2))
                self.assertFalse(task.done())
            finally:
                release.set()
                await task
            self.assertTrue(finished.is_set())
            self.assertIsNone(logs._handler)

        with patch.object(handler, "close", side_effect=close), patch(
            "application.lifecycle.cancel_all_stream_tasks", new_callable=AsyncMock,
        ):
            asyncio.run(scenario())
        self.assertNotEqual([threading.get_ident()], threads)
