"""TTS 台词提炼、长文本压缩和安全回退的离线测试。"""

from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from services.tts_service import TTSService


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
