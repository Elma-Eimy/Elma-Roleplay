"""公开开场冻结、混合来源和模型输入；不调用真实模型。"""
import json
import unittest
from dataclasses import replace

from core.models import Character, Session, GroupRound, GroupRoundOperation
from schemas import GroupSessionCreate
from services.conversation import group_session_service as service
from services.conversation import group_director_service as director
from tests.conversation import test_group_session_service as fixtures
from tests.conversation import test_group_generation as generation_fixtures


class GroupGreetingTests(unittest.TestCase):
    setUp = fixtures.GroupSessionServiceTests.setUp
    create = fixtures.GroupSessionServiceTests.create

    def test_mixed_origins_freeze_only_card_openings_and_do_not_start_rounds(self):
        card = self.db.get(Character, 2)
        card.first_mes = '{{char}} greets {{user}}'
        self.db.commit()
        result = self.create(replace(self.imported, user_nickname='visitor'))
        self.assertEqual([None, 'actor2 greets visitor'], [m['greeting_content'] for m in result['members']])
        card.first_mes = 'CHANGED'
        self.db.commit()
        self.db.expire_all()
        loaded = service.get_group_session_detail(result['session_id'], self.db)
        self.assertEqual(result['members'], loaded['members'])
        self.assertEqual(0, self.db.query(GroupRound).count())
        self.assertEqual(0, self.db.query(GroupRoundOperation).count())

    def test_alternate_index_preserves_empty_slots_editing_and_skip(self):
        self.db.get(Character, 1).extensions = json.dumps({'alternate_greetings': ['', 'ALT {{char}}']})
        self.db.commit()
        for index, override, expected in [(1, None, 'ALT actor1'), (0, None, None), (1, 'EDIT {{user}}', 'EDIT 用户'), (None, '', None)]:
            with self.subTest(index=index, override=override):
                draft = replace(self.cards, members=(service.GroupMember(1, greeting_index=index, greeting_content=override), service.GroupMember(2)))
                self.assertEqual(expected, self.create(draft)['members'][0]['greeting_content'])

    def test_invalid_openings_reject_atomically_in_schema_and_service(self):
        for member in (service.GroupMember(1, greeting_index=99), service.GroupMember(1, 'single_snapshot', 10, greeting_content='bad'),
                       service.GroupMember(1, greeting_content='x' * 20001), service.GroupMember(1, greeting_index=True)):
            with self.subTest(member=member), self.assertRaises(service.GroupSessionValidationError):
                self.create(replace(self.cards, members=(member, service.GroupMember(2))))
            self.assertEqual(0, self.db.query(Session).filter_by(kind='group').count())
        with self.assertRaises(ValueError):
            GroupSessionCreate.model_validate({'members': [{'character_id': 1, 'origin': {'mode': 'single_snapshot', 'session_id': 10}, 'greeting_content': ''},
                                                          {'character_id': 2, 'origin': {'mode': 'card'}}]})


class GreetingContextTests(unittest.TestCase):
    setUp = fixtures.GroupSessionServiceTests.setUp
    group = generation_fixtures.GroupGenerationTests.group
    context = generation_fixtures.GroupGenerationTests.context

    def test_both_members_and_director_read_frozen_public_greeting_without_card_leak(self):
        self.db.get(Character, 2).first_mes = 'PUBLIC_OPENING {{char}}'
        self.db.commit()
        self.group(visible='both')
        self.db.get(Character, 2).first_mes = 'LATER_OPENING'
        self.db.commit()
        for persona in (self.a, self.b):
            context = self.context(persona)
            self.assertIn('PUBLIC_OPENING actor2', context.messages_json)
            self.assertNotIn('LATER_OPENING', context.messages_json)
            self.assertNotIn('B_PRIVATE_CARD' if persona == self.a else 'A_PRIVATE_CARD', context.messages_json)
        payload = json.loads(director.build_director_context(self.sid, self.db, candidate_id=self.target['candidate_id'],
                            expected_revision=self.target['revision']).payload_json)
        self.assertEqual([{'persona_id': self.b, 'speaker_name': 'actor2', 'content': 'PUBLIC_OPENING actor2'}], payload['greetings'])
