"""公开回合确认、成员证据过滤、持久任务重试和删除竞态。"""
import asyncio
import json
import unittest
from datetime import datetime
from unittest.mock import patch

from application.group_runtime import group_runtime
from core.models import GroupMemoryCapture
from services.memory.group_memory_capture import enqueue_confirmed_group, process_one_capture
from services.conversation import group_session_service as groups
from scripts.group_chat_prototype.worker import _response
from tests.conversation import test_group_background as fixtures


class GroupCaptureTests(unittest.TestCase):
    setUp = fixtures.GroupBackgroundTests.setUp
    observed = fixtures.GroupBackgroundTests.observed
    submit = fixtures.GroupBackgroundTests.submit
    drain = fixtures.GroupBackgroundTests.drain

    def confirm(self):
        draft = groups.GroupSessionDraft(tuple(groups.GroupMember(i) for i in (1, 2, 3)))
        group = asyncio.run(groups.create_group_session(draft, self.db))
        self.sid = group["session_id"]
        self.ids = tuple(row["persona_id"] for row in group["members"])
        public, private = "铜铃放在大厅。", "甲另有密信。"
        user = public + private

        class Scene(fixtures.Model):
            async def __call__(model, stage, params):
                def grants(ids):
                    return [{"persona_id": pid, "decision": "visible" if pid in ids else "hidden"} for pid in model.ids]
                if stage == "user_visibility":
                    return _response(json.dumps({"units": [
                        {"start": 0, "end": len(public), "recipients": grants(model.ids[:2])},
                        {"start": len(public), "end": len(user), "recipients": grants(model.ids[:1])}]}))
                if stage == "utterance_visibility":
                    model.saved += 1
                    return _response(json.dumps({"units": [{"unit_index": 0, "recipients": grants(model.ids[:2])}]}))
                return await super().__call__(stage, params)

        async def scenario(owner):
            original = await self.submit(self.sid, owner, Scene(self.ids, text="已弃用对白"), user_content=user)
            await self.drain(owner)
            selected = await self.submit(self.sid, owner, Scene(self.ids, text="已采用对白"), kind="regenerate")
            await self.drain(owner)
            self.assertEqual(0, self.db.query(GroupMemoryCapture).count())
            self.assertNotEqual(original["accepted"]["candidate_id"], selected["accepted"]["candidate_id"])
            def fail_enqueue(*args):
                enqueue_confirmed_group(*args)
                raise RuntimeError("模拟确认事务失败")
            with patch("services.memory.group_memory_capture.enqueue_confirmed_group", side_effect=fail_enqueue):
                with self.assertRaises(RuntimeError):
                    await self.submit(self.sid, owner, fixtures.Model(self.ids))
            await self.drain(owner)
            self.assertEqual(0, self.db.query(GroupMemoryCapture).count())
            await self.submit(self.sid, owner, fixtures.Model(self.ids, fail="role_generation"))
            await self.drain(owner)
            jobs = self.db.query(GroupMemoryCapture).all()
            self.assertEqual(set(self.ids[:2]), {job.persona_id for job in jobs})
            self.assertEqual({selected["accepted"]["candidate_id"]}, {job.candidate_id for job in jobs})
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def process(self, extract):
        with self.sessions() as db:
            return process_one_capture(db, extract=extract)

    def test_only_confirmed_selected_evidence_and_silent_listeners(self):
        self.confirm()
        seen = {}
        def extract(evidence):
            seen[evidence["persona_id"]] = [row["text"] for row in evidence["records"]]
            row = evidence["records"][0]
            return {"cards": [{"ref": row["ref"], "quote": row["text"], "content": "铜铃在大厅。",
                               "memory_type": "fact", "temporal_status": "current"}]}
        self.assertTrue(self.process(extract))
        self.assertTrue(self.process(extract))
        self.assertFalse(self.process(extract))
        self.assertEqual(["铜铃放在大厅。", "甲另有密信。", "已采用对白"], seen[self.ids[0]])
        self.assertEqual(["铜铃放在大厅。", "已采用对白"], seen[self.ids[1]])
        self.db.expire_all()
        for job in self.db.query(GroupMemoryCapture):
            self.assertEqual(1, len(json.loads(job.cards_json)))
            self.assertEqual(1, job.attempts)

    def test_invalid_evidence_retries_and_delete_cannot_restore_results(self):
        self.confirm()
        def invalid(evidence, correction=None):
            return {"cards": [{"ref": "foreign", "quote": "秘密", "content": "杜撰",
                               "memory_type": "fact", "temporal_status": "unknown"}]}
        self.assertTrue(self.process(invalid))
        job = self.db.query(GroupMemoryCapture).filter_by(error_code="extraction_failed").one()
        self.assertIsNone(job.cards_json)
        job.run_after = datetime(2000, 1, 1)
        self.db.commit()
        self.assertTrue(self.process(lambda _: {"cards": []}))
        self.db.refresh(job)
        self.assertEqual((2, "[]", None), (job.attempts, job.cards_json, job.error_code))
        def delete_while_running(_):
            asyncio.run(groups.delete_group_session(self.sid, self.db))
            return {"cards": []}
        self.assertTrue(self.process(delete_while_running))
        self.assertEqual(0, self.db.query(GroupMemoryCapture).count())

    def test_expired_attempt_cannot_replace_newer_cards(self):
        self.confirm()

        def late_result(evidence):
            with self.sessions() as other:
                job = other.query(GroupMemoryCapture).filter_by(persona_id=evidence["persona_id"]).one()
                job.run_after = datetime(2000, 1, 1)
                other.commit()
                self.assertTrue(process_one_capture(other, extract=lambda _: {"cards": []}))
            row = evidence["records"][0]
            return {"cards": [{"ref": row["ref"], "quote": row["text"], "content": "过期回应",
                               "memory_type": "fact", "temporal_status": "unknown"}]}

        self.assertTrue(self.process(late_result))
        job = self.db.query(GroupMemoryCapture).filter_by(attempts=2).one()
        self.assertEqual("[]", job.cards_json)
