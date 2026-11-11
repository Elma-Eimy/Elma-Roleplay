"""已移除的角色 JSON、转换与审查不能通过旧参数或续接恢复。"""
import asyncio
import importlib.util
import json
import unittest
from uuid import uuid4
from unittest.mock import patch

from application.group_runtime import group_runtime
from core.config import settings
from core.models import GroupContentItem
from services.conversation import group_background_service as background
from services.conversation.group_call_snapshot import capture_group_calls, restore_group_calls, require_executable_calls
from services.conversation.group_round_service import run_group_round
from services.conversation.group_session_service import GroupSessionValidationError
from services.conversation.session_access import SessionKindConflict
from scripts.group_chat_prototype.worker import _response
from tests.conversation import test_group_background as fixtures


class GenerationCleanupTests(unittest.TestCase):
    setUp = fixtures.GroupBackgroundTests.setUp
    group = fixtures.GroupBackgroundTests.group
    observed = fixtures.GroupBackgroundTests.observed
    drain = fixtures.GroupBackgroundTests.drain
    candidate = fixtures.GroupBackgroundTests.candidate

    async def submit(self, sid, owner, model, **options):
        seen, revision = self.observed(sid)
        return await background.submit_group_operation(sid, str(uuid4()), 'send', revision, self.db,
            runtime=owner, call_model=model, model='fixture', user_content='共同讨论。', **seen, **options)

    def test_current_calls_are_only_director_and_single_chat_xml_even_with_old_config_enabled(self):
        sid, ids = self.group()
        model = fixtures.Model(ids)
        async def scenario(owner):
            receipt = await self.submit(sid, owner, model)
            await self.drain(owner)
            candidate = self.candidate(receipt)
            self.assertEqual('awaiting_confirmation', candidate.status)
            snapshot, _ = restore_group_calls(candidate, set(ids))
            self.assertEqual((0, False, None, 1), (snapshot.turn_policy, snapshot.experience_guard,
                snapshot.review_reasoning_effort, snapshot.output_attempts))
        with patch.multiple(settings, APP_GROUP_TURN_PLANNING=True, LLM_GROUP_JSON_MODE=True), group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))
        self.assertEqual(['next_action', 'role_generation', 'next_action'], [s for s, _ in model.calls])
        role = next(p for s, p in model.calls if s == 'role_generation')
        self.assertNotIn('response_format', role)
        self.assertIn('<reply>', role['messages'][-1]['content'])
        self.assertIsNone(importlib.util.find_spec('services.conversation.group_experience_guard'))
        self.assertIsNone(importlib.util.find_spec('services.conversation.group_output_retry'))

    def test_retired_role_json_and_empty_reply_fail_once_without_conversion_or_rewrite(self):
        for raw in ('', '{"units":[{"kind":"speech","text":"old"}],"status":{"emotion":"平静","affection_change":0}}'):
            sid, ids = self.group()
            base = fixtures.Model(ids)
            calls = []
            async def model(stage, parameters):
                calls.append(stage)
                return _response(raw) if stage == 'role_generation' else await base(stage, parameters)
            async def scenario(owner):
                receipt = await self.submit(sid, owner, model)
                await self.drain(owner)
                candidate = self.candidate(receipt)
                self.assertEqual(('failed', 'invalid_output'), (candidate.status, candidate.error_code))
                self.assertEqual(0, self.db.query(GroupContentItem).filter_by(candidate_id=candidate.id, kind='utterance').count())
            with group_runtime(self.engine) as owner:
                asyncio.run(scenario(owner))
            self.assertEqual(['next_action', 'role_generation'], calls)

    def test_old_snapshot_stays_readable_but_direct_service_resume_cannot_execute_it(self):
        sid, ids = self.group()
        async def scenario(owner):
            receipt = await self.submit(sid, owner, fixtures.Model(ids, fail='role_generation'))
            await self.drain(owner)
            candidate = self.candidate(receipt)
            old = json.loads(candidate.call_snapshot_json)
            old.pop('shared_chat')
            old.pop('reply_target')
            old.pop('director_ending')
            old.update(experience_guard=True, output_attempts=3)
            for member in old['members']:
                member['parameters']['response_format'] = {'type': 'json_object'}
            candidate.call_snapshot_json = json.dumps(old)
            self.db.commit()
            before = candidate.call_snapshot_json, candidate.revision, candidate.status
            snapshot, _ = restore_group_calls(candidate, set(ids))
            self.assertTrue(snapshot.experience_guard)
            with self.assertRaises(SessionKindConflict):
                require_executable_calls(snapshot)
            seen, revision = self.observed(sid)
            model = fixtures.Model(ids)
            with self.assertRaises(SessionKindConflict):
                await background.submit_group_operation(sid, str(uuid4()), 'resume', revision, self.db,
                    runtime=owner, call_model=model, target_candidate_id=candidate.id,
                    target_candidate_revision=candidate.revision, **seen)
            await self.drain(owner)
            self.db.expire_all()
            candidate = self.candidate(receipt)
            self.assertEqual(before, (candidate.call_snapshot_json, candidate.revision, candidate.status))
            self.assertEqual([], model.calls)
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_old_mode_is_rejected_before_any_model_call(self):
        sid, ids = self.group()
        with self.assertRaises(GroupSessionValidationError):
            capture_group_calls(sid, self.db, shared_chat=False)
        model = fixtures.Model(ids)
        with group_runtime(self.engine) as owner:
            with self.assertRaises(ValueError):
                asyncio.run(run_group_round(sid, 'test', self.db, runtime=owner, call_model=model, shared_chat=False))
        self.assertEqual([], model.calls)

    def test_each_retired_policy_is_independently_rejected_for_shared_candidates(self):
        from dataclasses import replace
        sid, ids = self.group()
        snapshot = capture_group_calls(sid, self.db, model='fixture')
        legacy_members = tuple((pid, json.dumps({**json.loads(encoded),
            'response_format': {'type': 'json_object'}})) for pid, encoded in snapshot.members)
        for fields in ({'experience_guard': True}, {'output_attempts': 3},
                       {'review_reasoning_effort': 'low'}, {'turn_policy': 2}, {'members': legacy_members}):
            with self.subTest(fields=tuple(fields)), self.assertRaises(SessionKindConflict):
                require_executable_calls(replace(snapshot, **fields))
