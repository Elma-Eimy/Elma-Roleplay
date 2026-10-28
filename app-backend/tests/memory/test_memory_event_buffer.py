"""进行中事件跨批次、来源与收尾的离线回归。"""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.models import (Base, Character, Session, SessionPersona, ChatMessage, MessageRole,
                         MemoryChunk, MemoryEventBuffer, OutboxJob, GraphEntity, GraphRelation)
from services.memory import memory_extraction_service as extraction
from services.memory.memory_event_buffer import load_event_snapshot, event_context
from services.memory.memory_facts import fact_sources_current
from services.conversation import context_assembler
from services.conversation.prompt_compiler import build_chat_messages
from services.conversation.session_service import create_session_service, safe_delete_session


class MemoryEventBufferTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(self.engine, "connect")
        def enable_fk(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)
        self.db = self.factory()
        character = Character(name="林墨", description="调查员", first_mes="你好。")
        story = Session(title="事件缓冲测试")
        self.db.add_all([character, story])
        self.db.flush()
        self.persona = SessionPersona(session_id=story.id, character_id=character.id)
        self.db.add(self.persona)
        self.db.commit()
        self.session_id = story.id
        self.current_user = None
        self.advance("用户与林墨开始约会。")

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def advance(self, text="用户与林墨继续谈心。"):
        if self.current_user is None:
            self.current_user = ChatMessage(session_id=self.session_id, role=MessageRole.user,
                                            content="一起去海边吧。", is_active=True)
            self.db.add(self.current_user)
            self.db.flush()
        first = self.current_user
        reply = ChatMessage(session_id=self.session_id, role=MessageRole.assistant, content=text, is_active=True)
        self.current_user = ChatMessage(session_id=self.session_id, role=MessageRole.user, content="请继续。", is_active=True)
        self.db.add_all([reply, self.current_user])
        self.db.commit()
        self.source_ids = [first.id, reply.id]

    def card(self, text="用户与林墨在海边开始约会，正在谈心。", **fields):
        return {"content": text, "memory_type": "event", "importance_score": .6,
                "temporal_status": "historical", "event_status": "ongoing", "buffer_id": None,
                "source_start_message_id": self.source_ids[0], "source_end_message_id": self.source_ids[-1], **fields}

    def extract(self, cards, entities=None, relations=None, *, force=False, callback=None):
        payload = {"memories": cards, "entities": entities or [], "relations": relations or []}
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)))])
        provider = SimpleNamespace(generate=MagicMock(return_value=response))
        if callback:
            def respond(**_):
                callback()
                return response
            provider.generate.side_effect = respond
        with patch.object(extraction, "get_llm_provider", return_value=provider), \
             patch.object(extraction, "resolve_memory_relationship_via_llm", return_value={"relation": "coexist"}):
            count = extraction.summarize_and_store_memory(self.session_id, self.db, flush_events=force)
        return count, provider

    def buffer(self):
        return self.db.query(MemoryEventBuffer).one()

    def test_invented_new_event_id_is_corrected_once_without_losing_batch(self):
        bad = self.card(buffer_id=1)
        good = self.card(buffer_id=None)
        responses = [SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps({"memories": [card], "entities": [], "relations": []}, ensure_ascii=False)))])
            for card in (bad, good)]
        provider = SimpleNamespace(generate=MagicMock(side_effect=responses))
        with patch.object(extraction, "get_llm_provider", return_value=provider), self.assertLogs(
                "uvicorn.error.memory_extraction", level="WARNING") as logs:
            self.assertEqual(0, extraction.summarize_and_store_memory(self.session_id, self.db))
        self.assertEqual(2, provider.generate.call_count)
        self.assertEqual("open", self.buffer().status)
        self.assertEqual(self.source_ids[-1], self.persona.last_summarized_msg_id)
        corrected = provider.generate.call_args.kwargs["messages"][0]["content"]
        self.assertIn("已有事件 ID 仅为 []", corrected)
        self.assertIn("invalid_event_reference", " ".join(logs.output))
        self.assertNotIn(good["content"], " ".join(logs.output))

    def test_repeated_invented_event_id_stays_deferred_without_creating_identity(self):
        pointer = self.persona.last_summarized_msg_id
        count, provider = self.extract([self.card(buffer_id=999)])
        self.assertEqual(0, count)
        self.assertEqual(2, provider.generate.call_count)
        self.assertEqual(pointer, self.persona.last_summarized_msg_id)
        self.assertEqual(0, self.db.query(MemoryEventBuffer).count())

    def test_stray_event_status_on_relationship_does_not_reject_independent_memories(self):
        cards = [self.card("用户与林墨的信任关系得到确认。", memory_type="relationship", event_status="ongoing", buffer_id=999),
                 self.card("用户与林墨完成海边散步。", event_status="complete")]
        count, provider = self.extract(cards)
        self.assertEqual(2, count)
        self.assertEqual(1, provider.generate.call_count)
        self.assertEqual({"relationship", "event"}, {row.memory_type.value for row in self.db.query(MemoryChunk).all()})
        self.assertEqual(self.source_ids[-1], self.persona.last_summarized_msg_id)

    def test_three_batches_form_one_event_with_all_source_fingerprints(self):
        original_sources = list(self.source_ids)
        self.assertEqual(0, self.extract([self.card()])[0])
        buffer_id = self.buffer().id
        self.assertEqual(0, self.db.query(MemoryChunk).count())
        self.assertEqual(0, self.db.query(OutboxJob).count())
        self.advance("海边下雨，两人来到咖啡馆。")
        original_sources += self.source_ids
        self.assertEqual(0, self.extract([self.card("约会因雨转到咖啡馆，两人继续谈心。", buffer_id=buffer_id)])[0])
        self.assertEqual(buffer_id, self.buffer().id)
        self.advance("林墨约定明年再来海边，约会结束。")
        original_sources += self.source_ids
        count, provider = self.extract([self.card(
            "用户与林墨的海边约会因雨转到咖啡馆，两人谈心并约定明年重游，随后结束约会。",
            event_status="complete", buffer_id=buffer_id)])
        self.assertEqual(1, count)
        self.assertEqual(0, self.db.query(MemoryEventBuffer).filter_by(status="open").count())
        chunk = self.db.query(MemoryChunk).one()
        self.assertEqual(original_sources, [source["id"] for source in json.loads(chunk.source_evidence_json)])
        self.assertTrue(fact_sources_current(chunk, self.db))
        self.assertEqual(1, self.db.query(OutboxJob).count())
        self.assertIn("咖啡馆", provider.generate.call_args.kwargs["messages"][1]["content"])

    def test_durable_fact_and_planned_promise_can_bypass_event_buffer(self):
        cards = [self.card(), self.card("用户偏爱不加糖的红茶。", memory_type="fact", event_status="complete"),
                 self.card("用户与林墨约定明年重游海边。", temporal_status="planned", event_status="complete")]
        self.assertEqual(2, self.extract(cards)[0])
        self.assertEqual(1, self.db.query(MemoryEventBuffer).filter_by(status="open").count())
        promise = self.db.query(MemoryChunk).filter_by(temporal_status="planned").one()
        self.assertIn("明年", promise.content)

    def test_unmentioned_event_is_flushed_at_batch_limit(self):
        self.extract([self.card()])
        self.advance()
        self.extract([])
        self.assertEqual(2, self.buffer().age_batches)
        self.advance("两人开始讨论另一件事。")
        self.assertEqual(1, self.extract([])[0])
        self.assertEqual(0, self.db.query(MemoryEventBuffer).filter_by(status="open").count())
        self.assertIn("约会", self.db.query(MemoryChunk).one().content)

    def test_event_capacity_flushes_oldest_without_losing_cards(self):
        cards = [self.card(f"用户与林墨正在参与独立事件 {index}。") for index in range(4)]
        self.assertEqual(1, self.extract(cards)[0])
        self.assertEqual(3, self.db.query(MemoryEventBuffer).filter_by(status="open").count())
        self.assertIn("事件 0", self.db.query(MemoryChunk).one().content)

    def test_source_limit_closes_event_without_truncating_evidence(self):
        self.extract([self.card()])
        buffer_id = self.buffer().id
        self.advance()
        with patch("services.memory.memory_event_buffer.MAX_EVENT_MESSAGES", 4):
            self.assertEqual(1, self.extract([self.card(buffer_id=buffer_id)])[0])
        chunk = self.db.query(MemoryChunk).one()
        self.assertEqual(4, len(json.loads(chunk.source_evidence_json)))
        self.assertEqual(0, self.db.query(MemoryEventBuffer).filter_by(status="open").count())

    def test_manual_flush_survives_restart_and_needs_no_new_messages_or_model_call(self):
        self.extract([self.card()])
        persona_id = self.persona.id
        self.db.close()
        self.db = self.factory()
        self.persona = self.db.get(SessionPersona, persona_id)
        with patch.object(extraction, "get_llm_provider") as provider:
            self.assertEqual(1, extraction.summarize_and_store_memory(self.session_id, self.db, flush_events=True))
        provider.assert_not_called()
        self.assertEqual(0, self.db.query(MemoryEventBuffer).filter_by(status="open").count())
        self.assertTrue(fact_sources_current(self.db.query(MemoryChunk).one(), self.db))

    def test_manual_route_flushes_pending_event(self):
        from routers.sessions import trigger_memory_summary
        self.extract([self.card()])
        with patch.object(extraction, "get_llm_provider") as provider:
            response = trigger_memory_summary(self.session_id, self.db)
            self.assertEqual("pending", response["status"])
            self.assertEqual(0, response["extracted_count"])
            from services.memory.memory_extraction_jobs import process_due_jobs
            process_due_jobs(self.db, self.persona.id)
            self.assertEqual(1, process_due_jobs(self.db, self.persona.id))
        self.assertEqual(0, self.db.query(MemoryEventBuffer).filter_by(status="open").count())
        provider.assert_not_called()

    def test_pending_graph_is_published_only_when_event_is_admitted(self):
        self.extract([self.card()], entities=[{"name": "海边", "description": "约会地点", "memory_indices": [0]}])
        self.assertEqual(0, self.db.query(GraphEntity).count())
        self.assertEqual(1, extraction.summarize_and_store_memory(self.session_id, self.db, flush_events=True))
        entity = self.db.query(GraphEntity).filter_by(name="海边").one()
        evidence = json.loads(entity.evidence_json)
        self.assertEqual(self.db.query(MemoryChunk).one().id, evidence["memories"][0]["id"])

    def test_graph_failure_rolls_back_buffer_release_and_progress(self):
        self.extract([self.card()], entities=[{"name": "海边", "memory_indices": [0]}])
        buffer_id = self.buffer().id
        pointer = self.persona.last_summarized_msg_id
        with patch.object(extraction, "upsert_graph_data", side_effect=RuntimeError("graph unavailable")):
            self.assertEqual(0, extraction.summarize_and_store_memory(self.session_id, self.db, flush_events=True))
        self.assertEqual(buffer_id, self.buffer().id)
        self.assertEqual(0, self.db.query(MemoryChunk).count())
        self.assertEqual(0, self.db.query(OutboxJob).count())
        self.assertEqual(pointer, self.persona.last_summarized_msg_id)

    def test_invalid_or_foreign_buffer_id_does_not_advance_progress(self):
        self.extract([self.card()])
        buffer_id = self.buffer().id
        pointer = self.persona.last_summarized_msg_id
        self.advance()
        self.assertEqual(0, self.extract([self.card(buffer_id=buffer_id + 100)])[0])
        self.assertEqual(1, self.buffer().age_batches)
        self.assertEqual(pointer, self.persona.last_summarized_msg_id)

    def test_event_temporal_change_is_rejected_with_safe_reason(self):
        self.extract([self.card()])
        buffer_id = self.buffer().id
        pointer = self.persona.last_summarized_msg_id
        self.advance()
        with self.assertLogs("uvicorn.error.memory_extraction", level="WARNING") as logs:
            self.assertEqual(0, self.extract([self.card(buffer_id=buffer_id, temporal_status="planned")])[0])
        self.assertIn("event_temporal_mismatch", " ".join(logs.output))
        self.assertNotIn("约会", " ".join(logs.output))
        self.assertEqual(pointer, self.persona.last_summarized_msg_id)
        self.assertEqual(1, self.buffer().age_batches)

    def test_changed_buffer_during_model_call_cannot_overwrite_new_state(self):
        self.extract([self.card()])
        buffer_id = self.buffer().id
        pointer = self.persona.last_summarized_msg_id
        self.advance()

        def change_buffer():
            self.buffer().revision += 1
            self.db.commit()

        self.assertEqual(0, self.extract([self.card(buffer_id=buffer_id)], callback=change_buffer)[0])
        self.assertEqual(2, self.buffer().revision)
        self.assertEqual(pointer, self.persona.last_summarized_msg_id)

    def test_source_edit_hides_buffer_and_prevents_stale_promotion(self):
        self.extract([self.card()])
        self.db.get(ChatMessage, self.source_ids[0]).content = "原消息已修改。"
        self.db.commit()
        self.assertEqual([], event_context(load_event_snapshot(self.persona.id, self.db)))
        self.assertEqual(0, extraction.summarize_and_store_memory(self.session_id, self.db, flush_events=True))
        self.assertEqual(0, self.db.query(MemoryChunk).count())
        self.assertEqual(0, self.db.query(MemoryEventBuffer).filter_by(status="open").count())

    def test_chat_context_receives_valid_pending_event_before_long_term_promotion(self):
        self.extract([self.card()])
        character = self.persona.character
        with patch.object(context_assembler, "retrieve_joint_memories", return_value=[]), \
             patch.object(context_assembler, "resolve_state", return_value=({"state": {}}, [])), \
             patch.object(context_assembler, "build_chat_messages", return_value=[]) as build:
            asyncio.run(context_assembler.assemble_prompt_context(
                self.session_id, character, self.persona, self.current_user, None, self.db))
        ongoing = build.call_args.kwargs["ongoing_events"]
        self.assertEqual(1, len(ongoing))
        messages = build_chat_messages(character, self.persona, [], "请继续。", ongoing_events=ongoing)
        rendered = json.dumps(messages, ensure_ascii=False)
        self.assertIn("<ongoing_events>", rendered)
        self.assertIn("正在谈心", rendered)
        self.assertEqual([], event_context(load_event_snapshot(
            self.persona.id, self.db, before_message_id=self.source_ids[-1])))

    def fork(self, message_id):
        result = create_session_service(character_id=self.persona.character_id, parent_session_id=self.session_id,
                                        title="分支", greeting_index=None, start_message_id=message_id, db=self.db)
        return result["persona_id"]

    def test_fork_flushes_only_event_wholly_before_boundary(self):
        self.extract([self.card()])
        child_id = self.fork(self.current_user.id)
        self.assertEqual(0, self.db.query(MemoryEventBuffer).filter_by(status="open").count())
        self.assertEqual(1, self.db.query(MemoryChunk).count())
        from services.memory.memory_visibility import memory_view
        visible, hidden = memory_view(child_id, self.db)
        self.assertEqual(1, self.db.query(MemoryChunk).filter(visible, MemoryChunk.id.not_in(hidden)).count())

    def test_fork_before_event_end_does_not_inherit_future_buffer(self):
        self.extract([self.card()])
        child_id = self.fork(self.source_ids[0])
        self.assertEqual(1, self.db.query(MemoryEventBuffer).filter_by(status="open").count())
        self.assertEqual(0, self.db.query(MemoryChunk).count())
        self.assertEqual([], event_context(load_event_snapshot(child_id, self.db)))

    def test_deleting_story_cascades_its_pending_events(self):
        self.extract([self.card()])
        with patch("services.memory.memory_manager.get_character_collection"):
            safe_delete_session(self.session_id, self.db)
        self.assertEqual(0, self.db.query(MemoryEventBuffer).count())

    def test_event_buffer_allows_compatible_temporal_refinement_and_note_addition(self):
        self.extract([self.card(temporal_status="unknown", temporal_note=None)])
        buffer_id = self.buffer().id
        self.advance("雨夜的海边风很大，两人转去咖啡馆。")
        self.assertEqual(0, self.extract([self.card(
            "雨夜海边起风后，两人转去咖啡馆继续约会。",
            buffer_id=buffer_id, temporal_status="historical", temporal_note="雨夜")])[0])
        self.advance("约会顺利结束。")
        self.assertEqual(1, self.extract([self.card(
            "雨夜海边约会转至咖啡馆并顺利结束。",
            buffer_id=buffer_id, event_status="complete", temporal_status="unknown", temporal_note=None)])[0])
        chunk = self.db.query(MemoryChunk).one()
        self.assertEqual("historical", chunk.temporal_status)
        self.assertEqual("雨夜", chunk.temporal_note)

    def test_transient_companion_emotion_is_absorbed_into_concurrent_event(self):
        cards = [
            self.card("用户与林墨在海边散步聊天。", event_status="complete"),
            {"content": "林墨感到有些害羞。", "memory_type": "emotion", "importance_score": 0.4,
             "source_start_message_id": self.source_ids[0], "source_end_message_id": self.source_ids[-1]},
        ]
        entities = [{"name": "海边", "description": "散步地点", "memory_indices": [1]}]
        self.assertEqual(1, self.extract(cards, entities=entities)[0])
        chunk = self.db.query(MemoryChunk).one()
        self.assertEqual("event", chunk.memory_type.value)
        self.assertIn("害羞", chunk.content)
        entity = self.db.query(GraphEntity).filter_by(name="海边").one()
        self.assertEqual([chunk.id], [m["id"] for m in json.loads(entity.evidence_json)["memories"]])

    def test_cross_card_graph_between_ongoing_event_and_admitted_fact_publishes_on_flush(self):
        cards = [
            self.card("用户与林墨在海边咖啡馆避雨谈心。", event_status="ongoing"),
            self.card("用户偏爱热美式咖啡。", memory_type="fact", event_status="complete"),
        ]
        entities = [{"name": "海边咖啡馆", "description": "避雨并点热美式的地点", "memory_indices": [0, 1]}]
        self.assertEqual(1, self.extract(cards, entities=entities)[0])
        fact_chunk = self.db.query(MemoryChunk).one()
        self.assertEqual(0, self.db.query(GraphEntity).count())
        self.assertEqual(1, extraction.summarize_and_store_memory(self.session_id, self.db, flush_events=True))
        self.assertEqual(2, self.db.query(MemoryChunk).count())
        entity = self.db.query(GraphEntity).filter_by(name="海边咖啡馆").one()
        evidence_ids = sorted(m["id"] for m in json.loads(entity.evidence_json)["memories"])
        self.assertEqual(2, len(evidence_ids))
        self.assertIn(fact_chunk.id, evidence_ids)

    def test_capacity_flush_retains_all_graph_dependencies_and_invalidation(self):
        cards = [self.card(f"用户与林墨正在参与独立事件 {index}。") for index in range(4)]
        cards.append(self.card("用户偏爱热美式咖啡。", memory_type="fact", event_status="complete"))
        entities = [{"name": "海边咖啡馆", "description": "事件和偏好共同支持的地点", "memory_indices": [0, 4]}]
        relations = [{"source": "用户", "target": "海边咖啡馆", "relation_type": "visited",
                      "description": "用户避雨时点了偏爱的热美式咖啡。", "memory_indices": [0, 4]}]
        self.assertEqual(2, self.extract(cards, entities=entities, relations=relations)[0])
        entity = self.db.query(GraphEntity).filter_by(name="海边咖啡馆", is_stub=False).one()
        relation = self.db.query(GraphRelation).one()
        ids = {chunk.id for chunk in self.db.query(MemoryChunk).all()}
        self.assertEqual(2, len(ids))
        for item in (entity, relation):
            evidence = json.loads(item.evidence_json)
            self.assertEqual(ids, {memory["id"] for memory in evidence["memories"]})
        fact = self.db.query(MemoryChunk).filter_by(memory_type="fact").one()
        fact.content = "用户已经不再偏爱咖啡。"
        self.db.commit()
        from services.memory.graph_evidence import load_graph_view
        valid_entities, valid_relations = load_graph_view(self.persona.id, self.db)
        self.assertNotIn(entity.id, {item.id for item in valid_entities})
        self.assertNotIn(relation.id, {item.id for item in valid_relations})

    def test_capacity_flush_does_not_publish_graph_with_unadmitted_dependency(self):
        cards = [self.card(f"用户与林墨正在参与独立事件 {index}。") for index in range(4)]
        self.assertEqual(1, self.extract(cards, entities=[{
            "name": "跨事件地点", "description": "必须同时由两个事件支持", "memory_indices": [0, 1]}])[0])
        self.assertEqual(0, self.db.query(GraphEntity).count())

    def test_evidence_writer_rejects_unresolved_dependencies(self):
        self.extract([self.card(event_status="complete")])
        chunk = self.db.query(MemoryChunk).one()
        from services.memory.graph_evidence import GraphEvidenceWriter, content_fingerprint
        writer = GraphEvidenceWriter(self.persona.id, json.loads(chunk.source_evidence_json), {0: {
            "memory_id": chunk.id, "hash": content_fingerprint(chunk.content),
            "source_start": chunk.source_start_message_id, "source_end": chunk.source_message_id}}, self.db)
        self.assertIsNotNone(writer.evidence_for({"memory_indices": [0]}))
        self.assertIsNone(writer.evidence_for({"memory_indices": [0], "_pending_indices": [1]}))

    def test_long_same_buffer_fragments_close_without_losing_text_or_graph_mapping(self):
        self.extract([self.card()])
        buffer_id = self.buffer().id
        self.advance()
        first_text = "A" * 490
        second_text = "UNIQUE_SECOND_FACT_" + "B" * 100
        cards = [self.card(first_text, buffer_id=buffer_id), self.card(second_text, buffer_id=buffer_id)]
        self.assertEqual(2, self.extract(cards, entities=[{
            "name": "后续片段", "description": "第二段独立依据", "memory_indices": [1]}])[0])
        self.assertEqual(1, self.db.query(MemoryEventBuffer).filter_by(status="open").count())
        extraction.summarize_and_store_memory(self.session_id, self.db, flush_events=True)
        chunks = self.db.query(MemoryChunk).all()
        self.assertTrue({first_text, second_text} <= {chunk.content for chunk in chunks})
        self.assertEqual({buffer_id}, {chunk.event_id for chunk in chunks})
        second_chunk = next(chunk for chunk in chunks if chunk.content == second_text)
        evidence = json.loads(self.db.query(GraphEntity).filter_by(name="后续片段").one().evidence_json)
        self.assertEqual([second_chunk.id], [item["id"] for item in evidence["memories"]])
        self.assertTrue(all(fact_sources_current(chunk, self.db) for chunk in chunks))
        self.assertEqual(self.source_ids[-1], self.persona.last_summarized_msg_id)

    def test_emotion_is_kept_separately_when_host_cannot_fit_it(self):
        event_text = "A" * 490
        emotion_text = "林墨想起昔日好友，心里感到十分悲伤。"
        cards = [self.card(event_text, event_status="complete"), self.card(
            emotion_text, memory_type="emotion", event_status="complete", importance_score=.4)]
        self.assertEqual(2, self.extract(cards)[0])
        self.assertEqual({event_text, emotion_text}, {chunk.content for chunk in self.db.query(MemoryChunk).all()})

    def test_invalid_graph_indices_after_absorption_do_not_abort_memory_writes(self):
        for attempt, indices in enumerate(([1, "invalid"], [1, {}], [1, []], [True, 1]), start=1):
            with self.subTest(indices=indices):
                cards = [self.card("用户与林墨在海边散步。", event_status="complete"), self.card(
                    "林墨感到有些害羞。", memory_type="emotion", event_status="complete", importance_score=.4)]
                self.assertEqual(1, self.extract(cards, entities=[
                    {"name": "非法依据地点", "memory_indices": indices},
                    {"name": "有效依据地点", "description": "散步地点", "memory_indices": [1]}], relations=[
                    {"source": "用户", "target": "海边", "relation_type": "visited", "memory_indices": indices}])[0])
                self.assertEqual(0, self.db.query(GraphEntity).filter_by(name="非法依据地点").count())
                self.assertEqual(0, self.db.query(GraphRelation).count())
                self.assertEqual(attempt, self.db.query(GraphEntity).filter_by(name="有效依据地点").count())
            self.advance()
