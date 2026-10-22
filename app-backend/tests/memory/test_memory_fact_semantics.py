"""Story-time semantics survive extraction, deduplication and consolidation."""
import json
import unittest
from unittest.mock import patch
from core.models import MemoryChunk, MemoryType
from services.memory import memory_extraction_service as extraction
from services.memory import memory_consolidation_service as consolidation
from services.memory.graph_evidence import snapshot_sources
from tests.memory import test_memory_card_extraction as extraction_fixture
from tests.memory import test_memory_consolidation as consolidation_fixture


class FactExtractionTests(unittest.TestCase):
    setUp = extraction_fixture.MemoryCardExtractionTests.setUp
    tearDown = extraction_fixture.MemoryCardExtractionTests.tearDown

    def extract(self, status=None, candidates=()):
        payload = {"memories": [{"content": "用户计划下个月搬到杭州滨江工作。", "memory_type": "event",
            "temporal_status": status, "temporal_note": "下个月",
            "source_start_message_id": self.messages[0].id, "source_end_message_id": self.messages[2].id}]}
        provider = extraction_fixture.MemoryCardExtractionTests._provider_with_payload(payload)
        with patch.object(extraction, "get_llm_provider", return_value=provider), \
             patch.object(extraction, "retrieve_memories", return_value=list(candidates)), \
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
