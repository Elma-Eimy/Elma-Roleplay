"""共同群聊仅调用导演和 XML 角色，失败保留已完成前缀。"""
import asyncio
import json
import unittest
from uuid import uuid4
from core.models import GroupContentItem, GroupDirectorStep
from application.group_runtime import group_runtime
from services.conversation import group_background_service as background
from services.conversation.group_query_service import get_group_candidate, compile_member_prompt
from services.conversation.group_history_service import list_group_rounds
from scripts.group_chat_prototype.worker import _response
from tests.conversation import test_group_background as fixtures


class SharedChatTests(unittest.TestCase):
    setUp = fixtures.GroupBackgroundTests.setUp
    group = fixtures.GroupBackgroundTests.group
    observed = fixtures.GroupBackgroundTests.observed
    drain = fixtures.GroupBackgroundTests.drain
    candidate = fixtures.GroupBackgroundTests.candidate

    def action(self, parameters, speaker):
        sources = json.loads(parameters['messages'][1]['content'])['response_sources'][str(speaker)]
        return _response(json.dumps({'action': 'speak', 'speaker_persona_id': speaker,
            'reason_code': 'follow_up', 'basis': list(sources)[-1]}))

    def test_director_controls_a_b_a_targets_counts_and_waits_for_user(self):
        sid, ids = self.group()
        chosen, generated = [], []
        script = [(ids[0], 'user'), (ids[1], 'group_member'), (ids[0], 'group_member')]
        texts = ['甲问乙：你选哪条路？', '乙回答甲：走河边，你同意吗？', '甲回答乙：同意。用户接下来想去哪？']
        async def model(stage, parameters):
            if stage == 'next_action':
                payload = json.loads(parameters['messages'][1]['content'])
                counts = {row['persona_id']: row['count'] for row in payload['current_turn_counts']}
                self.assertEqual({pid: generated.count(pid) for pid in ids}, counts)
                if len(generated) == len(script):
                    return _response('{"action":"end","reason_code":"wait_user"}')
                speaker, kind = script[len(generated)]
                sources = payload['response_sources'][str(speaker)]
                self.assertFalse(any(row['source'] == 'self' for row in sources.values()))
                basis = next(ref for ref, source in reversed(list(sources.items())) if source['source'] == kind)
                chosen.append(basis)
                return _response(json.dumps(dict(action='speak', speaker_persona_id=speaker,
                    reason_code='direct_response' if not generated else 'follow_up', basis=basis)))
            self.assertEqual('role_generation', stage)
            prompt = json.dumps(parameters['messages'], ensure_ascii=False)
            self.assertIn('本次主要回应对象', prompt)
            if generated:
                target = prompt.split('本次主要回应对象', 1)[1].split('这次主要承接', 1)[0]
                self.assertIn(texts[len(generated)-1], target)
            speaker = script[len(generated)][0]
            generated.append(speaker)
            return _response('<reply>' + texts[len(generated)-1] + '</reply>')
        async def scenario(owner):
            seen, revision = self.observed(sid)
            receipt = await background.submit_group_operation(sid, str(uuid4()), 'send', revision, self.db,
                runtime=owner, call_model=model, user_content='甲先问乙，再听乙回答，甲最后回应；然后等我。',
                model='fixture', max_steps=6, **seen)
            await self.drain(owner)
            candidate = self.candidate(receipt)
            self.assertEqual(('awaiting_confirmation', 'wait_user'), (candidate.status, candidate.finish_reason))
            steps = self.db.query(GroupDirectorStep).filter_by(candidate_id=candidate.id, stage='next_action').order_by(GroupDirectorStep.step_index).all()
            self.assertEqual(chosen, [json.loads(step.decision_json)['basis'] for step in steps])
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))
        self.assertEqual([ids[0], ids[1], ids[0]], generated)

    def test_invalid_or_missing_target_never_dispatches_role(self):
        for invalid in (None, 'item:999999'):
            sid, ids = self.group()
            calls = []
            async def model(stage, parameters):
                calls.append(stage)
                value = dict(action='speak', speaker_persona_id=ids[0], reason_code='direct_response')
                if invalid:
                    value['basis'] = invalid
                return _response(json.dumps(value))
            async def scenario(owner):
                seen, revision = self.observed(sid)
                receipt = await background.submit_group_operation(sid, str(uuid4()), 'send', revision, self.db,
                    runtime=owner, call_model=model, user_content='开始', model='fixture', **seen)
                await self.drain(owner)
                self.assertEqual('invalid_basis', self.candidate(receipt).error_code)
            with group_runtime(self.engine) as owner:
                asyncio.run(scenario(owner))
            self.assertEqual(['next_action'], calls)

    def test_director_can_repeat_a_and_point_b_at_an_earlier_message(self):
        from unittest.mock import patch
        from core.config import settings
        sid, ids = self.group()
        texts = ['甲的第一条问题', '甲补充了另一件事', '乙专门回答甲的第一条问题']
        count = 0
        async def model(stage, parameters):
            nonlocal count
            if stage == 'next_action':
                payload = json.loads(parameters['messages'][1]['content'])
                if count == 3:
                    return _response('{"action":"end","reason_code":"wait_user"}')
                speaker = ids[0] if count < 2 else ids[1]
                sources = payload['response_sources'][str(speaker)]
                if count < 2:
                    basis = next(ref for ref, source in sources.items() if source['source'] == 'user')
                else:
                    basis = next(row['reference'] for row in payload['history']
                        if any(unit.get('text') == texts[0] for unit in row.get('units', [])))
                return _response(json.dumps(dict(action='speak', speaker_persona_id=speaker,
                    reason_code='follow_up', basis=basis)))
            prompt = json.dumps(parameters['messages'], ensure_ascii=False)
            target = prompt.split('本次主要回应对象', 1)[1].split('这次主要承接', 1)[0]
            self.assertIn('"turn_reply_number": ' + str(count + 1 if count < 2 else 1), target.replace('\\"', '"'))
            if count == 2:
                self.assertIn(texts[0], target)
                self.assertNotIn(texts[1], target)
            text = texts[count]
            count += 1
            return _response('<reply>' + text + '</reply>')
        async def scenario(owner):
            seen, revision = self.observed(sid)
            receipt = await background.submit_group_operation(sid, str(uuid4()), 'send', revision, self.db,
                runtime=owner, call_model=model, user_content='甲说两次，乙回答甲的第一条。', model='fixture', max_steps=6, **seen)
            await self.drain(owner)
            candidate = self.candidate(receipt)
            self.assertEqual('wait_user', candidate.finish_reason)
            rows = self.db.query(GroupContentItem).filter_by(candidate_id=candidate.id, kind='utterance').order_by(GroupContentItem.sequence).all()
            self.assertEqual([ids[0], ids[0], ids[1]], [row.speaker_persona_id for row in rows])
        with patch.object(settings, 'APP_CONTEXT_HISTORY_LIMIT', 1), group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_older_shared_snapshot_does_not_require_a_new_target(self):
        from types import SimpleNamespace
        from services.conversation.group_call_snapshot import capture_group_calls, persist_group_calls, restore_group_calls
        sid, ids = self.group()
        snapshot = capture_group_calls(sid, self.db, model='fixture')
        encoded, fingerprint = persist_group_calls(snapshot, 4, set(ids))
        old = json.loads(encoded)
        old.pop('reply_target')
        candidate = SimpleNamespace(protocol_version=2, call_snapshot_json=json.dumps(old), provider_fingerprint=fingerprint)
        original = candidate.call_snapshot_json
        restored, _ = restore_group_calls(candidate, set(ids))
        self.assertTrue(restored.shared_chat)
        self.assertFalse(restored.reply_target)
        self.assertEqual(original, candidate.call_snapshot_json)

    def test_xml_prefix_is_visible_before_next_role_fails_and_resume_keeps_it(self):
        sid, ids = self.group()
        stages, count = [], 0
        async def model(stage, parameters):
            nonlocal count
            stages.append(stage)
            if stage == 'next_action':
                return self.action(parameters, ids[min(count, 1)])
            self.assertEqual('role_generation', stage)
            self.assertNotIn('response_format', parameters)
            prompt = json.dumps(parameters['messages'], ensure_ascii=False)
            self.assertIn('<reply>', prompt)
            self.assertNotIn('群聊单元输出协议', prompt)
            count += 1
            if count == 2:
                self.db.expire_all()
                latest = background.operations._latest(sid, self.db)
                view = get_group_candidate(sid, latest.id, latest.selected_candidate_id, self.db)
                self.assertEqual(['第一条'], [r['content'] for r in view['utterances']])
                self.assertEqual('generating', view['candidate']['status'])
                raise RuntimeError('second role failed')
            return _response('<reply>第一条</reply><status emotion="开心" affection_change="2"/>')
        async def scenario(owner):
            seen, revision = self.observed(sid)
            receipt = await background.submit_group_operation(sid, str(uuid4()), 'send', revision, self.db,
                runtime=owner, call_model=model, user_content='一起聊聊。', model='fixture', max_steps=2, **seen)
            await self.drain(owner)
            candidate = self.candidate(receipt)
            self.assertEqual('failed', candidate.status)
            self.assertTrue(json.loads(candidate.call_snapshot_json)['shared_chat'])
            first = self.db.query(GroupContentItem).filter_by(candidate_id=candidate.id, kind='utterance').one()
            first_id = first.id
            preview = compile_member_prompt(sid, ids[1], self.db)
            self.assertIn('第一条', json.dumps(preview['messages'], ensure_ascii=False))
            async def resumed(stage, parameters):
                self.assertEqual('role_generation', stage)
                self.assertIn('本次主要回应对象', json.dumps(parameters['messages'], ensure_ascii=False))
                return _response('第二条</reply><status emotion="平静" affection_change="0"/>')
            seen, revision = self.observed(sid)
            await background.submit_group_operation(sid, str(uuid4()), 'resume', revision, self.db,
                runtime=owner, call_model=resumed, target_candidate_id=candidate.id,
                target_candidate_revision=candidate.revision, **seen)
            await self.drain(owner)
            self.assertEqual('awaiting_confirmation', self.candidate(receipt).status)
            rows = self.db.query(GroupContentItem).filter_by(candidate_id=candidate.id, kind='utterance').order_by(GroupContentItem.sequence).all()
            self.assertEqual(first_id, rows[0].id)
            self.assertEqual(['第一条', '第二条'], [row.content for row in rows])
            old_id = candidate.id
            generated = 0
            async def regeneration(stage, parameters):
                nonlocal generated
                if stage == 'next_action':
                    return self.action(parameters, ids[0])
                generated += 1
                if generated == 2:
                    view = list_group_rounds(sid, self.db)['rounds'][0]
                    self.assertEqual(old_id, view['candidate_id'])
                    self.assertEqual(['新前缀'], [r['content'] for r in view['pending_candidate']['utterances']])
                    raise RuntimeError('regeneration failed')
                return _response('<reply>新前缀</reply>')
            seen, revision = self.observed(sid)
            await background.submit_group_operation(sid, str(uuid4()), 'regenerate', revision, self.db,
                runtime=owner, call_model=regeneration, model='fixture', max_steps=2, **seen)
            await self.drain(owner)
            view = list_group_rounds(sid, self.db)['rounds'][0]
            self.assertEqual(old_id, view['candidate_id'])
            self.assertEqual('failed', view['pending_candidate']['status'])
            self.assertEqual('新前缀', view['pending_candidate']['utterances'][0]['content'])
            old_round = view['round_id']
            seen, revision = self.observed(sid)
            await background.submit_group_operation(sid, str(uuid4()), 'send', revision, self.db,
                runtime=owner, call_model=regeneration, user_content='下一轮', model='fixture', max_steps=1, **seen)
            await self.drain(owner)
            prior = next(row for row in list_group_rounds(sid, self.db)['rounds'] if row['round_id'] == old_round)
            self.assertTrue(prior['confirmed'])
            self.assertIsNone(prior['pending_candidate'])
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))
        self.assertEqual(['next_action', 'role_generation', 'next_action', 'role_generation'], stages)
