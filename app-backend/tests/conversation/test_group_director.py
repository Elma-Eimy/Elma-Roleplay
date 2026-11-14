"""导演协议、真实个人输入与隔离原型；不调用网络模型。"""
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from application.group_runtime import group_runtime
from core.locking import is_session_locked
from core.models import GroupRound, GroupRoundCandidate, GroupContentItem, Character
from services.conversation.group import director_service as director, history_service as history
from services.conversation.group.session_service import create_group_session, GroupSessionValidationError
from services.conversation.session_access import SessionKindConflict
from scripts.group_chat_prototype.worker import _run_round, ReplayModel, _response, _require_workspace
from tests.conversation import test_group_session_service as fixtures


class DirectorProtocolTests(unittest.TestCase):
    def test_visibility_requires_exact_member_cover_and_visible_author(self):
        raw = '{"recipients":[{"persona_id":2,"decision":"hidden"},{"persona_id":1,"decision":"visible"}]}'
        self.assertEqual((1,), director.parse_visibility(raw, (1, 2), author_id=1).visible_to)
        for invalid in [raw.replace('"hidden"', '"visible", "extra":0'), raw.replace('"persona_id":2', '"persona_id":1'),
                        raw.replace('"persona_id":2', '"persona_id":true'), raw.replace('"persona_id":2', '"persona_id":9'),
                        raw.replace('"hidden"', '"unknown"'), '{"recipients":[]}', raw.replace('"visible"', '"hidden"')]:
            with self.subTest(raw=invalid), self.assertRaises(director.GroupDirectorError):
                director.parse_visibility(invalid, (1, 2), author_id=1)

    def test_strict_json_rejects_duplicates_constants_text_and_truncation(self):
        for raw in ['{"action":"end","action":"end","reason_code":"wait_user"}',
                    '{"action":"end","reason_code":"wait_user","x":NaN}',
                    '```json\n{}\n```', '{}{}', '[]', None, 'x' * 16001, '[' * 1200]:
            with self.subTest(raw=str(raw)[:80]), self.assertRaises(director.GroupDirectorError):
                director.parse_next_action(raw, (1, 2), (1,))
        with self.assertRaisesRegex(director.GroupDirectorError, "incomplete_output"):
            director.parse_next_action('{"action":"end","reason_code":"wait_user"}', (1, 2), (1,), finish_reason="length")

    def test_action_union_cannot_pick_hidden_member_or_add_freeform_reason(self):
        self.assertEqual(1, director.parse_next_action('{"action":"speak","speaker_persona_id":1,"reason_code":"follow_up"}', (1, 2), (1,)).speaker_persona_id)
        for raw in ['{"action":"speak","speaker_persona_id":2,"reason_code":"follow_up"}',
                    '{"action":"speak","speaker_persona_id":true,"reason_code":"follow_up"}',
                    '{"action":"end","speaker_persona_id":1,"reason_code":"wait_user"}',
                    '{"action":"end","reason_code":"SECRET_REASON"}',
                    '{"action":"end","reason_code":"wait_user","reason":"secret"}']:
            with self.subTest(raw=raw), self.assertRaises(director.GroupDirectorError):
                director.parse_next_action(raw, (1, 2), (1,))


class DirectorContextTests(unittest.TestCase):
    setUp = fixtures.GroupSessionServiceTests.setUp
    snapshot = fixtures.GroupSessionServiceTests.snapshot

    def group(self):
        group = asyncio.run(create_group_session(self.imported, self.db))
        return group["session_id"], tuple(member["persona_id"] for member in group["members"])

    def test_director_reads_secret_but_excludes_private_baselines_and_card_prompts(self):
        sid, ids = self.group()
        character = self.db.get(Character, 1)
        character.description = "PRIVATE_DESCRIPTION"
        character.personality = "PRIVATE_PERSONALITY"
        character.system_prompt_override = "PRIVATE_SYSTEM"
        character.extensions = '{"secret":"PRIVATE_EXTENSION"}'
        self.db.commit()
        target = asyncio.run(history.prepare_group_round(sid, "SCENE_SECRET", (ids[0],), self.db))
        ctx = director.build_director_context(sid, self.db, candidate_id=target["candidate_id"], expected_revision=1)
        self.assertEqual((ids[0],), ctx.eligible_ids)
        self.assertIn("SCENE_SECRET", ctx.payload_json)
        for marker in ("PRIVATE_", "knows user", "confirmed fact", "current_mood", "role_state", "initial_state"):
            self.assertNotIn(marker, ctx.payload_json)
        payload = json.loads(ctx.payload_json)
        self.assertEqual("hidden", payload["history"][0]["recipients"][1]["decision"])
        self.assertFalse(self.db.connection().connection.driver_connection.in_transaction)

    def test_snapshot_uses_selected_confirmed_history_not_sibling_failed_or_future(self):
        sid, ids = self.group()
        first = asyncio.run(history.prepare_group_round(sid, "CONFIRMED_CHOSEN", ids, self.db))
        asyncio.run(history.finish_group_round(sid, first["candidate_id"], 1, self.db))
        self.db.get(GroupRound, first["round_id"]).confirmed_at = datetime.utcnow()
        self.db.add(GroupRoundCandidate(session_id=sid, round_id=first["round_id"], version=2, status="awaiting_confirmation"))
        self.db.flush()
        sibling = self.db.query(GroupRoundCandidate).filter_by(version=2).one()
        self.db.add(GroupContentItem(session_id=sid, candidate_id=sibling.id, kind="utterance", sequence=1,
                                     speaker_persona_id=ids[0], content="SIBLING_SECRET"))
        self.db.commit()
        current = asyncio.run(history.prepare_group_round(sid, "CURRENT", ids, self.db))
        future = GroupRound(session_id=sid, round_index=99, user_content="FUTURE_SECRET", confirmed_at=datetime.utcnow())
        self.db.add(future)
        self.db.flush()
        future_candidate = GroupRoundCandidate(session_id=sid, round_id=future.id, status="awaiting_confirmation")
        self.db.add(future_candidate)
        self.db.flush()
        future.selected_candidate_id = future_candidate.id
        self.db.add(GroupContentItem(session_id=sid, candidate_id=future_candidate.id, kind="user", sequence=0))
        self.db.commit()
        ctx = director.build_director_context(sid, self.db, candidate_id=current["candidate_id"], expected_revision=1)
        self.assertIn("CONFIRMED_CHOSEN", ctx.payload_json)
        self.assertIn("CURRENT", ctx.payload_json)
        self.assertNotIn("SIBLING_SECRET", ctx.payload_json)
        self.assertNotIn("FUTURE_SECRET", ctx.payload_json)
        self.db.get(GroupRoundCandidate, first["candidate_id"]).status = "failed"
        self.db.commit()
        ctx = director.build_director_context(sid, self.db, candidate_id=current["candidate_id"], expected_revision=1)
        self.assertNotIn("CONFIRMED_CHOSEN", ctx.payload_json)

    def test_current_context_cannot_be_silently_truncated(self):
        sid, ids = self.group()
        target = asyncio.run(history.prepare_group_round(sid, "SECRET" * 300, ids, self.db))
        with self.assertRaisesRegex(director.GroupDirectorError, "context_budget"):
            director.build_director_context(sid, self.db, candidate_id=target["candidate_id"], expected_revision=1, max_chars=400)


    def test_older_context_budget_omits_whole_items_and_signals_incomplete_history(self):
        sid, ids = self.group()
        target = asyncio.run(history.prepare_group_round(sid, "OLD" * 300, ids, self.db))
        asyncio.run(history.finish_group_round(sid, target["candidate_id"], 1, self.db))
        self.db.get(GroupRound, target["round_id"]).confirmed_at = datetime.utcnow()
        self.db.commit()
        ctx = director.build_director_context(sid, self.db, max_chars=500)
        payload = json.loads(ctx.payload_json)
        self.assertTrue(payload["history_incomplete"])
        self.assertEqual([], payload["history"])


    def test_clean_transaction_and_type_checks_preserve_caller_writes(self):
        with self.assertRaises(SessionKindConflict):
            director.build_director_context(10, self.db)
        sid, _ = self.group()
        self.db.get(Character, 1).name = "caller write"
        with self.assertRaises(GroupSessionValidationError):
            director.build_director_context(sid, self.db)
        self.assertEqual("caller write", self.db.get(Character, 1).name)
        self.db.rollback()


class DirectorPrototypeTests(unittest.TestCase):
    setUp = fixtures.GroupSessionServiceTests.setUp

    def case(self):
        path = Path(__file__).resolve().parents[1] / "fixtures/group_shared_director_cases.json"
        return json.loads(path.read_text(encoding="utf-8"))["cases"][0]

    def run_case(self, case=None, intercept=None, **kwargs):
        case = case or self.case()
        group = asyncio.run(create_group_session(self.cards, self.db))
        ids = tuple(member["persona_id"] for member in group["members"])
        replay = ReplayModel(case, ids)
        async def model(stage, parameters):
            self.assertTrue(is_session_locked(group["session_id"]))
            self.assertFalse(self.db.connection().connection.driver_connection.in_transaction)
            if intercept:
                result = await intercept(stage, parameters, replay, group)
                if result is not None:
                    return result
            return await replay(stage, parameters["messages"])
        with group_runtime(self.engine) as runtime:
            result = asyncio.run(_run_round(group["session_id"], case["user"], self.db, runtime, model, **kwargs))
        self.assertFalse(is_session_locked(group["session_id"]))
        return group, ids, result

    def test_automatic_a_b_a_saves_order_and_never_passes_secret_to_b(self):
        group, ids, result = self.run_case()
        self.assertIsNone(result["error_code"])
        rows = history.list_group_rounds(group["session_id"], self.db)["rounds"][0]
        self.assertEqual([ids[0], ids[1], ids[0]], [row["speaker_persona_id"] for row in rows["utterances"]])
        self.assertEqual(7, len(result["calls"]))
        b_input = json.dumps(result["personal_inputs"][str(ids[1])], ensure_ascii=False)
        self.assertNotIn("SECRET_VAULT_731", b_input)
        self.assertIn(self.case()["steps"][0]["content"], b_input)
        role_calls = [c for c in result["calls"] if c["stage"] == "role_generation"]
        self.assertNotIn("SECRET_VAULT_731", json.dumps(role_calls[1], ensure_ascii=False))
        self.assertNotIn("eligible_persona_ids", json.dumps(role_calls, ensure_ascii=False))




    def test_reply_count_does_not_skip_final_director_decision(self):
        _, _, result = self.run_case(max_steps=2)
        self.assertEqual("wait_user", result["finish_reason"])
        self.assertEqual(7, len(result["calls"]))

    def test_full_old_history_cannot_block_a_short_new_user_input(self):
        group = asyncio.run(create_group_session(self.cards, self.db))
        sid = group["session_id"]
        ids = tuple(member["persona_id"] for member in group["members"])
        old = asyncio.run(history.prepare_group_round(sid, "OLD_MARKER", ids, self.db))
        asyncio.run(history.finish_group_round(sid, old["candidate_id"], 1, self.db))
        self.db.get(GroupRound, old["round_id"]).confirmed_at = datetime.utcnow()
        self.db.commit()
        initial = director.build_director_context(sid, self.db)
        original = "H" * (24000 - len(initial.payload_json) + len("OLD_MARKER"))
        self.db.get(GroupRound, old["round_id"]).user_content = original
        self.db.commit()
        self.assertEqual(24000, len(director.build_director_context(sid, self.db).payload_json))
        replay = ReplayModel({"user_visible": [0, 1], "steps": []}, ids)
        async def model(stage, kwargs):
            return await replay(stage, kwargs["messages"])
        with group_runtime(self.engine) as runtime:
            result = asyncio.run(_run_round(sid, "new small input", self.db, runtime, model))
        self.assertIsNone(result["error_code"])
        self.assertEqual(1, len(result["calls"]))
        self.assertEqual(original, self.db.get(GroupRound, old["round_id"]).user_content)


    def test_total_deadline_pauses_without_retry(self):
        async def slow(stage, parameters, replay, group):
            if stage == "next_action":
                await asyncio.Event().wait()
        group, _, result = self.run_case(intercept=slow, timeout=0.5)
        self.assertEqual("paused", result["finish_reason"])
        self.assertEqual("resource_paused", result["error_code"])
        self.assertEqual(1, len(result["calls"]))
        self.assertEqual("failed", history.list_group_rounds(group["session_id"], self.db)["rounds"][0]["status"])

    def test_cancellation_marks_candidate_failed_and_releases_whole_round_lock(self):
        group = asyncio.run(create_group_session(self.cards, self.db))
        ids = tuple(member["persona_id"] for member in group["members"])
        case = self.case()
        replay = ReplayModel(case, ids)
        async def scenario(runtime):
            started = asyncio.Event()
            calls = []
            async def model(stage, kwargs):
                calls.append(stage)
                if stage == "role_generation":
                    started.set()
                    await asyncio.Event().wait()
                return await replay(stage, kwargs["messages"])
            task = asyncio.create_task(_run_round(group["session_id"], case["user"], self.db, runtime, model))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(["next_action", "role_generation"], calls)
        with group_runtime(self.engine) as runtime:
            asyncio.run(scenario(runtime))
        self.assertFalse(is_session_locked(group["session_id"]))
        candidate = self.db.query(GroupRoundCandidate).one()
        self.assertEqual(("failed", "cancelled"), (candidate.status, candidate.error_code))
        self.assertEqual(1, self.db.query(GroupContentItem).count())

    def _cancel_during_finish(self, *, fail=False):
        group = asyncio.run(create_group_session(self.cards, self.db))
        sid = group["session_id"]
        ids = tuple(member["persona_id"] for member in group["members"])
        entered, release = threading.Event(), threading.Event()
        original = history._finish
        def finish(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("finish probe timeout")
            if fail:
                raise RuntimeError("injected finish failure")
            return original(*args, **kwargs)
        async def scenario(runtime):
            replay = ReplayModel({"user_visible": [0, 1], "steps": []}, ids)
            calls = []
            async def model(stage, kwargs):
                calls.append(stage)
                return await replay(stage, kwargs["messages"])
            task = asyncio.create_task(_run_round(sid, "stop here", self.db, runtime, model))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                task.cancel()
                await asyncio.sleep(0)
                self.assertFalse(task.done())
                self.assertTrue(is_session_locked(sid))
            finally:
                release.set()
            if fail:
                with self.assertRaises(asyncio.CancelledError):
                    await task
                result = None
            else:
                result = await task
            self.assertEqual(["next_action"], calls)
            return result
        with group_runtime(self.engine) as runtime, patch.object(history, "_finish", finish):
            result = asyncio.run(scenario(runtime))
        self.assertFalse(is_session_locked(sid))
        self.db.expire_all()
        return self.db.query(GroupRoundCandidate).one(), result

    def test_final_commit_wins_cancellation_and_returns_completed_result(self):
        candidate, result = self._cancel_during_finish()
        self.assertEqual("awaiting_confirmation", candidate.status)
        self.assertIsNone(candidate.error_code)
        self.assertIsNone(result["error_code"])
        self.assertEqual("wait_user", result["finish_reason"])
        self.assertEqual(candidate.revision, result["revision"])

    def test_cancelled_final_write_failure_still_marks_failed(self):
        candidate, _ = self._cancel_during_finish(fail=True)
        self.assertEqual(("failed", "cancelled"), (candidate.status, candidate.error_code))

    def test_revision_competition_discards_decision_without_overwriting_new_state(self):
        async def advance(stage, parameters, replay, group):
            if stage == "next_action":
                with self.engine.begin() as connection:
                    from sqlalchemy import text
                    connection.execute(text("UPDATE group_round_candidates SET revision=99"))
        _, _, result = self.run_case(intercept=advance)
        self.assertEqual("failed", result["finish_reason"])
        self.assertEqual(1, len(result["calls"]))
        self.db.expire_all()
        candidate = self.db.query(GroupRoundCandidate).one()
        self.assertEqual(("generating", 99), (candidate.status, candidate.revision))
        self.assertEqual(1, self.db.query(GroupContentItem).count())

    def test_worker_rejects_unisolated_execution_before_application_import(self):
        with patch.dict(os.environ, {"GROUP_PROTOTYPE_WORKER_ROOT": ""}):
            with self.assertRaisesRegex(RuntimeError, "隔离启动器"):
                _require_workspace()

    def test_cli_runs_all_virtual_cases_to_readonly_http_report(self):
        backend = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as output:
            completed = subprocess.run([sys.executable, "-m", "scripts.group_chat_prototype", "--output", output],
                cwd=backend, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            paths = list(Path(output).glob("*/report.json"))
            self.assertEqual(1, len(paths))
            report = json.loads(paths[0].read_text(encoding="utf-8"))
            self.assertEqual("offline", report["mode"])
            self.assertEqual("pending", report["semantic_review"])
            self.assertEqual(5, len(report["results"]))
            for result in report["results"]:
                self.assertEqual("invalid_output" if result["id"] == "failed-prefix" else None, result["error_code"], result["id"])
                self.assertTrue(all(result["checks"].values()), result["checks"])
                self.assertEqual("failed" if result["id"] == "failed-prefix" else "awaiting_confirmation",
                                 result["http_rounds"]["rounds"][0]["status"])
            for row in report["results"]:
                self.assertEqual(2, row["candidate_state"]["protocol_version"])
                if row["id"] == "failed-prefix":
                    self.assertEqual(1, len(row["http_rounds"]["rounds"][0]["utterances"]))
                    self.assertEqual(row["candidate_state"]["revision"], row["revision"])
                    continue
                self.assertEqual(row["finish_reason"], row["candidate_state"]["finish_reason"])
                self.assertEqual("finish", row["director_steps"][-1]["stage"])
                self.assertEqual(row["candidate_state"]["revision"], row["director_steps"][-1]["result_revision"])
                self.assertNotIn("PRIVATE_THOUGHT", json.dumps(row["director_steps"]))
