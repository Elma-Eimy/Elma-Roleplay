"""候选生命周期的终态保护、检查点顺序及新旧恢复语义。"""
import json
import unittest

from core.models import GroupRoundCandidate
from services.conversation.group import candidate_state as state
from services.conversation.session_access import SessionKindConflict


class GroupCandidateStateTests(unittest.TestCase):
    def candidate(self, *, checkpoint="user_visibility", status="generating", continuous=True):
        return GroupRoundCandidate(status=status, checkpoint=checkpoint, revision=7,
            error_code=None, finish_reason=None,
            call_snapshot_json=json.dumps({"max_steps": 1, "director_ending": continuous}))

    def snapshot(self, candidate):
        return (candidate.status, candidate.checkpoint, candidate.revision,
                candidate.error_code, candidate.finish_reason)

    def test_director_ending_and_frozen_step_limit_follow_distinct_checkpoints(self):
        for continuous in (True, False):
            with self.subTest(continuous=continuous):
                candidate = self.candidate(continuous=continuous)
                state.user_saved(candidate)
                state.action_saved(candidate, persistent=True)
                state.utterance_saved(candidate, completed_steps=1)
                self.assertEqual("next_action" if continuous else "finish", candidate.checkpoint)
                self.assertEqual(10, candidate.revision)
                if continuous:
                    state.prepare_finish(candidate, "wait_user")
                state.finish(candidate, "wait_user" if continuous else "step_limit", persistent=True)
                self.assertEqual(("awaiting_confirmation", "done", None),
                    (candidate.status, candidate.checkpoint, candidate.error_code))

    def test_terminal_candidates_reject_late_writes_without_changing_any_state(self):
        operations = (state.user_saved, lambda c: state.action_saved(c, persistent=True),
            lambda c: state.utterance_saved(c, completed_steps=1),
            lambda c: state.prepare_finish(c, "wait_user"),
            lambda c: state.finish(c, "wait_user"), lambda c: state.fail(c, "cancelled"))
        for status in ("awaiting_confirmation", "failed"):
            for operation in operations:
                candidate = self.candidate(status=status)
                before = self.snapshot(candidate)
                with self.subTest(status=status, operation=operation), self.assertRaises(SessionKindConflict):
                    operation(candidate)
                self.assertEqual(before, self.snapshot(candidate))

    def test_persistent_steps_cannot_skip_unfinished_work(self):
        for checkpoint, operation in (
            ("next_action", state.user_saved),
            ("role_generation", lambda c: state.action_saved(c, persistent=True)),
            ("next_action", lambda c: state.utterance_saved(c, completed_steps=1)),
            ("role_generation", lambda c: state.prepare_finish(c, "wait_user")),
            ("role_generation", lambda c: state.finish(c, "wait_user", persistent=True)),
        ):
            candidate = self.candidate(checkpoint=checkpoint)
            before = self.snapshot(candidate)
            with self.subTest(checkpoint=checkpoint), self.assertRaises(SessionKindConflict):
                operation(candidate)
            self.assertEqual(before, self.snapshot(candidate))

    def test_failed_final_commit_retains_saved_end_decision_through_resume(self):
        candidate = self.candidate(checkpoint="next_action")
        state.prepare_finish(candidate, "wait_user")
        state.fail(candidate, "execution_failed", preserve_finish=True)
        self.assertEqual(("failed", "finish", 9, "execution_failed", "wait_user"), self.snapshot(candidate))
        state.resume(candidate)
        self.assertEqual(("generating", "finish", 10, None, "wait_user"), self.snapshot(candidate))
        state.finish(candidate, candidate.finish_reason, persistent=True)
        self.assertEqual(("awaiting_confirmation", "done", 11, None, "wait_user"), self.snapshot(candidate))

    def test_internal_entry_keeps_legacy_checkpoint_and_failure_cleanup(self):
        candidate = self.candidate(checkpoint="done")
        state.action_saved(candidate, persistent=False)
        state.utterance_saved(candidate)
        candidate.finish_reason = "wait_user"
        state.fail(candidate, "cancelled")
        self.assertEqual(("failed", "done", 10, "cancelled", None), self.snapshot(candidate))
        state.resume(candidate)
        state.finish(candidate, None)
        self.assertEqual(("awaiting_confirmation", "done", 12, None, None), self.snapshot(candidate))

    def test_invalid_end_reason_and_resume_of_success_do_not_change_candidate(self):
        candidate = self.candidate(checkpoint="next_action")
        before = self.snapshot(candidate)
        with self.assertRaises(SessionKindConflict):
            state.prepare_finish(candidate, "step_limit")
        self.assertEqual(before, self.snapshot(candidate))
        state.finish(candidate, "wait_user")
        before = self.snapshot(candidate)
        with self.assertRaises(SessionKindConflict):
            state.resume(candidate)
        self.assertEqual(before, self.snapshot(candidate))
