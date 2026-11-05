"""轮次执行权、冻结参数、预算和关闭边界；仅临时数据与本地模型替身。"""
import asyncio
from contextlib import contextmanager
import json
from pathlib import Path
import threading
from functools import partial
import unittest
from unittest.mock import patch

from core.config import settings
from core.locking import (group_execution, require_group_execution, _GroupExecution,
                          get_session_lock, is_session_locked)
from core.models import Character, GroupRoundCandidate, GroupContentItem
from application.group_runtime import group_runtime
from services.conversation.group_call_snapshot import capture_group_calls
from services.conversation.group_round_service import run_group_round as _run_group_round, GroupRoundBudget
from services.conversation.group_session_service import create_group_session
from services.conversation.session_access import SessionKindConflict
from scripts.group_chat_prototype.worker import ReplayModel, _response
from tests.conversation import test_group_session_service as fixtures

# 既有执行权测试保留 v1 替身，v2 端到端覆盖在 test_group_units。
run_group_round = partial(_run_group_round, protocol_version=1)


class GroupRoundTests(unittest.TestCase):
    setUp = fixtures.GroupSessionServiceTests.setUp

    def group(self):
        group = asyncio.run(create_group_session(self.cards, self.db))
        return group["session_id"], tuple(member["persona_id"] for member in group["members"])

    def case(self):
        return json.loads((Path(__file__).resolve().parents[1] / "fixtures/group_director_cases.json").read_text(encoding="utf-8"))["cases"][0]

    def test_execution_rejects_forged_cross_task_cross_session_and_expired_tokens(self):
        sid, _ = self.group()
        async def scenario(owner):
            async with group_execution(sid, self.engine, owner) as execution:
                require_group_execution(execution, sid, self.engine)
                forged = _GroupExecution(owner, sid, get_session_lock(sid), asyncio.current_task())
                with self.assertRaises(RuntimeError):
                    require_group_execution(forged, sid, self.engine)
                with self.assertRaises(RuntimeError):
                    require_group_execution(execution, sid + 1, self.engine)
                async def borrow():
                    with self.assertRaises(RuntimeError):
                        require_group_execution(execution, sid, self.engine)
                await asyncio.create_task(borrow())
                with self.assertRaises(SessionKindConflict):
                    async with group_execution(sid, self.engine, owner):
                        self.fail("nested execution must fail")
            with self.assertRaises(RuntimeError):
                require_group_execution(execution, sid, self.engine)
            self.assertEqual(set(), owner.tasks)
            self.assertEqual({}, owner.executions)
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_round_freezes_model_controls_history_and_member_parameters(self):
        sid, ids = self.group()
        self.db.get(Character, 1).extensions = '{"temperature":0.1}'
        self.db.get(Character, 2).extensions = '{"temperature":0.9}'
        self.db.commit()
        case = self.case()
        replay = ReplayModel(case, ids)
        recorded = []
        async def model(stage, kwargs):
            recorded.append((stage, kwargs))
            self.assertFalse(self.db.connection().connection.driver_connection.in_transaction)
            if stage == "user_visibility":
                settings.LLM_DEFAULT_CHAT_MODEL = "changed-model"
                settings.LLM_MAX_TOKENS = 999
                settings.LLM_TEMPERATURE = 0.99
                settings.APP_CONTEXT_HISTORY_LIMIT = 1
                settings.LLM_MODEL_PROFILES = [{"id": "fixture-replay", "adapter": "reasoning"}]
                self.db.get(Character, 1).extensions = '{"temperature":0.99}'
                self.db.commit()
            return await replay(stage, kwargs["messages"])
        with patch.multiple(settings, LLM_DEFAULT_CHAT_MODEL="fixture-replay", LLM_MAX_TOKENS=111,
                LLM_TEMPERATURE=0.3, APP_CONTEXT_HISTORY_LIMIT=50, LLM_MODEL_PROFILES=[], LLM_TIMEOUT=4.0):
            with group_runtime(self.engine) as owner:
                result = asyncio.run(run_group_round(sid, case["user"], self.db, runtime=owner, call_model=model))
        self.assertIsNone(result["error_code"])
        roles = [kwargs for stage, kwargs in recorded if stage == "role_generation"]
        self.assertEqual([0.1, 0.9, 0.1], [kwargs["temperature"] for kwargs in roles])
        self.assertIn("SECRET_VAULT_731", json.dumps(roles[-1]["messages"], ensure_ascii=False))
        for _, kwargs in recorded:
            self.assertEqual("fixture-replay", kwargs["model"])
            self.assertEqual(111, kwargs["max_tokens"])
            self.assertLessEqual(kwargs["timeout"], 4)
        self.assertTrue(all("messages" not in entry for entry in result["calls"]))
        self.assertEqual({}, result["personal_inputs"])

    def test_snapshot_shares_thinking_selection_and_never_serializes_credentials(self):
        sid, ids = self.group()
        self.db.get(Character, 1).extensions = '{"reasoning_effort":"max"}'
        self.db.commit()
        with patch.multiple(settings, LLM_DEFAULT_CHAT_MODEL="deepseek-chat", LLM_REASONING_MODE=True,
                LLM_REASONING_EFFORT="low", CHAT_API_KEY="SENTINEL_PRIVATE_KEY"):
            snapshot = capture_group_calls(sid, self.db)
        for encoded in [snapshot.director_json, *(snapshot.member_parameters(pid) for pid in ids)]:
            parameters = json.loads(encoded)
            self.assertEqual("low", parameters["reasoning_effort"])
            self.assertEqual({"type": "enabled"}, parameters["extra_body"]["thinking"])
            self.assertNotIn("temperature", parameters)
            self.assertNotIn("SENTINEL_PRIVATE_KEY", encoded)
        self.assertNotIn("SENTINEL_PRIVATE_KEY", repr(snapshot))
        self.assertEqual("SENTINEL_PRIVATE_KEY", snapshot.connection.api_key)

    def test_budget_validates_before_dispatch_and_does_not_refund_failures(self):
        for steps, timeout in ((True, 2), (0, 2), (7, 2), (2, float("nan")), (2, -1)):
            with self.assertRaises(ValueError):
                GroupRoundBudget(steps, timeout, 1)
        budget = GroupRoundBudget(1, 20, 2)
        for _ in range(4):
            self.assertLessEqual(budget.consume(), 2)
        with self.assertRaisesRegex(ValueError, "call_budget"):
            budget.consume()
        self.assertEqual(4, budget.used)
        with patch("services.conversation.group_round_service.time.monotonic", return_value=budget.deadline + 1):
            with self.assertRaisesRegex(ValueError, "call_budget"):
                budget.remaining()

    def test_role_timeout_uses_frozen_call_limit_and_keeps_failed_candidate(self):
        sid, ids = self.group()
        replay = ReplayModel(self.case(), ids)
        calls = []
        async def model(stage, kwargs):
            calls.append(stage)
            if stage == "role_generation":
                await asyncio.Event().wait()
            return await replay(stage, kwargs["messages"])
        with patch.object(settings, "LLM_TIMEOUT", 0.1), group_runtime(self.engine) as owner:
            result = asyncio.run(run_group_round(sid, self.case()["user"], self.db, runtime=owner, call_model=model))
        self.assertEqual("timeout", result["error_code"])
        self.assertEqual(["user_visibility", "next_action", "role_generation"], calls)
        self.assertEqual("failed", self.db.query(GroupRoundCandidate).one().status)
        self.assertFalse(is_session_locked(sid))

    def test_single_timeout_rejects_late_results_in_every_model_stage(self):
        stages = ["user_visibility", "next_action", "role_generation", "utterance_visibility"]
        for late_stage in stages:
            with self.subTest(stage=late_stage):
                sid, ids = self.group()
                replay = ReplayModel(self.case(), ids)
                called, cleaned = [], []
                async def model(stage, kwargs):
                    called.append(stage)
                    if stage == late_stage:
                        try:
                            await asyncio.Event().wait()
                        except asyncio.CancelledError:
                            await asyncio.sleep(0.01)
                            cleaned.append(stage)
                    return await replay(stage, kwargs["messages"])
                with patch.object(settings, "LLM_TIMEOUT", 0.03), group_runtime(self.engine) as owner:
                    result = asyncio.run(run_group_round(sid, self.case()["user"], self.db, runtime=owner,
                                                        call_model=model, timeout=5, max_steps=1))
                self.assertEqual([late_stage], cleaned)
                self.assertEqual("timeout", result["error_code"])
                self.assertEqual(stages[:stages.index(late_stage) + 1], called)
                candidate = self.db.query(GroupRoundCandidate).filter_by(session_id=sid).first()
                if late_stage == "user_visibility":
                    self.assertIsNone(candidate)
                else:
                    self.assertEqual("failed", candidate.status)
                self.assertEqual(0, self.db.query(GroupContentItem).filter_by(session_id=sid, kind="utterance").count())
                self.assertFalse(is_session_locked(sid))
                self.db.rollback()

    def test_diagnostic_budget_error_cannot_change_completed_round(self):
        outcomes = []
        for collect in (False, True):
            sid, ids = self.group()
            latest = {}
            async def model(stage, kwargs):
                if stage == "next_action":
                    latest.update(json.loads(kwargs["messages"][1]["content"]))
                    return _response(json.dumps({"action": "speak", "speaker_persona_id": ids[0], "reason_code": "direct_response"}))
                if stage == "role_generation":
                    payload = {**latest, "stage": "utterance_visibility",
                               "pending_utterance": {"speaker_persona_id": ids[0], "content": ""}}
                    body = "x" * (24000 - len(json.dumps(payload, ensure_ascii=False)))
                    return _response('<reply>' + body + '</reply><status emotion="calm" affection_change="0"/>')
                if stage == "utterance_visibility":
                    self.assertEqual(24000, len(kwargs["messages"][1]["content"]))
                return _response(json.dumps({"recipients": [{"persona_id": pid, "decision": "visible"} for pid in ids]}))
            with group_runtime(self.engine) as owner:
                result = asyncio.run(run_group_round(sid, "user", self.db, runtime=owner, max_steps=1,
                                                    call_model=model, collect_inputs=collect))
            self.db.expire_all()
            candidate = self.db.query(GroupRoundCandidate).filter_by(session_id=sid).one()
            self.assertIsNone(result["error_code"])
            outcomes.append((result["error_code"], candidate.status, len(result["calls"])))
            self.assertEqual("context_budget" if collect else None, result.get("diagnostic_error_code"))
            self.assertEqual({}, result["personal_inputs"])
        self.assertEqual([(None, "awaiting_confirmation", 4)] * 2, outcomes)

    def test_diagnostic_exception_is_sanitized_without_failing_business(self):
        sid, ids = self.group()
        replay = ReplayModel(self.case(), ids)
        async def model(stage, kwargs):
            return await replay(stage, kwargs["messages"])
        with patch("services.conversation.group_round_service.build_member_context", side_effect=RuntimeError("PRIVATE_REPORT")), group_runtime(self.engine) as owner:
            result = asyncio.run(run_group_round(sid, self.case()["user"], self.db, runtime=owner,
                                                call_model=model, collect_inputs=True))
        self.assertIsNone(result["error_code"])
        self.assertEqual("input_collection_failed", result["diagnostic_error_code"])
        self.assertNotIn("PRIVATE_REPORT", json.dumps(result))
        self.assertEqual({}, result["personal_inputs"])
        self.assertEqual("awaiting_confirmation", self.db.query(GroupRoundCandidate).one().status)

    def test_cancellation_during_diagnostic_read_still_waits_and_fails_candidate(self):
        from services.conversation.group_context_service import build_member_context
        sid, ids = self.group()
        entered, release = threading.Event(), threading.Event()
        replay = ReplayModel(self.case(), ids)
        def read(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("diagnostic probe timeout")
            return build_member_context(*args, **kwargs)
        async def scenario(owner):
            async def model(stage, kwargs):
                return await replay(stage, kwargs["messages"])
            task = asyncio.create_task(run_group_round(sid, self.case()["user"], self.db, runtime=owner,
                                                       call_model=model, max_steps=1, collect_inputs=True))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                task.cancel()
                await asyncio.sleep(0)
                self.assertFalse(task.done())
                self.assertTrue(is_session_locked(sid))
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        with patch("services.conversation.group_round_service.build_member_context", read), group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))
        self.assertFalse(is_session_locked(sid))
        self.db.expire_all()
        self.assertEqual("failed", self.db.query(GroupRoundCandidate).one().status)

    def test_default_client_runs_whole_round_against_local_http(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        sid, ids = self.group()
        responses = [json.dumps({"recipients": [{"persona_id": pid, "decision": "visible"} for pid in ids]}),
                     '{"action":"end","reason_code":"wait_user"}']
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                body = json.dumps({"id": "fixture", "object": "chat.completion", "created": 0, "model": "fixture-replay",
                    "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": responses[len(requests) - 1]}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *_):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        serving = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        serving.start()
        try:
            with patch.multiple(settings, CHAT_BASE_URL=f"http://127.0.0.1:{server.server_port}/v1", CHAT_API_KEY="fixture-key",
                    LLM_DEFAULT_CHAT_MODEL="fixture-replay"), group_runtime(self.engine) as owner:
                result = asyncio.run(run_group_round(sid, "hello", self.db, runtime=owner))
            self.assertIsNone(result["error_code"])
            self.assertEqual("wait_user", result["finish_reason"])
            self.assertEqual(2, len(requests))
            self.assertEqual("awaiting_confirmation", self.db.query(GroupRoundCandidate).one().status)
        finally:
            server.shutdown()
            server.server_close()
            serving.join(2)

    def _assert_shutdown_waits(self, *, during_save):
        from application.lifecycle import lifespan
        from services.conversation import group_generation_service as generation
        from fastapi import FastAPI
        sid, ids = self.group()
        app = FastAPI()
        original = generation._save
        thread_release = threading.Event()
        holders = []
        @contextmanager
        def owned_runtime():
            with group_runtime(self.engine) as owner:
                holders.append(owner)
                yield owner
        async def scenario():
            entered, stopping, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
            loop = asyncio.get_running_loop()
            def save(*args):
                loop.call_soon_threadsafe(entered.set)
                if not thread_release.wait(5):
                    raise RuntimeError("save probe timeout")
                return original(*args)
            replay = ReplayModel(self.case(), ids)
            async def model(stage, kwargs):
                if stage == "role_generation" and not during_save:
                    entered.set()
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        stopping.set()
                        await release.wait()
                        raise
                return await replay(stage, kwargs["messages"])
            async def worker():
                await asyncio.Event().wait()
            request = None
            async def serve():
                nonlocal request
                async with lifespan(app):
                    request = asyncio.create_task(run_group_round(sid, self.case()["user"], self.db,
                        runtime=app.state.group_runtime_owner, call_model=model))
                    await asyncio.Event().wait()
            with patch("application.lifecycle.group_runtime", owned_runtime), patch("application.lifecycle.run_migrations"), patch(
                "application.lifecycle.run_memory_retry_worker", worker), patch("application.lifecycle.run_outbox_worker", worker), patch(
                "application.lifecycle.run_charx_cleanup", worker), patch("application.lifecycle.print_startup_banner"), patch.object(
                generation, "_save", save), patch("application.lifecycle.cancel_all_stream_tasks"):
                serving = asyncio.create_task(serve())
                try:
                    await asyncio.wait_for(entered.wait(), 5)
                    serving.cancel()
                    if not during_save:
                        await asyncio.wait_for(stopping.wait(), 2)
                    else:
                        await asyncio.sleep(0.03)
                    serving.cancel()
                    await asyncio.sleep(0)
                    self.assertTrue(holders[0].active)
                    self.assertFalse(holders[0].accepting)
                    self.assertFalse(serving.done())
                    self.assertTrue(is_session_locked(sid))
                    with self.assertRaisesRegex(RuntimeError, "单 Worker"):
                        with group_runtime(self.engine):
                            self.fail("runtime released before cleanup")
                    with self.assertRaises(SessionKindConflict):
                        await run_group_round(sid, "late request", self.db, runtime=holders[0], call_model=model)
                finally:
                    thread_release.set()
                    release.set()
                    with self.assertRaises(asyncio.CancelledError):
                        await serving
                    if request is not None:
                        with self.assertRaises(asyncio.CancelledError):
                            await request
        asyncio.run(scenario())
        self.assertFalse(holders[0].active)
        self.assertEqual(set(), holders[0].tasks)
        self.assertFalse(is_session_locked(sid))
        self.db.expire_all()
        self.assertEqual("failed", self.db.query(GroupRoundCandidate).one().status)

    def test_shutdown_waits_for_role_cleanup_before_releasing_runtime(self):
        self._assert_shutdown_waits(during_save=False)

    def test_repeated_shutdown_waits_for_dispatched_database_save(self):
        self._assert_shutdown_waits(during_save=True)
