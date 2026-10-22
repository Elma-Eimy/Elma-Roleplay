"""角色状态的增量校验、候选与分叉边界回归，不调用模型。"""

import unittest
from unittest.mock import patch
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from core.database import get_db
from core.models import Base, Character, ChatMessage, MessageRole
from application.factory import create_app
from services.conversation.session_service import create_session_service, save_chat_response
from services.conversation.message_service import switch_candidate, delete_message, update_message
from services.conversation.role_state_service import get_state, update_state, StateConflict
from services.conversation.prompt_compiler import build_chat_messages


class RoleStateTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, autoflush=False)()
        self.character = Character(name="露娜", description="守夜人", first_mes="你好")
        self.db.add(self.character)
        self.db.commit()
        result = create_session_service(self.character.id, None, "父故事", None, None, self.db)
        self.sid, self.pid = result["session_id"], result["persona_id"]

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def user(self):
        message = ChatMessage(session_id=self.sid, role=MessageRole.user, content="继续", is_active=True)
        self.db.add(message)
        self.db.commit()
        return message.id

    def reply(self, uid, delta=None, old=None):
        return save_chat_response(self.sid, self.pid, uid, "正文", "", "平静", 0, old is not None, old, self.db, role_state_patch=delta)[0]

    def test_optional_increment_keeps_old_fields_and_invalid_patch_is_ignored(self):
        self.reply(self.user(), {"scene": "客厅", "characters": {"露娜": {"clothing": "白衬衫", "posture": "坐着"}}})
        self.reply(self.user(), {"characters": {"露娜": {"posture": "站着"}}})
        self.reply(self.user())
        self.reply(self.user(), {"characters": {"露娜": {"clothing": None}}})
        state = get_state(self.sid, self.db)["state"]
        self.assertEqual("客厅", state["scene"])
        self.assertEqual({"clothing": "白衬衫", "posture": "站着"}, state["characters"]["露娜"])

    def test_regeneration_uses_pre_turn_state_and_candidates_restore_their_own_state(self):
        self.reply(self.user(), {"scene": "客厅"})
        uid = self.user()
        old = self.reply(uid, {"scene": "卧室"})
        new = self.reply(uid, old=old)
        self.assertEqual("客厅", get_state(self.sid, self.db)["state"]["scene"])
        switch_candidate(old, self.db)
        self.assertEqual("卧室", get_state(self.sid, self.db)["state"]["scene"])
        delete_message(old, self.db)
        self.assertEqual("客厅", get_state(self.sid, self.db)["state"]["scene"])
        delete_message(uid, self.db)
        self.assertIsNone(self.db.get(ChatMessage, new))
        self.assertEqual("客厅", get_state(self.sid, self.db)["state"]["scene"])

    def test_manual_correction_clear_and_optimistic_revision(self):
        self.reply(self.user(), {"scene": "客厅", "characters": {"露娜": {"clothing": "白衬衫", "posture": "坐着"}}})
        initial = get_state(self.sid, self.db)
        updated = update_state(self.sid, {"characters": {"露娜": {"clothing": "睡衣", "posture": None}}}, initial["revision"], self.db)
        self.assertEqual({"clothing": "睡衣"}, updated["state"]["characters"]["露娜"])
        with self.assertRaises(StateConflict):
            update_state(self.sid, {"scene": "旧页面"}, initial["revision"], self.db)
        self.reply(self.user())
        self.assertEqual("睡衣", get_state(self.sid, self.db)["state"]["characters"]["露娜"]["clothing"])

    def test_actor_limit_is_checked_after_merge_and_invalid_delta_changes_nothing(self):
        names = {f"角色{index}": {"posture": "坐着"} for index in range(8)}
        self.reply(self.user(), {"characters": names})
        self.reply(self.user(), {"scene": "不应保存", "characters": {"第九人": {"posture": "站着"}}})
        current = get_state(self.sid, self.db)
        self.assertNotIn("scene", current["state"])
        self.assertEqual(8, len(current["state"]["characters"]))
        updated = update_state(self.sid, {"characters": {"角色0": {"posture": None}, "新人物": {"posture": "站着"}}}, current["revision"], self.db)
        self.assertEqual(8, len(updated["state"]["characters"]))
        self.assertNotIn("角色0", updated["state"]["characters"])

    def test_empty_story_manual_baseline_is_persisted_without_fabricating_a_message(self):
        opening = self.db.query(ChatMessage).filter_by(session_id=self.sid).first()
        delete_message(opening.id, self.db)
        current = get_state(self.sid, self.db)
        updated = update_state(self.sid, {"scene": "客厅"}, current["revision"], self.db)
        self.assertEqual("客厅", updated["state"]["scene"])
        self.assertEqual(0, self.db.query(ChatMessage).filter_by(session_id=self.sid).count())

    def test_fork_snapshots_selected_candidate_without_ancestor_future_or_later_manual_edits(self):
        uid = self.user()
        selected = self.reply(uid, {"scene": "旧场景"})
        self.reply(uid, {"scene": "另一个候选"}, old=selected)
        self.reply(self.user(), {"scene": "父线未来"})
        branch = create_session_service(self.character.id, self.sid, "子故事", None, selected, self.db)
        self.assertEqual("旧场景", get_state(branch["session_id"], self.db)["state"]["scene"])
        current = get_state(self.sid, self.db)
        update_state(self.sid, {"scene": "父线手改"}, current["revision"], self.db)
        self.assertEqual("旧场景", get_state(branch["session_id"], self.db)["state"]["scene"])

    def test_failed_persistence_rolls_back_state_and_candidate_changes(self):
        uid = self.user()
        old = self.reply(uid, {"scene": "客厅"})
        with patch.object(self.db, "commit", side_effect=RuntimeError("commit failed")):
            with self.assertRaises(RuntimeError):
                self.reply(uid, {"scene": "卧室"}, old=old)
        self.assertTrue(self.db.get(ChatMessage, old).is_active)
        self.assertEqual("客厅", get_state(self.sid, self.db)["state"]["scene"])

    def test_editing_reply_invalidates_derived_patch_but_keeps_manual_correction(self):
        reply = self.reply(self.user(), {"scene": "卧室", "characters": {"露娜": {"posture": "站着"}}})
        current = get_state(self.sid, self.db)
        update_state(self.sid, {"scene": "客厅"}, current["revision"], self.db)
        update_message(reply, "手工修改后的正文", self.db)
        self.assertEqual({"scene": "客厅"}, get_state(self.sid, self.db)["state"])

    def test_cleared_scene_does_not_resurrect_initial_scenario_and_deleting_fork_anchor_rolls_back(self):
        selected = self.reply(self.user(), {"scene": "卧室"})
        branch = create_session_service(self.character.id, self.sid, "子故事", None, selected, self.db)
        copied = self.db.query(ChatMessage).filter_by(session_id=branch["session_id"]).first()
        delete_message(copied.id, self.db)
        self.assertNotIn("scene", get_state(branch["session_id"], self.db)["state"])
        current = get_state(self.sid, self.db)
        update_state(self.sid, {"scene": None}, current["revision"], self.db)
        self.assertIsNone(get_state(self.sid, self.db)["state"]["scene"])
        self.character.scenario = "过时的初始场景"
        messages = build_chat_messages(self.character, None, [], "继续", current_role_state={"scene": None})
        self.assertNotIn("过时的初始场景", "\n".join(item["content"] for item in messages))

    def test_prompt_marks_current_state_as_authoritative_over_recalled_history(self):
        messages = build_chat_messages(self.character, None, [], "继续", current_role_state={"scene": "客厅"}, retrieved_memories=[{"content": "曾在卧室"}])
        self.assertIn('"scene": "客厅"', messages[-3]["content"])
        self.assertIn("优先于召回的旧记忆", messages[-3]["content"])
        self.assertIn("全部未变化时省略整个 state_update", messages[-1]["content"])
        self.assertIn("有明确变化或首次明确描述时，必须", messages[-1]["content"])
        self.assertIn("发生状态变化时的 state_update", messages[-1]["content"])

    def test_api_rejects_invalid_fields_stale_edits_and_edits_during_generation(self):
        app = create_app()
        app.dependency_overrides[get_db] = lambda: self.db
        client = TestClient(app)
        url = f"/sessions/{self.sid}/role-state"
        current = client.get(url).json()
        invalid = client.put(url, json={"expected_revision": current["revision"], "patch": {"affection": 100}})
        self.assertEqual(422, invalid.status_code)
        saved = client.put(url, json={"expected_revision": current["revision"], "patch": {"scene": "窗边"}})
        self.assertEqual(200, saved.status_code, saved.text)
        self.assertEqual(409, client.put(url, json={"expected_revision": current["revision"], "patch": {}}).status_code)
        with patch("routers.sessions.get_session_lock") as get_lock:
            get_lock.return_value.locked.return_value = True
            self.assertEqual(409, client.put(url, json={"expected_revision": saved.json()["revision"], "patch": {}}).status_code)
        self.assertEqual(404, client.get("/sessions/999999/role-state").status_code)
        client.close()
