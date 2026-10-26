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
                         MemoryConsolidationScope, MemoryConsolidationScan, OutboxJob)
from routers.sessions import router
from services.memory import memory_consolidation_service as service, memory_manager
from services.memory.session_memory_query_service import query_session_memories, get_character_memory_overview
from services.memory.session_memory_service import update_memory, delete_memory, ProtectedMemoryMutationError
from services.conversation.session_service import create_session_service
from services.conversation.message_service import delete_message
from services.memory.memory_consolidation_guard import event_date_anchor, has_conflicting_event_dates, has_source_conflict


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

    def preview(self, payload=None, session_id=None, after_id=0, mode="full"):
        provider = MagicMock()
        provider.generate.return_value = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(payload or self.payload(), ensure_ascii=False)))])
        with patch.object(service, "get_llm_provider", return_value=provider):
            return service.preview(session_id or self.session.id, after_id, self.db, mode)

    def test_incremental_tracks_checks_independently_of_apply_and_undo(self):
        self.assertEqual(2, service.list_batches(self.session.id, self.db)["scan_status"]["pending_count"])
        batch = self.preview(mode="incremental")
        self.assertEqual(2, batch["recorded_count"])
        self.assertEqual(0, batch["scan_status"]["pending_count"])
        self.assertEqual(2, self.view()["total"])
        with patch.object(service, "get_llm_provider") as provider:
            empty = service.preview(self.session.id, 0, self.db, "incremental")
        provider.assert_not_called()
        self.assertEqual(0, empty["scanned_count"])
        self.assertEqual([], empty["groups"])
        service.apply(self.session.id, batch["id"], [0], self.db)
        self.assertEqual(0, service.scan_status(self.persona.id, self.db)["eligible_count"])
        service.undo(self.session.id, batch["id"], self.db)
        self.assertEqual({"eligible_count": 2, "checked_count": 2, "pending_count": 0}, service.scan_status(self.persona.id, self.db))
        full = self.preview()
        self.assertEqual(2, full["scanned_count"])
        self.assertEqual("full", full["scan_mode"])

    def model_response(self, content, finish_reason="stop"):
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content), finish_reason=finish_reason)])

    def test_bare_arrays_and_fenced_json_are_validated_before_preview(self):
        payload = self.payload()
        for output in (json.dumps(payload["groups"]), "[]",
                       "```json\n" + json.dumps(payload) + "\n```"):
            with self.subTest(output=output), patch.object(service, "get_llm_provider") as factory:
                factory.return_value.generate.return_value = self.model_response(output)
                batch = service.preview(self.session.id, 0, self.db)
                self.assertEqual(0 if output == "[]" else 1, len(batch["groups"]))
                factory.return_value.generate.assert_called_once()

    def test_structural_errors_retry_once_with_same_sources(self):
        invalid = ["not json", "null", '{"groups":null}', '{"items":[]}']
        for output in invalid:
            with self.subTest(output=output), patch.object(service, "get_llm_provider") as factory:
                provider = factory.return_value
                provider.generate.side_effect = [self.model_response(output),
                                                  self.model_response(json.dumps(self.payload()))]
                with self.assertLogs(service.logger, level="INFO") as logs:
                    batch = service.preview(self.session.id, 0, self.db)
                self.assertEqual(1, len(batch["groups"]))
                calls = provider.generate.call_args_list
                self.assertEqual(2, len(calls))
                self.assertEqual(calls[0].kwargs["messages"][1], calls[1].kwargs["messages"][1])
                self.assertIn("上一轮返回未通过格式校验", calls[1].kwargs["messages"][0]["content"])
                self.assertIn('"retry": true', "\n".join(logs.output))

    def test_too_many_groups_are_reported_and_retried_without_relaxing_limit(self):
        excessive = {"groups": self.payload()["groups"] * 13}
        with patch.object(service, "get_llm_provider") as factory:
            factory.return_value.generate.side_effect = [self.model_response(json.dumps(excessive)),
                                                         self.model_response(json.dumps(self.payload()))]
            with self.assertLogs(service.logger, level="INFO") as logs:
                batch = service.preview(self.session.id, 0, self.db)
            self.assertEqual(1, len(batch["groups"]))
            output = "\n".join(logs.output)
            self.assertIn('"reason": "too_many_groups"', output)
            self.assertIn('"returned_group_count": 13', output)

    def test_repeated_format_failure_keeps_scan_pending_and_logs_no_raw_content(self):
        secret = "PRIVATE_RESPONSE_AND_KEY"
        with patch.object(service, "get_llm_provider") as factory:
            factory.return_value.generate.return_value = self.model_response(secret)
            with self.assertLogs(service.logger, level="INFO") as logs:
                with self.assertRaises(service.ConsolidationModelError) as raised:
                    service.preview(self.session.id, 0, self.db, "incremental")
            self.assertEqual("invalid_json", raised.exception.reason)
            self.assertEqual(2, factory.return_value.generate.call_count)
        output = "\n".join(logs.output)
        self.assertNotIn(secret, output)
        self.assertNotIn(self.one.content, output)
        self.assertIn('"source_count": 2', output)
        self.assertIn('"json_error_position": 0', output)
        self.assertEqual(0, self.db.query(MemoryConsolidation).count())
        self.assertEqual(0, self.db.query(MemoryConsolidationScan).count())
        self.assertEqual(2, service.scan_status(self.persona.id, self.db)["pending_count"])

    def test_truncated_output_is_distinct_and_is_not_saved_or_retried(self):
        with patch.object(service, "get_llm_provider") as factory:
            factory.return_value.generate.return_value = self.model_response('{"groups":[', "length")
            with self.assertLogs(service.logger, level="WARNING") as logs:
                with self.assertRaises(service.ConsolidationModelError) as raised:
                    service.preview(self.session.id, 0, self.db, "incremental")
            self.assertEqual("response_truncated", raised.exception.reason)
            factory.return_value.generate.assert_called_once()
        self.assertIn('"finish_reason": "length"', "\n".join(logs.output))
        self.assertEqual(0, self.db.query(MemoryConsolidationScan).count())

    def test_long_input_card_is_allowed_but_oversized_summary_is_rejected(self):
        self.one.content = self.one.content * 100
        self.db.commit()
        self.assertEqual(1, len(self.preview()["groups"]))
        payload = self.payload()
        payload["groups"][0]["content"] = "长" * 501
        with self.assertLogs(service.logger, level="WARNING") as logs:
            with self.assertRaises(service.ConsolidationModelError) as raised:
                self.preview(payload)
        self.assertEqual("invalid_content_length", raised.exception.reason)
        self.assertIn('"group_index": 0', "\n".join(logs.output))

    def test_array_normalization_does_not_accept_unsafe_sources(self):
        payload = self.payload()["groups"]
        payload[0]["source_ids"] = [self.one.id, 99999]
        with patch.object(service, "get_llm_provider") as factory:
            factory.return_value.generate.return_value = self.model_response(json.dumps(payload))
            with self.assertLogs(service.logger, level="WARNING") as logs:
                with self.assertRaises(service.ConsolidationModelError) as raised:
                    service.preview(self.session.id, 0, self.db)
            self.assertEqual("unknown_source_id", raised.exception.reason)
            factory.return_value.generate.assert_called_once()
        self.assertIn('"normalized_array": true', "\n".join(logs.output))
        self.assertEqual(0, self.db.query(MemoryConsolidation).count())

    def test_model_call_error_logs_exception_type_without_message(self):
        with patch.object(service, "get_llm_provider", side_effect=RuntimeError("PRIVATE_API_KEY")):
            with self.assertLogs(service.logger, level="WARNING") as logs:
                with self.assertRaises(service.ConsolidationModelError):
                    service.preview(self.session.id, 0, self.db)
        output = "\n".join(logs.output)
        self.assertIn('"error_type": "RuntimeError"', output)
        self.assertNotIn("PRIVATE_API_KEY", output)

    def test_source_type_errors_retry_with_constraints_and_keep_only_valid_suggestions(self):
        third = self.memory("用户喜欢蓝色。")
        third.memory_type = MemoryType.fact
        self.db.commit()
        for kind, code in (("event", "non_event_source"), ("duplicate", "mixed_memory_types")):
            invalid = self.payload()
            invalid["groups"][0].update(kind=kind, source_ids=[self.one.id, third.id])
            with self.subTest(kind=kind), patch.object(service, "get_llm_provider") as factory:
                provider = factory.return_value
                provider.generate.side_effect = [self.model_response(json.dumps(invalid)),
                                                  self.model_response(json.dumps(self.payload()))]
                with self.assertLogs(service.logger, level="INFO") as logs:
                    groups = service._generate_groups("测试类型纠正", [service.snapshot(row) for row in
                                                       (self.one, self.two, third)])
                self.assertEqual([self.one.id, self.two.id], groups[0]["source_ids"])
                self.assertIn('"reason": "' + code + '"', "\n".join(logs.output))
                self.assertIn('"group_source_type_counts": {"event": 1, "fact": 1}', "\n".join(logs.output))
                calls = provider.generate.call_args_list
                self.assertEqual(2, len(calls))
                correction = calls[1].kwargs["messages"][0]["content"]
                self.assertIn("逐组按 source_ids 回查输入的 memory_type", correction)
                self.assertIn("不能只改 kind 凑合法", correction)
                self.assertEqual(calls[0].kwargs["messages"][1], calls[1].kwargs["messages"][1])

    def test_repeated_source_type_failure_does_not_save_or_advance_scan(self):
        self.one.memory_type = MemoryType.emotion
        self.two.memory_type = MemoryType.emotion
        self.db.commit()
        with patch.object(service, "get_llm_provider") as factory:
            factory.return_value.generate.return_value = self.model_response(json.dumps(self.payload()))
            with self.assertLogs(service.logger, level="WARNING"):
                with self.assertRaises(service.ConsolidationModelError) as raised:
                    service.preview(self.session.id, 0, self.db, "incremental")
            self.assertEqual("non_event_source", raised.exception.reason)
            self.assertEqual(2, factory.return_value.generate.call_count)
        self.assertEqual(0, self.db.query(MemoryConsolidation).count())
        self.assertEqual(0, self.db.query(MemoryConsolidationScan).count())
        self.assertEqual(2, service.scan_status(self.persona.id, self.db)["pending_count"])

    def test_mixed_types_are_sent_separately_and_combined_with_unique_group_ids(self):
        for kind in (MemoryType.fact, MemoryType.relationship, MemoryType.emotion):
            for _ in range(2):
                row = self.memory(f"相同的{kind.value}记忆内容。")
                row.memory_type = kind
        self.db.commit()
        calls = []
        def generate(**kwargs):
            cards = json.loads(kwargs["messages"][1]["content"])
            kinds = {card["memory_type"] for card in cards}
            self.assertEqual(1, len(kinds))
            calls.append(cards)
            kind = cards[0]["memory_type"]
            if kind == "event":
                payload = self.payload()
            else:
                self.assertIn("本次只允许 duplicate 去重，禁止 event", kwargs["messages"][0]["content"])
                payload = {"groups": [{"kind": "duplicate", "source_ids": [c["id"] for c in cards],
                                       "content": cards[0]["content"], "reason": "同一命题的重复表达"}]}
            return self.model_response(json.dumps(payload, ensure_ascii=False))
        with patch.object(service, "get_llm_provider") as factory:
            factory.return_value.generate.side_effect = generate
            with self.assertLogs(service.logger, level="INFO") as logs:
                batch = service.preview(self.session.id, 0, self.db, "incremental")
        self.assertEqual(4, len(calls))
        self.assertEqual([0, 1, 2, 3], [group["id"] for group in batch["groups"]])
        self.assertEqual(8, batch["scanned_count"])
        self.assertEqual(8, batch["recorded_count"])
        self.assertEqual(0, batch["scan_status"]["pending_count"])
        self.assertEqual(8, self.db.query(MemoryChunk).count())
        ids = [card["id"] for cards in calls for card in cards]
        self.assertEqual(8, len(set(ids)))
        records = [json.loads(line.split("start ", 1)[1]) for line in logs.output if "start " in line]
        self.assertEqual(1, len({record["request_id"] for record in records}))

    def test_cross_type_ids_are_rejected_even_when_they_exist_in_the_full_batch(self):
        facts = [self.memory("用户喜欢蓝色。") for _ in range(2)]
        for row in facts:
            row.memory_type = MemoryType.fact
        self.db.commit()
        invalid = self.payload()
        invalid["groups"][0]["source_ids"] = [self.one.id, facts[0].id]
        with patch.object(service, "get_llm_provider") as factory:
            factory.return_value.generate.return_value = self.model_response(json.dumps(invalid))
            with self.assertLogs(service.logger, level="WARNING"):
                with self.assertRaises(service.ConsolidationModelError) as raised:
                    service.preview(self.session.id, 0, self.db, "incremental")
            self.assertEqual("unknown_source_id", raised.exception.reason)
            sent = json.loads(factory.return_value.generate.call_args.kwargs["messages"][1]["content"])
            self.assertEqual({self.one.id, self.two.id}, {card["id"] for card in sent})
        self.assertEqual(0, self.db.query(MemoryConsolidation).count())
        self.assertEqual(0, self.db.query(MemoryConsolidationScan).count())

    def test_later_type_failure_does_not_persist_earlier_successful_type(self):
        facts = [self.memory("用户喜欢蓝色。") for _ in range(2)]
        for row in facts:
            row.memory_type = MemoryType.fact
        self.db.commit()
        invalid = {"groups": [{"kind": "event", "source_ids": [row.id for row in facts],
                               "content": "用户喜欢蓝色。", "reason": "错误的事件归并"}]}
        with patch.object(service, "get_llm_provider") as factory:
            factory.return_value.generate.side_effect = [self.model_response(json.dumps(self.payload())),
                self.model_response(json.dumps(invalid)), self.model_response(json.dumps(invalid))]
            with self.assertLogs(service.logger, level="WARNING"):
                with self.assertRaises(service.ConsolidationModelError) as raised:
                    service.preview(self.session.id, 0, self.db, "incremental")
            self.assertEqual("non_event_source", raised.exception.reason)
            self.assertEqual(3, factory.return_value.generate.call_count)
        self.assertEqual(0, self.db.query(MemoryConsolidation).count())
        self.assertEqual(0, self.db.query(MemoryConsolidationScan).count())
        self.assertEqual(4, self.db.query(MemoryChunk).count())

    def test_singletons_in_mixed_batch_get_zero_group_budget(self):
        self.one.memory_type = MemoryType.fact
        self.db.commit()
        with patch.object(service, "get_llm_provider") as factory:
            factory.return_value.generate.return_value = self.model_response('{"groups":[]}')
            batch = service.preview(self.session.id, 0, self.db, "incremental")
            self.assertEqual(2, factory.return_value.generate.call_count)
            for call in factory.return_value.generate.call_args_list:
                self.assertEqual(1, len(json.loads(call.kwargs["messages"][1]["content"])))
                self.assertIn("最多返回0组", call.kwargs["messages"][0]["content"])
        self.assertEqual([], batch["groups"])
        self.assertEqual(2, batch["recorded_count"])
        self.assertTrue(batch["model_checked"])

    def test_type_calls_share_twelve_group_budget_and_reserve_later_types(self):
        for index in range(22):
            self.memory(f"第 {index // 2} 次在山顶相遇。")
        for kind in (MemoryType.fact, MemoryType.emotion, MemoryType.relationship):
            for _ in range(2):
                row = self.memory(f"重复的{kind.value}记忆内容。")
                row.memory_type = kind
        self.db.commit()
        event_attempts = 0
        def generate(**kwargs):
            nonlocal event_attempts
            cards = json.loads(kwargs["messages"][1]["content"])
            if cards[0]["memory_type"] == "event":
                event_attempts += 1
                self.assertIn("最多返回9组", kwargs["messages"][0]["content"])
                groups = self.payload()["groups"]
                groups += [{"kind": "duplicate", "source_ids": [cards[i]["id"], cards[i + 1]["id"]],
                            "content": cards[i]["content"], "reason": "同一命题重复"} for i in range(2, 18, 2)]
                if event_attempts == 1:
                    groups.append({"kind": "duplicate", "source_ids": [cards[18]["id"], cards[19]["id"]],
                                   "content": cards[18]["content"], "reason": "同一命题重复"})
            else:
                self.assertIn("最多返回1组", kwargs["messages"][0]["content"])
                groups = [{"kind": "duplicate", "source_ids": [card["id"] for card in cards],
                           "content": cards[0]["content"], "reason": "同一命题重复"}]
            return self.model_response(json.dumps({"groups": groups}, ensure_ascii=False))
        with patch.object(service, "get_llm_provider") as factory:
            factory.return_value.generate.side_effect = generate
            with self.assertLogs(service.logger, level="WARNING") as logs:
                batch = service.preview(self.session.id, 0, self.db)
            self.assertEqual(5, factory.return_value.generate.call_count)
        self.assertEqual(12, len(batch["groups"]))
        self.assertEqual(list(range(12)), [group["id"] for group in batch["groups"]])
        self.assertEqual(30, batch["recorded_count"])
        self.assertIn('"group_limit": 9', "\n".join(logs.output))
        self.assertIn('"reason": "too_many_groups"', "\n".join(logs.output))

    def test_incremental_includes_modified_old_cards_and_new_cards_only(self):
        self.preview({"groups": []})
        self.one.content = "较早原卡已增加雨伞颜色信息。"
        self.db.commit()
        new = self.memory("用户新补充了一次独立经历。")
        batch = self.preview({"groups": []}, mode="incremental")
        self.assertEqual([self.one.id, new.id], [row["id"] for row in batch["sources"]])
        self.assertNotIn(self.two.id, [row["id"] for row in batch["sources"]])
        self.assertEqual({"eligible_count": 3, "checked_count": 3, "pending_count": 0}, batch["scan_status"])

    def test_single_pending_card_waits_for_another_without_model_call(self):
        self.preview({"groups": []})
        new = self.memory("独立新增但暂不足两张的记忆。")
        with patch.object(service, "get_llm_provider") as provider:
            batch = service.preview(self.session.id, 0, self.db, "incremental")
        provider.assert_not_called()
        self.assertFalse(batch["model_checked"])
        self.assertEqual(0, batch["recorded_count"])
        self.assertEqual(1, batch["scan_status"]["pending_count"])
        self.assertFalse(batch["has_more"])
        newer = self.memory("另一张新增的独立记忆。")
        next_batch = self.preview({"groups": []}, mode="incremental")
        self.assertEqual([new.id, newer.id], [s["id"] for s in next_batch["sources"]])
        self.assertEqual(0, next_batch["scan_status"]["pending_count"])

    def test_incremental_resumes_pending_batches_and_full_scan_can_repeat(self):
        for i in range(103):
            self.memory(f"第{i}条独立新增原卡。")
        first = self.preview({"groups": []}, mode="incremental")
        self.assertEqual(100, first["scanned_count"])
        self.assertEqual(5, first["scan_status"]["pending_count"])
        self.assertTrue(first["has_more"])
        second = self.preview({"groups": []}, mode="incremental")
        self.assertEqual(5, second["scanned_count"])
        self.assertFalse(second["has_more"])
        self.assertEqual(0, second["scan_status"]["pending_count"])
        self.assertEqual(100, self.preview({"groups": []})["scanned_count"])

    def test_failed_model_and_failed_progress_write_do_not_mark_cards_checked(self):
        with patch.object(service, "get_llm_provider", side_effect=RuntimeError("offline")):
            with self.assertRaises(service.ConsolidationModelError):
                service.preview(self.session.id, 0, self.db, "incremental")
        with self.assertRaises(service.ConsolidationModelError):
            self.preview({"groups": [{"bad": "invalid"}]}, mode="incremental")
        original = service.scan.record_unchanged
        def fail_after_record(*args):
            original(*args)
            raise RuntimeError("save failed")
        with patch.object(service.scan, "record_unchanged", side_effect=fail_after_record):
            with self.assertRaises(RuntimeError):
                self.preview({"groups": []}, mode="incremental")
        self.assertEqual(0, self.db.query(MemoryConsolidationScan).count())
        self.assertEqual(0, self.db.query(MemoryConsolidation).count())
        self.assertEqual(2, service.scan_status(self.persona.id, self.db)["pending_count"])

    def test_scan_does_not_mark_sources_changed_during_model_call(self):
        def generate(**kwargs):
            self.one.content = "模型调用期间原卡发生变化。"
            self.db.commit()
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"groups":[]}'))])
        provider = MagicMock()
        provider.generate.side_effect = generate
        with patch.object(service, "get_llm_provider", return_value=provider):
            batch = service.preview(self.session.id, 0, self.db, "incremental")
        self.assertEqual(1, batch["recorded_count"])
        self.assertEqual(1, batch["scan_status"]["pending_count"])
        self.assertIsNone(self.db.get(MemoryConsolidationScan, (self.persona.id, self.one.id)))

    def test_stale_suggestion_keeps_all_its_sources_pending_without_blocking_safe_groups(self):
        three = self.memory("周日用户送给林墨一本蓝色封面的诗集。")
        four = self.memory("那次周日赠书时，林墨收下了用户送的蓝色诗集。")
        payload = self.payload()
        payload["groups"].append({"kind": "event", "source_ids": [three.id, four.id],
                                  "content": "周日用户送给林墨一本蓝色封面的诗集，林墨收下了它。", "reason": "同一次赠书"})
        def generate(**kwargs):
            self.one.content = "雨夜相遇的时间和地点已补充修改。"
            self.db.commit()
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)))])
        provider = MagicMock()
        provider.generate.side_effect = generate
        with patch.object(service, "get_llm_provider", return_value=provider):
            batch = service.preview(self.session.id, 0, self.db, "incremental")
        self.assertEqual(2, batch["recorded_count"])
        self.assertEqual(2, batch["scan_status"]["pending_count"])
        self.assertTrue(batch["has_more"])
        self.assertIsNotNone(batch["groups"][0]["conflict"])
        self.assertIsNone(batch["groups"][1]["conflict"])
        next_batch = self.preview({"groups": []}, mode="incremental")
        self.assertTrue(next_batch["model_checked"])
        self.assertEqual([self.one.id, self.two.id], [row["id"] for row in next_batch["sources"]])

    def test_older_inflight_scan_does_not_overwrite_newer_checked_version(self):
        def generate(**kwargs):
            self.one.content = "较新的正文已经由另一次检查处理。"
            self.db.commit()
            self.preview({"groups": []}, mode="incremental")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"groups":[]}'))])
        provider = MagicMock()
        provider.generate.side_effect = generate
        with patch.object(service, "get_llm_provider", return_value=provider):
            batch = service.preview(self.session.id, 0, self.db, "incremental")
        self.assertEqual(1, batch["recorded_count"])
        self.assertEqual(0, batch["scan_status"]["pending_count"])
        self.assertEqual(service.scan.fingerprint(self.one), self.db.get(MemoryConsolidationScan, (self.persona.id, self.one.id)).fingerprint)

    def test_stale_group_does_not_clear_newer_successful_scan_records(self):
        payload = self.payload()
        def generate(**kwargs):
            self.one.content = "另一请求已经检查过的新版本车站相遇。"
            self.db.commit()
            self.preview(mode="incremental")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)))])
        provider = MagicMock()
        provider.generate.side_effect = generate
        with patch.object(service, "get_llm_provider", return_value=provider):
            batch = service.preview(self.session.id, 0, self.db, "incremental")
        self.assertEqual(0, batch["recorded_count"])
        self.assertEqual(0, batch["scan_status"]["pending_count"])
        self.assertEqual(2, self.db.query(MemoryConsolidationScan).count())

    def test_metadata_changes_invalidate_checked_versions(self):
        self.preview({"groups": []})
        self.one.importance_score = .9
        self.two.source_message_id_bound = self.last_message.id + 1
        self.db.commit()
        self.assertEqual(2, service.scan_status(self.persona.id, self.db)["pending_count"])
        self.assertEqual(2, self.preview({"groups": []}, mode="incremental")["recorded_count"])

    def test_branch_scan_state_excludes_inherited_cards_and_cascades_on_delete(self):
        self.preview({"groups": []})
        child = self.fork()
        child_persona = self.db.query(SessionPersona).filter_by(session_id=child).one()
        self.assertEqual(0, service.list_batches(child, self.db)["scan_status"]["eligible_count"])
        local_one = self.memory("分支自己的第一条记忆。", persona=child_persona)
        self.memory("分支自己的第二条记忆。", persona=child_persona)
        batch = self.preview({"groups": []}, session_id=child, mode="incremental")
        self.assertEqual(2, batch["recorded_count"])
        self.db.delete(local_one)
        self.db.commit()
        self.assertEqual(1, service.list_batches(child, self.db)["scan_status"]["checked_count"])
        self.assertEqual(2, service.list_batches(self.session.id, self.db)["scan_status"]["checked_count"])

    def test_scan_mode_http_validation_and_legacy_full_default(self):
        url = f"/sessions/{self.session.id}/memory-consolidations/preview"
        for request in ({"mode": "unknown"}, {"mode": "incremental", "after_id": 1}):
            self.assertEqual(422, self.client.post(url, json=request).status_code)
        self.preview({"groups": []})
        response = self.client.post(url, json={"mode": "incremental"})
        self.assertEqual(200, response.status_code)
        self.assertEqual(0, response.json()["scanned_count"])

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

    def test_review_preserves_model_original_and_applies_saved_edit(self):
        batch = self.preview()
        url = f"/sessions/{self.session.id}/memory-consolidations/{batch['id']}"
        content = "雨夜在车站相遇时，林墨将雨伞借给用户。"
        response = self.client.put(url + "/groups/0", json={"expected_revision": 0, "content": content})
        self.assertEqual(200, response.status_code)
        saved = response.json()
        self.assertEqual(batch["groups"][0]["content"], saved["groups"][0]["original_content"])
        self.assertEqual(content, saved["groups"][0]["content"])
        self.assertEqual(2, self.db.query(MemoryChunk).count())
        self.assertEqual(0, self.db.query(OutboxJob).count())
        self.assertEqual(409, self.client.post(url + "/apply", json={"group_ids": [0]}).status_code)
        result = self.client.post(url + "/apply", json={"group_ids": [0], "expected_revision": 1})
        self.assertEqual(200, result.status_code)
        self.assertEqual(content, result.json()["results"][0]["content"])
        self.assertEqual(409, self.client.put(url + "/groups/0", json={"expected_revision": 1}).status_code)
        service.undo(self.session.id, batch["id"], self.db)
        self.assertEqual(2, self.view()["total"])

    def test_ignore_restore_and_concurrent_review(self):
        batch = self.preview()
        url = f"/sessions/{self.session.id}/memory-consolidations/{batch['id']}"
        response = self.client.put(url + "/groups/0", json={"expected_revision": 0, "ignored": True, "ignore_reason": "事件不够明确"})
        self.assertEqual(200, response.status_code)
        self.assertEqual("事件不够明确", service.list_batches(self.session.id, self.db)["items"][0]["groups"][0]["ignore_reason"])
        self.assertEqual(409, self.client.post(url + "/apply", json={"group_ids": [0], "expected_revision": 1}).status_code)
        self.assertEqual(409, self.client.put(url + "/groups/0", json={"expected_revision": 0}).status_code)
        self.assertEqual(200, self.client.put(url + "/groups/0", json={"expected_revision": 1, "ignored": False}).status_code)
        self.assertEqual(200, self.client.post(url + "/apply", json={"group_ids": [0], "expected_revision": 2}).status_code)

    def test_review_validation_ownership_and_stale_group_details(self):
        batch = self.preview()
        url = f"/sessions/{self.session.id}/memory-consolidations/{batch['id']}/groups/0"
        for content in ("   ", "短", "长" * 501):
            self.assertEqual(422, self.client.put(url, json={"expected_revision": 0, "content": content}).status_code)
        child = self.fork()
        self.assertEqual(404, self.client.put(url.replace(f"/sessions/{self.session.id}/", f"/sessions/{child}/"), json={"expected_revision": 0}).status_code)
        with patch.object(service, "is_session_locked", return_value=True):
            self.assertEqual(409, self.client.put(url, json={"expected_revision": 0}).status_code)
        self.one.content = "原卡内容已修改，预览不再适用。"
        self.db.commit()
        group = service.list_batches(self.session.id, self.db)["items"][0]["groups"][0]
        self.assertIn("来源记忆", group["conflict"])
        self.assertEqual(409, self.client.put(url, json={"expected_revision": 0, "content": "不能用编辑绕过来源过期。"}).status_code)
        self.assertEqual(200, self.client.put(url, json={"expected_revision": 0, "ignored": True}).status_code)

    def test_conflicting_group_does_not_block_other_reviewed_groups(self):
        three = self.memory("用户周日送给林墨一本蓝色诗集。")
        four = self.memory("那本周日赠送的诗集是蓝色封面。")
        payload = self.payload()
        payload["groups"].append({"kind": "event", "source_ids": [three.id, four.id], "content": "周日用户送给林墨一本蓝色封面的诗集。", "reason": "同次赠书"})
        batch = self.preview(payload)
        self.one.content = "已修改的相遇记忆。"
        self.db.commit()
        listed = service.list_batches(self.session.id, self.db)["items"][0]
        self.assertIsNotNone(listed["groups"][0]["conflict"])
        self.assertIsNone(listed["groups"][1]["conflict"])
        result = service.apply(self.session.id, batch["id"], [1], self.db)
        self.assertEqual(1, len(result["results"]))

    def test_explicit_event_dates_support_partial_years_and_target_dates(self):
        for text_value, expected in (
            ("2025年6月7日雨夜在南站相遇。", (2025, 6, 7)),
            ("6月8号白天独自取回充电器。", (None, 6, 8)),
            ("用户在2025-06-07到达南站。", (2025, 6, 7)),
            ("2024年生日时用户送了一本诗集。", (2024, None, None)),
            ("那次拔牙后，林墨预约了6月27日上午十点复诊。", None),
            ("林墨答应2025年7月8日陪用户回家。", None),
            ("那次雨夜南站相遇时借了伞。", None),
        ):
            with self.subTest(text=text_value):
                self.assertEqual(expected, event_date_anchor(text_value))
        def sources(*texts):
            return [{"memory_type": "event", "content": content} for content in texts]
        self.assertTrue(has_conflicting_event_dates(sources("2025年6月7日相遇。", "6月8日独自取物。")))
        self.assertTrue(has_conflicting_event_dates(sources("2024年生日赠书。", "2025年生日赠书。")))
        self.assertFalse(has_conflicting_event_dates(sources("2025年6月7日相遇。", "6月7日借伞。")))
        self.assertFalse(has_conflicting_event_dates(sources("6月20日拔牙。", "预约了6月27日复诊。")))

    def test_cross_date_event_is_omitted_without_losing_safe_suggestions(self):
        self.one.content = "2025年6月7日用户和林墨在南站相遇。"
        self.two.content = "6月8日用户独自去南站取充电器，没有见到林墨。"
        a = self.memory("周日用户与林墨在旧书店找到一本诗集。")
        b = self.memory("那次周日逛旧书店时，林墨替用户买下那本诗集。")
        payload = self.payload()
        payload["groups"].append({"kind": "event", "source_ids": [a.id, b.id],
                                  "content": "周日用户与林墨在旧书店找到诗集，林墨替用户买下它。", "reason": "同一次购书。"})
        batch = self.preview(payload)
        self.assertEqual([0], [group["id"] for group in batch["groups"]])
        self.assertEqual([a.id, b.id], batch["groups"][0]["source_ids"])
        service.apply(self.session.id, batch["id"], [0], self.db)
        active_ids = {row["id"] for row in self.view()["items"]}
        self.assertTrue({self.one.id, self.two.id} <= active_ids)
        self.assertFalse({a.id, b.id} & active_ids)

    def test_appointment_target_does_not_block_same_visit_consolidation(self):
        self.one.content = "2025年6月20日林墨陪用户在城西诊所拔智齿。"
        self.two.content = "那次拔智齿结束后，林墨替用户预约了6月27日上午十点复诊。"
        self.db.commit()
        payload = self.payload()
        payload["groups"][0]["content"] = "2025年6月20日林墨陪用户在城西诊所拔智齿，并在结束后替用户预约了6月27日上午十点复诊。"
        batch = self.preview(payload)
        self.assertEqual(1, len(batch["groups"]))

    def test_duplicate_with_positive_and_negative_facts_is_omitted(self):
        self.one.content = "林墨喜欢别人叫他的名字。"
        self.two.content = "林墨不喜欢别人叫他的全名。"
        self.one.memory_type = self.two.memory_type = MemoryType.fact
        self.db.commit()
        payload = self.payload()
        payload["groups"][0].update(kind="duplicate", content="林墨喜欢被叫名字，不喜欢被叫全名。")
        batch = self.preview(payload)
        self.assertEqual([], batch["groups"])
        self.assertEqual(2, self.view()["total"])
        self.assertFalse(has_source_conflict("duplicate", [
            {"memory_type": "fact", "content": "用户不能吃花生。"},
            {"memory_type": "fact", "content": "用户不可以吃花生。"},
        ]))
        self.assertFalse(has_source_conflict("event", [
            {"memory_type": "event", "content": "7月3日用户爆胎。"},
            {"memory_type": "event", "content": "那次爆胎后，林墨的车没有损坏。"},
        ]))

    def test_old_duplicate_preview_with_negation_difference_cannot_apply(self):
        batch = self.preview()
        self.one.content = "林墨喜欢被叫名字。"
        self.two.content = "林墨不喜欢被叫全名。"
        self.one.memory_type = self.two.memory_type = MemoryType.fact
        payload = {**self.payload(), "sources": [service.snapshot(self.one), service.snapshot(self.two)]}
        payload["groups"][0].update(id=0, kind="duplicate")
        self.db.get(MemoryConsolidation, batch["id"]).preview_json = json.dumps(payload, ensure_ascii=False)
        self.db.commit()
        with self.assertRaisesRegex(service.ConsolidationConflict, "否定"):
            service.apply(self.session.id, batch["id"], [0], self.db)
        self.assertEqual(2, self.db.query(MemoryChunk).count())
        self.assertEqual(0, self.db.query(OutboxJob).count())

    def test_old_cross_date_preview_is_rejected_again_when_applying(self):
        batch = self.preview()
        self.one.content = "2025年6月7日用户和林墨在南站相遇。"
        self.two.content = "2025年6月8日用户独自去南站取充电器。"
        payload = {**self.payload(), "sources": [service.snapshot(self.one), service.snapshot(self.two)]}
        saved = self.db.get(MemoryConsolidation, batch["id"])
        payload["groups"][0]["id"] = 0
        saved.preview_json = json.dumps(payload, ensure_ascii=False)
        self.db.commit()
        with self.assertRaisesRegex(service.ConsolidationConflict, "不同日期"):
            service.apply(self.session.id, batch["id"], [0], self.db)
        self.assertEqual(2, self.db.query(MemoryChunk).count())
        self.assertEqual(0, self.db.query(OutboxJob).count())

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
        for index in range(103):
            self.memory(f"第 {index} 次独立事件。")
        first = self.preview({"groups": []})
        self.assertEqual(100, first["scanned_count"])
        self.assertTrue(first["has_more"])
        second = self.preview({"groups": []}, after_id=first["next_after_id"])
        self.assertEqual(5, second["scanned_count"])
        self.assertFalse(second["has_more"])
        self.assertFalse({m["id"] for m in first["sources"]} & {m["id"] for m in second["sources"]})

    def test_event_suggestions_with_emotion_or_relationship_sources_are_rejected_atomically(self):
        for kinds in ((MemoryType.emotion, MemoryType.emotion),
                      (MemoryType.relationship, MemoryType.relationship),
                      (MemoryType.emotion, MemoryType.relationship)):
            with self.subTest(kinds=kinds):
                self.one.memory_type, self.two.memory_type = kinds
                self.db.commit()
                with self.assertRaises(service.ConsolidationModelError):
                    self.preview()
                self.assertEqual(2, self.db.query(MemoryChunk).count())
                self.assertEqual(0, self.db.query(MemoryConsolidation).count())
                self.assertEqual(0, self.db.query(OutboxJob).count())

    def test_one_hundred_cards_are_scanned_together_including_distant_fragments(self):
        for index in range(97):
            self.memory(f"独立保留的第 {index} 条记忆。")
        payload = self.payload()
        last = self.memory("那次雨夜车站相遇后，林墨答应下周五陪用户回家。")
        payload["groups"][0]["source_ids"] = [self.one.id, last.id]
        preview = self.preview(payload)
        self.assertEqual(100, preview["scanned_count"])
        self.assertFalse(preview["has_more"])
        self.assertEqual([self.one.id, last.id], preview["groups"][0]["source_ids"])
        self.assertEqual(100, self.db.query(MemoryChunk).count())

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
