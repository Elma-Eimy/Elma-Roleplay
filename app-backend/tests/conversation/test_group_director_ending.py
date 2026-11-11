"""导演决定整轮结束，资源保护只暂停并保留原续接语义。"""
import asyncio
import json
import unittest
from unittest.mock import patch
from core.models import GroupContentItem, GroupRoundCandidate, GroupRoundOperation, GroupRound
from application.group_runtime import group_runtime
from services.conversation import group_round_service as rounds, group_operation_service as operations
from services.conversation.group_query_service import get_group_candidate
from services.conversation.session_access import SessionKindConflict
from tests.conversation import test_group_background as fixtures


class DirectorEndingTests(unittest.TestCase):
    setUp = fixtures.GroupBackgroundTests.setUp
    group = fixtures.GroupBackgroundTests.group
    observed = fixtures.GroupBackgroundTests.observed
    submit = fixtures.GroupBackgroundTests.submit
    drain = fixtures.GroupBackgroundTests.drain
    candidate = fixtures.GroupBackgroundTests.candidate

    def test_seven_replies_finish_only_after_director_end_despite_old_request_limit_one(self):
        sid, ids = self.group()
        model = fixtures.Model(ids, steps=7)
        async def scenario(owner):
            receipt = await self.submit(sid, owner, model, max_steps=1)
            await self.drain(owner)
            row = self.candidate(receipt)
            self.assertEqual(('awaiting_confirmation', 'wait_user', 'done'), (row.status, row.finish_reason, row.checkpoint))
            items = self.db.query(GroupContentItem).filter_by(candidate_id=row.id, kind='utterance').order_by(GroupContentItem.sequence).all()
            self.assertEqual(list(range(1,8)), [item.sequence for item in items])
            self.assertEqual([ids[i % 2] for i in range(7)], [item.speaker_persona_id for item in items])
            self.assertEqual(['next_action','role_generation'] * 7 + ['next_action'], [stage for stage, _ in model.calls])
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_resource_pause_keeps_pending_speaker_and_resume_appends_without_replaying(self):
        sid, ids = self.group()
        async def scenario(owner):
            model = fixtures.Model(ids, steps=3)
            with patch.object(rounds, 'DIRECTOR_CALL_LIMIT', 3), patch.object(operations, 'DIRECTOR_CALL_LIMIT', 3):
                receipt = await self.submit(sid, owner, model)
                await self.drain(owner)
            row = self.candidate(receipt)
            self.assertEqual(('failed','resource_paused','role_generation'), (row.status,row.error_code,row.checkpoint))
            self.assertEqual(3, self.db.get(GroupRoundOperation, receipt['operation_id']).call_count)
            first = self.db.query(GroupContentItem).filter_by(candidate_id=row.id,kind='utterance').one()
            prefix = first.id,first.content,first.affection_change
            view = get_group_candidate(sid, row.round_id, row.id, self.db)
            self.assertTrue(view['candidate']['can_resume'])
            with self.assertRaises(SessionKindConflict):
                await self.submit(sid,owner,fixtures.Model(ids),user_content='cannot confirm pause')
            self.assertIsNone(self.db.get(GroupRound,row.round_id).confirmed_at)
            after = fixtures.Model(ids,steps=3);after.saved=1
            resumed = await self.submit(sid,owner,after,kind='resume',target_candidate_id=row.id,target_candidate_revision=row.revision)
            await self.drain(owner)
            self.assertEqual(row.id,resumed['accepted']['candidate_id'])
            self.assertEqual('role_generation',after.calls[0][0])
            items=self.db.query(GroupContentItem).filter_by(candidate_id=row.id,kind='utterance').order_by(GroupContentItem.sequence).all()
            self.assertEqual(prefix,(items[0].id,items[0].content,items[0].affection_change))
            self.assertEqual(3,len(items));self.assertEqual(6,sum(item.affection_change for item in items))
            self.assertEqual('awaiting_confirmation',self.candidate(resumed).status)
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_finish_commit_failure_resumes_saved_director_end_with_zero_model_calls(self):
        from services.conversation import group_checkpoint_service as checkpoints
        sid,ids=self.group()
        async def scenario(owner):
            with patch.object(checkpoints,'finish',side_effect=RuntimeError('commit failure')):
                receipt=await self.submit(sid,owner,fixtures.Model(ids,steps=5))
                await self.drain(owner)
            row=self.candidate(receipt)
            self.assertEqual(('finish','wait_user'),(row.checkpoint,row.finish_reason))
            after=fixtures.Model(ids)
            resumed=await self.submit(sid,owner,after,kind='resume',target_candidate_id=row.id,target_candidate_revision=row.revision)
            await self.drain(owner)
            self.assertEqual([],after.calls)
            self.assertEqual('wait_user',self.candidate(resumed).finish_reason)
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_legacy_snapshot_without_new_policy_retains_its_frozen_limit(self):
        sid,ids=self.group()
        async def scenario(owner):
            receipt=await self.submit(sid,owner,fixtures.Model(ids,fail='role_generation'),max_steps=1)
            await self.drain(owner)
            row=self.candidate(receipt);policy=json.loads(row.call_snapshot_json);policy.pop('director_ending')
            row.call_snapshot_json=json.dumps(policy);self.db.commit();before=row.call_snapshot_json
            after=fixtures.Model(ids,steps=3)
            resumed=await self.submit(sid,owner,after,kind='resume',target_candidate_id=row.id,target_candidate_revision=row.revision)
            await self.drain(owner)
            self.assertEqual(['role_generation'],[stage for stage,_ in after.calls])
            self.assertEqual(before,self.candidate(resumed).call_snapshot_json)
            self.assertEqual('step_limit',self.candidate(resumed).finish_reason)
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))
