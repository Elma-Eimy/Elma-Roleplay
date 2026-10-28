"""Story-time semantics survive extraction, deduplication and consolidation."""
from types import SimpleNamespace
import json
import unittest
from unittest.mock import MagicMock, patch
from core.models import MemoryChunk, MemoryType
from services.memory import memory_extraction_service as extraction, memory_manager
from services.memory import memory_consolidation_service as consolidation
from services.memory.graph_evidence import snapshot_sources
from tests.memory import test_memory_card_extraction as extraction_fixture
from tests.memory import test_memory_consolidation as consolidation_fixture


class FactExtractionTests(unittest.TestCase):
    setUp = extraction_fixture.MemoryCardExtractionTests.setUp
    tearDown = extraction_fixture.MemoryCardExtractionTests.tearDown
    _write_candidate = extraction_fixture.MemoryCardExtractionTests._write_candidate
    _provider_with_payload = staticmethod(extraction_fixture.MemoryCardExtractionTests._provider_with_payload)

    def extract(self, status=None, candidates=()):
        payload = {"memories": [{"content": "用户计划下个月搬到杭州滨江工作。", "memory_type": "event",
            "temporal_status": status, "temporal_note": "下个月",
            "source_start_message_id": self.messages[0].id, "source_end_message_id": self.messages[2].id}]}
        provider = extraction_fixture.MemoryCardExtractionTests._provider_with_payload(payload)
        with patch.object(extraction, "get_llm_provider", return_value=provider), \
             patch.object(extraction, "retrieve_write_candidates", return_value=list(candidates)), \
             patch.object(extraction.cognition_service, "update_cognition_state"):
            return extraction.summarize_and_store_memory(self.session_id, self.db)

    def test_extraction_persists_story_time_and_exact_message_snapshot(self):
        self.assertEqual(1, self.extract("planned"))
        card = self.db.query(MemoryChunk).one()
        self.assertEqual(("planned", "下个月"), (card.temporal_status, card.temporal_note))
        self.assertEqual(snapshot_sources(self.messages[:3]), json.loads(card.source_evidence_json))

    def test_legacy_output_does_not_infer_temporal_status_from_content(self):
        self.assertEqual(1, self.extract())
        self.assertEqual("unknown", self.db.query(MemoryChunk).one().temporal_status)

    def test_normalization_preserves_same_words_with_distinct_story_times(self):
        cards = extraction.normalize_extracted_memories([
            {"content": "小红去旧城调查。", "temporal_status": "planned", "temporal_note": "明年"},
            {"content": "小红去旧城调查。", "temporal_status": "historical", "temporal_note": "去年"},
        ], [1, 2])
        self.assertEqual(2, len(cards))

    def test_different_temporal_status_cannot_take_same_or_replace_shortcut(self):
        old = MemoryChunk(persona_id=self.persona.id, content="用户曾搬到杭州滨江工作。",
                          memory_type=MemoryType.event, importance_score=.8, temporal_status="historical")
        self.db.add(old)
        self.db.commit()
        with patch.object(extraction, "resolve_memory_relationship_via_llm") as resolver:
            self.assertEqual(1, self.extract("planned", [{"id": old.id, "content": old.content,
                "distance": 0.0, "temporal_status": "historical", "temporal_note": None}]))
            resolver.assert_not_called()
        self.assertEqual(2, self.db.query(MemoryChunk).count())
        self.assertTrue(all(row.supersedes_id is None for row in self.db.query(MemoryChunk).all()))

    def test_current_fact_with_present_note_recalls_and_replaces_unknown_status_fact(self):
        old = self._write_candidate("用户住在北京。", temporal_status="unknown", temporal_note=None)
        self.db.commit()
        payload = {"memories": [{
            "content": "用户目前已经定居在杭州滨江。",
            "memory_type": "fact",
            "temporal_status": "current",
            "temporal_note": "目前",
            "importance_score": 0.8,
        }], "entities": [], "relations": []}
        extraction_response = self._provider_with_payload(payload).generate.return_value
        decision_response = self._provider_with_payload(
            {"relation": "replace", "resolved_content": "用户目前定居在杭州滨江。"}
        ).generate.return_value
        provider = SimpleNamespace(generate=MagicMock(side_effect=[extraction_response, decision_response]))
        collection = MagicMock()
        collection.query.return_value = {"ids": [[]], "distances": [[]]}
        with patch.object(extraction, "get_llm_provider", return_value=provider), \
             patch.object(memory_manager, "get_character_collection", return_value=collection), \
             patch.object(extraction.cognition_service, "update_cognition_state"):
            count = extraction.summarize_and_store_memory(self.session_id, self.db)
        self.assertEqual(1, count)
        chunks = self.db.query(MemoryChunk).order_by(MemoryChunk.id).all()
        self.assertEqual(2, len(chunks))
        self.assertEqual(old.id, chunks[1].supersedes_id)
        self.assertEqual("current", chunks[1].temporal_status)
        self.assertIsNone(chunks[1].temporal_note)


class FactConsolidationTests(unittest.TestCase):
    setUp = consolidation_fixture.MemoryConsolidationTests.setUp
    tearDown = consolidation_fixture.MemoryConsolidationTests.tearDown
    memory = consolidation_fixture.MemoryConsolidationTests.memory
    payload = consolidation_fixture.MemoryConsolidationTests.payload
    preview = consolidation_fixture.MemoryConsolidationTests.preview

    def test_different_story_time_sources_are_not_merged(self):
        self.one.temporal_status = "planned"
        self.two.temporal_status = "historical"
        self.db.commit()
        self.assertEqual([], self.preview()["groups"])

    def test_matching_story_time_is_preserved_on_summary_and_undo(self):
        for row in (self.one, self.two):
            row.temporal_status = "historical"
            row.temporal_note = "雨夜"
        self.db.commit()
        batch = self.preview()
        consolidation.apply(self.session.id, batch["id"], [0], self.db)
        summary = self.db.query(MemoryChunk).filter(MemoryChunk.consolidation_id == batch["id"]).one()
        self.assertEqual(("historical", "雨夜"), (summary.temporal_status, summary.temporal_note))
        consolidation.undo(self.session.id, batch["id"], self.db)
        self.assertEqual("historical", self.one.temporal_status)

    def test_supplementary_unknown_fragment_inherits_explicit_temporal_and_evidence_with_hints(self):
        from core.models import ChatMessage, MessageRole
        self.db.add(ChatMessage(session_id=self.session.id, role=MessageRole.user, content="确认上轮消息", is_active=True))
        self.one.temporal_status = "unknown"
        self.one.temporal_note = None
        self.one.source_evidence_json = json.dumps(snapshot_sources([self.first_message]), ensure_ascii=False)
        self.two.temporal_status = "historical"
        self.two.temporal_note = "雨夜"
        self.two.source_evidence_json = json.dumps(snapshot_sources([self.last_message]), ensure_ascii=False)
        self.db.commit()
        provider = MagicMock()
        provider.generate.return_value = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(self.payload(), ensure_ascii=False)))])
        with patch.object(consolidation, "get_llm_provider", return_value=provider):
            batch = consolidation.preview(self.session.id, 0, self.db)
        system_prompt = provider.generate.call_args.kwargs["messages"][0]["content"]
        self.assertIn("高相关候选配对线索", system_prompt)
        self.assertIn(f"[{self.one.id}, {self.two.id}]", system_prompt)
        consolidation.apply(self.session.id, batch["id"], [0], self.db)
        summary = self.db.query(MemoryChunk).filter(MemoryChunk.consolidation_id == batch["id"]).one()
        self.assertEqual(("historical", "雨夜"), (summary.temporal_status, summary.temporal_note))
        self.assertEqual(
            snapshot_sources([self.first_message, self.last_message]),
            json.loads(summary.source_evidence_json),
        )
