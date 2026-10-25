"""Graph evidence must agree with branch-local memory and message versions."""
import json
import unittest
from unittest.mock import patch
from core.models import ChatMessage, GraphEntity, GraphRelation, MemoryChunk, MessageRole, Session, SessionPersona
from services.memory.graph_evidence import content_fingerprint, snapshot_sources
from services.memory.graph_service import retrieve_graph_context, upsert_graph_data
from services.memory.memory_visibility import memory_view
from services.memory.memory_manager import delete_memory_chunk, update_memory_chunk
from tests.memory import test_graph_rag_quality as fixture
from tests.memory import test_memory_card_extraction as extraction_fixture
from services.memory import memory_extraction_service as extraction


class GraphMemoryConsistencyTests(unittest.TestCase):
    setUp = fixture.GraphRagQualityTests.setUp
    tearDown = fixture.GraphRagQualityTests.tearDown
    _upsert = fixture.GraphRagQualityTests._upsert

    def fact(self, persona=None, description="小红喜欢蛋糕。", relation="likes", entities=None):
        return self._upsert(persona or self.parent_persona,
            entities if entities is not None else [{"name":"小红", "entity_type":"person", "description":"旧身份"}, {"name":"蛋糕", "entity_type":"object"}],
            [{"source":"小红", "target":"蛋糕", "relation_type":relation, "description":description, "importance":.8}])

    def context(self, persona=None):
        return retrieve_graph_context((persona or self.parent_persona).id, "小红", self.db)

    def test_parent_future_is_excluded_from_both_memory_and_graph(self):
        old = self.fact()
        future = self.fact(description="小红后来把蛋糕藏在北塔。", relation="hid")
        visible, hidden = memory_view(self.child_persona.id, self.db)
        ids = {row.id for row in self.db.query(MemoryChunk).filter(visible, MemoryChunk.id.not_in(hidden)).all()}
        self.assertIn(old.id, ids)
        self.assertNotIn(future.id, ids)
        context = self.context(self.child_persona)
        self.assertIn("喜欢蛋糕", context)
        self.assertNotIn("北塔", context)

    def test_parent_update_retains_old_child_description_and_edge(self):
        self.fact()
        before = self.context(self.child_persona)
        self.fact(description="小红现在只偶尔吃蛋糕。", entities=[{"name":"小红", "entity_type":"person", "description":"新身份"}])
        self.assertEqual(before, self.context(self.child_persona))
        self.assertIn("只偶尔", self.context())
        self.assertNotIn("喜欢蛋糕", self.context())
        self.assertNotIn("旧身份", self.context())
        self.assertEqual(2, self.db.query(GraphRelation).count())

    def test_replacement_masks_opposite_edge_only_on_its_branch(self):
        old = self.fact()
        new = self.fact(self.child_persona, "小红已经讨厌蛋糕。", "dislikes")
        new.supersedes_id = old.id
        self.db.commit()
        context = self.context(self.child_persona)
        self.assertIn("讨厌蛋糕", context)
        self.assertNotIn("喜欢蛋糕", context)
        self.assertIn("喜欢蛋糕", self.context())

    def test_manual_edit_and_delete_invalidate_supported_graph(self):
        memory = self.fact()
        update_memory_chunk(memory.id, "这条记忆已人工纠正。", .8, self.db)
        self.assertEqual("", self.context())
        delete_memory_chunk(memory.id, self.db)
        self.assertEqual("", self.context())

    def test_source_message_edit_delete_or_inactive_invalidates_graph(self):
        memory = self.fact()
        message = self.db.get(ChatMessage, memory.source_message_id)
        original = message.content
        message.content = "修改过的对话"
        self.db.commit()
        self.assertEqual("", self.context())
        message.content = original
        message.is_active = False
        self.db.commit()
        self.assertEqual("", self.context())
        self.db.delete(message)
        self.db.commit()
        self.assertEqual("", self.context())

    def test_deleting_confirmation_does_not_recall_unconfirmed_last_turn(self):
        self.fact()
        confirmation = self.db.query(ChatMessage).filter(
            ChatMessage.session_id == self.parent_session.id,
            ChatMessage.role == MessageRole.user).order_by(ChatMessage.id.desc()).first()
        self.db.delete(confirmation)
        self.db.commit()
        self.assertEqual("", self.context())

    def test_unknown_legacy_rows_are_preserved_but_not_recalled(self):
        entity = GraphEntity(persona_id=self.parent_persona.id, name="小红", entity_type="person", description="没有来源的旧事实")
        self.db.add(entity)
        self.db.flush()
        self.db.add(GraphRelation(persona_id=self.parent_persona.id, source_id=entity.id, target_id=entity.id, relation_type="legacy", description="旧关系", importance=.9))
        self.db.commit()
        self.assertEqual("", self.context())
        self.assertEqual("", self.context(self.child_persona))
        self.assertEqual(1, self.db.query(GraphRelation).count())

    def test_missing_fork_boundary_does_not_inherit_graph(self):
        self.fact()
        self.child_session.fork_message_id = None
        self.db.commit()
        self.assertEqual("", self.context(self.child_persona))

    def test_aliases_do_not_become_detached_from_original_evidence(self):
        old = self.fact(entities=[{"name":"小红", "entity_type":"person", "aliases":["红红"]}])
        self.fact(description="新近的独立事件", relation="visited", entities=[{"name":"小红", "description":"新描述"}])
        self.assertIn("新近", retrieve_graph_context(self.parent_persona.id, "红红", self.db))
        update_memory_chunk(old.id, "旧别名已纠正", .8, self.db)
        self.assertEqual("", retrieve_graph_context(self.parent_persona.id, "红红", self.db))
        self.assertIn("新近", self.context())

    def test_prompt_time_boundary_excludes_later_current_facts(self):
        memory = self.fact()
        self.assertEqual("", retrieve_graph_context(self.parent_persona.id, "小红", self.db,
                                                   before_message_id=memory.source_message_id))

    def test_alias_resolution_does_not_rewrite_new_fact_identity_without_evidence(self):
        old = self.fact(entities=[{"name":"小红", "aliases":["红红"]}])
        self._upsert(self.parent_persona, [{"name":"红红", "description":"另一次对话中的名字"}],
                     [{"source":"红红", "target":"茶", "relation_type":"likes", "description":"红红喜欢茶。", "importance":.8}])
        update_memory_chunk(old.id, "先前的别名对应有误", .8, self.db)
        self.assertNotIn("喜欢茶", self.context())
        self.assertIn("喜欢茶", retrieve_graph_context(self.parent_persona.id, "红红", self.db))

    def test_lower_importance_latest_version_does_not_resurrect_old_edge(self):
        self.fact()
        self.fact(description="新关系低于阈值")
        latest = self.db.query(GraphRelation).order_by(GraphRelation.id.desc()).first()
        latest.importance = 0
        self.db.commit()
        with patch.object(fixture.settings, "APP_GRAPH_MIN_IMPORTANCE", .5):
            self.assertEqual("", self.context())

    def test_invalid_evidence_and_unbacked_writes_are_ignored(self):
        upsert_graph_data(self.parent_persona.id, [{"name":"小红"}], [], self.db)
        self.assertEqual(0, self.db.query(GraphEntity).count())
        self.fact()
        for row in self.db.query(GraphEntity).all() + self.db.query(GraphRelation).all():
            row.evidence_json = '{"version":1,"memories":null}'
        self.db.commit()
        self.assertEqual("", self.context())

    def test_consolidation_does_not_destroy_valid_original_evidence(self):
        from core.models import MemoryConsolidation, MemoryConsolidationSource, MemoryConsolidationScope
        one = self.fact()
        two = self.fact(description="小红送出了蛋糕。", relation="gave")
        batch = MemoryConsolidation(persona_id=self.parent_persona.id, status="applied", preview_json="{}")
        self.db.add(batch)
        self.db.flush()
        summary = MemoryChunk(persona_id=self.parent_persona.id, content="整理后的完整记忆", memory_type="fact", importance_score=.8,
                              consolidation_id=batch.id, source_message_id=two.source_message_id)
        self.db.add(summary)
        self.db.flush()
        self.db.add_all([MemoryConsolidationSource(summary_id=summary.id, source_id=one.id),
                         MemoryConsolidationSource(summary_id=summary.id, source_id=two.id),
                         MemoryConsolidationScope(persona_id=self.parent_persona.id, consolidation_id=batch.id)])
        self.db.commit()
        self.assertIn("喜欢蛋糕", self.context())
        self.assertIn("送出了", self.context())

    def test_sibling_and_multi_generation_boundaries_remain_independent(self):
        self.fact()
        child_memory = self.fact(self.child_persona, "小红在子故事送出蛋糕。", "gave")
        grand_session = Session(title="grandchild", parent_session_id=self.child_session.id,
                                fork_message_id=child_memory.source_message_id)
        self.db.add(grand_session)
        self.db.flush()
        grand = SessionPersona(session_id=grand_session.id, character_id=self.character.id,
                               parent_persona_id=self.child_persona.id)
        self.db.add(grand)
        self.db.commit()
        self.fact(self.child_persona, "小红在子故事未来去了北塔。", "visited")
        self.fact(description="小红在父故事未来去了南塔。", relation="visited")
        context = self.context(grand)
        self.assertIn("喜欢蛋糕", context)
        self.assertIn("送出蛋糕", context)
        self.assertNotIn("北塔", context)
        self.assertNotIn("南塔", context)


class GraphExtractionIntegrationTests(unittest.TestCase):
    setUp = extraction_fixture.MemoryCardExtractionTests.setUp
    tearDown = extraction_fixture.MemoryCardExtractionTests.tearDown
    _provider_with_payload = staticmethod(extraction_fixture.MemoryCardExtractionTests._provider_with_payload)

    def payload(self):
        return {"memories": [
            {"content":"hello"},
            {"content":"User plans to move to Hangzhou Binjiang for work.", "memory_type":"event", "importance_score":.4,
             "source_start_message_id":self.messages[0].id, "source_end_message_id":self.messages[2].id},
            {"content":"User's cat is named Doubao.", "memory_type":"fact", "importance_score":.4,
             "source_start_message_id":self.messages[3].id, "source_end_message_id":self.messages[3].id}],
            "entities":[{"name":"Doubao", "entity_type":"person", "description":"用户的猫", "memory_indices":[2]}],
            "relations":[{"source":"用户", "target":"Doubao", "relation_type":"owns", "description":"用户的猫叫 Doubao。", "importance":.8, "memory_indices":[2]}]}

    def run_extraction(self, payload, side_effect=None, candidates=None):
        provider = self._provider_with_payload(payload)
        if side_effect:
            response = provider.generate.return_value
            def respond(**_):
                side_effect()
                return response
            provider.generate.side_effect = respond
        with patch.object(extraction, "get_llm_provider", return_value=provider), \
             patch.object(extraction, "retrieve_write_candidates", return_value=candidates or []), \
             patch.object(extraction.cognition_service, "update_cognition_state"):
            return extraction.summarize_and_store_memory(self.session_id, self.db)

    def test_indices_refer_to_original_array_after_normalization_and_are_precise(self):
        self.assertEqual(2, self.run_extraction(self.payload()))
        relation = self.db.query(GraphRelation).one()
        evidence = json.loads(relation.evidence_json)
        cat = self.db.query(MemoryChunk).filter(MemoryChunk.content.contains("Doubao")).one()
        self.assertEqual([cat.id], [item["id"] for item in evidence["memories"]])
        other = self.db.query(MemoryChunk).filter(MemoryChunk.id != cat.id).one()
        delete_memory_chunk(other.id, self.db)
        self.assertIn("Doubao", retrieve_graph_context(self.persona.id, "用户", self.db))
        delete_memory_chunk(cat.id, self.db)
        self.assertEqual("", retrieve_graph_context(self.persona.id, "用户", self.db))

    def test_old_model_output_without_indices_uses_conservative_batch_dependencies(self):
        payload = self.payload()
        for row in payload["entities"] + payload["relations"]:
            row.pop("memory_indices")
        self.assertEqual(2, self.run_extraction(payload))
        self.assertEqual(2, len(json.loads(self.db.query(GraphRelation).one().evidence_json)["memories"]))

    def test_invalid_indices_cannot_attach_to_a_different_retained_memory(self):
        payload = self.payload()
        for row in payload["entities"] + payload["relations"]:
            row["memory_indices"] = [0]  # 寒暄已被丢弃，不能映射到后面的有效卡。
        self.assertEqual(2, self.run_extraction(payload))
        self.assertEqual(0, self.db.query(GraphRelation).count())

    def test_message_change_during_model_call_stores_neither_memory_nor_graph(self):
        def change_source():
            self.messages[0].content = "已经修改的历史"
            self.db.commit()
        self.assertEqual(0, self.run_extraction(self.payload(), change_source))
        self.assertEqual(0, self.db.query(MemoryChunk).count())
        self.assertEqual(0, self.db.query(GraphRelation).count())
        self.db.refresh(self.persona)
        self.assertIsNone(self.persona.last_summarized_msg_id)

    def test_graph_failure_rolls_back_only_dependent_component(self):
        from core.models import OutboxJob
        with patch.object(extraction, "upsert_graph_data", side_effect=RuntimeError("fixture graph write failed")):
            self.assertEqual(1, self.run_extraction(self.payload()))
        self.assertEqual(1, self.db.query(MemoryChunk).count())
        self.assertEqual(1, self.db.query(OutboxJob).count())
        self.db.refresh(self.persona)
        self.assertEqual(self.messages[-1].id, self.persona.last_summarized_msg_id)
        from core.models import MemoryExtractionJob
        self.assertEqual(1, self.db.query(MemoryExtractionJob).filter_by(status="retrying").count())

    def next_payload(self, name="Doubao"):
        message = ChatMessage(session_id=self.session_id, role=MessageRole.assistant,
                              content="用户的猫现在叫 " + name, is_active=True)
        self.db.add(message)
        self.db.flush()
        self.db.add(ChatMessage(session_id=self.session_id, role=MessageRole.user, content="继续", is_active=True))
        self.db.commit()
        return {"memories":[{"content":"User's cat is named " + name + ".", "memory_type":"fact", "importance_score":.4,
                              "source_start_message_id":message.id, "source_end_message_id":message.id}],
                "entities":[{"name":name, "description":"用户的猫", "memory_indices":[0]}],
                "relations":[{"source":"用户", "target":name, "relation_type":"owns", "description":"用户的猫叫 " + name,
                               "importance":.8, "memory_indices":[0]}]}

    def test_same_reuses_retained_memory_as_evidence(self):
        self.run_extraction(self.payload())
        old = self.db.query(MemoryChunk).filter(MemoryChunk.content.contains("Doubao")).one()
        payload = self.next_payload()
        with patch.object(extraction, "resolve_memory_relationship_via_llm", return_value={"relation":"same", "resolved_content":old.content}):
            self.assertEqual(0, self.run_extraction(payload, candidates=[{"id":old.id,"content":old.content,"distance":0.0}]))
        self.assertEqual(2, self.db.query(MemoryChunk).count())
        evidence = json.loads(self.db.query(GraphRelation).order_by(GraphRelation.id.desc()).first().evidence_json)
        self.assertEqual([old.id], [item["id"] for item in evidence["memories"]])

    def test_invalid_old_source_cannot_discard_fresh_same_evidence(self):
        from services.memory.memory_facts import fact_sources_current

        self.run_extraction(self.payload())
        old = self.db.query(MemoryChunk).filter(MemoryChunk.content.contains("Doubao")).one()
        self.db.get(ChatMessage, old.source_message_id).content = "先前的猫名记错了。"
        self.db.commit()
        self.assertFalse(fact_sources_current(old, self.db))
        payload = self.next_payload()
        with patch.object(extraction, "resolve_memory_relationship_via_llm",
                          return_value={"relation": "same"}) as resolver:
            self.assertEqual(1, self.run_extraction(payload, candidates=[{
                "id": old.id, "content": old.content, "distance": 0.0}]))
            resolver.assert_not_called()
        fresh = self.db.query(MemoryChunk).filter(
            MemoryChunk.content == old.content, MemoryChunk.id != old.id).one()
        self.assertTrue(fact_sources_current(fresh, self.db))
        self.assertIsNone(fresh.supersedes_id)
        self.assertEqual(payload["memories"][0]["source_end_message_id"], self.persona.last_summarized_msg_id)
        evidence = json.loads(self.db.query(GraphRelation).order_by(GraphRelation.id.desc()).first().evidence_json)
        self.assertEqual([fresh.id], [item["id"] for item in evidence["memories"]])

    def test_old_source_change_during_same_decision_rolls_back(self):
        self.run_extraction(self.payload())
        old = self.db.query(MemoryChunk).filter(MemoryChunk.content.contains("Doubao")).one()
        payload = self.next_payload()
        old_pointer = self.persona.last_summarized_msg_id

        def decision(*_):
            self.db.get(ChatMessage, old.source_message_id).content = "旧来源已被纠正。"
            self.db.commit()
            return {"relation": "same"}

        with patch.object(extraction, "resolve_memory_relationship_via_llm", side_effect=decision):
            self.assertEqual(0, self.run_extraction(payload, candidates=[{
                "id": old.id, "content": old.content, "distance": 0.0}]))
        self.assertEqual(2, self.db.query(MemoryChunk).count())
        self.assertEqual(1, self.db.query(GraphRelation).count())
        self.db.refresh(self.persona)
        self.assertEqual(payload["memories"][0]["source_end_message_id"], self.persona.last_summarized_msg_id)

    def test_replace_creates_new_graph_support_and_hides_old_target(self):
        self.run_extraction(self.payload())
        old = self.db.query(MemoryChunk).filter(MemoryChunk.content.contains("Doubao")).one()
        payload = self.next_payload("Mochi")
        with patch.object(extraction, "resolve_memory_relationship_via_llm", return_value={"relation":"replace", "resolved_content":payload["memories"][0]["content"]}):
            self.assertEqual(1, self.run_extraction(payload, candidates=[{"id":old.id,"content":old.content,"distance":0.0}]))
        context = retrieve_graph_context(self.persona.id, "用户", self.db)
        self.assertIn("Mochi", context)
        self.assertNotIn("Doubao", context)

    def test_source_change_during_relationship_decision_rolls_back_new_data(self):
        self.run_extraction(self.payload())
        old = self.db.query(MemoryChunk).filter(MemoryChunk.content.contains("Doubao")).one()
        payload = self.next_payload("Mochi")
        old_pointer = self.persona.last_summarized_msg_id
        def decision(*_):
            source = self.db.get(ChatMessage, payload["memories"][0]["source_end_message_id"])
            source.content = "已修改来源"
            self.db.commit()
            return {"relation":"replace", "resolved_content":payload["memories"][0]["content"]}
        with patch.object(extraction, "resolve_memory_relationship_via_llm", side_effect=decision):
            self.assertEqual(0, self.run_extraction(payload, candidates=[{"id":old.id,"content":old.content,"distance":0.0}]))
        self.assertEqual(2, self.db.query(MemoryChunk).count())
        self.assertEqual(1, self.db.query(GraphRelation).count())
        self.db.refresh(self.persona)
        self.assertEqual(payload["memories"][0]["source_end_message_id"], self.persona.last_summarized_msg_id)

    def test_memory_change_during_relationship_decision_cannot_advance_same(self):
        self.run_extraction(self.payload())
        old = self.db.query(MemoryChunk).filter(MemoryChunk.content.contains("Doubao")).one()
        old_content = old.content
        payload = self.next_payload()
        old_pointer = self.persona.last_summarized_msg_id
        def decision(*_):
            old.content = "用户已人工纠正猫的名字。"
            self.db.commit()
            return {"relation":"same", "resolved_content":old_content}
        with patch.object(extraction, "resolve_memory_relationship_via_llm", side_effect=decision):
            self.assertEqual(0, self.run_extraction(payload, candidates=[{"id":old.id,"content":old_content,"distance":0.0}]))
        self.assertEqual(1, self.db.query(GraphRelation).count())
        self.db.refresh(self.persona)
        self.assertEqual(payload["memories"][0]["source_end_message_id"], self.persona.last_summarized_msg_id)
