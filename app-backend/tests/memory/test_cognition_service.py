"""认知更新使用临时 SQLite 和模型替身验证来源与发布竞争。"""

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from core.models import Base, Character, ChatMessage, MessageRole, Session, SessionPersona
from services.conversation import message_service
from services.memory import cognition_service as cognition


class CognitionServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.engine = create_engine("sqlite:///" + str(Path(self.temporary.name) / "test.db"))
        self.addCleanup(self.engine.dispose)

        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.db = self.sessions()
        self.addCleanup(self.db.close)
        character = Character(name="认知角色", description="测试设定", first_mes="你好")
        session = Session(title="认知故事")
        self.db.add_all([character, session])
        self.db.flush()
        persona = SessionPersona(session_id=session.id, character_id=character.id, cognition_state="原认知")
        self.db.add(persona)
        self.db.flush()
        user = ChatMessage(session_id=session.id, role=MessageRole.user, content="原用户消息", is_active=True)
        self.db.add(user)
        self.db.flush()
        reply = ChatMessage(session_id=session.id, role=MessageRole.assistant, content="原回复",
                            parent_id=user.id, is_active=True)
        self.db.add(reply)
        self.db.commit()
        self.sid, self.pid, self.cid = session.id, persona.id, character.id
        self.uid, self.rid = user.id, reply.id
        self.db.rollback()

    def update(self, during=None, content="新认知"):
        def generate(**kwargs):
            self.assertFalse(self.db.in_transaction())
            if during:
                with self.sessions() as other:
                    during(other, kwargs)
                    other.commit()
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

        provider = SimpleNamespace(generate=generate)
        with patch.object(cognition, "get_llm_provider", return_value=provider):
            return cognition.update_cognition_state(self.pid, self.db)

    def assert_original(self):
        self.db.expire_all()
        persona = self.db.get(SessionPersona, self.pid)
        self.assertEqual("原认知", persona.cognition_state)
        self.assertIsNone(persona.last_cognition_update_msg_id)

    def test_publishes_after_model_call_without_holding_transaction(self):
        self.assertEqual("新认知", self.update())
        persona = self.db.get(SessionPersona, self.pid)
        self.assertEqual(self.rid, persona.last_cognition_update_msg_id)
        self.assertEqual("新认知", persona.cognition_state)

    def test_edit_during_model_call_discards_result(self):
        self.assertIsNone(self.update(lambda db, _: message_service.update_message(self.uid, "修改消息", db)))
        self.assert_original()

    def test_delete_during_model_call_discards_result(self):
        self.assertIsNone(self.update(lambda db, _: message_service.delete_message(self.rid, db)))
        self.assert_original()

    def test_candidate_switch_during_model_call_discards_result(self):
        def switch(db, _):
            candidate = ChatMessage(session_id=self.sid, role=MessageRole.assistant, content="另一候选",
                                    parent_id=self.uid, is_active=False)
            db.add(candidate)
            db.commit()
            message_service.switch_candidate(candidate.id, db)

        self.assertIsNone(self.update(switch))
        self.assert_original()

    def test_newer_update_cannot_be_overwritten_or_have_progress_rewound(self):
        def newer(db, _):
            message = ChatMessage(session_id=self.sid, role=MessageRole.user, content="下一轮", is_active=True)
            db.add(message)
            db.commit()
            response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="较新认知"))])
            with patch.object(cognition, "get_llm_provider", return_value=SimpleNamespace(generate=lambda **kw: response)):
                self.assertEqual("较新认知", cognition.update_cognition_state(self.pid, db))
            self.new_progress = message.id

        self.assertIsNone(self.update(newer))
        persona = self.db.get(SessionPersona, self.pid)
        self.assertEqual("较新认知", persona.cognition_state)
        self.assertEqual(self.new_progress, persona.last_cognition_update_msg_id)

    def test_new_messages_after_frozen_boundary_remain_pending(self):
        def append(db, _):
            db.add(ChatMessage(session_id=self.sid, role=MessageRole.user, content="新消息", is_active=True))

        self.assertEqual("新认知", self.update(append))
        self.assertEqual(self.rid, self.db.get(SessionPersona, self.pid).last_cognition_update_msg_id)
        self.assertEqual(1, cognition.get_cognition_unseen_count(self.pid, self.sid, self.db))

    def test_deleted_persona_is_not_reported_as_success(self):
        self.assertIsNone(self.update(lambda db, _: db.delete(db.get(SessionPersona, self.pid))))
        self.assertIsNone(self.db.get(SessionPersona, self.pid))

    def test_empty_model_output_does_not_advance_progress(self):
        self.assertIsNone(self.update(content="  "))
        self.assert_original()

    def test_failure_rolls_back_and_preserves_state(self):
        def fail(db, _):
            raise RuntimeError("model unavailable")

        self.assertIsNone(self.update(fail))
        self.assertFalse(self.db.in_transaction())
        self.assert_original()

    def test_parallel_updates_publish_only_one_result_from_the_same_version(self):
        barrier = threading.Barrier(2)

        def generate(**kwargs):
            barrier.wait(timeout=3)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="并发认知"))])

        def update():
            with self.sessions() as db:
                return cognition.update_cognition_state(self.pid, db)

        with patch.object(cognition, "get_llm_provider", return_value=SimpleNamespace(generate=generate)):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: update(), range(2)))
        self.assertCountEqual([None, "并发认知"], results)
        self.assertEqual(self.rid, self.db.get(SessionPersona, self.pid).last_cognition_update_msg_id)

    def test_unsaved_caller_changes_are_preserved_without_autoflush(self):
        message = self.db.get(ChatMessage, self.uid)
        message.content = "未保存的编辑"
        with patch.object(cognition, "get_llm_provider") as provider:
            with self.assertRaisesRegex(ValueError, "尚未保存"):
                cognition.update_cognition_state(self.pid, self.db)
        provider.assert_not_called()
        self.assertEqual("未保存的编辑", message.content)
        with self.sessions() as db:
            self.assertEqual("原用户消息", db.get(ChatMessage, self.uid).content)

    def test_publish_failure_rolls_back_cognition_and_progress_together(self):
        commit = self.db.commit
        count = 0

        def maybe_fail():
            nonlocal count
            count += 1
            if count == 3:
                self.db.flush()
                raise RuntimeError("commit failed")
            commit()

        with patch.object(self.db, "commit", side_effect=maybe_fail):
            self.assertIsNone(self.update())
        self.assertFalse(self.db.in_transaction())
        self.assert_original()

    def test_branch_uses_only_own_messages_and_frozen_cognition(self):
        with self.sessions() as db:
            child = Session(title="分支", parent_session_id=self.sid, fork_message_id=self.rid)
            sibling = Session(title="平行分支", parent_session_id=self.sid, fork_message_id=self.rid)
            db.add_all([child, sibling])
            db.flush()
            persona = SessionPersona(session_id=child.id, character_id=self.cid, parent_persona_id=self.pid,
                                     cognition_state="分支冻结认知")
            db.add(persona)
            db.add_all([
                ChatMessage(session_id=self.sid, role=MessageRole.user, content="祖先未来", is_active=True),
                ChatMessage(session_id=sibling.id, role=MessageRole.user, content="平行未来", is_active=True),
                ChatMessage(session_id=child.id, role=MessageRole.user, content="本分支输入", is_active=True),
            ])
            db.commit()
            self.pid = persona.id

        def inspect(db, kwargs):
            prompt = kwargs["messages"][1]["content"]
            self.assertIn("分支冻结认知", prompt)
            self.assertIn("本分支输入", prompt)
            self.assertNotIn("祖先未来", prompt)
            self.assertNotIn("平行未来", prompt)
            db.get(SessionPersona, self.pid).session.fork_message_id = self.uid

        self.assertIsNone(self.update(inspect))

