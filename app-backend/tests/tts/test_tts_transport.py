"""语音请求格式、解码、客户端归属和取消收尾的离线回归。"""
import asyncio
import base64
from pathlib import Path
import tempfile
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from services import tts_service


class TTSProviderImportTests(unittest.TestCase):
    def test_provider_module_import_and_request_build_do_not_initialize_runtime(self):
        script = (
            "import sys; from services.infrastructure.tts_provider import build_speech_request; "
            "url, headers, payload = build_speech_request('spoken', 'voice', 1.0, "
            "base_url='https://speech.example.invalid/v1', api_key='placeholder', model='test-tts'); "
            "assert url.endswith('/chat/completions'); assert 'speed' not in payload['audio']; "
            "forbidden = ('services.tts_service', 'core.config', 'core.database', 'httpx'); "
            "assert not [name for name in forbidden if name in sys.modules]"
        )
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True,
            text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


class TTSTransportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.service = tts_service.TTSService()
        self.asynchronous = MagicMock()
        self.asynchronous.post = AsyncMock()
        self.manager = MagicMock()
        self.manager.__aenter__ = AsyncMock(return_value=self.asynchronous)
        self.manager.__aexit__ = AsyncMock(return_value=False)
        self.synchronous = MagicMock()
        patches = (
            patch.multiple(tts_service.settings, TTS_ENABLED=True, TTS_CACHE_DIR=str(self.root),
                TTS_MIMO_BASE_URL="https://speech.example.invalid/v1", MIMO_API_KEY="test-mimo-key",
                TTS_MIMO_MODEL="test-tts-model", TTS_DEFAULT_VOICE="default-voice"),
            patch.object(self.service, "preprocess_roleplay_text_llm", new=AsyncMock(return_value="提炼台词")),
            patch.object(self.service, "preprocess_roleplay_text_llm_sync", return_value="提炼台词"),
            patch.object(self.service, "_get_client", return_value=self.synchronous),
            patch.object(tts_service.httpx, "AsyncClient", return_value=self.manager),
            patch.object(tts_service.httpx, "Client", side_effect=AssertionError("不得创建额外同步客户端")),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        thread = patch.object(tts_service.threading, "Thread")
        self.thread = thread.start()
        self.addCleanup(thread.stop)

    def audio_response(self, *, raw=False, status=200, payload=None):
        request = httpx.Request("POST", "https://speech.example.invalid/v1/chat/completions")
        if raw:
            return httpx.Response(status, content=b"ID3-test-audio",
                                  headers={"content-type": "audio/mpeg"}, request=request)
        if payload is None:
            payload = {"choices": [{"message": {"audio": {
                "data": base64.b64encode(b"ID3-test-audio").decode("ascii"),
            }}}]}
        return httpx.Response(status, json=payload, request=request)

    def synthesize(self, mode, **kwargs):
        if mode == "async":
            return asyncio.run(self.service.generate_speech_async("原始旁白", **kwargs))
        return self.service.generate_speech_sync("原始旁白", **kwargs)

    def test_request_shape_and_both_audio_formats_match_in_sync_and_async_paths(self):
        for mode in ("async", "sync"):
            for raw in (False, True):
                for speed in (1.0, 1.25):
                    with self.subTest(mode=mode, raw=raw, speed=speed), patch.object(
                        tts_service.settings, "TTS_CACHE_DIR", str(self.root / f"{mode}-{raw}-{speed}"),
                    ):
                        response = self.audio_response(raw=raw)
                        self.asynchronous.post.return_value = response
                        self.synchronous.post.return_value = response
                        url = self.synthesize(mode, voice=None, speed=speed)
                        path = Path(tts_service.settings.TTS_CACHE_DIR) / Path(url).name
                        self.assertEqual(b"ID3-test-audio", path.read_bytes())
                        post = self.asynchronous.post if mode == "async" else self.synchronous.post
                        audio = {"format": "mp3", "voice": "default-voice"}
                        if speed != 1.0:
                            audio["speed"] = speed
                        post.assert_called_once_with(
                            "https://speech.example.invalid/v1/chat/completions",
                            headers={"Authorization": "Bearer test-mimo-key", "Content-Type": "application/json"},
                            json={"model": "test-tts-model", "messages": [{"role": "assistant", "content": "提炼台词"}],
                                  "audio": audio},
                        )
                        post.reset_mock()

    def test_message_binding_and_client_lifetime_stay_owned_by_the_service(self):
        for mode, message_id in (("async", 7), ("sync", 8)):
            with self.subTest(mode=mode):
                events = []
                message = SimpleNamespace(content="数据库原文", audio_path=None,
                    session=SimpleNamespace(persona=SimpleNamespace(character=SimpleNamespace(name="角色A"))))
                db = MagicMock()
                expected = f"/audio/msg_{message_id}_p2_default-voice_1.00.mp3"

                async def post(*args, **kwargs):
                    events.append("post")
                    return self.audio_response(raw=True)

                def sync_post(*args, **kwargs):
                    events.append("post")
                    return self.audio_response(raw=True)

                def commit():
                    self.assertEqual(b"ID3-test-audio", (self.root / Path(expected).name).read_bytes())
                    self.assertEqual(expected, message.audio_path)
                    events.append("commit")

                async def close(*args):
                    events.append("close")
                    return False

                self.asynchronous.post.side_effect = post
                self.synchronous.post.side_effect = sync_post
                self.manager.__aexit__.side_effect = close
                db.commit.side_effect = commit
                with patch("services.conversation.session_access.get_single_message", return_value=message):
                    self.assertEqual(expected, self.synthesize(mode, message_id=message_id, db=db))
                self.assertEqual(["post", "commit", "close"] if mode == "async" else ["post", "commit"], events)
                db.commit.assert_called_once_with()
                db.refresh.assert_called_once_with(message)
                preprocess = (self.service.preprocess_roleplay_text_llm if mode == "async"
                              else self.service.preprocess_roleplay_text_llm_sync)
                preprocess.assert_called_once_with("数据库原文", character_name="角色A")
                self.synchronous.close.assert_not_called()

    def test_async_cancellation_closes_client_without_writing_audio_or_binding(self):
        message = SimpleNamespace(content="数据库原文", audio_path=None, session=None)
        db = MagicMock()
        self.asynchronous.post.side_effect = asyncio.CancelledError
        with patch("services.conversation.session_access.get_single_message", return_value=message):
            with self.assertRaises(asyncio.CancelledError):
                self.synthesize("async", message_id=7, db=db)
        self.manager.__aexit__.assert_awaited_once()
        self.assertEqual([], list(self.root.glob("*.mp3")))
        self.assertIsNone(message.audio_path)
        db.commit.assert_not_called()
        db.refresh.assert_not_called()
        self.thread.assert_not_called()

    def test_provider_and_decode_errors_keep_existing_contracts_without_retries(self):
        for mode in ("async", "sync"):
            cases = (
                ("http", self.audio_response(status=500), None, "调用云端语音 API 失败:"),
                ("network", None, RuntimeError("test-mimo-key private-response"), "调用云端语音 API 失败:"),
                ("structure", self.audio_response(payload={}), None,
                 "云端语音 API 返回格式异常。" if mode == "async" else "解析云端语音响应失败"),
                ("decode", self.audio_response(payload={"choices": [{"message": {"audio": {"data": "abcde"}}}]}),
                 None, "解析语音数据失败:" if mode == "async" else "解析云端语音响应失败"),
            )
            for name, response, error, expected in cases:
                with self.subTest(mode=mode, case=name):
                    post = self.asynchronous.post if mode == "async" else self.synchronous.post
                    post.return_value, post.side_effect = response, error
                    with self.assertLogs("services.tts_service", level="INFO") as captured:
                        with self.assertRaises(RuntimeError) as failure:
                            self.synthesize(mode)
                    self.assertTrue(str(failure.exception).startswith(expected), str(failure.exception))
                    post.assert_called_once()
                    post.reset_mock()
                    output = " ".join(captured.output)
                    for private in ("test-mimo-key", "private-response", "原始旁白", "提炼台词"):
                        self.assertNotIn(private, output)
                    self.assertIn("task_id=tts-", output)
                    self.assertEqual([], list(self.root.glob("*.mp3")))
        self.thread.assert_not_called()

    def test_missing_empty_and_mismatched_message_cache_are_rebuilt_from_database_text(self):
        for mode in ("async", "sync"):
            for state in ("missing", "empty", "mismatched"):
                with self.subTest(mode=mode, state=state):
                    path = self.root / "msg_7_p2_default-voice_1.00.mp3"
                    if path.exists():
                        path.unlink()
                    if state == "empty":
                        path.write_bytes(b"")
                    elif state == "mismatched":
                        path.write_bytes(b"unbound-cache")
                    message = SimpleNamespace(content="数据库原文", session=None,
                        audio_path="/audio/old.mp3" if state == "mismatched" else "/audio/" + path.name)
                    db = MagicMock()
                    self.asynchronous.post.return_value = self.audio_response(raw=True)
                    self.synchronous.post.return_value = self.audio_response(raw=True)
                    with patch("services.conversation.session_access.get_single_message", return_value=message):
                        self.assertEqual("/audio/" + path.name, self.synthesize(mode, message_id=7, db=db))
                    self.assertEqual(b"ID3-test-audio", path.read_bytes())
                    db.commit.assert_called_once()

    def test_cache_write_failure_does_not_bind_or_commit_or_start_cleanup(self):
        for mode in ("async", "sync"):
            with self.subTest(mode=mode):
                message = SimpleNamespace(content="数据库原文", audio_path=None, session=None)
                db = MagicMock()
                self.asynchronous.post.return_value = self.audio_response(raw=True)
                self.synchronous.post.return_value = self.audio_response(raw=True)
                with patch("services.conversation.session_access.get_single_message", return_value=message), patch(
                    "builtins.open", side_effect=OSError("write failed"),
                ), patch("tempfile.NamedTemporaryFile", side_effect=OSError("write failed")), self.assertRaises(OSError):
                    self.synthesize(mode, message_id=7, db=db)
                self.assertIsNone(message.audio_path)
                db.commit.assert_not_called()
                db.refresh.assert_not_called()
        self.thread.assert_not_called()

    def test_binding_commit_failure_keeps_written_file_and_skips_refresh_and_cleanup(self):
        for mode in ("async", "sync"):
            with self.subTest(mode=mode):
                message = SimpleNamespace(content="数据库原文", audio_path=None, session=None)
                db = MagicMock()
                db.commit.side_effect = RuntimeError("commit failed")
                self.asynchronous.post.return_value = self.audio_response(raw=True)
                self.synchronous.post.return_value = self.audio_response(raw=True)
                with patch("services.conversation.session_access.get_single_message", return_value=message):
                    with self.assertRaisesRegex(RuntimeError, "commit failed"):
                        self.synthesize(mode, message_id=7, db=db)
                self.assertEqual(b"ID3-test-audio", (self.root / Path(message.audio_path).name).read_bytes())
                db.refresh.assert_not_called()
                db.rollback.assert_not_called()
        self.thread.assert_not_called()

    def test_missing_message_and_disabled_setting_keep_validation_order(self):
        for mode in ("async", "sync"):
            with self.subTest(mode=mode), patch(
                "services.conversation.session_access.get_single_message", return_value=None,
            ) as load, patch.object(tts_service.os, "makedirs") as mkdir:
                with patch.object(tts_service.settings, "TTS_ENABLED", False):
                    with self.assertRaisesRegex(ValueError, "已被禁用"):
                        self.synthesize(mode, message_id=7, db=MagicMock())
                load.assert_called_once()
                mkdir.assert_not_called()
                with self.assertRaisesRegex(ValueError, "Message ID 7"):
                    self.synthesize(mode, message_id=7, db=MagicMock())
                mkdir.assert_called_once()

    def test_cache_publication_failure_does_not_bind_or_commit_or_leave_partial_audio(self):
        for mode in ("async", "sync"):
            with self.subTest(mode=mode):
                message = SimpleNamespace(content="数据库原文", audio_path=None, session=None)
                db = MagicMock()
                self.asynchronous.post.return_value = self.audio_response(raw=True)
                self.synchronous.post.return_value = self.audio_response(raw=True)
                with patch("services.conversation.session_access.get_single_message", return_value=message), patch(
                    "services.media.tts_cache.os.replace", side_effect=OSError("replace failed"),
                ), self.assertRaisesRegex(OSError, "replace failed"):
                    self.synthesize(mode, message_id=7, db=db)
                if mode == "async":
                    self.manager.__aexit__.assert_awaited_once()
                self.assertIsNone(message.audio_path)
                db.commit.assert_not_called()
                db.refresh.assert_not_called()
                self.assertEqual([], list(self.root.iterdir()))
        self.thread.assert_not_called()
