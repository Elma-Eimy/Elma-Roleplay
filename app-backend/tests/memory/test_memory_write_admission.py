"""写入准入、即时反应归入事件及持续状态补全的隔离回归。"""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.models import ChatMessage, GraphEntity, MemoryChunk, MemoryType
from services.memory import memory_extraction_service as extraction
from services.memory.memory_facts import fact_sources_current
from tests.memory import test_memory_event_buffer as fixture


class MemoryWriteAdmissionTests(unittest.TestCase):
    def setUp(self):
        fixture.MemoryEventBufferTests.setUp(self)
        cognition = patch.object(extraction.cognition_service, "update_cognition_state")
        cognition.start()
        self.addCleanup(cognition.stop)
    tearDown = fixture.MemoryEventBufferTests.tearDown
    advance = fixture.MemoryEventBufferTests.advance
    card = fixture.MemoryEventBufferTests.card
    extract = fixture.MemoryEventBufferTests.extract

    def test_high_importance_long_reaction_is_preserved_in_its_event_with_graph(self):
        event = self.card("用户陪林墨在旧书店寻找一本诗集。", event_status="complete", retention="episode")
        reaction = self.card("林墨因用户耐心陪伴而感到十分安心，这份安心只是本次找书过程中的即时感受，并非新增关系。",
                             memory_type="emotion", importance_score=.9, retention="transient", event_index=0)
        self.assertEqual(1, self.extract([event, reaction], entities=[{
            "name": "旧书店", "description": "本次找书地点", "memory_indices": [1]}])[0])
        chunk = self.db.query(MemoryChunk).one()
        self.assertIn(event["content"].rstrip("。"), chunk.content)
        self.assertIn(reaction["content"].rstrip("。"), chunk.content)
        self.assertEqual(.9, chunk.importance_score)
        self.assertEqual(MemoryType.event, chunk.memory_type)
        entity = self.db.query(GraphEntity).one()
        self.assertEqual([chunk.id], [item["id"] for item in json.loads(entity.evidence_json)["memories"]])
        self.assertTrue(fact_sources_current(chunk, self.db))

    def test_explicit_link_extends_event_sources_to_adjacent_reaction(self):
        event = self.card("用户与林墨到旧书店找书。", event_status="complete", retention="episode",
                          source_end_message_id=self.source_ids[0])
        reaction = self.card("林墨因为这次陪伴而放松下来。", memory_type="relationship", retention="transient",
                             event_index=0, source_start_message_id=self.source_ids[-1])
        self.assertEqual(1, self.extract([event, reaction])[0])
        chunk = self.db.query(MemoryChunk).one()
        self.assertEqual(self.source_ids, [source["id"] for source in json.loads(chunk.source_evidence_json)])
        self.db.get(ChatMessage, self.source_ids[-1]).content = "这条反应已修改。"
        self.db.commit()
        self.assertFalse(fact_sources_current(chunk, self.db))

    def test_explicit_durable_emotion_and_promise_are_not_absorbed(self):
        cards = [self.card(event_status="complete"), self.card("林墨长期害怕被抛弃。", memory_type="emotion",
                importance_score=.4, retention="state"), self.card("林墨承诺下次迟到前先通知用户。",
                memory_type="relationship", retention="state")]
        self.assertEqual(3, self.extract(cards)[0])
        self.assertEqual({MemoryType.event, MemoryType.emotion, MemoryType.relationship},
                         {row.memory_type for row in self.db.query(MemoryChunk).all()})

    def test_invalid_or_ambiguous_event_link_preserves_independent_reaction(self):
        for index in (True, "0", -1, 2):
            with self.subTest(index=index):
                cards = [self.card(retention="episode"), self.card("林墨此刻因为陪伴感到安心。",
                         memory_type="emotion", retention="transient", event_index=index)]
                normalized = extraction.normalize_extracted_memories(cards, self.source_ids)
                self.assertEqual(2, len(normalized))
        cards = [self.card("用户与林墨在书店找书。"), self.card("用户与林墨开始讨论旧地图。"),
                 self.card("林墨此刻觉得很放松。", memory_type="emotion", retention="transient")]
        self.assertEqual(3, len(extraction.normalize_extracted_memories(cards, self.source_ids)))

    def test_reaction_time_refines_event_and_prevents_merging_different_time(self):
        cards = [self.card("用户与林墨在书店找书。", retention="episode", temporal_status="unknown"),
                 self.card("林墨因为陪伴而放松下来。", memory_type="emotion", retention="transient",
                           event_index=0, temporal_note="周六夜里"),
                 self.card("林墨在另一次聊天时又觉得开心。", memory_type="emotion", retention="transient",
                           event_index=0, temporal_note="周日夜里")]
        normalized = extraction.normalize_extracted_memories(cards, self.source_ids)
        self.assertEqual(2, len(normalized))
        self.assertEqual(("historical", "周六夜里"),
                         (normalized[0]["temporal_status"], normalized[0]["temporal_note"]))
        self.assertEqual("周日夜里", normalized[1]["temporal_note"])

    def test_oversized_event_keeps_reaction_separate_without_truncating(self):
        event_text, reaction_text = "A" * 490, "本次反应" * 30
        cards = [self.card(event_text, event_status="complete"), self.card(reaction_text, memory_type="emotion",
                 retention="transient", event_index=0, importance_score=.9)]
        self.assertEqual(2, self.extract(cards)[0])
        self.assertEqual({event_text, reaction_text}, {row.content for row in self.db.query(MemoryChunk).all()})

    def _refine(self, *, kind="refinement", old_legacy=False, incoming_text=None, resolved_text=None):
        old_text = "用户与林墨约定周六见面，只有暴雨时才取消。"
        if old_legacy:
            old = MemoryChunk(persona_id=self.persona.id, content=old_text, memory_type=MemoryType.relationship,
                              temporal_status="current", importance_score=.8)
            self.db.add(old)
            self.db.commit()
        else:
            self.extract([self.card(old_text, memory_type="relationship", retention="state", temporal_status="current")])
            old = self.db.query(MemoryChunk).one()
        old_id = old.id
        old_sources = list(self.source_ids)
        self.advance("林墨补充了见面条件。")
        new_text = "用户与林墨约定周六八点在公园东门见面。" if kind == "refinement" else "用户与林墨取消了周六见面的约定。"
        new_text = incoming_text or new_text
        outputs = [{"memories": [self.card(new_text, memory_type="relationship", retention="state",
                    temporal_status="current")], "entities": [], "relations": []},
                   {"relation": "replace", "change_kind": kind, "matched_memory_id": old_id,
                    "resolved_content": resolved_text or new_text}]
        provider = SimpleNamespace(generate=MagicMock(side_effect=[
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(data, ensure_ascii=False)))])
            for data in outputs]))
        with patch.object(extraction, "get_llm_provider", return_value=provider):
            self.assertEqual(1, extraction.summarize_and_store_memory(self.session_id, self.db))
        new = self.db.query(MemoryChunk).filter(MemoryChunk.id != old_id).one()
        return old, new, old_text, new_text, old_sources

    def test_state_refinement_preserves_old_condition_and_both_message_proofs(self):
        old, new, old_text, new_text, old_sources = self._refine()
        self.assertEqual(old.id, new.supersedes_id)
        self.assertIn(old_text, new.content)
        self.assertIn(new_text, new.content)
        self.assertEqual(old_sources + self.source_ids, [s["id"] for s in json.loads(new.source_evidence_json)])
        self.assertTrue(fact_sources_current(new, self.db))
        self.db.get(ChatMessage, old_sources[0]).content = "原来的取消条件被改写了。"
        self.db.commit()
        self.assertFalse(fact_sources_current(new, self.db))

    def test_state_correction_does_not_retain_cancelled_promise_or_old_proof(self):
        old, new, old_text, new_text, old_sources = self._refine(kind="correction")
        self.assertEqual(old.id, new.supersedes_id)
        self.assertEqual(new_text, new.content)
        self.assertEqual(self.source_ids, [s["id"] for s in json.loads(new.source_evidence_json)])
        self.db.get(ChatMessage, old_sources[0]).content = "旧消息已编辑，不影响新的明确取消。"
        self.db.commit()
        self.assertTrue(fact_sources_current(new, self.db))

    def test_unverified_legacy_state_refinement_preserves_both_cards(self):
        old, new, old_text, new_text, _ = self._refine(old_legacy=True)
        self.assertIsNone(new.supersedes_id)
        self.assertEqual(old_text, old.content)
        self.assertEqual(new_text, new.content)

    def test_partial_correction_keeps_old_condition_evidence_without_old_time(self):
        resolved = "双方改到周日上午九点见面，仍然只有暴雨时才取消。"
        old, new, _, _, old_sources = self._refine(kind="correction",
            incoming_text="双方把见面时间改为周日上午九点。", resolved_text=resolved)
        self.assertEqual(old.id, new.supersedes_id)
        self.assertEqual(resolved, new.content)
        self.assertEqual(old_sources + self.source_ids, [s["id"] for s in json.loads(new.source_evidence_json)])
