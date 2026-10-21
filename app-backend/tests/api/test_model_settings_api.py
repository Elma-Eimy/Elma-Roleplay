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
