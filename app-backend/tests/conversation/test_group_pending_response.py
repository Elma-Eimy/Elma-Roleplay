"""首条口头请求不能被导演直接跳过；普通陈述仍可沉默。"""
import asyncio
import json
import unittest
from unittest.mock import patch

from application.group_runtime import group_runtime
from core.config import settings
from core.locking import is_session_locked
from core.models import GroupContentItem, GroupRoundOperation
from services.conversation.group_director_service import parse_next_action, GroupDirectorError
from scripts.group_chat_prototype.worker import _response
from tests.conversation import test_group_background as fixtures


class PendingResponseTests(unittest.TestCase):
    setUp = fixtures.GroupBackgroundTests.setUp
    group = fixtures.GroupBackgroundTests.group
    submit = fixtures.GroupBackgroundTests.submit
    drain = fixtures.GroupBackgroundTests.drain
    observed = fixtures.GroupBackgroundTests.observed
    candidate = fixtures.GroupBackgroundTests.candidate

    def test_only_pending_speech_request_blocks_end_and_legacy_stays_compatible(self):
        raw = '{"action":"end","reason_code":"wait_user"}'
        for source, mode, blocked in [('user_request', 'speech', True), ('user_request', 'action', False),
                                      ('user_request', 'either', False), ('user', 'speech', False)]:
            sources = {'1': {'request:1:0': {'source': source, 'reply_mode': mode}}}
            with self.subTest(source=source, mode=mode):
                self.assertEqual('end', parse_next_action(raw, (1, 2), (1,), response_sources=sources).action)
                if blocked:
                    with self.assertRaises(GroupDirectorError) as error:
                        parse_next_action(raw, (1, 2), (1,), response_sources=sources, require_response=True)
                    self.assertEqual('pending_response', error.exception.code)
                else:
                    self.assertEqual('end', parse_next_action(raw, (1, 2), (1,), response_sources=sources, require_response=True).action)
        self.assertEqual('end', parse_next_action(raw, (1, 2), (2,), response_sources={'1': {'x': {'source': 'user_request', 'reply_mode': 'speech'}}}, require_response=True).action)

    def exercise(self, *, reject_count, statement=False):
        sid, ids = self.group()
        calls = []
        action_attempts = 0
        user = '请回答。' if not statement else '天气晴朗。'
        async def model(stage, parameters):
            nonlocal action_attempts
            calls.append((stage, parameters))
            recipients = [{'persona_id': pid, 'decision': 'visible'} for pid in ids]
            if stage == 'user_visibility':
                value = {'units': [{'start': 0, 'end': len(user), 'meaning': 'fact' if statement else 'request',
                    'request_to': [] if statement else [ids[0]], **({} if statement else {'reply_mode': 'speech'}), 'recipients': recipients}]}
            elif stage == 'next_action':
                action_attempts += 1
                scene = json.loads(parameters['messages'][1]['content'])
                if statement or action_attempts <= reject_count or len(scene['history']) > 1:
                    value = {'action': 'end', 'reason_code': 'wait_user'}
                else:
                    value = {'action': 'speak', 'speaker_persona_id': ids[0], 'reason_code': 'direct_response',
                             'basis': next(iter(scene['response_sources'][str(ids[0])]))}
                if 1 < action_attempts <= min(reject_count + 1, 3):
                    self.assertIn('本轮尚无角色发言，仍有明确要求口头回答', parameters['messages'][-1]['content'])
            elif stage == 'role_generation':
                value = {'units': [{'kind': 'speech', 'text': '收到。'}], 'status': {'emotion': '平静', 'affection_change': 0}}
            else:
                value = {'review': 'ok', 'request_result': 'fulfilled', 'units': [{'unit_index': 0, 'recipients': recipients}]}
            return _response(json.dumps(value, ensure_ascii=False))

        async def scenario(owner):
            receipt = await self.submit(sid, owner, model, user_content=user, max_steps=2)
            await self.drain(owner)
            candidate = self.candidate(receipt)
            saved = self.db.query(GroupContentItem).filter_by(candidate_id=candidate.id, kind='utterance').count()
            operation = self.db.get(GroupRoundOperation, receipt['operation_id'])
            self.assertEqual(len(calls), operation.call_count)
            self.assertFalse(is_session_locked(sid))
            if reject_count >= 3:
                self.assertEqual(('failed', 'pending_response'), (candidate.status, candidate.error_code))
                self.assertEqual((3, 0), (action_attempts, saved))
                self.assertEqual('failed', operation.status)
            else:
                self.assertEqual('awaiting_confirmation', candidate.status)
                self.assertEqual(0 if statement else 1, saved)
                self.assertEqual('succeeded', operation.status)
                self.assertEqual(1, sum(stage == 'user_visibility' for stage, _ in calls))
        with patch.object(settings, 'APP_GROUP_TURN_PLANNING', True), group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_premature_end_corrects_within_budget_and_saves_one_reply(self):
        self.exercise(reject_count=2)

    def test_three_premature_ends_fail_explicitly_without_partial_reply(self):
        self.exercise(reject_count=3)

    def test_statement_can_finish_without_any_role_call(self):
        self.exercise(reject_count=0, statement=True)
