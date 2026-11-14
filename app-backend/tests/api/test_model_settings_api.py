from contextlib import ExitStack
from copy import deepcopy
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from application.factory import create_app
from core.config import settings
from core.database import SessionLocal
from core.models import ChatMessage


class ModelSettingsApiTests(unittest.TestCase):
    def setUp(self):
        self.original = deepcopy(settings.config)
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(settings, '_save_yaml_config'))
        self.client = TestClient(create_app())

    def tearDown(self):
        self.client.close()
        settings.config = self.original
        settings.migrate_and_bind_config()
        self.stack.close()

    def test_default_model_and_thinking_update_independently_and_auxiliary_settings_are_separate(self):
        body = {'default_chat_model': 'deepseek-flash', 'reasoning_mode': True, 'reasoning_effort': 'max',
                'memory_model': 'deepseek-v4-pro', 'memory_thinking_mode': 'disabled',
                'tts_preprocess_model': 'deepseek-flash', 'tts_thinking_mode': 'disabled'}
        response = self.client.put('/utils/settings', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.put('/utils/settings', json={'reasoning_mode': False, 'reasoning_effort': None})
        self.assertEqual(response.status_code, 200, response.text)
        value = self.client.get('/utils/settings').json()
        self.assertEqual(value['default_chat_model'], 'deepseek-flash')
        self.assertIsNone(value['reasoning_effort'])
        self.assertEqual(value['memory_model'], 'deepseek-v4-pro')
        self.assertEqual(value['memory_thinking_mode'], 'disabled')
        flash = next(item for item in value['model_catalog'] if item['id'] == 'deepseek-flash')
        self.assertEqual(flash['thinking'], 'toggle')

    def test_invalid_profile_combination_leaves_settings_unchanged(self):
        before = settings.LLM_DEFAULT_CHAT_MODEL
        response = self.client.put('/utils/settings', json={'default_chat_model': 'ordinary-model', 'reasoning_mode': True})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(settings.LLM_DEFAULT_CHAT_MODEL, before)
        response = self.client.put('/utils/settings', json={'model_profiles': [{'id': 'a', 'adapter': 'invented'}]})
        self.assertEqual(response.status_code, 422)

    def test_invalid_chat_model_settings_fail_before_any_user_message_is_written(self):
        with SessionLocal() as db:
            before = db.query(ChatMessage).count()
        for path in ('/chat', '/chat/stream'):
            response = self.client.post(path, json={'session_id': 999999, 'user_message': 'Hello', 'model': 'ordinary-model', 'thinking_mode': 'enabled'})
            self.assertEqual(response.status_code, 400, response.text)
        with SessionLocal() as db:
            self.assertEqual(db.query(ChatMessage).count(), before)

    def test_canonical_mode_and_translation_defaults_are_exposed(self):
        body = {"default_chat_model": "proxy-model", "chat_thinking_mode": "enabled", "reasoning_effort": "low",
                "model_profiles": [{"id": "proxy-model", "adapter": "compatible", "thinking": "toggle", "efforts": ["low", "high"]}],
                "translation_model": "proxy-model", "translation_thinking_mode": "enabled", "translation_reasoning_effort": "high"}
        result = self.client.put("/utils/settings", json=body)
        self.assertEqual(result.status_code, 200, result.text)
        value = self.client.get("/utils/settings").json()
        self.assertEqual(value["chat_thinking_mode"], "enabled")
        self.assertTrue(value["reasoning_mode"])
        self.assertEqual(value["translation_reasoning_effort"], "high")
        self.assertEqual(value["default_chat_model"], "proxy-model")

    def test_failed_save_returns_error_without_publishing_settings(self):
        before = deepcopy(settings.config)
        with patch.object(settings, "_save_yaml_config", side_effect=OSError("simulated disk failure")):
            response = self.client.put("/utils/settings", json={"temperature": 0.91})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(settings.config, before)

    def test_fixed_translation_model_can_roundtrip_complete_settings(self):
        response = self.client.put("/utils/settings", json={"translation_model": "o3-mini"})
        self.assertEqual(response.status_code, 200, response.text)
        value = self.client.get("/utils/settings").json()
        self.assertEqual(value["translation_thinking_mode"], "enabled")
        value["temperature"] = 0.81
        response = self.client.put("/utils/settings", json=value)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(settings.LLM_TEMPERATURE, 0.81)
        response = self.client.put("/utils/settings", json={"translation_thinking_mode": "disabled"})
        self.assertEqual(response.status_code, 400)

    def test_conflicting_alias_and_canonical_mode_are_rejected(self):
        before = deepcopy(settings.config)
        response = self.client.put("/utils/settings", json={"chat_thinking_mode": "disabled", "reasoning_mode": True})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(settings.config, before)
