"""Joint recall must find connected facts without duplicating or leaking them."""
import unittest
import json
from unittest.mock import patch

from core.models import (ChatMessage, MemoryChunk, MessageRole, MemoryConsolidation,
                         MemoryConsolidationSource, MemoryConsolidationScope)
from services.memory import joint_retrieval as joint
from services.memory.graph_evidence import content_fingerprint, snapshot_sources
from services.memory.graph_service import upsert_graph_data
from services.memory.memory_facts import normalize_temporal
from tests.memory import test_graph_rag_quality as fixture


class JointRetrievalTests(unittest.TestCase):
    setUp = fixture.GraphRagQualityTests.setUp
    tearDown = fixture.GraphRagQualityTests.tearDown

    def fact(self, text, source="小红", target="旧城", *, persona=None, status="unknown", note=None):
        persona = persona or self.parent_persona
        message = ChatMessage(session_id=persona.session_id, role=MessageRole.user,
                              content=text, is_active=True)
        self.db.add(message)
        self.db.flush()
        if persona.id == self.parent_persona.id and self.child_session.fork_message_id is None:
            self.child_session.fork_message_id = message.id
        self.db.add(ChatMessage(session_id=persona.session_id, role=MessageRole.user,
                                content="继续", is_active=True))
        memory = MemoryChunk(persona_id=persona.id, content=text, memory_type="event", importance_score=.8,
                             source_start_message_id=message.id, source_message_id=message.id,
                             temporal_status=status, temporal_note=note)
        self.db.add(memory)
        memory.source_evidence_json = json.dumps(snapshot_sources([message]))
        self.db.flush()
        upsert_graph_data(persona.id, [], [{"source": source, "target": target,
            "relation_type": "visited", "description": "独立图谱措辞不应进入聊天", "importance": .9}], self.db,
            source_messages=snapshot_sources([message]), memory_bindings={0: {
                "memory_id": memory.id, "hash": content_fingerprint(text),
                "source_start": message.id, "source_end": message.id}})
        self.db.commit()
        return memory

    def recall(self, query="小红", semantic=(), persona=None, **kwargs):
        persona = persona or self.parent_persona
        with patch.object(joint.memory_manager, "retrieve_memories", return_value=list(semantic)):
            return joint.retrieve_joint_memories(persona.id, self.character.id, query, self.db, **kwargs)

    def test_semantic_seed_finds_neighbors_without_entity_name_in_question(self):
        one = self.fact("小红曾去旧城调查。")
        two = self.fact("旧城靠近北塔。", "旧城", "北塔")
        result = self.recall("后来那里怎么样？", [{"id": one.id}])
        self.assertEqual([one.id, two.id], [row["id"] for row in result])
        self.assertEqual(["semantic", "graph"], [row["retrieval_channel"] for row in result])

    def test_graph_recovers_original_card_when_vector_has_no_hits(self):
        card = self.fact("小红去了旧城。")
        result = self.recall()
        self.assertEqual([card.content], [row["content"] for row in result])
        self.assertNotIn("独立图谱措辞", str(result))

    def test_shared_fact_is_injected_only_once_and_sqlite_text_wins(self):
        card = self.fact("小红去了旧城。")
        result = self.recall(semantic=[{"id": card.id, "content": "过期索引正文"}] * 2)
        self.assertEqual(1, len(result))
        self.assertEqual(card.content, result[0]["content"])

    def test_semantic_age_survives_joint_recall_and_prompt_rendering(self):
        from services.conversation.prompt_compiler import build_chat_messages

        card = self.fact("小红去了旧城。")
        result = self.recall(semantic=[{"id": card.id, "turns_passed": 100}])
        self.assertEqual(100, result[0]["turns_passed"])
        with patch.object(fixture.settings, "APP_RP_TIME_TIERS", [{"max_turns": 100, "label": "很久以前"}]):
            messages = build_chat_messages(self.character, self.parent_persona, [], "后来呢？",
                                           retrieved_memories=result)
        self.assertIn("[很久以前] [event] " + card.content,
                      "\n".join(message["content"] for message in messages))

    def test_graph_age_counts_only_visible_branch_user_turns(self):
        card = self.fact("小红去了旧城。")
        self.db.add_all([
            ChatMessage(session_id=self.parent_session.id, role=MessageRole.user,
                        content="父线分叉后的未来", is_active=True),
            ChatMessage(session_id=self.child_session.id, role=MessageRole.user,
                        content=card.content, is_active=True),  # 分叉边界的复制消息
            ChatMessage(session_id=self.child_session.id, role=MessageRole.assistant,
                        content="助手回复", is_active=True),
            ChatMessage(session_id=self.child_session.id, role=MessageRole.user,
                        content="旧候选", is_active=False),
            ChatMessage(session_id=self.child_session.id, role=MessageRole.user,
                        content="子线继续", is_active=True),
        ])
        self.db.commit()
        result = self.recall(persona=self.child_persona)
        self.assertEqual([card.id], [row["id"] for row in result])
        self.assertEqual(1, result[0]["turns_passed"])

    def test_graph_fact_age_matches_semantic_fact_convention(self):
        card = self.fact("小红是调查员。")
        card.memory_type = "fact"
        self.db.commit()
        self.assertEqual(0, self.recall()[0]["turns_passed"])

    def test_future_parent_cannot_seed_graph_or_be_injected_in_child(self):
        old = self.fact("小红去了旧城。")
        future = self.fact("小红未来去了秘密北塔。", target="秘密北塔")
        result = self.recall(semantic=[{"id": future.id}], persona=self.child_persona)
        self.assertEqual([old.id], [row["id"] for row in result])
        self.assertNotIn("秘密", str(result))

    def test_invalidated_graph_does_not_recover_deleted_or_edited_sources(self):
        card = self.fact("小红去了旧城。")
        self.db.get(ChatMessage, card.source_message_id).content = "已纠正原文"
        self.db.commit()
        self.assertEqual([], self.recall())
        self.assertEqual([], self.recall(semantic=[{"id": card.id}]))

    def test_replaced_fact_cannot_be_reintroduced_by_vector_seed(self):
        old = self.fact("小红去了旧城。")
        new = self.fact("小红改去南城。", target="南城")
        new.supersedes_id = old.id
        self.db.commit()
        self.assertEqual([new.id], [row["id"] for row in self.recall(semantic=[{"id": old.id}])])

    def test_prompt_cutoff_resolves_replacements_as_of_that_turn(self):
        old = self.fact("小红去了旧城。")
        new = self.fact("小红改去南城。", target="南城")
        new.supersedes_id = old.id
        self.db.commit()
        result = self.recall(semantic=[{"id": old.id}, {"id": new.id}],
                             before_message_id=new.source_message_id)
        self.assertEqual([old.id], [row["id"] for row in result])

    def test_plan_and_historical_event_on_same_edge_coexist(self):
        planned = self.fact("小红计划下个月去旧城。", status="planned", note="下个月")
        historical = self.fact("小红去年去过旧城。", status="historical", note="去年")
        result = self.recall()
        self.assertEqual({planned.id, historical.id}, {row["id"] for row in result})
        self.assertEqual({"planned", "historical"}, {row["temporal_status"] for row in result})

    def test_prompt_renders_plan_once_with_its_story_time(self):
        from services.conversation.prompt_compiler import build_chat_messages
        planned = self.fact("小红计划去旧城。", status="planned", note="下个月")
        memories = self.recall(semantic=[{"id": planned.id}])
        messages = build_chat_messages(self.character, self.parent_persona, [], "她去过了吗？",
                                       retrieved_memories=memories)
        text = "\n".join(message["content"] for message in messages)
        self.assertEqual(1, text.count(planned.content))
        self.assertIn("计划，尚未确认发生；下个月", text)
        self.assertNotIn("<factual_relationships>", text)

    def test_consolidated_graph_sources_map_to_active_summary(self):
        one = self.fact("小红去了旧城。")
        two = self.fact("旧城靠近北塔。", "旧城", "北塔")
        batch = MemoryConsolidation(persona_id=self.parent_persona.id, status="applied", preview_json="{}")
        self.db.add(batch)
        self.db.flush()
        summary = MemoryChunk(persona_id=self.parent_persona.id, content="小红去过靠近北塔的旧城。",
                              memory_type="event", importance_score=.8, consolidation_id=batch.id,
                              source_message_id=two.source_message_id)
        self.db.add(summary)
        self.db.flush()
        self.db.add_all([MemoryConsolidationSource(summary_id=summary.id, source_id=one.id),
                         MemoryConsolidationSource(summary_id=summary.id, source_id=two.id),
                         MemoryConsolidationScope(persona_id=self.parent_persona.id, consolidation_id=batch.id)])
        self.db.commit()
        self.assertEqual([summary.id], [row["id"] for row in self.recall()])
        three = self.fact("北塔附近有一座港口。", "北塔", "港口")
        result = self.recall("后来那里怎么样？", [{"id": summary.id}])
        self.assertEqual([summary.id, three.id], [row["id"] for row in result])

    def test_budget_skips_oversize_cards_without_truncating_other_facts(self):
        one = self.fact("小红去了旧城。")
        two = self.fact("小红又去了南城。", target="南城")
        one.content = "很长的人工记忆。" * 200
        self.db.commit()
        with patch.object(joint, "MAX_FACT_CHARS", len(two.content) + 80):
            result = self.recall(semantic=[{"id": one.id}, {"id": two.id}])
        self.assertEqual([two.id], [row["id"] for row in result])
        with patch.object(joint, "MAX_FACTS", 1):
            self.assertEqual(1, len(self.recall(semantic=[{"id": one.id}])) )

    def test_temporal_normalization_keeps_uncertainty_and_bounds_notes(self):
        self.assertEqual(("unknown", None), normalize_temporal("invented", []))
        self.assertEqual(("unknown", None), normalize_temporal([], None))
        status, note = normalize_temporal("planned", "下个月 " * 100)
        self.assertEqual("planned", status)
        self.assertLessEqual(len(note), 120)

    def test_entity_only_graph_can_return_backing_fact(self):
        card = self.fact("小红是调查员。")
        from core.models import GraphRelation
        self.db.query(GraphRelation).delete()
        message = self.db.get(ChatMessage, card.source_message_id)
        upsert_graph_data(self.parent_persona.id,
            [{"name": "小红", "description": "调查员"}], [], self.db,
            source_messages=snapshot_sources([message]), memory_bindings={0: {
                "memory_id": card.id, "hash": content_fingerprint(card.content),
                "source_start": message.id, "source_end": message.id}})
        self.db.commit()
        self.assertEqual([card.id], [row["id"] for row in self.recall()])
