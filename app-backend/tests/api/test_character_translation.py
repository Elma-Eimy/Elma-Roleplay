"""中文阅读缓存、模型边界与失败原子性的隔离回归。"""
import asyncio
import json
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from application.factory import create_app
from core.config import settings
from core.database import SessionLocal
from core.models import CharacterTranslation
from services import character_translation_service as service


class CharacterTranslationTests(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        self.client = TestClient(create_app())
        self.card = {
            "name": "Translation fixture", "description": "She is a traveler. {{char}} <b>Welcome</b>",
            "personality": "Kind", "scenario": "The forest", "first_mes": "Hello {{user}}!",
            "mes_example": "<START>\n{{char}}: Hello.", "creator_notes": "Read before playing.",
            "system_prompt_override": "HIDDEN_PROMPT", "post_history_instructions": "HIDDEN_PHI",
            "extensions": {"alternate_greetings": ["", "Second greeting", None], "character_book": {"secret": "HIDDEN_WORLD"}},
        }
        self.card["description"] += " " + self._testMethodName

    def tearDown(self):
        self.db.close()
        self.client.close()

    def provider(self, transform=None):
        async def generate(**kwargs):
            values = json.loads(kwargs["messages"][-1]["content"])
            values = [("译文：" + text) if text.strip() else text for text in values]
            if transform:
                values = transform(values)
            return SimpleNamespace(choices=[SimpleNamespace(
                finish_reason="stop", message=SimpleNamespace(content=json.dumps({"translations": values}, ensure_ascii=False)),
            )])
        return SimpleNamespace(generate_async=AsyncMock(side_effect=generate))

    def test_translation_is_separate_cached_and_excludes_hidden_prompt(self):
        provider = self.provider()
        original = deepcopy(self.card)
        with patch("services.infrastructure.llm_provider.get_llm_provider", return_value=provider), patch.object(settings, "LLM_TRANSLATION_MODEL", "deepseek-flash"):
            result = asyncio.run(service.translate_card(self.card, self.db))
            count = provider.generate_async.await_count
            cached = asyncio.run(service.translate_card(self.card, self.db))
        self.assertEqual(count, provider.generate_async.await_count)
        self.assertEqual(result, cached)
        self.assertEqual(original, self.card)
        self.assertIn("{{char}} <b>", result["fields"]["description"])
        self.assertIn("{{user}}", result["fields"]["first_mes"])
        self.assertEqual(["", "译文：Second greeting", ""], result["fields"]["alternate_greetings"])
        for call in provider.generate_async.call_args_list:
            wire = json.dumps(call.kwargs["messages"])
            self.assertNotIn("HIDDEN_", wire)
            self.assertEqual("deepseek-flash", call.kwargs["model"])
            self.assertEqual("disabled", call.kwargs["extra_body"]["thinking"]["type"])
        self.assertEqual(1, self.db.query(CharacterTranslation).filter_by(source_hash=result["source_hash"]).count())

    def test_reading_changes_invalidate_cache_but_avatar_and_hidden_fields_do_not(self):
        with patch("services.infrastructure.llm_provider.get_llm_provider", return_value=self.provider()):
            asyncio.run(service.translate_card(self.card, self.db))
        changed = deepcopy(self.card)
        changed.update(avatar_path="another.png", system_prompt_override="new hidden prompt")
        self.assertIsNotNone(service.cached_translation(changed, self.db))
        changed["description"] += " Changed."
        self.assertIsNone(service.cached_translation(changed, self.db))

    def test_failed_refresh_preserves_previous_translation(self):
        with patch("services.infrastructure.llm_provider.get_llm_provider", return_value=self.provider()):
            saved = asyncio.run(service.translate_card(self.card, self.db))
        broken = self.provider(lambda values: [value.replace("⟦RP_KEEP_0⟧", "") for value in values])
        with patch("services.infrastructure.llm_provider.get_llm_provider", return_value=broken):
            with self.assertRaises(service.TranslationError):
                asyncio.run(service.translate_card(self.card, self.db, force=True))
        self.assertEqual(saved, service.cached_translation(self.card, self.db))

    def test_long_card_is_chunked_without_losing_placeholders(self):
        self.card["description"] = ("Long setting {{char}}.\n" * 400)
        provider = self.provider()
        with patch("services.infrastructure.llm_provider.get_llm_provider", return_value=provider):
            result = asyncio.run(service.translate_card(self.card, self.db, force=True))
        self.assertGreater(provider.generate_async.await_count, 2)
        self.assertEqual(400, result["fields"]["description"].count("{{char}}"))
        for call in provider.generate_async.call_args_list:
            self.assertTrue(all(len(text) <= 2400 for text in json.loads(call.kwargs["messages"][-1]["content"])))

    def test_truncated_response_is_not_saved(self):
        card = {**self.card, "description": "Truncated unique source"}
        provider = SimpleNamespace(generate_async=AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="length", message=SimpleNamespace(content='{"translations":[]}'),
        )])))
        with patch("services.infrastructure.llm_provider.get_llm_provider", return_value=provider):
            with self.assertRaises(service.TranslationError):
                asyncio.run(service.translate_card(card, self.db))
        self.assertIsNone(service.cached_translation(card, self.db))

    def test_chunk_boundaries_preserve_paragraph_breaks_when_model_trims_whitespace(self):
        self.card["description"] = "A" * 2398 + "\n\n" + "B" * 2398 + "\n\n" + "C" * 100
        with patch("services.infrastructure.llm_provider.get_llm_provider", return_value=self.provider(
            lambda values: [value.strip() for value in values]
        )):
            result = asyncio.run(service.translate_card(self.card, self.db))
        self.assertEqual(2, result["fields"]["description"].count("\n\n"))

    def test_literal_internal_markers_in_source_are_preserved_without_requiring_card_edits(self):
        self.card["description"] = "A literal ⟦RP_KEEP_0⟧ with {{char}} <b>text</b>"
        with patch("services.infrastructure.llm_provider.get_llm_provider", return_value=self.provider()):
            result = asyncio.run(service.translate_card(self.card, self.db))
        self.assertIn("⟦RP_KEEP_0⟧", result["fields"]["description"])
        self.assertIn("{{char}} <b>", result["fields"]["description"])

    def test_endpoints_cache_read_never_generates_and_translation_does_not_create_character(self):
        before = self.client.get("/characters").json()["characters"]
        with patch("services.infrastructure.llm_provider.get_llm_provider", return_value=self.provider()) as factory:
            card = {**self.card, "description": "API unique source"}
            response = self.client.post("/characters/translation-cache", json={"card": card})
            self.assertEqual(200, response.status_code)
            self.assertIsNone(response.json()["translation"])
            factory.assert_not_called()
            response = self.client.post("/characters/translate", json={"card": card})
            self.assertEqual(200, response.status_code, response.text)
            cached = self.client.post("/characters/translation-cache", json={"card": card})
            self.assertEqual(response.json(), cached.json())
        self.assertEqual(before, self.client.get("/characters").json()["characters"])

    def test_translation_model_is_independent_and_persisted_through_settings(self):
        original = deepcopy(settings.config)
        try:
            with patch.object(settings, "_save_yaml_config") as save:
                old_model = settings.LLM_DEFAULT_CHAT_MODEL
                result = self.client.put("/utils/settings", json={"translation_model": "custom-translator"})
                self.assertEqual(200, result.status_code, result.text)
                self.assertEqual("custom-translator", self.client.get("/utils/settings").json()["translation_model"])
                self.assertEqual(old_model, settings.LLM_DEFAULT_CHAT_MODEL)
                save.assert_called_once()
        finally:
            settings.config = original
            settings.migrate_and_bind_config()
