import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.conversation.chat_engine import _build_generation_kwargs


class TestChatEngineModelParams(unittest.TestCase):
    def _kwargs(self, model: str, is_reasoning_active: bool, repetition: float = 1.0):
        return _build_generation_kwargs(
            model=model,
            messages=[{"role": "user", "content": "hi"}],
            is_reasoning_active=is_reasoning_active,
            final_temp=0.7,
            final_top_p=1.0,
            final_presence=0.0,
            final_frequency=0.0,
            final_repetition=repetition,
            final_reasoning_effort="high",
        )

    def test_deepseek_flash_disables_thinking_and_keeps_sampling(self):
        kwargs = self._kwargs("deepseek-v4-flash", False)

        self.assertEqual(kwargs["extra_body"]["thinking"], {"type": "disabled"})
        self.assertEqual(kwargs["temperature"], 0.7)
        self.assertNotIn("reasoning_effort", kwargs)

    def test_deepseek_pro_enables_thinking_without_sampling(self):
        kwargs = self._kwargs("deepseek-v4-pro", True)

        self.assertEqual(kwargs["extra_body"]["thinking"], {"type": "enabled"})
        self.assertEqual(kwargs["reasoning_effort"], "high")
        self.assertNotIn("temperature", kwargs)
        self.assertNotIn("top_p", kwargs)

    def test_deepseek_pro_name_does_not_force_reasoning_when_switch_is_off(self):
        kwargs = self._kwargs("deepseek-v4-pro", False)

        self.assertEqual(kwargs["extra_body"]["thinking"], {"type": "disabled"})
        self.assertEqual(kwargs["temperature"], 0.7)
        self.assertNotIn("reasoning_effort", kwargs)

    def test_openai_reasoning_model_still_skips_sampling(self):
        kwargs = self._kwargs("o3-mini", True)

        self.assertEqual(kwargs["reasoning_effort"], "high")
        self.assertNotIn("temperature", kwargs)
        self.assertNotIn("extra_body", kwargs)


if __name__ == "__main__":
    unittest.main()
