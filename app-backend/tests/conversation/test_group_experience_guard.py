"""亲历审查在提交之前执行，失败重写不能留下状态或旁听记录。"""
import asyncio
import json
import unittest
from dataclasses import replace
from unittest.mock import patch
from types import SimpleNamespace

from application.group_runtime import group_runtime
from core.locking import is_session_locked
from core.models import GroupContentItem, GroupRoundOperation, SessionPersona
from scripts.group_chat_prototype.worker import _response
from services.conversation.group_call_snapshot import capture_group_calls, persist_group_calls, restore_group_calls
from services.conversation.group_experience_guard import experience_evidence, validate_experience_review
from services.conversation.group_history_service import GroupHistoryItem
from services.conversation.group_unit_protocol import ContentUnit, GroupUnitError
from tests.conversation import test_group_background as fixtures


class GroupExperienceGuardTests(unittest.TestCase):
    setUp = fixtures.GroupBackgroundTests.setUp
    group = fixtures.GroupBackgroundTests.group
    observed = fixtures.GroupBackgroundTests.observed
    submit = fixtures.GroupBackgroundTests.submit
    drain = fixtures.GroupBackgroundTests.drain
    candidate = fixtures.GroupBackgroundTests.candidate

    def test_frozen_review_effort_does_not_change_role_generation_parameters(self):
        from services.conversation import group_background_service as background
        sid, ids = self.group()
        base = fixtures.Model(ids)
        capture = background.capture_group_calls
        async def scenario(owner):
            with patch.object(background, 'capture_group_calls', side_effect=lambda *args, **kwargs:
                    replace(capture(*args, **kwargs), review_reasoning_effort='low')):
                receipt = await self.submit(sid, owner, base, max_steps=1, experience_guard=True)
                await self.drain(owner)
            self.assertEqual('awaiting_confirmation', self.candidate(receipt).status)
            role = next(parameters for stage, parameters in base.calls if stage == 'role_generation')
            review = next(parameters for stage, parameters in base.calls if stage == 'role_experience_review')
            self.assertEqual('low', review['reasoning_effort'])
            self.assertNotEqual('low', role.get('reasoning_effort'))
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_unsupported_experience_rewrites_before_any_visibility_or_state_is_saved(self):
        sid, ids = self.group()
        base = fixtures.Model(ids)
        generated = []
        async def model(stage, parameters):
            if stage == 'role_generation':
                generated.append(parameters)
                if len(generated) == 1:
                    return _response(json.dumps({'units': [{'kind': 'speech', 'text': '我亲眼看过纸条。'}],
                        'status': {'emotion': '确信', 'affection_change': 5}}))
                self.assertEqual(0, self.db.query(GroupContentItem).filter_by(kind='utterance',session_id=sid).count())
                self.assertIn('缺乏本人可见依据', parameters['messages'][-1]['content'])
                self.assertNotIn('我亲眼看过纸条。', json.dumps(parameters['messages'], ensure_ascii=False))
            if stage == 'role_experience_review' and len(generated) == 1:
                payload = json.loads(parameters['messages'][1]['content'])
                self.assertEqual(ids[0], payload['experience_evidence']['persona_id'])
                return _response(json.dumps({'claims': [{'quote': '我亲眼看过纸条。', 'mode': 'witnessed', 'basis_refs': []}]}))
            return await base(stage, parameters)
        async def scenario(owner):
            receipt = await self.submit(sid, owner, model, max_steps=1, experience_guard=True)
            await self.drain(owner)
            candidate = self.candidate(receipt)
            self.assertEqual('awaiting_confirmation', candidate.status)
            row = self.db.query(GroupContentItem).filter_by(candidate_id=candidate.id, kind='utterance').one()
            self.assertEqual(('NEW_REPLY',2), (row.content,row.affection_change))
            self.assertEqual(2,len(generated))
            operation=self.db.get(GroupRoundOperation,receipt['operation_id'])
            self.assertEqual(7,operation.call_count)
            self.assertLessEqual(operation.call_count,operation.call_limit)
            self.assertFalse(is_session_locked(sid))
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_repeated_unsupported_claim_fails_without_prefix_and_keeps_frozen_policy(self):
        sid, ids = self.group()
        base = fixtures.Model(ids,text='我见过。')
        async def model(stage, parameters):
            if stage == 'role_experience_review':
                return _response(json.dumps({'claims':[{'quote':'我见过。','mode':'witnessed','basis_refs':[]}]}))
            return await base(stage,parameters)
        async def scenario(owner):
            receipt=await self.submit(sid,owner,model,max_steps=1,experience_guard=True)
            await self.drain(owner)
            candidate=self.candidate(receipt)
            self.assertEqual(('failed','unsupported_experience'),(candidate.status,candidate.error_code))
            self.assertEqual(0,self.db.query(GroupContentItem).filter_by(candidate_id=candidate.id,kind='utterance').count())
            self.assertEqual(0,self.db.get(SessionPersona,ids[0]).affection_score)
            snapshot,_=restore_group_calls(candidate,set(ids))
            self.assertTrue(snapshot.experience_guard)
            self.assertFalse(is_session_locked(sid))
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_hearsay_requests_disputes_and_unknown_refs_cannot_prove_witnessing(self):
        units=(ContentUnit('speech','我亲眼看过。'),)
        evidence={'sources':[{'ref':'speech','kind':'speech'}, {'ref':'action','kind':'action'},
            {'ref':'request','kind':'request'}, {'ref':'legacy','kind':'legacy'},
            {'ref':'disputed','kind':'observed','disputed':True}]}
        def review(ref, mode='witnessed'):
            return {'claims':[{'quote':'我亲眼看过。','mode':mode,'basis_refs':[ref]}]}
        for ref in ('speech','request','legacy','disputed'):
            with self.subTest(ref=ref),self.assertRaisesRegex(GroupUnitError,'unsupported_experience'):
                validate_experience_review(review(ref),units,evidence)
        validate_experience_review(review('action'),units,evidence)
        validate_experience_review(review('action','heard'),units,evidence)
        validate_experience_review(review('speech','heard'),units,evidence)
        with self.assertRaises(GroupUnitError):
            validate_experience_review(review('hidden'),units,evidence)
        with self.assertRaises(GroupUnitError):
            validate_experience_review({'claims':[{'quote':'未输出的句子','mode':'heard','basis_refs':['speech']}]},units,evidence)
        evidence['sources'].append({'ref':'unknown','kind':'observed','source_known':False})
        with self.assertRaisesRegex(GroupUnitError,'unsupported_experience'):
            validate_experience_review(review('unknown'),units,evidence)

    def test_evidence_keeps_speakers_and_only_supplied_visible_fragments(self):
        rows=[GroupHistoryItem(1,1,1,1,1,'utterance',12,'whole text must not leak',
              visible_units=(ContentUnit('speech','甲说他见过纸条。'),))]
        memories=[{'source_speaker':12,'claim_kind':'statement','fact_fragments':[
            {'content':'甲说见过。','claim_kind':'statement','disputed':True}]}]
        evidence=experience_evidence(11,rows,memories,[{'content':'请看看纸条。'}])
        encoded=json.dumps(evidence,ensure_ascii=False)
        self.assertNotIn('whole text',encoded)
        self.assertEqual(['speech','statement','request'],[source['kind'] for source in evidence['sources']])
        self.assertEqual(12,evidence['sources'][0]['speaker_id'])

    def test_new_policy_is_frozen_and_absent_flag_keeps_old_policy(self):
        sid,ids=self.group()
        snapshot=capture_group_calls(sid,self.db,model='fixture')
        self.assertTrue(snapshot.experience_guard)
        encoded,fingerprint=persist_group_calls(snapshot,1,set(ids))
        candidate=SimpleNamespace(protocol_version=2,call_snapshot_json=encoded,provider_fingerprint=fingerprint)
        restored,_=restore_group_calls(candidate,set(ids))
        self.assertTrue(restored.experience_guard)
        legacy=json.loads(encoded); legacy.pop('experience_guard')
        candidate.call_snapshot_json=json.dumps(legacy)
        restored,_=restore_group_calls(candidate,set(ids))
        self.assertFalse(restored.experience_guard)

    def test_private_memory_only_reaches_own_review_and_never_director_or_other_member(self):
        from tests.conversation.test_group_memory_recall import GroupMemoryRecallTests
        sid,ids=GroupMemoryRecallTests.group(self)
        model=fixtures.Model(ids,user='铜铃在哪里？',steps=2)
        async def scenario(owner):
            receipt=await self.submit(sid,owner,model,user_content='铜铃在哪里？',max_steps=2,experience_guard=True)
            await self.drain(owner)
            self.assertEqual('awaiting_confirmation',self.candidate(receipt).status)
            reviews=[json.dumps(params['messages'],ensure_ascii=False) for stage,params in model.calls if stage=='role_experience_review']
            self.assertEqual(2,len(reviews))
            self.assertIn('Q17',reviews[0])
            self.assertNotIn('Q17',reviews[1])
            for stage,params in model.calls:
                encoded=json.dumps(params['messages'],ensure_ascii=False)
                self.assertNotIn('FUTURE_ONLY',encoded)
                if stage not in ('role_generation','role_experience_review'):
                    self.assertNotIn('Q17',encoded)
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_invalid_review_stops_after_three_checks_without_replaying_role_or_saving(self):
        sid,ids=self.group()
        base=fixtures.Model(ids)
        calls=[]
        async def model(stage,parameters):
            calls.append(stage)
            if stage=='role_experience_review':
                return _response('{"claims":"not an array"}')
            return await base(stage,parameters)
        async def scenario(owner):
            receipt=await self.submit(sid,owner,model,max_steps=1,experience_guard=True)
            await self.drain(owner)
            candidate=self.candidate(receipt)
            self.assertEqual('experience_check_failed',candidate.error_code)
            self.assertEqual(1,calls.count('role_generation'))
            self.assertEqual(3,calls.count('role_experience_review'))
            self.assertNotIn('utterance_visibility',calls)
            self.assertEqual(0,self.db.query(GroupContentItem).filter_by(candidate_id=candidate.id,kind='utterance').count())
            self.assertFalse(is_session_locked(sid))
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))
