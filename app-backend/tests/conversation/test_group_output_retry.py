"""格式重试只消耗当前阶段预算，不重复提交或放宽校验。"""
import asyncio
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from application.group_runtime import group_runtime
from core.locking import is_session_locked
from core.models import GroupContentItem, GroupDirectorStep, GroupRoundOperation, SessionPersona
from scripts.group_chat_prototype.worker import _response
from services.conversation import group_background_service as background
from services.conversation.group_call_snapshot import capture_group_calls, persist_group_calls, restore_group_calls
from services.conversation.group_output_retry import validated_output
from services.conversation.group_unit_protocol import GroupUnitError, load_object
from tests.conversation import test_group_background as fixtures


class GroupOutputRetryTests(unittest.TestCase):
    setUp = fixtures.GroupBackgroundTests.setUp
    group = fixtures.GroupBackgroundTests.group
    submit = fixtures.GroupBackgroundTests.submit
    drain = fixtures.GroupBackgroundTests.drain
    observed = fixtures.GroupBackgroundTests.observed
    candidate = fixtures.GroupBackgroundTests.candidate

    def test_each_stage_can_recover_twice_and_commits_one_utterance(self):
        sid, ids = self.group()
        model = fixtures.Model(ids)
        counts = {}
        async def invalid_then_valid(stage, parameters):
            counts[stage] = counts.get(stage, 0) + 1
            if counts[stage] < 3:
                return _response('{"invalid":')
            self.assertEqual(1, sum('上次响应未通过' in m['content'] for m in parameters['messages']))
            return await model(stage, parameters)
        async def scenario(owner):
            receipt = await self.submit(sid, owner, invalid_then_valid, max_steps=1)
            await self.drain(owner)
            candidate = self.candidate(receipt)
            self.assertEqual('awaiting_confirmation', candidate.status)
            self.assertEqual({3}, set(counts.values()))
            self.assertEqual(4, len(counts))
            operation = self.db.get(GroupRoundOperation, receipt['operation_id'])
            self.assertEqual((12, 12), (operation.call_count, operation.call_limit))
            self.assertEqual(1, self.db.query(GroupContentItem).filter_by(candidate_id=candidate.id, kind='utterance').count())
            self.assertEqual(4, self.db.query(GroupDirectorStep).filter_by(candidate_id=candidate.id).count())
            utterance = self.db.query(GroupContentItem).filter_by(candidate_id=candidate.id, kind='utterance').one()
            self.assertEqual(2, utterance.affection_change)
            self.assertEqual(0, self.db.get(SessionPersona, ids[0]).affection_score)
            self.assertFalse(is_session_locked(sid))
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_missing_status_and_invalid_json_exhaust_three_attempts_without_partial_write(self):
        for raw in ('{"units":[]', '{"units":[{"kind":"speech","text":"UNSAVED"}]}'):
            with self.subTest(raw=raw):
                sid, ids = self.group()
                model = fixtures.Model(ids)
                attempts = []
                async def invalid(stage, parameters):
                    if stage == 'role_generation':
                        attempts.append(parameters)
                        return _response(raw)
                    return await model(stage, parameters)
                async def scenario(owner):
                    receipt = await self.submit(sid, owner, invalid, max_steps=1)
                    await self.drain(owner)
                    candidate = self.candidate(receipt)
                    self.assertEqual(('failed', 'role_generation', 'invalid_output'),
                                     (candidate.status, candidate.checkpoint, candidate.error_code))
                    self.assertEqual(3, len(attempts))
                    self.assertEqual(0, self.db.query(GroupContentItem).filter_by(candidate_id=candidate.id, kind='utterance').count())
                    self.assertEqual(0, self.db.get(SessionPersona, ids[0]).affection_score)
                    self.assertEqual(5, self.db.get(GroupRoundOperation, receipt['operation_id']).call_count)
                    self.assertFalse(is_session_locked(sid))
                with group_runtime(self.engine) as owner:
                    asyncio.run(scenario(owner))

    def test_resume_keeps_frozen_retry_policy_and_does_not_repeat_saved_prefix(self):
        sid, ids = self.group()
        first = fixtures.Model(ids, steps=2)
        attempts = 0
        async def fail_second_role(stage, parameters):
            nonlocal attempts
            if stage == 'role_generation' and first.saved == 1:
                attempts += 1
                return _response('invalid')
            return await first(stage, parameters)
        async def scenario(owner):
            receipt = await self.submit(sid, owner, fail_second_role, max_steps=2)
            await self.drain(owner)
            failed = self.candidate(receipt)
            self.assertEqual(3, attempts)
            prefix = [row.id for row in self.db.query(GroupContentItem).filter_by(candidate_id=failed.id, kind='utterance')]
            self.assertEqual(1, len(prefix))
            snapshot, _ = restore_group_calls(failed, set(ids))
            self.assertEqual(3, snapshot.output_attempts)
            model = fixtures.Model(ids)
            resumed = await self.submit(sid, owner, model, kind='resume', target_candidate_id=failed.id,
                                        target_candidate_revision=failed.revision)
            await self.drain(owner)
            self.assertEqual('awaiting_confirmation', self.candidate(resumed).status)
            rows = self.db.query(GroupContentItem).filter_by(candidate_id=failed.id, kind='utterance').order_by(GroupContentItem.id).all()
            self.assertEqual(2, len(rows))
            self.assertEqual(prefix, [rows[0].id])
            self.assertEqual(1, sum(stage == 'role_generation' for stage, _ in model.calls))
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_old_snapshot_keeps_single_attempt(self):
        sid, ids = self.group()
        async def invalid(stage, parameters):
            return _response('invalid')
        def legacy(*args, **kwargs):
            return replace(capture_group_calls(*args, **kwargs), output_attempts=1)
        async def scenario(owner):
            with patch.object(background, 'capture_group_calls', side_effect=legacy):
                receipt = await self.submit(sid, owner, invalid)
                await self.drain(owner)
            candidate = self.candidate(receipt)
            self.assertEqual('invalid_output', candidate.error_code)
            self.assertNotIn('output_attempts', json.loads(candidate.call_snapshot_json))
            restored, _ = restore_group_calls(candidate, set(ids))
            self.assertEqual(1, restored.output_attempts)
            self.assertEqual(1, self.db.get(GroupRoundOperation, receipt['operation_id']).call_count)
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_snapshot_rejects_unbounded_or_noninteger_attempts(self):
        sid, ids = self.group()
        snapshot = capture_group_calls(sid, self.db)
        for value in (0, 4, True, '3'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                persist_group_calls(replace(snapshot, output_attempts=value), 1, set(ids))

    def test_fact_strategy_is_frozen_and_absent_legacy_flag_defaults_false(self):
        from types import SimpleNamespace
        sid, ids = self.group()
        snapshot = capture_group_calls(sid, self.db)
        encoded, fingerprint = persist_group_calls(snapshot, 1, set(ids))
        self.assertTrue(json.loads(encoded)['fact_recall'])
        restored, _ = restore_group_calls(SimpleNamespace(protocol_version=2, call_snapshot_json=encoded, provider_fingerprint=fingerprint), set(ids))
        self.assertTrue(restored.fact_recall)
        legacy = json.loads(encoded)
        del legacy['fact_recall']
        restored, _ = restore_group_calls(SimpleNamespace(protocol_version=2, call_snapshot_json=json.dumps(legacy), provider_fingerprint=fingerprint), set(ids))
        self.assertFalse(restored.fact_recall)
        with self.assertRaises(ValueError):
            persist_group_calls(replace(snapshot, fact_recall=1), 1, set(ids))


class RetryBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_network_cancel_truncation_and_semantic_rejection_are_not_retried(self):
        for error in (ConnectionError(), asyncio.CancelledError(), GroupUnitError('incomplete_output'),
                      GroupUnitError('agency_conflict'), GroupUnitError('unsupported_history')):
            with self.subTest(error=type(error).__name__, code=getattr(error, 'code', None)):
                calls = []
                async def invoke(parameters):
                    calls.append(parameters)
                    if isinstance(error, GroupUnitError):
                        return _response('{}')
                    raise error
                def validate(choice):
                    raise error
                with self.assertRaises(type(error)):
                    await validated_output(invoke, {'messages': []}, validate, 3)
                self.assertEqual(1, len(calls))

    async def test_cancellation_between_format_attempts_stops_dispatch(self):
        calls = []
        entered = asyncio.Event()
        async def invoke(parameters):
            calls.append(parameters)
            if len(calls) == 1:
                return _response('bad')
            entered.set()
            await asyncio.Future()
        task = asyncio.create_task(validated_output(invoke, {'messages': []},
            lambda choice: load_object(choice.message.content), 3))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(2, len(calls))
