"""群聊记忆确认与提纯执行夹具。"""

import asyncio
import json
from unittest.mock import patch
from application.group_runtime import group_runtime
from core.models import GroupMemoryCapture
from services.memory.group_memory_capture import enqueue_confirmed_group, process_one_capture
from services.conversation.group import session_service as groups
from tests.support.group import background as fixtures


class GroupCaptureFixture:
    setUp = fixtures.GroupBackgroundFixture.setUp
    observed = fixtures.GroupBackgroundFixture.observed

    submit = fixtures.GroupBackgroundFixture.submit
    drain = fixtures.GroupBackgroundFixture.drain

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
            from services.conversation.group.unit_protocol import ContentUnit, UnitPlan
            from services.conversation.group.unit_service import _write_units
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
