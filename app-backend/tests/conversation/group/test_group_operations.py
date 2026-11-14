"""接受确认、持久幂等、选择版本与撤回边界；不调用真实模型。"""
from tests.support.group.operations import GroupOperationFixture
import asyncio
import json
from dataclasses import replace
from uuid import uuid4
from unittest.mock import patch
import unittest

from core.models import GroupRound, GroupRoundCandidate, GroupRoundOperation, Session, GroupContentItem, GroupContentVisibility
from services.conversation.group import operation_service as operations, history_service as history
from services.conversation.group import session_service as groups
from services.conversation.group.call_snapshot import persist_group_calls, capture_group_calls
from core.config import settings
from services.infrastructure.llm_provider import GroupModelConnection
from services.conversation.session_access import SessionKindConflict
from application.group_runtime import fail_interrupted_group_candidates, group_runtime
from core.locking import get_session_lock


class GroupOperationTests(GroupOperationFixture, unittest.TestCase):
    def test_send_draft_has_no_visibility_and_duplicate_precedes_version_and_snapshot(self):
        sid, ids = self.group()
        rid = str(uuid4())
        expected = (0, None, None, None)
        first = self.command(sid, request_id=rid, expected=expected)
        candidate = self.db.get(GroupRoundCandidate, first["accepted"]["candidate_id"])
        self.assertEqual("user_visibility", candidate.checkpoint)
        self.assertNotIn("never-persist", candidate.call_snapshot_json)
        self.assertNotIn("example.invalid", candidate.call_snapshot_json)
        self.assertEqual(0, self.db.query(GroupContentVisibility).count())
        self.assertEqual(1, self.db.query(GroupContentItem).count())
        with self.assertRaises(SessionKindConflict):
            asyncio.run(history.finish_group_round(sid, candidate.id, candidate.revision, self.db))
        self.settle(first, False)
        duplicate = self.command(sid, request_id=rid, expected=expected, call_snapshot=None)
        self.assertEqual("failed", duplicate["status"])
        self.assertEqual(first["accepted"], duplicate["accepted"])
        with self.assertRaises(SessionKindConflict):
            self.command(sid, request_id=rid, expected=expected, user_content="changed")
        self.assertEqual(1, self.db.query(GroupRoundOperation).count())

        async def replay_while_locked():
            async with get_session_lock(sid):
                return await operations.accept_group_operation(sid, rid, "send", 0, self.db,
                    user_content="  原文 {{char}} 😀  ")

        self.assertEqual(duplicate, asyncio.run(replay_while_locked()))

    def test_confirmation_and_new_acceptance_rollback_together_and_failure_does_not_unconfirm(self):
        sid, ids = self.group()
        first = self.command(sid)
        self.settle(first)
        rid = str(uuid4())
        with patch.object(self.db, "commit", side_effect=RuntimeError("commit failed")):
            with self.assertRaises(RuntimeError):
                self.command(sid, request_id=rid)
        original = self.db.get(GroupRound, first["accepted"]["round_id"])
        self.assertIsNone(original.confirmed_at)
        self.assertEqual(1, self.db.query(GroupRound).count())
        next_ = self.command(sid, request_id=rid)
        self.settle(next_, False)
        self.assertIsNotNone(self.db.get(GroupRound, original.id).confirmed_at)
        with self.assertRaises(SessionKindConflict):
            self.command(sid)

    def test_discard_hides_round_rejects_old_target_and_duplicate_never_revives(self):
        sid, ids = self.group()
        first = self.prepare(sid, ids, "discard secret")
        asyncio.run(history.finish_group_round(sid, first["candidate_id"], first["revision"], self.db, failed=True))
        request_id = str(uuid4())
        revision = self.db.get(Session, sid).group_revision
        expected = (revision, first["round_id"], first["candidate_id"], first["revision"] + 1)
        self.command(sid, "discard", request_id, expected)
        self.assertEqual(0, history.list_group_rounds(sid, self.db)["total"])
        with self.assertRaises(SessionKindConflict):
            history.get_member_history(sid, ids[0], first["candidate_id"], 10, self.db)
        next_ = self.prepare(sid, ids, "new user")
        self.assertEqual(2, self.db.get(GroupRound, next_["round_id"]).round_index)
        self.assertEqual(["new user"], [row.content for row in history.get_member_history(sid, ids[0], next_["candidate_id"], 10, self.db)])
        self.command(sid, "discard", request_id, expected)
        with self.assertRaises(SessionKindConflict):
            self.command(sid, "discard", expected=expected)
        self.assertEqual(2, self.db.query(GroupRound).count())

    def test_select_same_round_success_only_and_a_b_a_rejects_stale_revision(self):
        sid, ids = self.group()
        first = self.command(sid)
        self.settle(first)
        round_id = first["accepted"]["round_id"]
        a = first["accepted"]["candidate_id"]
        b = GroupRoundCandidate(session_id=sid, round_id=round_id, version=2, status="awaiting_confirmation")
        self.db.add(b)
        self.db.commit()
        expected = (self.db.get(Session, sid).group_revision, round_id, a, 1)
        self.command(sid, "select", expected=expected, target_candidate_id=b.id, target_candidate_revision=0)
        self.command(sid, "select", target_candidate_id=a, target_candidate_revision=1)
        with self.assertRaises(SessionKindConflict):
            self.command(sid, "select", expected=expected, target_candidate_id=b.id, target_candidate_revision=0)
        other, others = self.group()
        foreign = self.prepare(other, others)
        with self.assertRaises(SessionKindConflict):
            self.command(sid, "select", target_candidate_id=foreign["candidate_id"], target_candidate_revision=1)
        b.status = "failed"
        self.db.commit()
        with self.assertRaises(SessionKindConflict):
            self.command(sid, "select", target_candidate_id=b.id, target_candidate_revision=0)

    def test_active_operation_blocks_other_requests_delete_and_capabilities(self):
        sid, ids = self.group()
        self.command(sid)
        caps = operations.get_group_operation_capabilities(sid, self.db)
        self.assertFalse(caps["can_generate"])
        self.assertFalse(caps["can_discard"])
        for kind in ("send", "discard"):
            with self.assertRaises(SessionKindConflict):
                self.command(sid, kind)
        with self.assertRaises(SessionKindConflict):
            asyncio.run(groups.delete_group_session(sid, self.db))

    def test_snapshot_rejects_secrets_nested_fields_foreign_members_and_nan(self):
        sid, ids = self.group()
        calls = self.calls(ids)
        good, digest = persist_group_calls(calls, 4, set(ids))
        self.assertEqual(64, len(digest))
        self.assertEqual(digest, persist_group_calls(replace(calls, connection=GroupModelConnection(
            "https://example.invalid/v1", "rotated")), 4, set(ids))[1])
        for bad in (
            replace(calls, director_json='{"model":"x","max_tokens":2,"api_key":"secret"}'),
            replace(calls, director_json='{"model":"x","max_tokens":2,"extra_body":{"api_key":"secret"}}'),
            replace(calls, call_timeout=float("nan")),
            replace(calls, members=((999, calls.director_json),)),
            replace(calls, connection=GroupModelConnection("https://secret@example.invalid/v1", "key")),
        ):
            with self.assertRaises(groups.GroupSessionValidationError):
                persist_group_calls(bad, 4, set(ids))
        self.assertNotIn("never-persist", good)

    def test_validation_does_not_consume_request_or_confirm_and_dirty_transaction_survives(self):
        sid, ids = self.group()
        first = self.command(sid)
        self.settle(first)
        request_id = str(uuid4())
        with self.assertRaises(groups.GroupSessionValidationError):
            self.command(sid, request_id=request_id, call_snapshot=None)
        self.assertIsNone(self.db.get(GroupRound, first["accepted"]["round_id"]).confirmed_at)
        group = self.db.get(Session, sid)
        group.title = "uncommitted"
        with self.assertRaises(groups.GroupSessionValidationError):
            self.command(sid, request_id=request_id)
        self.assertIn(group, self.db.dirty)
        self.db.rollback()
        self.command(sid, request_id=request_id)

    def test_concurrent_requests_accept_once_and_replay_after_restart_and_discard(self):
        sid, ids = self.group()
        request_ids = [str(uuid4()), str(uuid4())]

        async def send(request_id):
            with self.sessions() as db:
                return await operations.accept_group_operation(sid, request_id, "send", 0, db,
                    user_content="原文", call_snapshot=self.calls(ids))

        async def race():
            return await asyncio.gather(*(send(rid) for rid in request_ids), return_exceptions=True)

        results = asyncio.run(race())
        self.assertEqual(1, sum(isinstance(result, dict) for result in results))
        self.assertEqual(1, sum(isinstance(result, SessionKindConflict) for result in results))
        winner = next(result for result in results if isinstance(result, dict))
        request_id = request_ids[results.index(winner)]
        self.db.expire_all()
        revision = self.db.get(Session, sid).group_revision
        self.db.rollback()
        with group_runtime(self.engine) as owner:
            fail_interrupted_group_candidates(owner)
            fail_interrupted_group_candidates(owner)
        self.db.expire_all()
        self.assertEqual(revision + 1, self.db.get(Session, sid).group_revision)
        operation = self.db.get(GroupRoundOperation, winner["operation_id"])
        self.assertEqual("process_interrupted", operation.error_code)
        self.assertEqual("failed", self.db.get(GroupRoundCandidate, operation.candidate_id).status)
        self.command(sid, "discard")
        replay = self.command(sid, request_id=request_id, expected=(0, None, None, None),
                              user_content="原文", call_snapshot=None)
        self.assertEqual("failed", replay["status"])
        self.assertEqual(winner["accepted"], replay["accepted"])
        self.assertEqual(0, history.list_group_rounds(sid, self.db)["total"])

    def test_director_pending_query_excludes_discarded_round_and_old_confirmation_stays(self):
        from services.conversation.group import director_service as director
        sid, ids = self.group()
        first = self.command(sid)
        self.settle(first)
        second = self.command(sid)
        self.settle(second, False)
        self.command(sid, "discard")
        self.assertIsNotNone(self.db.get(GroupRound, first["accepted"]["round_id"]).confirmed_at)
        # 初判前用户草稿缺少权限，因此已确认项也不会泄漏给导演历史。
        snapshot = director.build_director_context(sid, self.db)
        self.assertNotIn("原文", snapshot.payload_json)

    def test_equivalent_default_selection_replays_same_receipt(self):
        sid, ids = self.group()
        request_id = str(uuid4())
        expected = (0, None, None, None)
        first = self.command(sid, request_id=request_id, expected=expected)
        replay = self.command(sid, request_id=request_id, expected=expected,
                              thinking_mode="inherit", reasoning_effort="inherit", call_snapshot=None)
        self.assertEqual(first, replay)
        # 正文仍逐字参与指纹，不能随模型参数一起 trim。
        with self.assertRaises(SessionKindConflict):
            self.command(sid, request_id=request_id, expected=expected, user_content="原文 {{char}} 😀")

    def test_invalid_or_mismatched_selection_does_not_consume_request_or_confirm(self):
        sid, ids = self.group()
        first = self.command(sid)
        self.settle(first)
        request_id = str(uuid4())
        for options in (
            dict(model="o3", thinking_mode="disabled"),
            dict(model="another-model"),
            dict(model="fixture", thinking_mode="enabled"),
            dict(thinking_mode="unknown"),
        ):
            with self.subTest(options=options), self.assertRaises(groups.GroupSessionValidationError):
                self.command(sid, request_id=request_id, **options)
            self.assertIsNone(self.db.get(GroupRound, first["accepted"]["round_id"]).confirmed_at)
            self.assertEqual(1, self.db.query(GroupRoundOperation).count())
        self.command(sid, request_id=request_id, model=" fixture ")

    def test_real_captured_selection_matches_director_and_members(self):
        for model, mode, effort in (("fixture", "disabled", None), ("o3", "enabled", "low"),
                                     ("deepseek-v4-flash", "enabled", "high"), ("deepseek-v4-flash", "disabled", None)):
            with self.subTest(model=model, mode=mode):
                sid, ids = self.group()
                calls = capture_group_calls(sid, self.db, model=model, thinking_mode=mode, reasoning_effort=effort)
                wrong = json.loads(calls.members[0][1])
                wrong["model"] = "wrong-member-model"
                broken = replace(calls, members=((ids[0], json.dumps(wrong)), *calls.members[1:]))
                with self.assertRaises(groups.GroupSessionValidationError):
                    self.command(sid, model=model, thinking_mode=mode, reasoning_effort=effort, call_snapshot=broken)
                result = self.command(sid, model=model, thinking_mode=mode, reasoning_effort=effort, call_snapshot=calls)
                saved = json.loads(self.db.get(GroupRoundCandidate, result["accepted"]["candidate_id"]).call_snapshot_json)
                self.assertEqual(model, saved["director"]["model"])

    def test_inherited_selection_and_replay_use_frozen_values_after_settings_change(self):
        sid, ids = self.group()
        with patch.object(settings, "LLM_CHAT_THINKING_MODE", "enabled"):
            calls = capture_group_calls(sid, self.db, model="deepseek-v4-flash", reasoning_effort="low")
        request_id = str(uuid4())
        expected = (0, None, None, None)
        with patch.object(settings, "LLM_CHAT_THINKING_MODE", "disabled"), patch.object(settings, "LLM_REASONING_EFFORT", "max"):
            first = self.command(sid, request_id=request_id, expected=expected, call_snapshot=calls)
        with patch("services.conversation.group.operation_service.validate_group_call_selection", side_effect=AssertionError("revalidated")):
            replay = self.command(sid, request_id=request_id, expected=expected, thinking_mode="inherit",
                                  reasoning_effort="inherit", call_snapshot=None)
        self.assertEqual(first, replay)

    def test_custom_reasoning_toggle_is_frozen_without_requiring_current_profile_on_restore(self):
        from services.conversation.group.call_snapshot import restore_group_calls
        for mode in ("enabled", "disabled"):
            sid, ids = self.group()
            profile = [{"id": "proxy-model", "adapter": "compatible", "thinking": "toggle", "efforts": ["low", "high"]}]
            with patch.object(settings, "LLM_MODEL_PROFILES", profile):
                calls = capture_group_calls(sid, self.db, model="proxy-model", thinking_mode=mode, reasoning_effort="low")
                receipt = self.command(sid, model="proxy-model", thinking_mode=mode, reasoning_effort="low", call_snapshot=calls)
            candidate = self.db.get(GroupRoundCandidate, receipt["accepted"]["candidate_id"])
            restored, _ = restore_group_calls(candidate, set(ids))
            self.assertEqual(json.loads(restored.director_json)["reasoning_effort"], "low" if mode == "enabled" else "none")
