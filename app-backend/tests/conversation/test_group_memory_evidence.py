"""分开的事实进入长期证据，请求与私密内容仍遵守成员授权。"""
import asyncio
from datetime import datetime
import json
import unittest

from core.models import GroupMemoryCapture, GroupRound, GroupRoundCandidate
from services.conversation import group_history_service as history, group_session_service as groups
from services.conversation.group_unit_protocol import ContentUnit, UnitPlan
from services.memory.group_memory_capture import _evidence, _capture_results, enqueue_confirmed_group
from tests.conversation import test_group_session_service as fixtures


class GroupMemoryEvidenceTests(unittest.TestCase):
    setUp = fixtures.GroupSessionServiceTests.setUp

    def test_fact_survives_without_role_repetition_and_relationship_refs_exclude_other_sources(self):
        group = asyncio.run(groups.create_group_session(self.cards, self.db))
        sid = group['session_id']
        a, b = [m['persona_id'] for m in group['members']]
        parts = ('铜铃现在由赤羽保管。', '我承认故意骗了你。', '请甲确认，不要转述。', '我心里另藏秘密。')
        kinds = ('fact', 'speech', 'request', 'private')
        units = []
        start = 0
        for text, meaning in zip(parts, kinds):
            units.append(ContentUnit('user', start=start, end=start+len(text), meaning=meaning,
                                     reply_mode='speech' if meaning=='request' else None))
            start += len(text)
        plan = UnitPlan(tuple(units), ((a,b),(a,),(),()), ((),(),(a,),()))
        target = history._prepare(sid, ''.join(parts), (), self.db, unit_plan=plan, model='fixture')
        # 角色只确认，不复述事实；长期证据必须仍包含原始事实。
        reply = UnitPlan((ContentUnit('speech', '知道了。'),), ((a,b),))
        saved = history._append(sid,target['candidate_id'],a,'知道了。',(a,b),target['revision'],self.db,
                                unit_plan=reply,model='fixture')
        history._finish(sid,target['candidate_id'],saved['revision'],False,self.db,finish_reason='wait_user',model='fixture')
        round_ = self.db.get(GroupRound,target['round_id'])
        round_.confirmed_at = datetime.utcnow()
        candidate = self.db.get(GroupRoundCandidate,target['candidate_id'])
        enqueue_confirmed_group(round_,candidate,self.db)
        self.db.commit()
        owner = _evidence(self.db.query(GroupMemoryCapture).filter_by(persona_id=a).one(),self.db)
        observer = _evidence(self.db.query(GroupMemoryCapture).filter_by(persona_id=b).one(),self.db)
        self.assertIn(parts[0],[r['text'] for r in owner['records']])
        self.assertIn(parts[0],[r['text'] for r in observer['records']])
        self.assertNotIn(parts[1],json.dumps(observer,ensure_ascii=False))
        for evidence in (owner,observer):
            self.assertNotIn(parts[2],json.dumps(evidence,ensure_ascii=False))
            self.assertNotIn(parts[3],json.dumps(evidence,ensure_ascii=False))
        user_refs = owner['relationship_refs']['user']
        self.assertEqual([parts[1]],[r['text'] for r in owner['records'] if r['ref'] in user_refs])
        self.assertNotIn('user',observer['relationship_refs'])
        own_reply = next(r for r in owner['records'] if r['speaker_id']==a)
        admission = next(r for r in owner['records'] if r['text']==parts[1])
        value = {'cards':[],'insights':[dict(target='user',content='我对用户产生戒心',ref=admission['ref'],quote=parts[1])]}
        _, insights = _capture_results(value,owner)
        self.assertEqual('user',insights[0]['kind'])
        value['insights'][0].update(ref=own_reply['ref'],quote=own_reply['text'])
        with self.assertRaises(ValueError):
            _capture_results(value,owner)
