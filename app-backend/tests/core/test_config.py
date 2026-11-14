"""配置迁移、校验、原子保存和运行状态发布；只操作临时文件。"""
import copy
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import yaml

from core.config import Settings
from services.infrastructure.model_capabilities import resolve_selection


class TestConfigSystem(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "config.yaml"

    def settings(self, llm=None, **sections):
        self.path.write_text(yaml.safe_dump({"llm": llm or {}, **sections}), encoding="utf-8")
        return Settings(self.path)

    def test_legacy_slots_migrate_once_without_switching_models_on_thinking_change(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                config = self.settings({"chat_model": "deepseek-pro", "non_reasoning_chat_model": "deepseek-flash", "reasoning_mode": enabled})
                model = "deepseek-pro" if enabled else "deepseek-flash"
                self.assertEqual(config.LLM_DEFAULT_CHAT_MODEL, model)
                self.assertEqual(config.LLM_MEMORY_MODEL, "deepseek-pro")
                self.assertEqual(config.LLM_TTS_PREPROCESS_MODEL, "deepseek-flash")
                self.assertEqual(config.LLM_TRANSLATION_MODEL, "deepseek-flash")
                config.update_and_persist({"chat_thinking_mode": "disabled" if enabled else "enabled"})
                loaded = Settings(self.path)
                self.assertEqual(loaded.LLM_DEFAULT_CHAT_MODEL, model)
                self.assertEqual(loaded.LLM_MEMORY_MODEL, "deepseek-pro")
                self.assertEqual(resolve_selection(use_reasoning=True, config=loaded).model, "deepseek-pro")
                self.assertEqual(resolve_selection(use_reasoning=False, config=loaded).model, "deepseek-flash")

    def test_modern_defaults_freeze_task_models_without_legacy_slot_fallback(self):
        config = self.settings({"default_chat_model": "custom-chat"})
        self.assertEqual(config.LLM_MEMORY_MODEL, "custom-chat")
        self.assertEqual(config.LLM_TTS_PREPROCESS_MODEL, "custom-chat")
        self.assertNotIn("chat_model", config.config["llm"])
        self.assertNotIn("non_reasoning_chat_model", config.config["llm"])
        self.assertEqual(resolve_selection(use_reasoning=False, config=config).model, "custom-chat")
        config.update_and_persist({"default_chat_model": "another-chat"})
        loaded = Settings(self.path)
        self.assertEqual(loaded.LLM_MEMORY_MODEL, "custom-chat")
        self.assertEqual(loaded.LLM_TRANSLATION_MODEL, "custom-chat")
        self.assertEqual(loaded.LLM_DEFAULT_CHAT_MODEL, "another-chat")

    def test_canonical_mode_wins_over_legacy_value_on_load(self):
        config = self.settings({"default_chat_model": "deepseek-flash", "chat_thinking_mode": "enabled", "reasoning_mode": False})
        self.assertTrue(config.LLM_REASONING_MODE)
        self.assertTrue(yaml.safe_load(self.path.read_text(encoding="utf-8"))["llm"]["reasoning_mode"])

    def test_partial_legacy_slots_preserve_old_auxiliary_defaults(self):
        cases = [({"non_reasoning_chat_model": "deepseek-flash"}, "deepseek-flash", "gpt-3.5-turbo", "deepseek-flash"),
                 ({"chat_model": "deepseek-pro"}, "deepseek-pro", "deepseek-pro", "deepseek-pro"),
                 ({"chat_model": "deepseek-pro", "non_reasoning_chat_model": ""}, "deepseek-pro", "deepseek-pro", "deepseek-pro")]
        for llm, chat, memory, tts in cases:
            with self.subTest(llm=llm):
                config = self.settings(llm)
                self.assertEqual(config.LLM_DEFAULT_CHAT_MODEL, chat)
                self.assertEqual(config.LLM_MEMORY_MODEL, memory)
                self.assertEqual(config.LLM_TTS_PREPROCESS_MODEL, tts)
                self.assertEqual(config.LLM_TRANSLATION_MODEL, tts)

    def test_unknown_legacy_model_keeps_its_previous_implicit_non_thinking_behavior(self):
        config = self.settings({"chat_model": "proxy-reasoner", "reasoning_mode": True})
        self.assertEqual(config.LLM_DEFAULT_CHAT_MODEL, "proxy-reasoner")
        self.assertEqual(config.LLM_CHAT_THINKING_MODE, "disabled")
        self.assertFalse(resolve_selection(config=config).thinking)
        loaded = Settings(self.path)
        self.assertEqual(loaded.LLM_DEFAULT_CHAT_MODEL, "proxy-reasoner")
        self.assertFalse(loaded.LLM_REASONING_MODE)
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            config.update_and_persist({"chat_thinking_mode": "enabled"})
        self.assertEqual(self.path.read_bytes(), before)

    def test_fixed_thinking_task_defaults_can_be_saved_back_unchanged(self):
        config = self.settings({"default_chat_model": "custom-chat", "translation_model": "o3-mini",
                                "memory_model": "o3-mini", "tts_preprocess_model": "o3-mini"})
        values = {key: config.config["llm"][key] for key in (
            "translation_thinking_mode", "memory_thinking_mode", "tts_thinking_mode")}
        self.assertEqual(set(values.values()), {"enabled"})
        config.update_and_persist({"temperature": 0.8, **values})
        loaded = Settings(self.path)
        self.assertEqual(loaded.LLM_TEMPERATURE, 0.8)
        self.assertEqual(loaded.LLM_TRANSLATION_THINKING_MODE, "enabled")
        with self.assertRaises(ValueError):
            loaded.update_and_persist({"translation_thinking_mode": "disabled"})

    def test_switching_task_to_fixed_thinking_normalizes_implicit_mode(self):
        config = self.settings()
        config.update_and_persist({"translation_model": "o3-mini"})
        self.assertEqual(config.LLM_TRANSLATION_THINKING_MODE, "enabled")
        self.assertEqual(config.config["llm"]["translation_thinking_mode"], "enabled")

    def test_alias_updates_and_conflicts(self):
        config = self.settings({"default_chat_model": "deepseek-flash"})
        config.update_and_persist({"reasoning_mode": True})
        self.assertEqual(config.LLM_CHAT_THINKING_MODE, "enabled")
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            config.update_and_persist({"reasoning_mode": True, "chat_thinking_mode": "disabled"})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(config.LLM_REASONING_MODE)

    def test_defaults_and_unknown_fields_survive_upgrade(self):
        config = self.settings({"temperature": 0.5, "custom": "keep"}, app={"context_history_limit": 5})
        self.assertEqual(config.LLM_TEMPERATURE, 0.5)
        self.assertEqual(config.APP_CONTEXT_HISTORY_LIMIT, 5)
        self.assertEqual(config.LLM_MAX_TOKENS, 4096)
        self.assertEqual(yaml.safe_load(self.path.read_text(encoding="utf-8"))["llm"]["custom"], "keep")

    def test_update_persists_normalized_values_and_ignores_static_fields(self):
        config = self.settings()
        config.update_and_persist({"temperature": 0.95, "context_history_limit": "25", "chat_model": "ignored", "reasoning_effort": "none"})
        loaded = Settings(self.path)
        self.assertEqual(loaded.LLM_TEMPERATURE, 0.95)
        self.assertEqual(loaded.APP_CONTEXT_HISTORY_LIMIT, 25)
        self.assertEqual(loaded.CHAT_MODEL_REASONING, "gpt-3.5-turbo")
        self.assertIsNone(loaded.LLM_REASONING_EFFORT)

    def test_invalid_yaml_or_shape_is_not_overwritten(self):
        for content in ("llm: [", "- list", "llm: []", "app: scalar", "llm:\n  temperature: .nan"):
            with self.subTest(content=content):
                self.path.write_text(content, encoding="utf-8")
                with self.assertRaises((ValueError, yaml.YAMLError)):
                    Settings(self.path)
                self.assertEqual(self.path.read_text(encoding="utf-8"), content)

    def test_missing_file_is_initialized(self):
        config = Settings(self.path)
        self.assertTrue(self.path.exists())
        self.assertEqual(config.LLM_CHAT_THINKING_MODE, "disabled")

    def test_failed_replace_keeps_old_file_and_runtime_state(self):
        config = self.settings()
        previous = self.path.read_bytes()
        state = copy.deepcopy(config.config)
        with patch("core.config.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                config.update_and_persist({"temperature": 0.8})
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(config.config, state)
        self.assertEqual(config.LLM_TEMPERATURE, 0.7)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_failed_serialization_keeps_old_file_and_state(self):
        config = self.settings()
        previous = self.path.read_bytes()
        with patch("core.config.yaml.safe_dump", side_effect=RuntimeError("encoding failure")):
            with self.assertRaises(RuntimeError):
                config.update_and_persist({"temperature": 0.8})
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(config.LLM_TEMPERATURE, 0.7)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_invalid_models_and_nonfinite_values_do_not_change_state_or_file(self):
        config = self.settings()
        previous = self.path.read_bytes()
        for updates in ({"chat_thinking_mode": "enabled"}, {"temperature": float("inf")},
                        {"model_profiles": [{"id": "a"}, {"id": "a"}]},
                        {"model_profiles": [{"id": "a", "adapter": "invalid"}]}):
            with self.subTest(updates=updates):
                with self.assertRaises(ValueError):
                    config.update_and_persist(updates)
                self.assertEqual(self.path.read_bytes(), previous)
                self.assertEqual(config.LLM_CHAT_THINKING_MODE, "disabled")

    def test_concurrent_updates_merge_without_lost_fields(self):
        config = self.settings()
        barrier = threading.Barrier(2)
        def update(values):
            barrier.wait()
            config.update_and_persist(values)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(update, value) for value in ({"temperature": 0.9}, {"context_history_limit": 27})]
            for result in results:
                result.result()
        loaded = Settings(self.path)
        self.assertEqual(loaded.LLM_TEMPERATURE, 0.9)
        self.assertEqual(loaded.APP_CONTEXT_HISTORY_LIMIT, 27)

    def test_running_state_is_published_only_after_file_replace(self):
        config = self.settings()
        original = __import__("os").replace
        def replace(source, target):
            self.assertEqual(config.LLM_TEMPERATURE, 0.7)
            original(source, target)
        with patch("core.config.os.replace", side_effect=replace):
            config.update_and_persist({"temperature": 0.9})
        self.assertEqual(config.LLM_TEMPERATURE, 0.9)

    def test_models_can_declare_capabilities_independently_of_name(self):
        config = self.settings({"default_chat_model": "proxy-flash", "chat_thinking_mode": "enabled",
            "model_profiles": [{"id": "proxy-flash", "adapter": "compatible", "thinking": "toggle", "efforts": ["low", "high"]}]})
        self.assertTrue(resolve_selection(config=config).thinking)
        config.update_and_persist({"chat_thinking_mode": "disabled"})
        self.assertEqual(config.LLM_DEFAULT_CHAT_MODEL, "proxy-flash")
        self.assertFalse(resolve_selection(config=config).thinking)
