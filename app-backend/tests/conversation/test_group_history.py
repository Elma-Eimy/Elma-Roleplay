"""群聊个人历史、候选隔离和内容原子写入；仅使用临时库。"""
import asyncio
from dataclasses import FrozenInstanceError
from datetime import datetime
import unittest
from unittest.mock import patch

from sqlalchemy import text

from core.locking import get_session_lock, is_session_locked
from core.models import (GroupRound, GroupRoundCandidate, GroupContentItem, GroupContentVisibility,
                         ChatMessage, MessageRole, MemoryExtractionJob, Character)
from services.conversation import group_history_service as history
from services.conversation import group_session_service as groups
from services.conversation.session_access import SessionKindConflict
from tests.conversation import test_group_session_service as fixtures


class GroupHistoryTests(unittest.TestCase):
    setUp = fixtures.GroupSessionServiceTests.setUp
    snapshot = fixtures.GroupSessionServiceTests.snapshot

    def group(self):
        result = asyncio.run(groups.create_group_session(self.cards, self.db))
        return result["session_id"], tuple(member["persona_id"] for member in result["members"])

    def prepare(self, sid, visible, content="  用户原话 {{char}} <tag>  "):
        return asyncio.run(history.prepare_group_round(sid, content, visible, self.db))

    def append(self, sid, target, speaker, content, visible=()):
        result = asyncio.run(history.append_group_utterance(sid, target["candidate_id"], speaker,
            content, visible, target["revision"], self.db))
        target["revision"] = result["revision"]
        return result

    def read(self, sid, pid, target, before=100, **kwargs):
        return history.get_member_history(sid, pid, target["candidate_id"], before, self.db, **kwargs)

    def test_round_keeps_original_user_once_and_one_pending_round(self):
        sid, (a, b) = self.group()
        target = self.prepare(sid, (a,))
        items = self.db.query(GroupContentItem).all()
        self.assertEqual(1, len(items))
        self.assertIsNone(items[0].content)
        self.assertEqual([(a, "visible"), (b, "hidden")],
            [(v.recipient_persona_id, v.decision) for v in self.db.query(GroupContentVisibility).order_by(GroupContentVisibility.recipient_persona_id)])
        self.assertEqual("  用户原话 {{char}} <tag>  ", self.read(sid, a, target)[0].content)
        self.assertEqual((), self.read(sid, b, target))
        with self.assertRaises(SessionKindConflict):
            self.prepare(sid, (a, b))
        self.assertEqual(1, self.db.query(GroupRound).count())
        self.assertEqual(4, self.db.query(ChatMessage).count())
        self.assertEqual(0, self.db.query(MemoryExtractionJob).count())

    def test_visible_before_limit_and_current_sequence_keep_silent_listener(self):
        sid, (a, b) = self.group()
        target = self.prepare(sid, (a,), "secret")
        self.append(sid, target, a, "public retelling", (b,))
        self.append(sid, target, a, "private A")
        self.append(sid, target, a, "more private A")
        self.assertEqual(["public retelling"], [r.content for r in self.read(sid, b, target, limit=1)])
        self.assertEqual((), self.read(sid, b, target, before=1))
        self.assertEqual(["secret", "public retelling"], [r.content for r in self.read(sid, a, target, before=2)])
        self.append(sid, target, b, "B responds", (a,))
        self.append(sid, target, a, "A again", (b,))
        rows = self.read(sid, a, target)
        self.assertEqual([0, 1, 2, 3, 4, 5], [r.sequence for r in rows])
        self.assertEqual([a, a, a, b, a], [r.speaker_persona_id for r in rows[1:]])
        with self.assertRaises(FrozenInstanceError):
            rows[0].content = "changed"
        self.assertFalse(hasattr(rows[-1], "role_state_patch"))

    def test_only_earlier_confirmed_selected_successful_candidates_are_history(self):
        sid, (a, b) = self.group()
        first = self.prepare(sid, (a, b), "first user")
        self.append(sid, first, a, "chosen", (b,))
        asyncio.run(history.finish_group_round(sid, first["candidate_id"], first["revision"], self.db))
        round_ = self.db.get(GroupRound, first["round_id"])
        round_.confirmed_at = datetime.utcnow()
        sibling = GroupRoundCandidate(round_id=round_.id, session_id=sid, version=2, status="awaiting_confirmation")
        self.db.add(sibling)
        self.db.flush()
        item = GroupContentItem(candidate_id=sibling.id, session_id=sid, sequence=1, kind="utterance", speaker_persona_id=a, content="wrong sibling")
        self.db.add(item)
        self.db.flush()
        self.db.add(GroupContentVisibility(item_id=item.id, session_id=sid, recipient_persona_id=b, decision="visible"))
        self.db.commit()
        current = self.prepare(sid, (a,), "current private")
        self.assertEqual(["first user", "chosen"], [r.content for r in self.read(sid, b, current)])
        # 不向过去候选开放当前或未来轮次；已确认候选也不能作为执行目标。
        with self.assertRaises(SessionKindConflict):
            self.read(sid, a, first)
        self.db.get(GroupRoundCandidate, first["candidate_id"]).status = "failed"
        self.db.commit()
        self.assertEqual((), self.read(sid, b, current))

    def test_foreign_members_candidates_and_single_targets_reject_without_writes(self):
        sid, (a, b) = self.group()
        other, (c, d) = self.group()
        target = self.prepare(sid, (a,))
        foreign = self.prepare(other, (c,))
        baseline = self.snapshot()
        actions = [lambda: self.prepare(sid, (c,)),
            lambda: self.append(sid, target, c, "wrong"),
            lambda: self.append(sid, target, a, "wrong recipient", (c,)),
            lambda: self.read(sid, c, target), lambda: self.read(sid, a, foreign),
            lambda: self.prepare(10, (100,)), lambda: self.read(10, 100, target)]
        for action in actions:
            with self.subTest(action=action):
                with self.assertRaises((groups.GroupSessionValidationError, groups.GroupSessionNotFound, SessionKindConflict)):
                    action()
                self.assertEqual(baseline, self.snapshot())
                self.assertFalse(is_session_locked(sid))

    def test_missing_visibility_is_hidden_and_reported_without_personal_metadata(self):
        sid, (a, b) = self.group()
        target = self.prepare(sid, (a, b), "secret")
        self.db.query(GroupContentVisibility).filter_by(recipient_persona_id=b).delete()
        self.db.commit()
        with self.assertLogs(history.logger, level="WARNING") as logged:
            rows = self.read(sid, b, target)
        self.assertEqual((), rows)
        self.assertNotIn("secret", " ".join(logged.output))
        self.assertEqual("secret", self.read(sid, a, target)[0].content)

    def test_visibility_and_commit_failures_rollback_content_revision_and_round(self):
        sid, (a, b) = self.group()
        baseline = self.snapshot()
        with patch.object(history, "_visibility", side_effect=RuntimeError("visibility failed")):
            with self.assertRaisesRegex(RuntimeError, "visibility failed"):
                self.prepare(sid, (a,))
        self.assertEqual(baseline, self.snapshot())
        target = self.prepare(sid, (a,))
        baseline = self.snapshot()
        with patch.object(history, "_visibility", side_effect=RuntimeError("visibility failed")):
            with self.assertRaises(RuntimeError):
                self.append(sid, target, a, "failed")
        with patch.object(self.db, "commit", side_effect=RuntimeError("commit failed")):
            with self.assertRaises(RuntimeError):
                self.append(sid, target, a, "failed commit")
        self.assertEqual(baseline, self.snapshot())
        self.assertFalse(is_session_locked(sid))

    def test_stale_revision_and_finished_or_failed_round_cannot_append_or_restart(self):
        for failed in (False, True):
            sid, (a, b) = self.group()
            target = self.prepare(sid, (a,))
            old_revision = target["revision"]
            self.append(sid, target, a, "saved")
            with self.assertRaises(SessionKindConflict):
                asyncio.run(history.append_group_utterance(sid, target["candidate_id"], a, "late", (), old_revision, self.db))
            asyncio.run(history.finish_group_round(sid, target["candidate_id"], target["revision"], self.db, failed=failed))
            with self.assertRaises(SessionKindConflict):
                self.append(sid, target, a, "late")
            with self.assertRaises(SessionKindConflict):
                self.prepare(sid, (a,))
            if failed:
                with self.assertRaises(SessionKindConflict):
                    self.read(sid, a, target)
            else:
                self.assertEqual(2, len(self.read(sid, a, target)))

    def test_busy_session_and_invalid_limits_or_visibility_leave_no_partial_data(self):
        sid, (a, b) = self.group()
        async def busy():
            lock = get_session_lock(sid)
            await lock.acquire()
            try:
                with self.assertRaises(SessionKindConflict):
                    await history.prepare_group_round(sid, "text", (a,), self.db)
            finally:
                lock.release()
        asyncio.run(busy())
        for visible in ([a], (True,), (a, a), (9999,)):
            with self.assertRaises(groups.GroupSessionValidationError):
                self.prepare(sid, visible)
        self.assertEqual(0, self.db.query(GroupRound).count())
        target = self.prepare(sid, (a,))
        for limit in (0, True, 501):
            with self.assertRaises(groups.GroupSessionValidationError):
                self.read(sid, a, target, limit=limit)
        with self.assertRaises(groups.GroupSessionValidationError):
            self.read(sid, a, target, before=-1)

    def test_group_delete_cascades_cycle_and_outbox_failure_preserves_all_rows(self):
        sid, (a, b) = self.group()
        target = self.prepare(sid, (a, b))
        self.append(sid, target, a, "saved", (b,))
        self.db.add(ChatMessage(session_id=sid, role=MessageRole.assistant, content="audio", audio_path="fixture.mp3"))
        self.db.commit()
        baseline = self.snapshot()
        with patch.object(groups, "OutboxJob", side_effect=RuntimeError("outbox failed")):
            with self.assertRaises(RuntimeError):
                asyncio.run(groups.delete_group_session(sid, self.db))
        self.assertEqual(baseline, self.snapshot())
        asyncio.run(groups.delete_group_session(sid, self.db))
        for model in (GroupRound, GroupRoundCandidate, GroupContentItem, GroupContentVisibility):
            self.assertEqual(0, self.db.query(model).count())
        self.assertEqual([], self.db.execute(text("PRAGMA foreign_key_check")).all())

    def test_pending_caller_changes_are_rejected_without_flushing_or_rolling_back(self):
        sid, (a, b) = self.group()
        target = self.prepare(sid, (a,))
        actions = [lambda: self.prepare(sid, (a,)),
            lambda: self.append(sid, target, a, "reply"),
            lambda: asyncio.run(history.finish_group_round(sid, target["candidate_id"], 1, self.db)),
            lambda: self.read(sid, a, target)]
        for autoflush in (False, True):
            self.db.autoflush = autoflush
            for action in actions:
                with self.subTest(autoflush=autoflush, action=action):
                    actor = self.db.get(Character, 1)
                    actor.name = "pending caller edit"
                    try:
                        with self.assertRaises(groups.GroupSessionValidationError):
                            action()
                        self.assertEqual("pending caller edit", actor.name)
                        self.assertIn(actor, self.db.dirty)
                    finally:
                        self.db.rollback()

    def test_flushed_caller_transaction_is_rejected_without_losing_its_writes(self):
        sid, (a, b) = self.group()
        target = self.prepare(sid, (a,))
        actions = [lambda: self.prepare(sid, (a,)),
            lambda: self.append(sid, target, a, "reply"),
            lambda: asyncio.run(history.finish_group_round(sid, target["candidate_id"], 1, self.db)),
            lambda: self.read(sid, a, target)]
        for action in actions:
            with self.subTest(action=action):
                actor = self.db.get(Character, 1)
                actor.name = "flushed caller edit"
                self.db.flush()
                try:
                    with self.assertRaises(groups.GroupSessionValidationError):
                        action()
                    self.db.expire(actor)
                    self.assertEqual("flushed caller edit", actor.name)
                finally:
                    self.db.rollback()
