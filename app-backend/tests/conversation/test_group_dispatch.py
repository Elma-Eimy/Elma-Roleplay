"""业务调度独立于审计，缺失记录不回退审计，旧候选保留原恢复契约。"""
import asyncio
import unittest
from unittest.mock import patch

from sqlalchemy import event
from core.models import GroupDispatch, GroupDirectorStep, GroupContentItem
from application.group_runtime import group_runtime
from services.conversation.group import audit_service as audit, checkpoint_service as checkpoints
from services.conversation.group.query_service import get_group_candidate, compile_member_prompt
from services.conversation.session_access import SessionKindConflict
from tests.conversation import test_group_background as fixtures


class GroupDispatchTests(unittest.TestCase):
    setUp = fixtures.GroupBackgroundTests.setUp
    group = fixtures.GroupBackgroundTests.group
    observed = fixtures.GroupBackgroundTests.observed
    submit = fixtures.GroupBackgroundTests.submit
    drain = fixtures.GroupBackgroundTests.drain
    candidate = fixtures.GroupBackgroundTests.candidate

    def test_prompt_and_resume_use_saved_target_even_when_all_audit_records_are_removed(self):
        sid, ids = self.group()
        first = fixtures.Model(ids, steps=2, text='FROZEN_FIRST_REPLY')

        async def fail_second_role(stage, parameters):
            if stage == 'role_generation' and first.saved == 1:
                raise RuntimeError('second role failed')
            return await first(stage, parameters)

        async def scenario(owner):
            receipt = await self.submit(sid, owner, fail_second_role)
            await self.drain(owner)
            candidate = self.candidate(receipt)
            self.assertEqual((1, 'failed', 'role_generation'),
                             (candidate.dispatch_version, candidate.status, candidate.checkpoint))
            prefix = self.db.query(GroupContentItem).filter_by(candidate_id=candidate.id, kind='utterance').one()
            prefix_id = prefix.id
            self.db.query(GroupDirectorStep).filter_by(candidate_id=candidate.id).delete()
            self.db.commit()

            def reject_audit_reads(connection, cursor, statement, parameters, context, executemany):
                if statement.lstrip().upper().startswith('SELECT') and 'group_director_steps' in statement:
                    raise AssertionError('new candidate must not read audit')

            after = fixtures.Model(ids, steps=2, text='SECOND_REPLY')
            after.saved = 1

            async def resume_model(stage, parameters):
                if stage == 'role_generation':
                    self.assertIn('FROZEN_FIRST_REPLY', str(parameters['messages']))
                    self.assertIn('本次主要回应对象', str(parameters['messages']))
                return await after(stage, parameters)

            event.listen(self.engine, 'before_cursor_execute', reject_audit_reads)
            try:
                # 测试关闭审计写入，以便同时禁止审计表的 SELECT max 等写入辅助查询。
                with patch.object(audit, 'record', return_value=None):
                    view = get_group_candidate(sid, candidate.round_id, candidate.id, self.db)
                    self.assertTrue(view['candidate']['can_resume'])
                    for persona_id in ids:
                        compile_member_prompt(sid, persona_id, self.db)
                    resumed = await self.submit(sid, owner, resume_model, kind='resume',
                        target_candidate_id=candidate.id, target_candidate_revision=candidate.revision)
                    await self.drain(owner)
                    # 已确认历史继续使用业务内容；下一轮也不应重新读取上一轮审计。
                    next_turn = await self.submit(sid, owner, fixtures.Model(ids), user_content='next turn')
                    await self.drain(owner)
                    self.assertEqual('awaiting_confirmation', self.candidate(next_turn).status)
            finally:
                event.remove(self.engine, 'before_cursor_execute', reject_audit_reads)
            self.assertEqual('role_generation', after.calls[0][0])
            self.assertEqual('awaiting_confirmation', self.candidate(resumed).status)
            items = self.db.query(GroupContentItem).filter_by(candidate_id=candidate.id, kind='utterance').order_by(GroupContentItem.sequence).all()
            self.assertEqual(2, len(items))
            self.assertEqual([(prefix_id, 'FROZEN_FIRST_REPLY'), (items[1].id, 'SECOND_REPLY')],
                             [(item.id, item.content) for item in items])
            self.assertTrue(all(row.completed_revision is not None for row in
                                self.db.query(GroupDispatch).filter_by(candidate_id=candidate.id)))
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_saved_finish_resumes_with_zero_calls_after_audit_cleanup(self):
        sid, ids = self.group()

        async def scenario(owner):
            with patch.object(checkpoints, 'finish', side_effect=RuntimeError('final commit failed')):
                receipt = await self.submit(sid, owner, fixtures.Model(ids))
                await self.drain(owner)
            candidate = self.candidate(receipt)
            self.assertEqual(('finish', 'wait_user'), (candidate.checkpoint, candidate.finish_reason))
            self.db.query(GroupDirectorStep).filter_by(candidate_id=candidate.id).delete()
            self.db.commit()
            model = fixtures.Model(ids)
            resumed = await self.submit(sid, owner, model, kind='resume', target_candidate_id=candidate.id,
                                        target_candidate_revision=candidate.revision)
            await self.drain(owner)
            self.assertEqual([], model.calls)
            self.assertEqual('awaiting_confirmation', self.candidate(resumed).status)
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_missing_or_forged_business_decision_never_falls_back_to_valid_audit(self):
        for mutation in ('delete', 'reference', 'revision', 'speaker'):
            sid, ids = self.group()

            async def scenario(owner):
                model = fixtures.Model(ids, steps=2)

                async def fail_role(stage, parameters):
                    if stage == 'role_generation' and (mutation != 'speaker' or model.saved == 1):
                        raise RuntimeError('role failed')
                    return await model(stage, parameters)

                receipt = await self.submit(sid, owner, fail_role)
                await self.drain(owner)
                candidate = self.candidate(receipt)
                decision = self.db.query(GroupDispatch).filter_by(candidate_id=candidate.id).order_by(GroupDispatch.sequence).first()
                if mutation == 'delete':
                    self.db.delete(decision)
                elif mutation == 'reference':
                    decision.response_reference = 'item:999999'
                elif mutation == 'revision':
                    decision.expected_revision += 100
                    decision.result_revision += 100
                else:
                    # 已完成调度的成员必须与已保存正文一致；跨群成员由外键专项拒绝。
                    decision.speaker_persona_id = ids[1]
                self.db.commit()
                self.assertTrue(self.db.query(GroupDirectorStep).filter_by(candidate_id=candidate.id).count())
                self.assertFalse(get_group_candidate(sid, candidate.round_id, candidate.id, self.db)['candidate']['can_resume'])
                model = fixtures.Model(ids)
                with self.assertRaises(SessionKindConflict):
                    await self.submit(sid, owner, model, kind='resume', target_candidate_id=candidate.id,
                                      target_candidate_revision=candidate.revision)
                self.assertEqual([], model.calls)
            with self.subTest(mutation=mutation), group_runtime(self.engine) as owner:
                asyncio.run(scenario(owner))

    def test_old_candidate_keeps_audit_recovery_and_is_not_silently_upgraded(self):
        for remove_audit in (False, True):
            sid, ids = self.group()

            async def scenario(owner):
                receipt = await self.submit(sid, owner, fixtures.Model(ids, fail='role_generation'))
                await self.drain(owner)
                candidate = self.candidate(receipt)
                # 重建迁移前候选形状：保留旧审计，不存在独立调度。
                candidate.dispatch_version = 0
                self.db.query(GroupDispatch).filter_by(candidate_id=candidate.id).delete()
                if remove_audit:
                    self.db.query(GroupDirectorStep).filter_by(candidate_id=candidate.id).delete()
                self.db.commit()
                if remove_audit:
                    with self.assertRaises(SessionKindConflict):
                        await self.submit(sid, owner, fixtures.Model(ids), kind='resume',
                            target_candidate_id=candidate.id, target_candidate_revision=candidate.revision)
                else:
                    resumed = await self.submit(sid, owner, fixtures.Model(ids), kind='resume',
                        target_candidate_id=candidate.id, target_candidate_revision=candidate.revision)
                    await self.drain(owner)
                    self.assertEqual('awaiting_confirmation', self.candidate(resumed).status)
                    self.assertEqual(0, self.candidate(resumed).dispatch_version)
                    self.assertEqual(0, self.db.query(GroupDispatch).filter_by(candidate_id=candidate.id).count())
            with self.subTest(remove_audit=remove_audit), group_runtime(self.engine) as owner:
                asyncio.run(scenario(owner))

    def test_dispatch_and_reply_completion_are_atomic_with_existing_transaction(self):
        original = audit.record
        for stage in ('next_action', 'utterance_visibility'):
            sid, ids = self.group()

            def fail(candidate, current_stage, *args, **kwargs):
                original(candidate, current_stage, *args, **kwargs)
                if current_stage == stage:
                    raise RuntimeError('audit write failed')

            async def scenario(owner):
                with patch.object(audit, 'record', side_effect=fail):
                    receipt = await self.submit(sid, owner, fixtures.Model(ids))
                    await self.drain(owner)
                candidate = self.candidate(receipt)
                self.assertEqual('failed', candidate.status)
                self.assertEqual(0, self.db.query(GroupContentItem).filter_by(candidate_id=candidate.id, kind='utterance').count())
                decisions = self.db.query(GroupDispatch).filter_by(candidate_id=candidate.id).all()
                self.assertEqual(0 if stage == 'next_action' else 1, len(decisions))
                self.assertTrue(all(row.completed_revision is None for row in decisions))
                resumed = await self.submit(sid, owner, fixtures.Model(ids), kind='resume',
                    target_candidate_id=candidate.id, target_candidate_revision=candidate.revision)
                await self.drain(owner)
                self.assertEqual('awaiting_confirmation', self.candidate(resumed).status)
            with self.subTest(stage=stage), group_runtime(self.engine) as owner:
                asyncio.run(scenario(owner))
