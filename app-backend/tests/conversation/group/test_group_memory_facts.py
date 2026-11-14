"""事实入口不依赖导演用途，分段更正只影响本人未来候选。"""
import asyncio
from datetime import datetime
import json
import unittest
from sqlalchemy import func
from core.models import GroupMemoryCapture, GroupRound, GroupRoundCandidate, GroupRecallCard
from services.conversation.group import session_service as groups,history_service as history
from services.conversation.group.unit_protocol import ContentUnit,UnitPlan
from services.memory.group_memory_assertions import classified_records, prepare_assertions
from services.memory.group_memory_capture import enqueue_confirmed_group,process_one_capture,_validated_cards
from services.memory.group_memory_index import unified_memories
from tests.support.group import session_service as fixtures


class GroupMemoryFactsTests(unittest.TestCase):
    setUp=fixtures.GroupSessionFixture.setUp

    def prepare(self,text,*,speaker=None,reply=None):
        if not hasattr(self,'sid'):
            group=asyncio.run(groups.create_group_session(self.imported,self.db))
            self.sid=group['session_id']
            self.a,self.b=[m['persona_id'] for m in group['members']]
        # 同一个 request 对甲可见，对乙只有执行授权，不能让乙获得事实。
        plan=UnitPlan((ContentUnit('user',start=0,end=len(text),meaning='request',reply_mode='speech'),),
                      ((self.a,),),((self.a,self.b),))
        target=history._prepare(self.sid,text,(self.a,),self.db,unit_plan=plan,model='fixture')
        candidate=self.db.get(GroupRoundCandidate,target['candidate_id'])
        candidate.call_snapshot_json=json.dumps({'group_card_limit':self.db.query(func.max(GroupRecallCard.id)).scalar() or 0})
        self.db.commit()
        if reply:
            speaker=speaker or self.a
            response=UnitPlan((ContentUnit('speech',reply),),((self.a,),))
            saved=history._append(self.sid,candidate.id,speaker,reply,(self.a,),target['revision'],self.db,
                                 unit_plan=response,model='fixture')
            target['revision']=saved['revision']
        history._finish(self.sid,candidate.id,target['revision'],False,self.db,finish_reason='wait_user',model='fixture')
        round_=self.db.get(GroupRound,target['round_id'])
        round_.confirmed_at=datetime.utcnow()
        enqueue_confirmed_group(round_,candidate,self.db)
        self.db.commit()
        return target

    def classify(self,sources,correction=None):
        return {'units':[{'ref':r['ref'],'segments':[{'start':0,'end':len(r['text']),'kind':'statement'}]} for r in sources]}

    def test_mixed_denial_enters_memory_without_role_echo_and_request_authority_does_not_grant_knowledge(self):
        denied='我没给你看过纸条。'
        request='请别猜。'
        self.prepare(denied+request,reply='知道了。')
        seen=[]
        def classify(sources,correction=None):
            return {'units':[{'ref':r['ref'],'segments':[{'start':0,'end':len(denied),'kind':'statement'},
                {'start':len(denied),'end':len(r['text']),'kind':'request'}]} if r['speaker_id'] is None else {'ref':r['ref'],'segments':[{'text':r['text'],'kind':'statement'}]} for r in sources]}
        def extract(evidence):
            seen.append(evidence)
            source=next(r for r in evidence['records'] if r['speaker_id'] is None)
            self.assertEqual(denied,source['text'])
            self.assertNotIn(request,json.dumps(evidence['records'],ensure_ascii=False))
            return {'cards':[dict(content='用户否认给我看过纸条。',memory_type='fact',temporal_status='current',
                ref=source['ref'],quote=source['text'],claim_kind='statement')],'insights':[],'partitions':[],'unmatched_corrections':[]}
        with self.sessions() as db:
            self.assertTrue(process_one_capture(db,classify=classify,extract=extract))
        self.assertEqual(1,len(seen))
        self.assertEqual({self.a},{j.persona_id for j in self.db.query(GroupMemoryCapture)})
        self.db.expire_all()
        ceiling=self.db.query(func.max(GroupRecallCard.id)).scalar()
        view=unified_memories(self.a,2,ceiling,['纸条'],self.db,{},facts=True)
        self.assertTrue(any(c['claim_kind']=='statement' and c['source_speaker'] is None for c in view))
        self.assertEqual([],unified_memories(self.b,2,ceiling,['纸条'],self.db,{},facts=True))

    def test_partial_retraction_retains_engraving_old_candidate_and_other_member(self):
        old='我看过纸条。怀表刻着北风47。'
        first=self.prepare('请确认。',reply=old)
        def old_extract(evidence):
            source=next(r for r in evidence['records'] if r['speaker_id']==self.a)
            return {'cards':[dict(content=old,memory_type='fact',temporal_status='current',ref=source['ref'],quote=old)],'insights':[]}
        with self.sessions() as db:
            process_one_capture(db,extract=old_extract)
        self.db.expire_all()
        old_card=self.db.query(GroupRecallCard).filter(GroupRecallCard.capture_id.isnot(None)).one()
        old_id=old_card.id
        ceiling=self.db.query(func.max(GroupRecallCard.id)).scalar()
        self.prepare('请把刚才说错的地方讲清楚。',reply='我没见过纸条，刚才说错了。')
        split=len('我看过纸条。')
        def correct(evidence):
            prior=next(c for c in evidence['prior_facts'] if c['id']==old_id)
            self.assertEqual(old,prior['source_content'])
            source=next(r for r in evidence['records'] if r['speaker_id']==self.a)
            return {'cards':[dict(content='我没见过纸条。',memory_type='fact',temporal_status='current',
                ref=source['ref'],quote=source['text'],claim_kind='statement',replaces_part={
                    'card_id':old_id,'start':0,'end':split,'mode':'retract'})],
                'insights':[],'unmatched_corrections':[],'partitions':[{'card_id':old_id,'parts':[{'start':0,'end':split},{'start':split,'end':len(old)}]}]}
        with self.sessions() as db:
            self.assertTrue(process_one_capture(db,classify=self.classify,extract=correct))
        self.db.expire_all()
        self.assertIsNotNone(self.db.get(GroupRecallCard,old_id).parts_json)
        latest=self.db.query(func.max(GroupRecallCard.id)).scalar()
        old_view=unified_memories(self.a,2,ceiling,['纸条','北风'],self.db,{},facts=True)
        self.assertIn('我看过纸条。',str(old_view))
        new_view=unified_memories(self.a,3,latest,['纸条','北风'],self.db,{},facts=True)
        self.assertNotIn('我看过纸条。',str(new_view))
        self.assertIn('北风47',str(new_view))
        self.assertIn('我没见过纸条',str(new_view))
        self.assertEqual([],unified_memories(self.b,3,latest,['纸条'],self.db,{},facts=True))
        # 旧策略继续只读旧格式原文；不在升级时改写既有候选。
        self.assertIn(old,str(unified_memories(self.a,3,latest,['纸条'],self.db,{},facts=False)))

    def test_request_only_classification_cannot_write_a_completed_fact(self):
        self.prepare('请明天把表送出去。')
        def classify(sources,correction=None):
            return {'units':[{'ref':r['ref'],'segments':[{'start':0,'end':len(r['text']),'kind':'request'}]} for r in sources]}
        def unexpected(evidence):
            self.fail('纯请求不应进入事实提取')
        with self.sessions() as db:
            process_one_capture(db,classify=classify,extract=unexpected)
        self.db.expire_all()
        self.assertEqual('[]',self.db.query(GroupMemoryCapture).one().cards_json)

    def test_classification_rejects_gaps_duplicates_and_foreign_refs(self):
        sources=[dict(ref='1:0',text='😀事实。请求。',speaker_id=None,speaker='用户',kind='request')]
        for units in ([{'ref':'foreign','segments':[]}],
                      [{'ref':'1:0','segments':[{'start':1,'end':7,'kind':'statement'}]}],
                      [{'ref':'1:0','segments':[{'start':0,'end':1,'kind':'statement'}]}]):
            with self.subTest(units=units),self.assertRaises(ValueError):
                classified_records(sources,{'units':units},1)

    def test_statement_cannot_become_observed_fact_and_other_person_cannot_retract_it(self):
        record=dict(ref='1:0',text='我没见过。',speaker_id=2,speaker='乙',kind='speech',allowed_targets=['self'])
        evidence={'schema_version':2,'records':[record],'prior_facts':[dict(id=4,source_content='我见过。',parts_frozen=True,
            fact_fragments=[{'start':0,'end':5}],claim_kind='statement',source_known=True,source_speaker=1)]}
        card=dict(content='我没见过。',memory_type='fact',temporal_status='current',ref='1:0',quote='我没见过。',claim_kind='observed')
        value={'cards':[card],'insights':[],'partitions':[],'unmatched_corrections':[]}
        with self.assertRaisesRegex(ValueError,'升级'):
            _validated_cards(value,evidence)
        card.update(claim_kind='statement',replaces_part={'card_id':4,'start':0,'end':5,'mode':'retract'})
        with self.assertRaisesRegex(ValueError,'原说话人'):
            _validated_cards(value,evidence)

    def test_explicit_correction_requires_relation_or_diagnostic(self):
        record=dict(ref='1:0',text='我刚才说错了。',speaker_id=1,speaker='甲',kind='speech',
                    correction=True,allowed_targets=['self'])
        evidence={'schema_version':2,'records':[record],'prior_facts':[]}
        value={'cards':[],'insights':[],'partitions':[],'unmatched_corrections':[]}
        with self.assertRaisesRegex(ValueError,'更正'):
            _validated_cards(value,evidence)
        value['unmatched_corrections']=[{'ref':'1:0','reason':'no_target'}]
        with self.assertRaisesRegex(ValueError,'保留来源卡'):
            _validated_cards(value,evidence)
        value['cards']=[dict(content='甲承认刚才说错。', memory_type='fact',temporal_status='current',
            ref='1:0',quote=record['text'],claim_kind='statement')]
        self.assertEqual(1,len(_validated_cards(value,evidence)))
        value['unmatched_corrections'][0]['ref']='foreign'
        with self.assertRaises(ValueError):
            _validated_cards(value,evidence)

    def test_three_validation_attempts_then_no_partial_write(self):
        self.prepare('我刚才说错了。')
        calls=[]
        def classify(sources,correction=None):
            return {'units':[{'ref':r['ref'],'segments':[{'text':r['text'],'kind':'correction'}]} for r in sources]}
        def extract(evidence,correction=None):
            calls.append(correction)
            return {'cards':[],'insights':[],'partitions':[],'unmatched_corrections':[]}
        with self.sessions() as db:
            process_one_capture(db,classify=classify,extract=extract)
        self.db.expire_all()
        job=self.db.query(GroupMemoryCapture).one()
        self.assertEqual(3,len(calls))
        self.assertIsNone(job.cards_json)
        self.assertEqual('extraction_failed',job.error_code)

    def test_unmatched_correction_saved_with_diagnostic(self):
        self.prepare('我刚才说错了。')
        def classify(sources,correction=None):
            return {'units':[{'ref':r['ref'],'segments':[{'text':r['text'],'kind':'correction'}]} for r in sources]}
        def extract(evidence):
            source=evidence['records'][0]
            return {'cards':[dict(content='用户承认刚才说错。',memory_type='fact',temporal_status='current',
                ref=source['ref'],quote=source['text'],claim_kind='statement')],'insights':[],'partitions':[],'unmatched_corrections':[
                {'ref':evidence['records'][0]['ref'],'reason':'no_target'}]}
        with self.sessions() as db:
            process_one_capture(db,classify=classify,extract=extract)
        self.db.expire_all()
        self.assertEqual('correction_unmatched',self.db.query(GroupMemoryCapture).one().error_code)

    def test_dispute_keeps_original_and_does_not_affect_other_speaker(self):
        from services.memory.group_memory_facts import effective_facts
        def row(id_,speaker,round_,revision=None):
            return dict(id=id_,content='我见过纸条。',parts_json=None,claim_kind='statement',
                source_speaker=speaker,source_known=True,source_name=str(speaker),memory_type='fact',
                temporal_status='current',temporal_note=None,round_index=round_,revision_json=json.dumps(revision))
        target=row(1,1,1)
        peer=row(2,2,1)
        revision={'card_id':1,'start':0,'end':len(target['content']),'mode':'dispute'}
        new=row(3,None,2,revision)
        result=effective_facts([target,peer,new])
        self.assertTrue(result[0]['fact_fragments'][0]['disputed'])
        self.assertFalse(result[1]['fact_fragments'][0]['disputed'])
        new['revision_json']=json.dumps({**revision,'mode':'retract'})
        self.assertEqual([2,3],[r['id'] for r in effective_facts([target,peer,new])])

    def test_adjacent_corrections_merge_but_requests_stay_excluded(self):
        sources=[dict(ref='1:0',text='是我错了。我没见过。请别猜。',speaker_id=1,speaker='甲',kind='speech')]
        result=classified_records(sources,{'units':[{'ref':'1:0','segments':[
            {'text':'是我错了。','kind':'correction'},{'text':'我没见过。','kind':'correction'},
            {'text':'请别猜。','kind':'request'}]}]},1)
        self.assertEqual(1,len(result))
        self.assertEqual('是我错了。我没见过。',result[0]['text'])
        self.assertTrue(result[0]['correction'])

    def test_foreign_statement_correct_is_restricted_to_dispute(self):
        from services.memory.group_memory_facts import validate_revision
        prior=dict(id=4,source_content='甲见过。',parts_frozen=True,fact_fragments=[{'start':0,'end':4}],
                   claim_kind='statement',source_known=True,source_speaker=1)
        result=validate_revision({'card_id':4,'start':0,'end':4,'mode':'correct'},
            {'claim_kind':'statement'},{'speaker_id':2},{'prior_facts':[prior]}, {})
        self.assertEqual('dispute',result['mode'])

    def test_independent_review_recovers_correction_inside_whole_request_and_preserves_it_without_target(self):
        request='先去拿灯，还有，'
        corrected='昨天修好的是门锁，不是窗户。'
        self.prepare(request+corrected)
        seen=[]
        def classify(sources,correction=None):
            return {'units':[{'ref':r['ref'],'segments':[{'text':r['text'],'kind':'request'}]} for r in sources]}
        def review(sources,classified,correction=None):
            self.assertEqual('request',classified['units'][0]['segments'][0]['kind'])
            self.assertEqual(request+corrected,sources[0]['text'])
            return {'units':[{'ref':sources[0]['ref'],'segments':[
                {'text':request,'kind':'request'},{'text':corrected,'kind':'correction'}]}]}
        def extract(evidence):
            seen.extend(evidence['records'])
            source=evidence['records'][0]
            return {'cards':[dict(content='用户更正昨天修好的是门锁而非窗户。', memory_type='fact',
                temporal_status='historical',ref=source['ref'],quote=corrected,claim_kind='statement')],
                'insights':[],'partitions':[], 'unmatched_corrections':[{'ref':source['ref'],'reason':'no_target'}]}
        with self.sessions() as db:
            self.assertTrue(process_one_capture(db,classify=classify,review=review,extract=extract))
        self.assertEqual([corrected],[record['text'] for record in seen])
        self.db.expire_all()
        job=self.db.query(GroupMemoryCapture).one()
        self.assertEqual('correction_unmatched',job.error_code)
        self.assertIn('门锁',job.cards_json)
        self.assertEqual({self.a},{row.persona_id for row in self.db.query(GroupMemoryCapture)})

    def test_bad_review_retries_with_same_visible_sources_and_never_saves_partial_memory(self):
        self.prepare('我刚才说错了，是门锁。请确认。')
        seen=[]
        def classify(sources,correction=None):
            return {'units':[{'ref':r['ref'],'segments':[{'text':r['text'],'kind':'correction'}]} for r in sources]}
        def review(sources,classified,correction=None):
            seen.append((sources,correction))
            return {'units':[{'ref':r['ref'],'segments':[{'text':r['text'],'kind':'request'}]} for r in sources]}
        def extract(evidence):
            self.fail('更正被复核丢弃时不应继续提取')
        with self.sessions() as db:
            process_one_capture(db,classify=classify,review=review,extract=extract)
        self.assertEqual(2,len(seen))
        self.assertEqual(seen[0][0],seen[1][0])
        self.assertIn('不得静默丢弃',seen[1][1][1])
        self.db.expire_all()
        job=self.db.query(GroupMemoryCapture).one()
        self.assertIsNone(job.cards_json)
        self.assertEqual('extraction_failed',job.error_code)

    def test_review_rejects_foreign_ref_and_pure_request_still_has_no_fact(self):
        sources=[dict(ref='1:0',text='请明天修门锁。',speaker_id=None,speaker='用户',kind='request')]
        evidence=lambda:dict(persona_id=1,user_sources=sources,records=[])
        classify=lambda sources: {'units':[{'ref':'1:0','segments':[{'text':sources[0]['text'],'kind':'request'}]}]}
        review=lambda sources,classified: classified
        self.assertEqual([],prepare_assertions(evidence(),classify,review)['records'])
        def foreign(sources,classified,correction=None):
            return {'units':[{'ref':'hidden','segments':[{'text':'秘密','kind':'correction'}]}]}
        with self.assertRaises(ValueError):
            prepare_assertions(evidence(),classify,foreign)

    def test_correction_search_can_include_more_than_three_old_facts_without_widening_owner_or_turn(self):
        self.prepare('请确认门锁。')
        self.db.query(GroupMemoryCapture).one().cards_json=json.dumps([
            dict(content=f'门锁记录编号{i}',memory_type='fact',temporal_status='current',ref='1:0',quote='门锁') for i in range(6)])
        self.db.commit()
        ceiling=self.db.query(func.max(GroupRecallCard.id)).scalar()
        from services.memory.group_memory_capture import _evidence
        target=self.prepare('昨天修好的是门锁，不是窗户。')
        job=self.db.query(GroupMemoryCapture).filter_by(candidate_id=target['candidate_id']).one()
        evidence=_evidence(job,self.db,raw=True)
        self.assertEqual(6,len([row for row in evidence['prior_facts'] if '门锁记录' in row['content']]))
        self.assertEqual([],unified_memories(self.b,3,ceiling,['门锁'],self.db,{},facts=True,limit=12))
        self.assertEqual([],unified_memories(self.a,1,ceiling,['门锁'],self.db,{},facts=True,limit=12))
