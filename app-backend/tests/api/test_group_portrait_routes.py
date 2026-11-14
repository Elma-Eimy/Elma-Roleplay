"""群聊立绘的请求校验、资源归属和版本冲突。"""
import unittest
from core.models import CharacterPortrait
from tests.api import test_group_session_routes as fixtures


class GroupPortraitRoutesTests(unittest.TestCase):
    setUp = fixtures.GroupSessionRoutesTests.setUp

    def test_selection_roundtrip_and_resource_version_guards(self):
        self.db.add_all([CharacterPortrait(id=1001, character_id=1, name='A', image_path='a.png'),
                         CharacterPortrait(id=2001, character_id=2, name='B', image_path='b.png')])
        self.db.commit()
        group = self.client.post('/group-sessions', json=self.payload).json()
        sid, pid = group['session_id'], group['members'][0]['persona_id']
        path = f'/group-sessions/{sid}/members/{pid}/portrait'
        body = {'portrait_id': 1001, 'expected_group_revision': 0}
        response = self.client.put(path, json=body)
        self.assertEqual(200, response.status_code, response.text)
        result = self.client.get(f'/group-sessions/{sid}/portraits').json()
        self.assertEqual(1001, result['members'][0]['portrait_id'])
        self.assertEqual(1, result['current']['group_revision'])
        self.assertEqual(409, self.client.put(path, json=body).status_code)
        body['expected_group_revision'] = 1
        for invalid in (True, 0, 2001):
            self.assertEqual(422, self.client.put(path, json={**body, 'portrait_id': invalid}).status_code)
        self.assertEqual(422, self.client.put(path, json={**body, 'unknown': True}).status_code)
        self.assertEqual(422, self.client.put(path, json={**body, 'observed_round_id': 9}).status_code)
        self.assertEqual(200, self.client.put(path, json={**body, 'portrait_id': None}).status_code)
        self.assertIsNone(self.client.get(f'/group-sessions/{sid}/portraits').json()['members'][0]['portrait_id'])
        self.assertEqual(409, self.client.get('/group-sessions/10/portraits').status_code)
        self.assertEqual(409, self.client.put('/group-sessions/10/members/100/portrait', json=body).status_code)
