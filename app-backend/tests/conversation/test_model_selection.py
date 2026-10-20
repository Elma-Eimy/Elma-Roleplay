import asyncio
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from core.config import settings
from services.infrastructure.model_capabilities import resolve_selection, generation_controls, auxiliary_controls
from services.conversation import chat_engine


class ModelSelectionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in {'LLM_DEFAULT_CHAT_MODEL': 'deepseek-flash', 'CHAT_MODEL_REASONING': 'deepseek-v4-pro',
                            'CHAT_MODEL_NON_REASONING': 'deepseek-v4-flash', 'LLM_REASONING_MODE': False,
                            'LLM_REASONING_EFFORT': 'high', 'LLM_MODEL_PROFILES': []}.items():
            self.stack.enter_context(patch.object(settings, name, value))

    def test_flash_and_pro_each_support_independent_thinking_toggle(self):
        for model in ('deepseek-flash', 'deepseek-v4-pro'):
            for mode in ('enabled', 'disabled'):
                with self.subTest(model=model, mode=mode):
                    selection = resolve_selection(model, mode, effort='max')
                    self.assertEqual(selection.model, model)
                    kwargs = generation_controls(selection, temperature=0.8, top_p=0.6)
                    self.assertEqual(kwargs['extra_body']['thinking']['type'], mode)
                    self.assertEqual('temperature' in kwargs, mode == 'disabled')
                    self.assertEqual('reasoning_effort' in kwargs, mode == 'enabled')
                    if model == 'deepseek-flash':
                        self.assertEqual(kwargs.get('top_p'), 0.95 if mode == 'enabled' else None)

    def test_modern_inherit_uses_default_model_without_legacy_slot_switching(self):
        settings.LLM_REASONING_MODE = True
        selection = resolve_selection(thinking_mode='inherit')
        self.assertEqual(selection.model, 'deepseek-flash')
        self.assertTrue(selection.thinking)
        self.assertEqual(resolve_selection(use_reasoning=True).model, 'deepseek-v4-pro')
        self.assertEqual(resolve_selection(use_reasoning=False).model, 'deepseek-v4-flash')

    def test_generic_pro_name_does_not_imply_reasoning_and_profiles_enable_custom_models(self):
        selection = resolve_selection('my-pro-model', 'disabled')
        self.assertIn('temperature', generation_controls(selection))
        with self.assertRaises(ValueError):
            resolve_selection('my-pro-model', 'enabled')
        settings.LLM_MODEL_PROFILES = [{'id': 'my-pro-model', 'adapter': 'deepseek'}]
        self.assertTrue(resolve_selection('my-pro-model', 'enabled').thinking)

    def test_invalid_effort_and_disabling_fixed_reasoning_fail_explicitly(self):
        with self.assertRaises(ValueError):
            resolve_selection('deepseek-flash', 'enabled', effort='banana')
        with self.assertRaises(ValueError):
            resolve_selection('o3-mini', 'disabled')
        self.assertTrue(resolve_selection('o3-mini', 'inherit').thinking)

    def test_auxiliary_tasks_keep_their_own_thinking_strategy(self):
        with patch.multiple(settings, LLM_MEMORY_MODEL='deepseek-flash',
                            LLM_MEMORY_THINKING_MODE='enabled', LLM_MEMORY_REASONING_EFFORT='max',
                            LLM_TTS_PREPROCESS_MODEL='deepseek-v4-pro',
                            LLM_TTS_THINKING_MODE='disabled', LLM_TTS_REASONING_EFFORT='low'):
            memory = auxiliary_controls('memory', 0.2)
            tts = auxiliary_controls('tts', 0.1)
        self.assertEqual(memory['extra_body']['thinking']['type'], 'enabled')
        self.assertEqual(memory['reasoning_effort'], 'max')
        self.assertNotIn('temperature', memory)
        self.assertEqual(tts['extra_body']['thinking']['type'], 'disabled')
        self.assertEqual(tts['temperature'], 0.1)
        self.assertNotIn('reasoning_effort', tts)

    def test_stream_and_nonstream_send_the_same_selected_model_and_thinking(self):
        provider = SimpleNamespace(generate_async=AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='<reply>Hello</reply>', reasoning_content='reason'))])), generate_stream_async=AsyncMock(return_value=object()))
        character = SimpleNamespace(extensions='{"reasoning_effort":"low"}')
        with patch('services.infrastructure.llm_provider.get_llm_provider', return_value=provider), patch.object(chat_engine, 'log_llm_stream_wrapper_async', side_effect=lambda response, *args: response):
            result = asyncio.run(chat_engine.generate_reply(character, [], model='deepseek-flash', thinking_mode='enabled', reasoning_effort='max'))
            _, model = asyncio.run(chat_engine.generate_reply_stream(character, [], model='deepseek-flash', thinking_mode='enabled', reasoning_effort='max'))
        self.assertEqual(result['model_used'], model)
        for call in (provider.generate_async.call_args, provider.generate_stream_async.call_args):
            self.assertEqual(call.kwargs['model'], 'deepseek-flash')
            self.assertEqual(call.kwargs['reasoning_effort'], 'max')
            self.assertEqual(call.kwargs['extra_body']['thinking']['type'], 'enabled')
