"""群聊继承卡只跟随本人的可见输入和候选策略进入个人 Prompt。"""
import asyncio
import json
import unittest

from application.group_runtime import group_runtime
from core.models import MemoryChunk, GroupRoundCandidate
from services.conversation import group_session_service as groups, group_history_service as history
from services.conversation.group_context_service import build_member_context
from services.conversation.group_unit_protocol import ContentUnit, UnitPlan
from tests.conversation import test_group_background as background


class GroupMemoryRecallTests(unittest.TestCase):
    setUp = background.GroupBackgroundTests.setUp
    observed = background.GroupBackgroundTests.observed
    submit = background.GroupBackgroundTests.submit
    drain = background.GroupBackgroundTests.drain

    def group(self):
        card = self.db.get(MemoryChunk, 1)
        card.content = "铜铃原定交给青鹭，暗记 Q17。"
        card.temporal_status = "planned"
        card.temporal_note = "入群前的计划"
        self.db.get(MemoryChunk, 2).content = "铜铃未来密钥 FUTURE_ONLY"
        self.db.commit()
        group = asyncio.run(groups.create_group_session(self.imported, self.db))
        self.db.delete(card)
        self.db.commit()
        return group["session_id"], tuple(member["persona_id"] for member in group["members"])

    def test_send_uses_frozen_card_only_in_owners_role_call(self):
        sid, ids = self.group()
        user = "提到铜铃，你们想起什么？"
        model = background.Model(ids, steps=2, user=user)

        async def scenario(owner):
            receipt = await self.submit(sid, owner, model, user_content=user, max_steps=2)
            await self.drain(owner)
            candidate = self.db.get(GroupRoundCandidate, receipt["accepted"]["candidate_id"])
            self.assertEqual("awaiting_confirmation", candidate.status)
            self.assertTrue(json.loads(candidate.call_snapshot_json)["inherited_recall"])

        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))
        roles = [json.dumps(params["messages"], ensure_ascii=False) for stage, params in model.calls if stage == "role_generation"]
        self.assertEqual(2, len(roles))
        self.assertIn("暗记 Q17", roles[0])
        self.assertIn("入群前的计划", roles[0])
        self.assertNotIn("FUTURE_ONLY", roles[0])
        self.assertNotIn("暗记 Q17", roles[1])
        for stage, params in model.calls:
            if stage != "role_generation":
                self.assertNotIn("暗记 Q17", json.dumps(params["messages"], ensure_ascii=False))

    def test_hidden_or_discontinuous_trigger_and_old_policy_do_not_recall(self):
        sid, (a, b) = self.group()
        content = "铜隐藏铃"
        units = tuple(ContentUnit("user", start=start, end=end) for start, end in ((0, 1), (1, 3), (3, 4)))
        plan = UnitPlan(units, ((a, b), (b,), (a, b)))
        target = history._prepare(sid, content, (b,), self.db, unit_plan=plan, model="fixture")
        def prompt():
            return build_member_context(sid, a, target["candidate_id"], target["revision"], self.db).messages_json
        self.assertNotIn("暗记 Q17", prompt())
        reply = UnitPlan((ContentUnit("speech", "铜铃"),), ((a, b),))
        target.update(history._append(sid, target["candidate_id"], b, "铜铃", (a, b), target["revision"],
                                     self.db, unit_plan=reply, model="fixture"))
        self.assertIn("暗记 Q17", prompt())
        candidate = self.db.get(GroupRoundCandidate, target["candidate_id"])
        candidate.call_snapshot_json = json.dumps({"history_limit": 10})
        self.db.commit()
        self.assertNotIn("暗记 Q17", prompt())
