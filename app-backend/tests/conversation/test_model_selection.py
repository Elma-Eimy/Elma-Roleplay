import asyncio
from contextlib import ExitStack
import json
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
                            'CHAT_MODEL_NON_REASONING': 'deepseek-v4-flash', 'LLM_CHAT_THINKING_MODE': 'disabled',
                            'LLM_REASONING_EFFORT': 'high', 'LLM_MODEL_PROFILES': []}.items():
            self.stack.enter_context(patch.object(settings, name, value))
        self.stack.enter_context(patch.multiple(
            settings, LLM_TEMPERATURE=0.7, LLM_TOP_P=0.9,
            LLM_PRESENCE_PENALTY=0.1, LLM_FREQUENCY_PENALTY=0.2,
            LLM_REPETITION_PENALTY=1.0, LLM_MAX_TOKENS=321,
        ))

    def _generate_with_both_transports(self, character, **options):
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content='<reply>Hello</reply>', reasoning_content='reason',
        ))])
        stream = object()
        provider = SimpleNamespace(
            generate_async=AsyncMock(return_value=response),
            generate_stream_async=AsyncMock(return_value=stream),
        )
        messages = [{'role': 'user', 'content': 'hi'}]
        with patch('services.infrastructure.llm_provider.get_llm_provider', return_value=provider), patch.object(
            chat_engine, 'log_llm_stream_wrapper_async', side_effect=lambda response, *args: response,
        ):
            result = asyncio.run(chat_engine.generate_reply(character, messages, **options))
            actual_stream, model = asyncio.run(chat_engine.generate_reply_stream(character, messages, **options))

        self.assertEqual(result['reply'], 'Hello')
        self.assertEqual(result['model_used'], model)
        self.assertIs(actual_stream, stream)
        provider.generate_async.assert_awaited_once()
        provider.generate_stream_async.assert_awaited_once()
        plain_kwargs = provider.generate_async.call_args.kwargs
        stream_kwargs = dict(provider.generate_stream_async.call_args.kwargs)
        self.assertIs(plain_kwargs['messages'], messages)
        self.assertIs(stream_kwargs['messages'], messages)
        self.assertTrue(stream_kwargs.pop('stream'))
        self.assertNotIn('stream', plain_kwargs)
        self.assertEqual(plain_kwargs, stream_kwargs)
        return plain_kwargs

    def test_request_sampling_overrides_card_settings_including_zero_values(self):
        extensions = {'temperature': 0.8, 'top_p': 0.6, 'presence_penalty': 0.4,
                      'frequency_penalty': 0.3, 'repetition_penalty': 1.2}
        for value in (extensions, json.dumps(extensions)):
            with self.subTest(extensions=value):
                kwargs = self._generate_with_both_transports(
                    SimpleNamespace(extensions=value), model='custom-chat', thinking_mode='disabled',
                    temperature=0.0, top_p=0.0, presence_penalty=0.0,
                    frequency_penalty=0.0, repetition_penalty=1.4,
                )
                self.assertEqual(kwargs['temperature'], 0.0)
                self.assertEqual(kwargs['top_p'], 0.0)
                self.assertEqual(kwargs['presence_penalty'], 0.0)
                self.assertEqual(kwargs['frequency_penalty'], 0.0)
                self.assertEqual(kwargs['extra_body'], {'repetition_penalty': 1.4})
                self.assertEqual(kwargs['max_tokens'], 321)
        self.assertEqual(extensions['temperature'], 0.8)
        self.assertEqual(extensions['repetition_penalty'], 1.2)

    def test_card_sampling_settings_override_global_defaults_without_leaking_to_next_call(self):
        extensions = {'temperature': 0.3, 'repetition_penalty': 1.2}
        for value in (extensions, json.dumps(extensions)):
            with self.subTest(extensions=value):
                kwargs = self._generate_with_both_transports(
                    SimpleNamespace(extensions=value), model='custom-chat', thinking_mode='disabled',
                )
                self.assertEqual(kwargs['temperature'], 0.3)
                self.assertEqual(kwargs['top_p'], 0.9)
                self.assertEqual(kwargs['presence_penalty'], 0.1)
                self.assertEqual(kwargs['frequency_penalty'], 0.2)
                self.assertEqual(kwargs['extra_body'], {'repetition_penalty': 1.2})
        kwargs = self._generate_with_both_transports(
            SimpleNamespace(extensions={}), model='custom-chat', thinking_mode='disabled',
        )
        self.assertEqual(kwargs['temperature'], 0.7)
        self.assertNotIn('extra_body', kwargs)

    def test_missing_or_unparseable_card_extensions_keep_global_defaults(self):
        for character in (None, SimpleNamespace(extensions=None), SimpleNamespace(extensions=''),
                          SimpleNamespace(extensions='{broken json')):
            with self.subTest(character=character):
                kwargs = self._generate_with_both_transports(
                    character, model='custom-chat', thinking_mode='disabled',
                )
                self.assertEqual(kwargs['temperature'], 0.7)
                self.assertEqual(kwargs['top_p'], 0.9)
                self.assertEqual(kwargs['presence_penalty'], 0.1)
                self.assertEqual(kwargs['frequency_penalty'], 0.2)
                self.assertNotIn('extra_body', kwargs)

    def test_effort_inheritance_keeps_modern_and_legacy_selection_rules(self):
        character = SimpleNamespace(extensions='{"reasoning_effort":"low"}')
        cases = [
            ({'model': 'deepseek-v4-pro', 'thinking_mode': 'enabled'}, 'high'),
            ({'model': 'deepseek-v4-pro', 'thinking_mode': 'enabled', 'reasoning_effort': 'inherit'}, 'high'),
            ({'thinking_mode': 'enabled'}, 'high'),
            ({'use_reasoning': True}, 'low'),
            ({'model': 'deepseek-v4-pro', 'thinking_mode': 'enabled', 'reasoning_effort': 'max'}, 'max'),
        ]
        for options, effort in cases:
            with self.subTest(options=options):
                kwargs = self._generate_with_both_transports(character, **options)
                self.assertEqual(kwargs['reasoning_effort'], effort)
                self.assertEqual(kwargs['extra_body']['thinking'], {'type': 'enabled'})
                self.assertNotIn('temperature', kwargs)

    def test_invalid_selection_fails_before_either_provider_is_called(self):
        with patch('services.infrastructure.llm_provider.get_llm_provider') as get_provider:
            for generate in (chat_engine.generate_reply, chat_engine.generate_reply_stream):
                with self.subTest(generate=generate.__name__), self.assertRaises(ValueError):
                    asyncio.run(generate(None, [], model='o3-mini', thinking_mode='disabled'))
            get_provider.assert_not_called()

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
        settings.LLM_CHAT_THINKING_MODE = "enabled"
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

    def test_custom_capability_overrides_do_not_depend_on_model_name(self):
        settings.LLM_MODEL_PROFILES = [{"id": "proxy-model", "adapter": "compatible",
            "thinking": "toggle", "efforts": ["low", "high"]}]
        enabled = resolve_selection("proxy-model", "enabled", effort="low")
        disabled = resolve_selection("proxy-model", "disabled")
        self.assertEqual(generation_controls(enabled)["reasoning_effort"], "low")
        self.assertEqual(generation_controls(disabled)["reasoning_effort"], "none")
        self.assertEqual(enabled.model, disabled.model)
        self.assertEqual(resolve_selection("proxy-model", "enabled", effort=None).effort, "high")

    def test_declared_deepseek_efforts_are_not_overridden_by_legacy_aliases(self):
        settings.LLM_MODEL_PROFILES = [{"id": "custom", "adapter": "deepseek",
            "thinking": "toggle", "efforts": ["medium"]}]
        self.assertEqual(resolve_selection("custom", "enabled", effort="medium").effort, "medium")

    def test_model_without_effort_levels_omits_global_and_request_effort(self):
        settings.LLM_MODEL_PROFILES = [{"id": "custom", "adapter": "deepseek",
            "thinking": "toggle", "efforts": []}]
        for effort in (None, "inherit", "high"):
            with self.subTest(effort=effort):
                selected = resolve_selection("custom", "enabled", effort=effort)
                self.assertIsNone(selected.effort)
                kwargs = self._generate_with_both_transports(
                    None, model="custom", thinking_mode="enabled", reasoning_effort=effort)
                self.assertNotIn("reasoning_effort", kwargs)
                self.assertEqual(kwargs["extra_body"]["thinking"]["type"], "enabled")

    def test_auxiliary_tasks_keep_their_own_modes_and_efforts(self):
        with patch.multiple(settings, LLM_MEMORY_MODEL="deepseek-flash", LLM_MEMORY_THINKING_MODE="enabled",
                LLM_MEMORY_REASONING_EFFORT="low", LLM_TTS_PREPROCESS_MODEL="deepseek-flash",
                LLM_TTS_THINKING_MODE="disabled", LLM_TRANSLATION_MODEL="deepseek-flash",
                LLM_TRANSLATION_THINKING_MODE="enabled", LLM_TRANSLATION_REASONING_EFFORT=None):
            self.assertEqual(auxiliary_controls("memory", 0.3)["reasoning_effort"], "low")
            self.assertNotIn("reasoning_effort", auxiliary_controls("tts", 0.3))
            self.assertNotIn("reasoning_effort", auxiliary_controls("translation", 0.3))
            self.assertEqual(auxiliary_controls("translation", 0.3)["extra_body"]["thinking"]["type"], "enabled")

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
