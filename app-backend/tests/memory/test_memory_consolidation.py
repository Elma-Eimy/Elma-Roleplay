"""整理预览、原子应用、撤销、分支快照与 SQLite 检索边界的隔离回归。"""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from core.database import get_db
from core.models import (Base, Character, Session, SessionPersona, ChatMessage, MessageRole,
                         MemoryChunk, MemoryType, MemoryConsolidation, MemoryConsolidationSource,
                         MemoryConsolidationScope, OutboxJob)
from routers.sessions import router
from services.memory import memory_consolidation_service as service, memory_manager
from services.memory.session_memory_query_service import query_session_memories, get_character_memory_overview
from services.memory.session_memory_service import update_memory, delete_memory, ProtectedMemoryMutationError
from services.conversation.session_service import create_session_service
from services.conversation.message_service import delete_message


class MemoryConsolidationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.character = Character(name="林墨", description="测试角色", first_mes="你好")
        self.session = Session(title="当前故事")
        self.db.add_all([self.character, self.session])
        self.db.flush()
        self.persona = SessionPersona(session_id=self.session.id, character_id=self.character.id)
        self.db.add(self.persona)
        self.db.flush()
        self.first_message = ChatMessage(session_id=self.session.id, role=MessageRole.user, content="第一次", is_active=True)
        self.last_message = ChatMessage(session_id=self.session.id, role=MessageRole.user, content="第二次", is_active=True)
        self.db.add_all([self.first_message, self.last_message])
        self.db.commit()
        self.one = self.memory("用户和林墨在雨夜的车站相遇。", source=self.first_message.id)
        self.two = self.memory("那次车站相遇时，林墨把伞借给了用户。", source=self.last_message.id)
        self.app = FastAPI()
        self.app.include_router(router, prefix="/sessions")
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.engine.dispose()

    def memory(self, content, source=None, persona=None):
        persona = persona or self.persona
        row = MemoryChunk(persona_id=persona.id, origin_session_id=persona.session_id,
                          content=content, memory_type=MemoryType.event, importance_score=.7,
                          source_start_message_id=source, source_message_id=source)
        self.db.add(row)
        self.db.flush()
        row.chroma_doc_id = f"mem_{row.id}"
        self.db.commit()
        return row

    def payload(self):
        return {"groups": [{"kind": "event", "source_ids": [self.one.id, self.two.id],
                            "content": "用户和林墨在雨夜的车站相遇，林墨把伞借给了用户。", "reason": "同一次车站相遇的互补细节"}]}

    def preview(self, payload=None, session_id=None, after_id=0):
        provider = MagicMock()
        provider.generate.return_value = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(payload or self.payload(), ensure_ascii=False)))])
        with patch.object(service, "get_llm_provider", return_value=provider):
            return service.preview(session_id or self.session.id, after_id, self.db)

    def view(self, session_id=None, status="active"):
        return query_session_memories(session_id=session_id or self.session.id, q=None,
                                      scope="all", status=status, limit=100, offset=0, db=self.db)

    def fork(self, message_id=None, parent_id=None):
        result = create_session_service(self.character.id, parent_id or self.session.id,
                                        "分支", None, message_id or self.last_message.id, self.db)
        return result["session_id"]

    def test_preview_preserves_originals_and_requires_explicit_selection(self):
        result = self.preview()
        self.assertEqual("preview", result["status"])
        self.assertEqual(2, self.db.query(MemoryChunk).count())
        self.assertEqual(0, self.db.query(OutboxJob).count())
        self.assertEqual(2, len(result["sources"]))
        self.assertEqual([], result["selected_group_ids"])
        with self.assertRaises(service.ConsolidationConflict):
            service.apply(self.session.id, result["id"], [], self.db)

    def test_apply_and_undo_restore_list_stats_and_keep_provenance(self):
        batch = self.preview()
        result = service.apply(self.session.id, batch["id"], [0], self.db)
        self.assertEqual("applied", result["status"])
        self.assertEqual(3, self.db.query(MemoryChunk).count())
        self.assertEqual(2, self.db.query(MemoryConsolidationSource).count())
        self.assertEqual(1, self.db.query(OutboxJob).count())
        self.assertEqual(1, self.view()["facets"]["effective_total"])
        self.assertEqual(2, self.view(status="superseded")["total"])
        overview = get_character_memory_overview(character_id=self.character.id, limit=50, offset=0, db=self.db)
        self.assertEqual(self.view()["facets"], overview["sessions"][0]["memory_stats"])
        service.undo(self.session.id, batch["id"], self.db)
        self.assertEqual({self.one.id, self.two.id}, {m["id"] for m in self.view()["items"]})
        self.assertEqual(3, self.db.query(MemoryChunk).count())

    def test_apply_and_undo_are_idempotent(self):
        batch = self.preview()
        service.apply(self.session.id, batch["id"], [0], self.db)
        service.apply(self.session.id, batch["id"], [0], self.db)
        self.assertEqual(1, self.db.query(OutboxJob).count())
        service.undo(self.session.id, batch["id"], self.db)
        service.undo(self.session.id, batch["id"], self.db)
        self.assertEqual(2, self.view()["total"])

    def test_stale_edit_deletion_or_competing_preview_cannot_apply(self):
        batch = self.preview()
        other = self.preview()
        self.one.content = "用户独自到了车站。"
        self.db.commit()
        with self.assertRaises(service.ConsolidationConflict):
            service.apply(self.session.id, batch["id"], [0], self.db)
        self.assertEqual(0, self.db.query(OutboxJob).count())
        fresh = self.preview()
        service.apply(self.session.id, fresh["id"], [0], self.db)
        with self.assertRaises(service.ConsolidationConflict):
            service.apply(self.session.id, other["id"], [0], self.db)

    def test_failed_outbox_write_rolls_back_cards_scopes_and_status(self):
        batch = self.preview()
        with patch.object(memory_manager, "_enqueue_vector_upsert", side_effect=RuntimeError("offline")):
            with self.assertRaises(RuntimeError):
                service.apply(self.session.id, batch["id"], [0], self.db)
        self.assertEqual(2, self.db.query(MemoryChunk).count())
        self.assertEqual(0, self.db.query(MemoryConsolidationScope).count())
        self.assertEqual("preview", self.db.get(MemoryConsolidation, batch["id"]).status)

    def test_model_failure_and_fabricated_or_overlapping_sources_are_rejected(self):
        bad = self.payload()
        bad["groups"][0]["source_ids"] = [self.one.id, 99999]
        with self.assertRaises(service.ConsolidationModelError):
            self.preview(bad)
        bad = self.payload()
        bad["groups"].append(dict(bad["groups"][0]))
        with self.assertRaises(service.ConsolidationModelError):
            self.preview(bad)
        with patch.object(service, "get_llm_provider", side_effect=RuntimeError("provider failed")):
            with self.assertRaises(service.ConsolidationModelError):
                service.preview(self.session.id, 0, self.db)
        self.assertEqual(0, self.db.query(MemoryConsolidation).count())
        self.assertEqual(2, self.db.query(MemoryChunk).count())

    def test_preview_is_bounded_and_next_batch_advances_without_modifying_cards(self):
        for index in range(83):
            self.memory(f"第 {index} 次独立事件。")
        first = self.preview({"groups": []})
        self.assertEqual(80, first["scanned_count"])
        self.assertTrue(first["has_more"])
        second = self.preview({"groups": []}, after_id=first["next_after_id"])
        self.assertEqual(5, second["scanned_count"])
        self.assertFalse(second["has_more"])
        self.assertFalse({m["id"] for m in first["sources"]} & {m["id"] for m in second["sources"]})

    def test_forks_before_and_after_apply_have_independent_snapshots(self):
        before = self.fork()
        batch = self.preview()
        service.apply(self.session.id, batch["id"], [0], self.db)
        after = self.fork()
        self.assertEqual(2, self.view(before)["total"])
        self.assertEqual(1, self.view(after)["total"])
        service.undo(self.session.id, batch["id"], self.db)
        self.assertEqual(2, self.view()["total"])
        self.assertEqual(1, self.view(after)["total"])
        # 父故事撤销后，子故事仍引用原卡来源，不能破坏其历史。
        with self.assertRaises(ProtectedMemoryMutationError):
            update_memory(self.session.id, self.one.id, "改写旧卡", .5, self.db)

    def test_fork_at_earlier_message_never_inherits_summary_with_future_source(self):
        batch = self.preview()
        service.apply(self.session.id, batch["id"], [0], self.db)
        early = self.fork(self.first_message.id)
        self.assertEqual([self.one.id], [m["id"] for m in self.view(early)["items"]])
        self.assertEqual(0, self.view(early, "superseded")["total"])

    def test_child_preview_excludes_inherited_and_sibling_cards(self):
        child = self.fork()
        child_persona = self.db.query(SessionPersona).filter_by(session_id=child).one()
        local = self.memory("子故事独有的经历。", persona=child_persona)
        with patch.object(service, "get_llm_provider") as provider:
            result = service.preview(child, 0, self.db)
        self.assertEqual([local.id], [m["id"] for m in result["sources"]])
        provider.assert_not_called()

    def test_applied_cards_are_protected_until_undo(self):
        batch = self.preview()
        result = service.apply(self.session.id, batch["id"], [0], self.db)
        for memory_id in [self.one.id, result["results"][0]["id"]]:
            with self.assertRaises(ProtectedMemoryMutationError):
                delete_memory(self.session.id, memory_id, self.db)
        service.undo(self.session.id, batch["id"], self.db)
        update_memory(self.session.id, self.one.id, "用户和林墨曾在车站相遇。", .8, self.db)

    def test_retrieval_whitelists_effective_ids_before_vector_query_and_undo_restores_them(self):
        batch = self.preview()
        result = service.apply(self.session.id, batch["id"], [0], self.db)
        summary = self.db.get(MemoryChunk, result["results"][0]["id"])
        collection = MagicMock()
        collection.count.return_value = 3
        collection.query.return_value = {"ids": [[summary.chroma_doc_id]], "documents": [["过期向量正文"]],
                                         "metadatas": [[{}]], "distances": [[.1]]}
        with patch.object(memory_manager, "get_character_collection", return_value=collection):
            recalled = memory_manager.retrieve_memories(self.persona.id, self.character.id, "车站", self.db)
            self.assertEqual([summary.chroma_doc_id], collection.query.call_args.kwargs["ids"])
            self.assertEqual(summary.content, recalled[0]["content"])
            service.undo(self.session.id, batch["id"], self.db)
            memory_manager.retrieve_memories(self.persona.id, self.character.id, "车站", self.db)
            self.assertEqual({self.one.chroma_doc_id, self.two.chroma_doc_id}, set(collection.query.call_args.kwargs["ids"]))

    def test_undo_rejects_later_replacement(self):
        batch = self.preview()
        result = service.apply(self.session.id, batch["id"], [0], self.db)
        newer = self.memory("用户说明借伞的人其实是其他人。")
        newer.supersedes_id = result["results"][0]["id"]
        self.db.commit()
        with self.assertRaises(service.ConsolidationConflict):
            service.undo(self.session.id, batch["id"], self.db)

    def test_api_validation_ownership_busy_and_history(self):
        batch = self.preview()
        base = f"/sessions/{self.session.id}/memory-consolidations"
        self.assertEqual(422, self.client.post(f"{base}/{batch['id']}/apply", json={"group_ids": []}).status_code)
        self.assertEqual(422, self.client.post(f"{base}/preview", json={"after_id": -1}).status_code)
        child = self.fork()
        self.assertEqual(404, self.client.post(f"/sessions/{child}/memory-consolidations/{batch['id']}/apply", json={"group_ids": [0]}).status_code)
        with patch.object(service, "is_session_locked", return_value=True):
            self.assertEqual(409, self.client.post(f"{base}/{batch['id']}/apply", json={"group_ids": [0]}).status_code)
        self.assertEqual(200, self.client.post(f"{base}/{batch['id']}/apply", json={"group_ids": [0]}).status_code)
        self.assertEqual("applied", self.client.get(base).json()["items"][0]["status"])
        self.assertEqual(200, self.client.post(f"{base}/{batch['id']}/undo").status_code)

    def test_deleting_story_cascades_consolidation_records(self):
        batch = self.preview()
        service.apply(self.session.id, batch["id"], [0], self.db)
        self.db.execute(text("DELETE FROM sessions WHERE id = :id"), {"id": self.session.id})
        self.db.commit()
        self.assertEqual(0, self.db.query(MemoryConsolidationSource).count())
        self.assertEqual(0, self.db.query(MemoryConsolidationScope).count())
        self.assertEqual(0, self.db.query(MemoryConsolidation).count())

    def test_history_paginates_to_older_applied_batches(self):
        batch = self.preview()
        service.apply(self.session.id, batch["id"], [0], self.db)
        for _ in range(11):
            service.preview(self.session.id, 0, self.db)
        first = service.list_batches(self.session.id, self.db)
        self.assertTrue(first["has_more"])
        second = service.list_batches(self.session.id, self.db, offset=10)
        self.assertFalse(second["has_more"])
        self.assertEqual("applied", second["items"][-1]["status"])

    def test_partial_selection_leaves_other_groups_active_and_unchanged(self):
        third = self.memory("用户曾送给林墨一本诗集。")
        fourth = self.memory("那本诗集是用户在生日时送给林墨的。")
        payload = self.payload()
        payload["groups"].append({"kind": "event", "source_ids": [third.id, fourth.id],
                                  "content": "用户曾在生日时送给林墨一本诗集。", "reason": "同一次赠书"})
        batch = self.preview(payload)
        result = service.apply(self.session.id, batch["id"], [1], self.db)
        self.assertEqual([1], result["selected_group_ids"])
        self.assertEqual({self.one.id, self.two.id, result["results"][0]["id"]}, {m["id"] for m in self.view()["items"]})

    def test_deleted_source_and_unknown_group_reject_without_writing_results(self):
        batch = self.preview()
        with self.assertRaises(service.ConsolidationConflict):
            service.apply(self.session.id, batch["id"], [99], self.db)
        delete_memory(self.session.id, self.two.id, self.db)
        with self.assertRaises(service.ConsolidationConflict):
            service.apply(self.session.id, batch["id"], [0], self.db)
        self.assertEqual(0, self.db.query(MemoryConsolidationSource).count())

    def test_child_consolidation_does_not_change_parent_or_sibling(self):
        child, sibling = self.fork(), self.fork()
        persona = self.db.query(SessionPersona).filter_by(session_id=child).one()
        one = self.memory("子故事中用户和林墨重逢。", persona=persona)
        two = self.memory("那次重逢时，用户给林墨带了礼物。", persona=persona)
        payload = {"groups": [{"kind": "event", "source_ids": [one.id, two.id],
                               "content": "子故事中用户和林墨重逢，用户给林墨带了礼物。", "reason": "同一次重逢"}]}
        batch = self.preview(payload, session_id=child)
        service.apply(child, batch["id"], [0], self.db)
        self.assertEqual(3, self.view(child)["total"])
        self.assertEqual(2, self.view(sibling)["total"])
        self.assertEqual(2, self.view()["total"])

    def assert_overview_matches_lists(self):
        overview = get_character_memory_overview(character_id=self.character.id, limit=50, offset=0, db=self.db)
        for story in overview["sessions"]:
            self.assertEqual(self.view(story["session_id"])["facets"], story["memory_stats"])

    def test_deleted_future_source_never_reveals_summary_or_original_in_early_fork(self):
        batch = self.preview()
        result = service.apply(self.session.id, batch["id"], [0], self.db)
        summary_id = result["results"][0]["id"]
        early = self.fork(self.first_message.id)
        delete_message(self.last_message.id, self.db)
        self.db.expire_all()
        self.assertIsNone(self.two.source_message_id)
        self.assertEqual(self.db.get(MemoryChunk, summary_id).source_message_id_bound,
                         self.two.source_message_id_bound)
        self.assertEqual([self.one.id], [item["id"] for item in self.view(early)["items"]])
        self.assertEqual(0, self.view(early, "superseded")["total"])
        # 即使旧库还残留曾复制的无效 scope，也不能绕过持久来源边界。
        child_persona = self.db.query(SessionPersona).filter_by(session_id=early).one()
        self.db.add(MemoryConsolidationScope(persona_id=child_persona.id, consolidation_id=batch["id"]))
        self.db.commit()
        self.assertEqual([self.one.id], [item["id"] for item in self.view(early)["items"]])
        self.assert_overview_matches_lists()
        collection = MagicMock()
        collection.count.return_value = 3
        collection.query.return_value = {"ids": [[f"mem_{summary_id}", self.two.chroma_doc_id]],
            "documents": [["未来摘要", "未来原卡"]], "metadatas": [[{}, {}]], "distances": [[.1, .1]]}
        with patch.object(memory_manager, "get_character_collection", return_value=collection):
            recalled = memory_manager.retrieve_memories(child_persona.id, self.character.id, "借伞", self.db)
        self.assertEqual([], recalled)
        self.assertEqual([self.one.chroma_doc_id], collection.query.call_args.kwargs["ids"])

    def test_fork_created_after_source_deletion_still_obeys_original_cutoff(self):
        batch = self.preview()
        service.apply(self.session.id, batch["id"], [0], self.db)
        delete_message(self.last_message.id, self.db)
        self.db.expire_all()
        early = self.fork(self.first_message.id)
        self.assertEqual([self.one.id], [item["id"] for item in self.view(early)["items"]])
        self.assert_overview_matches_lists()

    def test_deleted_source_boundary_is_carried_into_new_consolidation(self):
        future_bound = self.last_message.id
        delete_message(future_bound, self.db)
        self.db.expire_all()
        batch = self.preview()
        result = service.apply(self.session.id, batch["id"], [0], self.db)
        summary = self.db.get(MemoryChunk, result["results"][0]["id"])
        self.assertEqual(self.first_message.id, summary.source_message_id)
        self.assertEqual(future_bound, summary.source_message_id_bound)
        early = self.fork(self.first_message.id)
        self.assertEqual([self.one.id], [item["id"] for item in self.view(early)["items"]])

    def test_invisible_early_fork_does_not_protect_sources_after_parent_undo(self):
        batch = self.preview()
        service.apply(self.session.id, batch["id"], [0], self.db)
        early = self.fork(self.first_message.id)
        child_persona = self.db.query(SessionPersona).filter_by(session_id=early).one()
        self.assertIsNone(self.db.get(MemoryConsolidationScope, (child_persona.id, batch["id"])))
        # 兼容第一版已写入的无效关联，保护判断也必须验证实际可见性。
        self.db.add(MemoryConsolidationScope(persona_id=child_persona.id, consolidation_id=batch["id"]))
        self.db.commit()
        service.undo(self.session.id, batch["id"], self.db)
        update_memory(self.session.id, self.one.id, "父故事修正了车站经历。", .8, self.db)
        delete_memory(self.session.id, self.two.id, self.db)
        self.assertEqual("父故事修正了车站经历。", self.db.get(MemoryChunk, self.one.id).content)

    def test_mixed_batch_protects_only_sources_of_visible_groups(self):
        early_other = self.memory("用户和林墨在车站初遇时互通了姓名。", source=self.first_message.id)
        future_other = self.memory("借伞后，用户向林墨道谢。", source=self.last_message.id)
        payload = {"groups": [
            {"kind": "event", "source_ids": [self.one.id, early_other.id], "content": "用户和林墨在雨夜车站初遇并互通姓名。", "reason": "同一次初遇"},
            {"kind": "event", "source_ids": [self.two.id, future_other.id], "content": "林墨借伞给用户，用户向林墨道谢。", "reason": "同一次借伞"},
        ]}
        batch = self.preview(payload)
        service.apply(self.session.id, batch["id"], [0, 1], self.db)
        early = self.fork(self.first_message.id)
        service.undo(self.session.id, batch["id"], self.db)
        with self.assertRaises(ProtectedMemoryMutationError):
            update_memory(self.session.id, self.one.id, "不能改写分支仍引用的初遇。", .8, self.db)
        update_memory(self.session.id, self.two.id, "父故事修正借伞经过。", .8, self.db)
        self.assertEqual(1, self.view(early)["total"])
        self.assert_overview_matches_lists()

    def test_child_replacement_does_not_block_parent_undo_or_change_child(self):
        batch = self.preview()
        result = service.apply(self.session.id, batch["id"], [0], self.db)
        child = self.fork()
        persona = self.db.query(SessionPersona).filter_by(session_id=child).one()
        newer = self.memory("子故事中重新解释了那次车站相遇。", persona=persona)
        newer.supersedes_id = result["results"][0]["id"]
        self.db.commit()
        before = self.view(child)
        self.assertEqual("undone", service.undo(self.session.id, batch["id"], self.db)["status"])
        self.assertEqual(before, self.view(child))
        self.assertEqual({self.one.id, self.two.id}, {item["id"] for item in self.view()["items"]})
        self.assert_overview_matches_lists()

    def test_truly_manual_sources_can_still_be_inherited_without_message_boundary(self):
        first = self.memory("用户曾在日记中补记了一次赠书。")
        second = self.memory("日记补记的赠书发生在用户生日。")
        payload = {"groups": [{"kind": "event", "source_ids": [first.id, second.id],
            "content": "用户在日记中补记了生日赠书的经历。", "reason": "同一次手动补记"}]}
        batch = self.preview(payload)
        result = service.apply(self.session.id, batch["id"], [0], self.db)
        early = self.fork(self.first_message.id)
        self.assertIn(result["results"][0]["id"], {item["id"] for item in self.view(early)["items"]})
        self.assert_overview_matches_lists()
