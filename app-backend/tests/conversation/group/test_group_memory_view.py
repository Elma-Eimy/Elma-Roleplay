"""成员记忆浏览只读取本人已确认来源，不调用向量或模型。"""
import asyncio
import unittest
from fastapi.testclient import TestClient
from application.factory import create_app
from core.database import get_db
from services.conversation.group import query_service as query, session_service as groups
from tests.support.group import session_service as fixtures
from tests.support.group import memory_capture as capture


class GroupMemoryViewTests(unittest.TestCase):
    setUp = fixtures.GroupSessionFixture.setUp

    def test_inherited_snapshot_is_scoped_and_searchable_through_http(self):
        group = asyncio.run(groups.create_group_session(self.imported, self.db))
        sid = group['session_id']
        a, b = [member['persona_id'] for member in group['members']]
        app = create_app()
        app.dependency_overrides[get_db] = lambda: self.db
        with TestClient(app) as client:
            url = f'/group-sessions/{sid}/members/{a}/memories'
            response = client.get(url)
            self.assertEqual(200, response.status_code)
            rows = response.json()
            self.assertGreater(rows['total'], 0)
            self.assertNotIn('unconfirmed fact', str(rows))
            self.assertTrue(all(not row['is_local'] for row in rows['items']))
            text = rows['items'][0]['content']
            self.assertGreater(client.get(url, params={'q': text[:3], 'limit': 1}).json()['total'], 0)
            self.assertEqual(0, client.get(url, params={'scope': 'local'}).json()['total'])
            self.assertEqual(0, client.get(f'/group-sessions/{sid}/members/{b}/memories').json()['total'])
            self.assertEqual(409, client.get(f'/group-sessions/{sid}/members/100/memories').status_code)
            self.assertEqual(404, client.get(f'/group-sessions/{sid}/members/9999/memories').status_code)
            self.assertEqual(422, client.get(url, params={'limit': 0}).status_code)
            self.assertEqual(422, client.get(url, params={'scope': 'foreign'}).status_code)


class ConfirmedGroupMemoryViewTests(unittest.TestCase):
    setUp = capture.GroupCaptureFixture.setUp
    observed = capture.GroupCaptureFixture.observed
    submit = capture.GroupCaptureFixture.submit
    drain = capture.GroupCaptureFixture.drain
    confirm = capture.GroupCaptureFixture.confirm
    process = capture.GroupCaptureFixture.process

    def test_only_confirmed_member_evidence_enters_browser_and_pagination(self):
        self.confirm()
        def extract(evidence):
            record = evidence['records'][0]
            return {'insights': [], 'cards': [{'ref': record['ref'], 'quote': record['text'],
                'content': 'member-' + str(evidence['persona_id']), 'memory_type': 'fact', 'temporal_status': 'current'}]}
        self.assertTrue(self.process(extract))
        self.assertTrue(self.process(extract))
        a, b, c = self.ids
        rows = query.get_member_memories(self.sid, a, self.db)
        self.assertEqual(['member-' + str(a)], [row['content'] for row in rows['items']])
        self.assertTrue(rows['items'][0]['is_local'])
        self.assertEqual(1, rows['facets']['local_active'])
        self.assertEqual(0, query.get_member_memories(self.sid, c, self.db)['total'])
        self.assertEqual([], query.get_member_memories(self.sid, a, self.db, offset=1)['items'])
        self.assertEqual(0, query.get_member_memories(self.sid, a, self.db, q='member-' + str(b))['total'])
