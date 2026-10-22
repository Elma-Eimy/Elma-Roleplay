"""上传边界必须在读取 body 和 multipart 临时文件创建之前生效。"""
import asyncio
import unittest
from unittest.mock import patch

from application.charx_upload import CharxUploadMiddleware
from core.config import settings


class CharxUploadBoundaryTests(unittest.TestCase):
    def run_request(self, chunks, headers=(), active=0):
        received, sent, called = [], [], []
        async def inner(scope, receive, send):
            called.append(True)
            while (await receive()).get('more_body'):
                pass
        middleware = CharxUploadMiddleware(inner)
        middleware.active = active
        iterator = iter(chunks)
        async def receive():
            received.append(True)
            return next(iterator)
        async def send(value):
            sent.append(value)
        scope = {'type': 'http', 'method': 'POST', 'path': '/characters/charx/preview', 'headers': list(headers)}
        asyncio.run(middleware(scope, receive, send))
        return received, sent, called, middleware.active

    def test_unauthenticated_request_never_reads_body(self):
        with patch.object(settings, 'ACCESS_API_KEY', 'test-secret'):
            received, sent, called, _ = self.run_request([])
        self.assertEqual([], received)
        self.assertEqual([], called)
        self.assertEqual(403, sent[0]['status'])

    def test_content_length_rejection_never_reads_body(self):
        with patch('application.charx_upload.upload_limit', return_value=1):
            received, sent, called, _ = self.run_request([], [(b'content-length', b'100000')])
        self.assertEqual([], received)
        self.assertEqual([], called)
        self.assertEqual(413, sent[0]['status'])

    def test_chunked_body_stops_at_limit_before_multipart(self):
        chunks = [{'type': 'http.request', 'body': b'x' * 32769, 'more_body': True}] * 3
        with patch('application.charx_upload.upload_limit', return_value=1):
            received, sent, called, active = self.run_request(chunks)
        self.assertEqual(2, len(received))
        self.assertEqual(413, sent[0]['status'])
        self.assertEqual([], called)
        self.assertEqual(0, active)

    def test_concurrent_upload_limit_and_disconnect_release(self):
        received, sent, _, active = self.run_request([], active=3)
        self.assertEqual([], received)
        self.assertEqual(429, sent[0]['status'])
        self.assertEqual(3, active)
        _, _, called, active = self.run_request([{'type': 'http.disconnect'}])
        self.assertEqual([], called)
        self.assertEqual(0, active)

    def test_idle_upload_times_out_and_releases_its_slot(self):
        sent = []
        async def inner(*args):
            self.fail('timed out upload must not reach the parser')
        async def receive():
            await asyncio.sleep(1)
        async def send(message):
            sent.append(message)
        middleware = CharxUploadMiddleware(inner)
        scope = {'type': 'http', 'method': 'POST', 'path': '/characters/charx/preview', 'headers': []}
        with patch('application.charx_upload.UPLOAD_IDLE_TIMEOUT', 0.001):
            asyncio.run(middleware(scope, receive, send))
        self.assertEqual(408, sent[0]['status'])
        self.assertEqual(0, middleware.active)
