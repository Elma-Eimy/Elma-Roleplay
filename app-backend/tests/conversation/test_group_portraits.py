"""成员立绘归属、候选冻结、版本竞争及撤回恢复；只用临时库。"""
import asyncio
import json
from dataclasses import replace
import unittest
from unittest.mock import patch

from core.models import CharacterPortrait, GroupRoundCandidate, SessionPersona
from core.locking import get_session_lock
from services.media.group_portraits import update_group_portrait
from services.media.character_portraits import delete_portrait
from services.conversation import group_query_service as queries
from services.conversation.group_session_service import GroupSessionValidationError
from services.conversation.session_access import SessionKindConflict
from tests.conversation import test_group_operations as fixtures


class GroupPortraitTests(unittest.TestCase):
    group = fixtures.GroupOperationTests.group
    command = fixtures.GroupOperationTests.command
    calls = fixtures.GroupOperationTests.calls
    settle = fixtures.GroupOperationTests.settle

    def setUp(self):
        fixtures.GroupOperationTests.setUp(self)
        self.db.add_all([CharacterPortrait(id=1001, character_id=1, name='A1', image_path='a1.png'),
                         CharacterPortrait(id=1002, character_id=1, name='A2', image_path='a2.png'),
                         CharacterPortrait(id=2001, character_id=2, name='B', image_path='b.png')])
        self.db.commit()
        self.sid, self.ids = self.group()

    def view(self):
        return queries.get_group_portraits(self.sid, self.db)

    def choose(self, portrait_id, member=None, expected=None):
        if expected is None:
            state = self.view()['current']
            latest = state['latest'] or {}
            expected = (state['group_revision'], latest.get('round_id'), latest.get('candidate_id'), latest.get('candidate_revision'))
        return asyncio.run(update_group_portrait(self.sid, member or self.ids[0], portrait_id, expected, self.db))

    def chosen(self):
        return {row['persona_id']: row['portrait_id'] for row in self.view()['members']}

    def test_initial_selection_freezes_on_send_without_mutating_origin(self):
        original = self.db.get(SessionPersona, self.ids[0]).group_origin.initial_state_json
        self.choose(1001)
        self.assertEqual({self.ids[0]: 1001, self.ids[1]: None}, self.chosen())
        with self.assertRaises(SessionKindConflict):
            self.choose(1002, expected=(0, None, None, None))
        with self.assertRaises(GroupSessionValidationError):
            self.choose(2001)
        result = self.command(self.sid)
        candidate = self.db.get(GroupRoundCandidate, result['accepted']['candidate_id'])
        self.assertEqual(1001, json.loads(candidate.portrait_selections_json)[str(self.ids[0])])
        self.assertEqual(original, self.db.get(SessionPersona, self.ids[0]).group_origin.initial_state_json)
        self.assertFalse(self.view()['can_update'])
        with self.assertRaises(SessionKindConflict):
            self.choose(None)

    def test_sibling_switch_failure_and_resume_keep_independent_portraits(self):
        first = self.command(self.sid)
        self.settle(first)
        self.choose(1001)
        first_id = first['accepted']['candidate_id']
        second = self.command(self.sid, kind='regenerate', call_snapshot=replace(self.calls(self.ids), shared_chat=True))
        self.settle(second)
        second_id = second['accepted']['candidate_id']
        self.command(self.sid, kind='select', target_candidate_id=second_id,
                     target_candidate_revision=self.db.get(GroupRoundCandidate, second_id).revision)
        self.choose(1002)
        self.assertEqual(1002, self.chosen()[self.ids[0]])
        self.command(self.sid, kind='select', target_candidate_id=first_id,
                     target_candidate_revision=self.db.get(GroupRoundCandidate, first_id).revision)
        self.assertEqual(1001, self.chosen()[self.ids[0]])
        preview = queries.get_group_candidate(self.sid, first['accepted']['round_id'], second_id, self.db)
        self.assertEqual(1002, preview['state_preview']['members'][0]['portrait']['portrait_id'])
        failed = self.command(self.sid, kind='regenerate', call_snapshot=replace(self.calls(self.ids), shared_chat=True))
        self.settle(failed, False)
        self.assertEqual(1001, self.chosen()[self.ids[0]])
        failed_id = failed['accepted']['candidate_id']
        before = self.db.get(GroupRoundCandidate, failed_id).portrait_selections_json
        resumed = self.command(self.sid, kind='resume', target_candidate_id=failed_id,
                               target_candidate_revision=self.db.get(GroupRoundCandidate, failed_id).revision)
        self.assertEqual(before, self.db.get(GroupRoundCandidate, resumed['accepted']['candidate_id']).portrait_selections_json)

    def test_discard_restores_previous_confirmed_selection_and_cannot_modify_it(self):
        first = self.command(self.sid)
        self.settle(first)
        self.choose(1001)
        second = self.command(self.sid)
        self.settle(second)
        self.choose(1002)
        self.command(self.sid, kind='discard')
        self.assertEqual(1001, self.chosen()[self.ids[0]])
        self.assertFalse(self.view()['can_update'])
        with self.assertRaises(SessionKindConflict):
            self.choose(None)

    def test_deleted_and_legacy_portraits_fall_back_without_rewriting_snapshot(self):
        self.choose(1001)
        first = self.command(self.sid)
        self.settle(first)
        candidate_id = first['accepted']['candidate_id']
        frozen = self.db.get(GroupRoundCandidate, candidate_id).portrait_selections_json
        self.db.get(GroupRoundCandidate, candidate_id).portrait_selections_json = None
        self.db.commit()
        self.assertIsNone(self.chosen()[self.ids[0]])
        self.db.get(GroupRoundCandidate, candidate_id).portrait_selections_json = frozen
        self.db.commit()
        delete_portrait(1, 1001, self.db)
        self.assertIsNone(self.chosen()[self.ids[0]])
        self.assertEqual(frozen, self.db.get(GroupRoundCandidate, candidate_id).portrait_selections_json)
        candidate = self.db.get(GroupRoundCandidate, candidate_id)
        candidate.portrait_selections_json = None
        self.db.commit()
        self.assertIsNone(self.chosen()[self.ids[0]])
        self.assertEqual(1001, self.db.get(SessionPersona, self.ids[0]).portrait_base)

    def test_foreign_members_failed_commit_and_session_lock_do_not_change_selection(self):
        other, ids = self.group()
        with self.assertRaises(LookupError):
            self.choose(1001, member=ids[0])
        state = self.view()
        with patch.object(self.db, 'commit', side_effect=RuntimeError('commit failed')):
            with self.assertRaises(RuntimeError):
                self.choose(1001)
        self.assertEqual(state, self.view())
        async def busy():
            lock = get_session_lock(self.sid)
            await lock.acquire()
            try:
                with self.assertRaises(SessionKindConflict):
                    await update_group_portrait(self.sid, self.ids[0], 1001, (0, None, None, None), self.db)
            finally:
                lock.release()
        asyncio.run(busy())
        self.assertIsNone(self.chosen()[self.ids[0]])

    def test_pending_caller_changes_are_rejected_without_implicit_flush(self):
        member = self.db.get(SessionPersona, self.ids[0])
        member.current_mood = '尚未提交的编辑'
        with self.assertRaises(GroupSessionValidationError):
            asyncio.run(update_group_portrait(self.sid, self.ids[0], 1001, (0, None, None, None), self.db))
        self.assertIn(member, self.db.dirty)
        self.assertEqual('尚未提交的编辑', member.current_mood)
        self.db.rollback()
        self.assertIsNone(self.chosen()[self.ids[0]])
