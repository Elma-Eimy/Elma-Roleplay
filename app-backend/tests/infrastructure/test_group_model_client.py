"""轮次专用 SDK 客户端仅连接本地 HTTP 替身，不访问真实模型。"""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import unittest
from unittest.mock import patch, AsyncMock

from services.infrastructure.llm_provider import GroupModelConnection, group_model_session, OpenAICompatibleProvider


class GroupModelClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_http_failure_is_sent_once_without_sdk_retries(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(self.rfile.read(int(self.headers["Content-Length"])))
                body = b'{"error":{"message":"fixture failure","type":"server_error"}}'
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *_):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        serving = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        serving.start()
        try:
            from openai import InternalServerError
            connection = GroupModelConnection(f"http://127.0.0.1:{server.server_port}/v1", "fixture-key")
            async with group_model_session(connection, timeout=2) as client:
                with self.assertRaises(InternalServerError):
                    await client.chat.completions.create(model="fixture-replay", messages=[{"role": "user", "content": "fixture"}])
            self.assertEqual(1, len(requests))
            self.assertTrue(client.is_closed())
            from openai import AsyncOpenAI
            provider = OpenAICompatibleProvider()
            provider._async_client = AsyncOpenAI(api_key="fixture-key", base_url=connection.base_url, max_retries=2, timeout=2)
            try:
                with self.assertRaises(InternalServerError):
                    await provider.generate_async(model="fixture-replay", messages=[{"role": "user", "content": "fixture"}],
                                                  _group_no_retry=True)
                self.assertEqual(2, len(requests))
            finally:
                await provider._async_client.close()
        finally:
            await asyncio.to_thread(server.shutdown)
            server.server_close()
            serving.join(2)

    async def test_default_single_chat_client_keeps_its_existing_options(self):
        with patch("services.infrastructure.llm_provider.AsyncOpenAI") as client:
            provider = OpenAICompatibleProvider()
            provider.async_client
            self.assertNotIn("max_retries", client.call_args.kwargs)

    async def test_completed_round_survives_cancellation_during_client_cleanup(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def close():
            started.set()
            await release.wait()
        client = AsyncMock()
        client.close.side_effect = close
        async def execute():
            async with group_model_session(GroupModelConnection("http://example.invalid/v1", "fixture-key"), timeout=1):
                return "committed"
        with patch("services.infrastructure.llm_provider.AsyncOpenAI", return_value=client):
            task = asyncio.create_task(execute())
            await started.wait()
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            release.set()
            self.assertEqual("committed", await task)
            client.close.assert_awaited_once()
