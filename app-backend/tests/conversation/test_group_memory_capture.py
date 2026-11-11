"""公开回合确认、成员证据过滤、持久任务重试和删除竞态。"""
import asyncio
import json
import unittest
from datetime import datetime
from unittest.mock import patch

from application.group_runtime import group_runtime
from core.models import GroupMemberInsight, GroupMemoryCapture, GroupRoundCandidate
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

        def restore_legacy_permissions(candidate_id):
            # 直接构造已保存的旧权限，不调用已移除的裁决模型。
            from core.models import GroupContentItem, GroupContentUnit, GroupUnitVisibility, GroupDirectorStep
            from services.conversation.group_unit_protocol import ContentUnit, UnitPlan
            from services.conversation.group_unit_service import _write_units
            for item in self.db.query(GroupContentItem).filter_by(candidate_id=candidate_id):
                old_ids = [row.id for row in self.db.query(GroupContentUnit).filter_by(item_id=item.id)]
                self.db.query(GroupUnitVisibility).filter(GroupUnitVisibility.unit_id.in_(old_ids)).delete(synchronize_session=False)
                self.db.query(GroupContentUnit).filter_by(item_id=item.id).delete(synchronize_session=False)
                if item.kind == 'user':
                    plan = UnitPlan((ContentUnit('user', start=0, end=len(public)),
                                     ContentUnit('user', start=len(public), end=len(user))),
                                    (self.ids[:2], self.ids[:1]))
                else:
                    plan = UnitPlan((ContentUnit('speech', item.content),), (self.ids[:2],))
                _write_units(item, plan, set(self.ids), user, self.db)
                step = self.db.query(GroupDirectorStep).filter_by(item_id=item.id).one()
                step.decision_json = json.dumps(plan.decision(self.ids))
            self.db.commit()

        async def scenario(owner):
            original = await self.submit(self.sid, owner, fixtures.Model(self.ids, text="已弃用对白"), user_content=user)
            await self.drain(owner)
            selected = await self.submit(self.sid, owner, fixtures.Model(self.ids, text="已采用对白"), kind="regenerate")
            await self.drain(owner)
            restore_legacy_permissions(selected["accepted"]["candidate_id"])
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
            return {"insights": [], "cards": [{"ref": row["ref"], "quote": row["text"], "content": "铜铃在大厅。",
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
            return {"insights": [], "cards": [{"ref": "foreign", "quote": "秘密", "content": "杜撰",
                               "memory_type": "fact", "temporal_status": "unknown"}]}
        self.assertTrue(self.process(invalid))
        job = self.db.query(GroupMemoryCapture).filter_by(error_code="extraction_failed").one()
        self.assertIsNone(job.cards_json)
        job.run_after = datetime(2000, 1, 1)
        self.db.commit()
        self.assertTrue(self.process(lambda _: {"insights": [], "cards": []}))
        self.db.refresh(job)
        self.assertEqual((2, "[]", None), (job.attempts, job.cards_json, job.error_code))
        def delete_while_running(_):
            asyncio.run(groups.delete_group_session(self.sid, self.db))
            return {"insights": [], "cards": []}
        self.assertTrue(self.process(delete_while_running))
        self.assertEqual(0, self.db.query(GroupMemoryCapture).count())

    def test_expired_attempt_cannot_replace_newer_cards(self):
        self.confirm()

        def late_result(evidence):
            with self.sessions() as other:
                job = other.query(GroupMemoryCapture).filter_by(persona_id=evidence["persona_id"]).one()
                job.run_after = datetime(2000, 1, 1)
                other.commit()
                self.assertTrue(process_one_capture(other, extract=lambda _: {"insights": [], "cards": []}))
            row = evidence["records"][0]
            return {"insights": [{"target": "self", "ref": row["ref"], "quote": row["text"], "content": "过期印象"}],
                    "cards": [{"ref": row["ref"], "quote": row["text"], "content": "过期回应",
                               "memory_type": "fact", "temporal_status": "unknown"}]}

        self.assertTrue(self.process(late_result))
        job = self.db.query(GroupMemoryCapture).filter_by(attempts=2).one()
        self.assertEqual("[]", job.cards_json)
        self.assertEqual(0, self.db.query(GroupMemberInsight).count())

    def test_correction_reuses_personal_evidence_and_saves_only_revised_result(self):
        self.confirm()
        attempts = []
        def extract(evidence, correction=None):
            attempts.append(evidence)
            row = evidence["records"][0]
            if correction:
                previous, reason = correction
                self.assertEqual("不存在的原文", previous["insights"][0]["quote"])
                self.assertIn("第 1 条", reason)
            return {"cards": [], "insights": [{"target": "self", "ref": row["ref"],
                    "quote": row["text"] if correction else "不存在的原文", "content": "我记下了铜铃的位置"}]}
        self.assertTrue(self.process(extract))
        self.assertEqual(2, len(attempts))
        self.assertEqual(attempts[0], attempts[1])
        saved = self.db.query(GroupMemberInsight).one()
        self.assertEqual("铜铃放在大厅。", saved.quote)

    def test_confirmed_growth_reaches_only_owners_later_candidate(self):
        from services.memory.group_member_insights import member_insights
        from core.models import GroupRound
        self.confirm()
        # 上一轮已经确认，正在等待重试的下一轮候选先于提纯结果创建。
        original = self.db.query(GroupRoundCandidate).order_by(GroupRoundCandidate.id.desc()).first()
        def extract(evidence):
            private = evidence["persona_id"] == self.ids[0]
            record = evidence["records"][1 if private else -1]
            return {"cards": [], "insights": [{
                "ref": record["ref"], "quote": record["text"],
                "target": "self" if private else self.ids[0],
                "content": "我要藏好密信" if private else "我对说话人仍有戒心"}]}
        self.assertTrue(self.process(extract))
        self.assertTrue(self.process(extract))
        self.assertEqual([], member_insights(self.ids[0], self.db.get(GroupRound, original.round_id), original, self.db))
        model = fixtures.Model(self.ids, steps=3)
        async def generate(owner):
            receipt = await self.submit(self.sid, owner, model, kind="regenerate", max_steps=3)
            await self.drain(owner)
            candidate = self.db.get(GroupRoundCandidate, receipt["accepted"]["candidate_id"])
            self.assertEqual("awaiting_confirmation", candidate.status)
        with group_runtime(self.engine) as owner:
            asyncio.run(generate(owner))
        prompts = [json.dumps(params["messages"], ensure_ascii=False)
                   for stage, params in model.calls if stage == "role_generation"]
        self.assertEqual(3, len(prompts))
        self.assertIn("我要藏好密信", prompts[0])
        self.assertNotIn("说话人仍有戒心", prompts[0])
        self.assertIn("我对说话人仍有戒心", prompts[1])
        self.assertNotIn("我要藏好密信", prompts[1])
        self.assertNotIn("本人在群聊中形成的认识", prompts[2])
        for stage, params in model.calls:
            if stage != "role_generation":
                self.assertNotIn("我对说话人仍有戒心", str(params))
        asyncio.run(groups.delete_group_session(self.sid, self.db))
        self.assertEqual(0, self.db.query(GroupMemberInsight).count())

    def test_invalid_relationship_after_correction_preserves_verified_results(self):
        self.confirm()
        def extract(evidence, correction=None):
            row = evidence["records"][0]
            source = {"ref": row["ref"], "quote": row["text"], "content": "记住铜铃的位置"}
            return {"cards": [dict(source, memory_type="fact", temporal_status="current")],
                    "insights": [dict(source, target="self"), dict(source, target=9999)]}
        self.assertTrue(self.process(extract))
        finished = self.db.query(GroupMemoryCapture).filter_by(error_code="insights_filtered").one()
        self.assertEqual(1, len(json.loads(finished.cards_json)))
        insight = self.db.query(GroupMemberInsight).filter_by(capture_id=finished.id).one()
        self.assertEqual("cognition", insight.kind)

    def test_relationship_requires_direct_evidence_from_its_target(self):
        from services.memory.group_member_insights import validated_insights
        evidence = {"persona_id": 7, "records": [
            {"ref": "1:0", "kind": "speech", "speaker_id": None, "text": "我会留下"},
            {"ref": "2:0", "kind": "action", "speaker_id": 9, "text": "推开了门"}]}
        def impression(target, index):
            record = evidence["records"][index]
            return dict(target=target, ref=record["ref"], content="我开始相信对方", quote=record["text"])
        rows = validated_insights([impression("user", 0), impression("9", 1)], evidence)
        self.assertEqual([("user", None), ("member", 9)], [(r["kind"], r["target_persona_id"]) for r in rows])
        for target, index in (("user", 1), (9, 0), (7, 1), (77, 1)):
            with self.subTest(target=target, index=index), self.assertRaises(ValueError):
                validated_insights([impression(target, index)], evidence)
        evidence["records"][0]["kind"] = "fact"
        with self.assertRaises(ValueError):
            validated_insights([impression("user", 0)], evidence)
