"""TTS 台词提炼、长文本压缩和安全回退的离线测试。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from services.tts_service import TTSService
from services.media.tts_text import TTSTextProcessor


def response(payload=None, *, finish_reason="stop", raw_content=None):
    content = raw_content
    if content is None:
        content = json.dumps(payload, ensure_ascii=False)
    return SimpleNamespace(
        choices=[SimpleNamespace(
            finish_reason=finish_reason,
            message=SimpleNamespace(content=content),
        )]
    )


class TTSPreprocessingTests(unittest.TestCase):
    def setUp(self):
        self.service = TTSService()

    def test_text_methods_remain_available_through_the_service(self):
        for name in (
            "preprocess_roleplay_text_rules", "_normalize_style_tags", "_build_preprocess_messages",
            "_normalize_control_tags", "_sanitize_spoken_text", "_parse_preprocess_response",
            "_truncate_spoken_text", "_safe_fallback_extract",
        ):
            with self.subTest(method=name):
                self.assertIs(getattr(TTSService, name), getattr(TTSTextProcessor, name))
        self.assertEqual("2", self.service.PREPROCESSOR_VERSION)

    def test_text_strategy_runs_without_model_cache_or_database_dependencies(self):
        script = textwrap.dedent('''
            import sys
            from types import SimpleNamespace as N
            from services.media.tts_text import TTSTextProcessor
            processor = TTSTextProcessor()
            assert processor._safe_fallback_extract('角色：“先走吧。”', '角色') == '先走吧。'
            assert len(processor._build_preprocess_messages('待处理正文')) == 2
            response = N(choices=[N(finish_reason='stop', message=N(
                content='{"status":"ok","spoken_text":"[温柔]你好。"}'))])
            assert processor._parse_preprocess_response(response, '你好。') == '[温柔]你好。'
            forbidden = ('services.tts_service', 'core.config', 'core.database',
                         'services.infrastructure.llm_provider', 'httpx')
            assert not [name for name in forbidden if name in sys.modules]
        ''')
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True,
            text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_inherited_text_strategy_honors_service_overrides(self):
        with patch.object(self.service, "_sanitize_spoken_text", return_value="兼容清洗") as clean:
            self.assertEqual("兼容清洗", self.service._parse_preprocess_response(
                response({"status": "ok", "spoken_text": "原正文"}), "原正文",
            ))
        clean.assert_called_once_with("原正文")
        with patch.object(self.service, "LONG_TEXT_THRESHOLD", 2), patch.object(
            self.service, "MAX_SPOKEN_CHARS", 3,
        ):
            messages = self.service._build_preprocess_messages("长文本输入")
            self.assertIn("不得超过 3 个字符", messages[0]["content"])
            with self.assertRaisesRegex(ValueError, "未有效压缩"):
                self.service._parse_preprocess_response(
                    response({"status": "ok", "spoken_text": "超过三个字"}), "长文本输入",
                )

    def test_existing_p2_cache_hits_skip_preprocessing_and_provider_calls(self):
        cases = (
            (None, "02434807217a181a509f46a2ffe7cea0.mp3"),
            (7, "msg_7_p2_testvoice_1.00.mp3"),
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            "services.tts_service.settings.TTS_CACHE_DIR", directory,
        ), patch("services.tts_service.settings.TTS_ENABLED", True), patch(
            "services.tts_service.settings.MIMO_API_KEY", "",
        ), patch("services.conversation.session_access.get_single_message") as load, patch.object(
            self.service, "preprocess_roleplay_text_llm", new_callable=AsyncMock,
        ) as asynchronous, patch.object(self.service, "preprocess_roleplay_text_llm_sync") as synchronous, patch.object(
            self.service, "_get_client",
        ) as client, patch("services.tts_service.httpx.AsyncClient") as async_client:
            for message_id, filename in cases:
                with self.subTest(message_id=message_id):
                    expected = "/audio/" + filename
                    (Path(directory) / filename).write_bytes(b"cached audio")
                    db = MagicMock()
                    load.return_value = SimpleNamespace(content="你好。", audio_path=expected, session=None)
                    self.assertEqual(expected, asyncio.run(self.service.generate_speech_async(
                        "你好。", voice="testvoice", message_id=message_id, db=db,
                    )))
                    self.assertEqual(expected, self.service.generate_speech_sync(
                        "你好。", voice="testvoice", message_id=message_id, db=db,
                    ))
                    db.commit.assert_not_called()
            asynchronous.assert_not_awaited()
            synchronous.assert_not_called()
            client.assert_not_called()
            async_client.assert_not_called()

    def test_preprocess_failure_logs_only_task_id_and_error_type(self):
        failure = RuntimeError("credential-and-private-response")
        provider = SimpleNamespace(generate_async=AsyncMock(side_effect=failure), generate=MagicMock(side_effect=failure))
        with patch("services.infrastructure.llm_provider.get_llm_provider", return_value=provider), self.assertLogs(
            "services.tts_service", level="INFO",
        ) as captured:
            self.assertEqual("私人台词", asyncio.run(self.service.preprocess_roleplay_text_llm("“私人台词”")))
            self.assertEqual("私人台词", self.service.preprocess_roleplay_text_llm_sync("“私人台词”"))
        output = " ".join(captured.output)
        self.assertIn("task_id=tts-preprocess-", output)
        self.assertIn("RuntimeError", output)
        self.assertNotIn("credential-and-private-response", output)
        self.assertNotIn("私人台词", output)

    def test_provider_rejection_does_not_log_body_credentials_or_spoken_text(self):
        response = MagicMock(status_code=500, text="private-response-body")
        response.raise_for_status.side_effect = RuntimeError("fake-mimo-credential private-response-body")
        client = MagicMock()
        client.post = AsyncMock(return_value=response)
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=client)
        manager.__aexit__ = AsyncMock(return_value=False)
        sync_client = MagicMock()
        sync_client.post.return_value = response

        with tempfile.TemporaryDirectory() as directory, patch(
            "services.tts_service.settings.TTS_CACHE_DIR", directory,
        ), patch("services.tts_service.settings.TTS_ENABLED", True), patch(
            "services.tts_service.settings.MIMO_API_KEY", "fake-mimo-credential",
        ), patch.object(self.service, "preprocess_roleplay_text_llm", new_callable=AsyncMock, return_value="私人台词"), patch.object(
            self.service, "preprocess_roleplay_text_llm_sync", return_value="私人台词",
        ), patch("services.tts_service.httpx.AsyncClient", return_value=manager), patch.object(
            self.service, "_get_client", return_value=sync_client,
        ), self.assertLogs("services.tts_service", level="INFO") as captured:
            with self.assertRaises(RuntimeError):
                asyncio.run(self.service.generate_speech_async("私人台词"))
            with self.assertRaises(RuntimeError):
                self.service.generate_speech_sync("私人台词")
        output = " ".join(captured.output)
        self.assertIn("status_code=500", output)
        self.assertIn("task_id=tts-", output)
        for private in ("fake-mimo-credential", "private-response-body", "私人台词"):
            self.assertNotIn(private, output)

    def test_short_text_uses_structured_result_and_disables_thinking(self):
        provider = SimpleNamespace(
            generate_async=AsyncMock(return_value=response({
                "status": "ok",
                "spoken_text": "[温柔，轻笑]你终于来啦。",
                "was_compressed": False,
            }))
        )

        with patch(
            "services.tts_service.settings.LLM_TTS_PREPROCESS_MODEL",
            "deepseek-test-model",
        ), patch(
            "services.infrastructure.llm_provider.get_llm_provider",
            return_value=provider,
        ):
            result = asyncio.run(
                self.service.preprocess_roleplay_text_llm(
                    "*她轻轻笑了笑*“你终于来啦。”"
                )
            )

        self.assertEqual("[温柔, 轻笑]你终于来啦。", result)
        kwargs = provider.generate_async.call_args.kwargs
        self.assertEqual(
            {"thinking": {"type": "disabled"}},
            kwargs["extra_body"],
        )
        self.assertIn(
            "不要翻译",
            kwargs["messages"][0]["content"],
        )

    def test_long_text_retries_when_first_response_is_truncated(self):
        provider = SimpleNamespace(
            generate_async=AsyncMock(side_effect=[
                response(raw_content="", finish_reason="length"),
                response({
                    "status": "ok",
                    "spoken_text": "[严肃]钥匙在北门值班室。明天别独自过去，等我。",
                    "was_compressed": True,
                }),
            ])
        )
        source = "旁白和重复说明。" * 150

        with patch(
            "services.infrastructure.llm_provider.get_llm_provider",
            return_value=provider,
        ):
            result = asyncio.run(
                self.service.preprocess_roleplay_text_llm(source)
            )

        self.assertEqual(
            "[严肃]钥匙在北门值班室。明天别独自过去，等我。",
            result,
        )
        self.assertEqual(2, provider.generate_async.call_count)
        retry_prompt = provider.generate_async.call_args.kwargs["messages"][0]["content"]
        self.assertIn("强制压缩", retry_prompt)

    def test_no_speech_is_not_replaced_with_original_narration(self):
        provider = SimpleNamespace(
            generate_async=AsyncMock(return_value=response({
                "status": "no_speech",
                "spoken_text": "",
                "was_compressed": False,
            }))
        )

        with patch(
            "services.infrastructure.llm_provider.get_llm_provider",
            return_value=provider,
        ):
            result = asyncio.run(
                self.service.preprocess_roleplay_text_llm(
                    "她走到窗前，把信放在桌上，然后沉默地离开。"
                )
            )

        self.assertEqual("", result)
        provider.generate_async.assert_awaited_once()

    def test_long_failure_fallback_extracts_quotes_instead_of_raw_text(self):
        provider = SimpleNamespace(
            generate_async=AsyncMock(side_effect=RuntimeError("offline"))
        )
        source = (
            "雨夜的车站里，她检查了每扇门和每一盏灯。" * 60
            + "她最后说：“别等我，天亮前先走。”"
            + "列车经过后，她把信留在桌上。" * 20
        )

        with patch(
            "services.infrastructure.llm_provider.get_llm_provider",
            return_value=provider,
        ):
            result = asyncio.run(
                self.service.preprocess_roleplay_text_llm(source)
            )

        self.assertEqual("别等我，天亮前先走。", result)
        self.assertNotIn("雨夜的车站", result)

    def test_target_speaker_fallback_excludes_other_speakers(self):
        provider = SimpleNamespace(
            generate_async=AsyncMock(side_effect=RuntimeError("offline"))
        )
        source = (
            ('Reina: "The east gate is closed."\n' * 30)
            + ('Vera: "Use the west gate and wait for me."\n' * 30)
        )

        with patch(
            "services.infrastructure.llm_provider.get_llm_provider",
            return_value=provider,
        ):
            result = asyncio.run(
                self.service.preprocess_roleplay_text_llm(
                    source, character_name="Vera"
                )
            )

        self.assertIn("Use the west gate", result)
        self.assertNotIn("east gate", result)

    def test_generate_speech_rejects_empty_preprocess_result(self):
        with (
            patch.object(
                self.service,
                "preprocess_roleplay_text_llm",
                new=AsyncMock(return_value=""),
            ),
            patch("services.tts_service.settings.MIMO_API_KEY", "test-key"),
            patch("services.tts_service.os.path.exists", return_value=False),
        ):
            with self.assertRaisesRegex(ValueError, "未检测到可安全合成"):
                asyncio.run(
                    self.service.generate_speech_async(
                        "只有旁白，没有任何台词。",
                        voice="测试音色",
                    )
                )

    def test_sync_and_async_paths_share_result_validation(self):
        provider = SimpleNamespace(
            generate=MagicMock(return_value=response({
                "status": "ok",
                "spoken_text": "[未知动作]保留正文。",
                "was_compressed": False,
            }))
        )

        with patch(
            "services.infrastructure.llm_provider.get_llm_provider",
            return_value=provider,
        ):
            result = self.service.preprocess_roleplay_text_llm_sync("保留正文。")

        self.assertEqual("保留正文。", result)


if __name__ == "__main__":
    unittest.main()
