"""后台接受、检查点续接、候选隔离与持久预算；仅临时库和假模型。"""
import asyncio
import json
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import event
from core.models import Session, GroupRound, GroupRoundCandidate, GroupRoundOperation, GroupContentItem, GroupDirectorStep
from core.locking import is_session_locked, stop_group_executions
from application.group_runtime import group_runtime
from services.conversation import group_background_service as background, group_checkpoint_service as checkpoints
from services.conversation import group_operation_service as operations, group_generation_service as generation
from services.conversation import group_round_service as rounds
from services.conversation.session_access import SessionKindConflict
from scripts.group_chat_prototype.worker import _response
from tests.conversation import test_group_operations as fixtures


class Model:
    def __init__(self, ids, *, fail=None, steps=1, text="NEW_REPLY", user="hello"):
        self.ids, self.fail, self.steps, self.text, self.user = ids, fail, steps, text, user
        self.calls = []
        self.saved = 0

    async def __call__(self, stage, parameters):
        self.calls.append((stage, parameters))
        if stage == self.fail:
            raise RuntimeError("PRIVATE_FAILURE")
        recipients = [{"persona_id": pid, "decision": "visible"} for pid in self.ids]
        if stage == "user_visibility":
            value = {"units": [{"start": 0, "end": len(self.user), "recipients": recipients}]}
        elif stage == "next_action":
            value = ({"action": "speak", "speaker_persona_id": self.ids[self.saved % len(self.ids)], "reason_code": "follow_up"}
                     if self.saved < self.steps else {"action": "end", "reason_code": "wait_user"})
        elif stage == "role_generation":
            value = {"units": [{"kind": "speech", "text": self.text}], "status": {"emotion": "平静", "affection_change": 2}}
        else:
            value = {"units": [{"unit_index": 0, "recipients": recipients}]}
            self.saved += 1
        return _response(json.dumps(value, ensure_ascii=False))


class GroupBackgroundTests(unittest.TestCase):
    setUp = fixtures.GroupOperationTests.setUp
    group = fixtures.GroupOperationTests.group

    @contextmanager
    def delayed_budget_clock(self, seconds):
        class Clock:
            now = datetime.utcnow()

            @classmethod
            def utcnow(cls):
                return cls.now

        original = Clock.now
        def delay(connection, cursor, statement, parameters, context, executemany):
            if statement.startswith("UPDATE group_round_operations SET") and "call_count=" in statement:
                # 模拟读取期限之后、预算提交完成之前经过的时间，无需真实等待。
                Clock.now = original + timedelta(seconds=seconds)
        event.listen(self.engine, "before_cursor_execute", delay)
        try:
            with patch.object(checkpoints, "datetime", Clock), patch.object(rounds, "datetime", Clock):
                yield Clock
        finally:
            event.remove(self.engine, "before_cursor_execute", delay)

    def observed(self, sid):
        self.db.expire_all()
        group = self.db.get(Session, sid)
        round_ = operations._latest(sid, self.db)
        candidate = self.db.get(GroupRoundCandidate, round_.selected_candidate_id) if round_ else None
        return dict(observed_round_id=round_.id if round_ else None, observed_candidate_id=candidate.id if candidate else None,
                    observed_candidate_revision=candidate.revision if candidate else None), group.group_revision

    async def submit(self, sid, owner, model, kind="send", request_id=None, **kwargs):
        seen, revision = self.observed(sid)
        if kind == "send":
            kwargs.setdefault("user_content", "hello")
        if kind != "resume":
            kwargs.setdefault("model", "fixture")
        return await background.submit_group_operation(sid, request_id or str(uuid4()), kind, revision, self.db,
            runtime=owner, call_model=model, **seen, **kwargs)

    async def drain(self, owner):
        while owner.tasks:
            await asyncio.gather(*tuple(owner.tasks), return_exceptions=True)
        self.db.expire_all()

    def candidate(self, receipt):
        self.db.expire_all()
        return self.db.get(GroupRoundCandidate, receipt["accepted"]["candidate_id"])

    def test_send_succeeds_and_commits_budget_audit_and_operation(self):
        sid, ids = self.group()
        model = Model(ids)
        async def scenario(owner):
            receipt = await self.submit(sid, owner, model)
            self.assertEqual("queued", receipt["status"])
            await self.drain(owner)
            candidate = self.candidate(receipt)
            self.assertEqual(("awaiting_confirmation", "done"), (candidate.status, candidate.checkpoint))
            operation = self.db.get(GroupRoundOperation, receipt["operation_id"])
            self.assertEqual(("succeeded", 5), (operation.status, operation.call_count))
            self.assertEqual(["user_visibility", "next_action", "utterance_visibility", "finish"],
                [row.stage for row in self.db.query(GroupDirectorStep).order_by(GroupDirectorStep.step_index)])
            self.assertFalse(is_session_locked(sid))
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_every_failed_stage_resumes_only_unfinished_steps(self):
        for stage, checkpoint in (("user_visibility", "user_visibility"), ("next_action", "next_action"),
                                  ("role_generation", "role_generation"), ("utterance_visibility", "role_generation")):
            with self.subTest(stage=stage):
                sid, ids = self.group()
                async def scenario(owner):
                    receipt = await self.submit(sid, owner, Model(ids, fail=stage))
                    await self.drain(owner)
                    candidate = self.candidate(receipt)
                    self.assertEqual(("failed", checkpoint), (candidate.status, candidate.checkpoint))
                    model = Model(ids)
                    resumed = await self.submit(sid, owner, model, "resume", target_candidate_id=candidate.id,
                                                target_candidate_revision=candidate.revision)
                    await self.drain(owner)
                    self.assertEqual(candidate.id, resumed["accepted"]["candidate_id"])
                    self.assertEqual("done", self.candidate(resumed).checkpoint)
                    stages = [name for name, _ in model.calls]
                    self.assertEqual(stage == "user_visibility", "user_visibility" in stages)
                    if checkpoint == "role_generation":
                        self.assertEqual("role_generation", stages[0])
                    self.assertEqual(1, self.db.query(GroupContentItem).filter_by(candidate_id=candidate.id, kind="utterance").count())
                with group_runtime(self.engine) as owner:
                    asyncio.run(scenario(owner))

    def test_regeneration_keeps_old_selection_until_success_and_excludes_old_content(self):
        sid, ids = self.group()
        async def scenario(owner):
            first = await self.submit(sid, owner, Model(ids, text="OLD_CANDIDATE_SECRET"))
            await self.drain(owner)
            old_id = first["accepted"]["candidate_id"]
            model = Model(ids, fail="role_generation")
            second = await self.submit(sid, owner, model, "regenerate")
            await self.drain(owner)
            round_ = self.db.get(GroupRound, first["accepted"]["round_id"])
            self.assertEqual(old_id, round_.selected_candidate_id)
            for _, parameters in model.calls:
                self.assertNotIn("OLD_CANDIDATE_SECRET", json.dumps(parameters["messages"]))
            candidate = self.candidate(second)
            resumed = await self.submit(sid, owner, Model(ids), "resume", target_candidate_id=candidate.id,
                                        target_candidate_revision=candidate.revision)
            await self.drain(owner)
            self.assertEqual(resumed["accepted"]["candidate_id"], self.db.get(GroupRound, round_.id).selected_candidate_id)
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))
    def test_saved_prefix_is_not_replayed_and_finish_resume_uses_zero_calls(self):
        for maximum in (1, 3):
            sid, ids = self.group()
            async def scenario(owner):
                model = Model(ids, steps=3)
                if maximum == 1:
                    with patch.object(checkpoints, "finish", side_effect=RuntimeError("finish failed")):
                        receipt = await self.submit(sid, owner, model, max_steps=maximum)
                        await self.drain(owner)
                else:
                    async def fail_after_first(stage, parameters):
                        if stage == "next_action" and model.saved:
                            raise RuntimeError("next failed")
                        return await model(stage, parameters)
                    receipt = await self.submit(sid, owner, fail_after_first, max_steps=maximum)
                    await self.drain(owner)
                candidate = self.candidate(receipt)
                self.assertEqual("finish" if maximum == 1 else "next_action", candidate.checkpoint)
                self.assertEqual(1, self.db.query(GroupContentItem).filter_by(candidate_id=candidate.id, kind="utterance").count())
                after = Model(ids, steps=0)
                resumed = await self.submit(sid, owner, after, "resume", target_candidate_id=candidate.id,
                                           target_candidate_revision=candidate.revision)
                await self.drain(owner)
                self.assertEqual([] if maximum == 1 else ["next_action"], [stage for stage, _ in after.calls])
                self.assertEqual("done", self.candidate(resumed).checkpoint)
                self.assertEqual(2, sum(row.affection_change or 0 for row in self.db.query(GroupContentItem).filter_by(candidate_id=candidate.id)))
                self.assertEqual(0 if maximum == 1 else 1, self.db.get(GroupRoundOperation, resumed["operation_id"]).call_count)
            with group_runtime(self.engine) as owner:
                asyncio.run(scenario(owner))

    def test_corrupt_or_legacy_prefix_and_changed_provider_reject_before_acceptance(self):
        from core.config import settings
        from core.models import GroupUnitVisibility
        sid, ids = self.group()
        async def scenario(owner):
            receipt = await self.submit(sid, owner, Model(ids, fail="role_generation"))
            await self.drain(owner)
            candidate = self.candidate(receipt)
            kwargs = dict(target_candidate_id=candidate.id, target_candidate_revision=candidate.revision)
            with patch.object(settings, "CHAT_BASE_URL", "https://different.invalid/v1"):
                with self.assertRaises(ValueError):
                    await self.submit(sid, owner, Model(ids), "resume", **kwargs)
            original = candidate.call_snapshot_json
            candidate.call_snapshot_json = None
            self.db.commit()
            with self.assertRaises(ValueError):
                await self.submit(sid, owner, Model(ids), "resume", **kwargs)
            candidate.call_snapshot_json = original
            self.db.query(GroupUnitVisibility).filter_by(recipient_persona_id=ids[0]).delete()
            self.db.commit()
            with self.assertRaises(SessionKindConflict):
                await self.submit(sid, owner, Model(ids), "resume", **kwargs)
            await self.drain(owner)
            self.assertEqual(1, self.db.query(GroupRoundOperation).filter_by(session_id=sid).count())
            self.assertEqual("failed", self.candidate(receipt).status)
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_disconnect_before_acceptance_does_not_cancel_background_or_borrow_request_db(self):
        import threading
        sid, ids = self.group()
        entered, release = threading.Event(), threading.Event()
        original = operations._accept
        worker_dbs = []
        def hold(*args, **kwargs):
            worker_dbs.append(args[5])
            entered.set()
            release.wait(5)
            return original(*args, **kwargs)
        async def scenario(owner):
            with patch.object(operations, "_accept", side_effect=hold):
                caller = asyncio.create_task(self.submit(sid, owner, Model(ids)))
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                caller.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await caller
                self.assertNotEqual(id(self.db), id(worker_dbs[0]))
                self.db.close()
                release.set()
                await self.drain(owner)
                self.assertEqual("succeeded", self.db.query(GroupRoundOperation).filter_by(session_id=sid).one().status)
                self.assertFalse(is_session_locked(sid))
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_shutdown_before_execution_and_during_model_always_cleans_registration(self):
        sid, ids = self.group()
        async def scenario(owner):
            entered = asyncio.Event()
            async def wait_model(stage, parameters):
                entered.set()
                await asyncio.Event().wait()
            receipt = await self.submit(sid, owner, wait_model)
            await entered.wait()
            await stop_group_executions(owner)
            self.db.expire_all()
            self.assertEqual("failed", self.db.get(GroupRoundOperation, receipt["operation_id"]).status)
            self.assertEqual("cancelled", self.candidate(receipt).error_code)
            self.assertFalse(is_session_locked(sid))
            self.assertFalse(owner.tasks)
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))
        sid2, ids2 = self.group()
        async def before_start(owner):
            request = asyncio.create_task(self.submit(sid2, owner, Model(ids2)))
            # 让 submit 登记 Worker，但在其首次运行前停止。
            await asyncio.sleep(0)
            await stop_group_executions(owner)
            with self.assertRaises(SessionKindConflict):
                await request
            self.assertFalse(owner.tasks)
        with group_runtime(self.engine) as owner:
            asyncio.run(before_start(owner))

    def test_final_commit_wins_over_cancellation(self):
        sid, ids = self.group()
        original = checkpoints.finish
        async def scenario(owner):
            loop = asyncio.get_running_loop()
            def commit_and_cancel(scope, *args):
                result = original(scope, *args)
                loop.call_soon_threadsafe(scope.execution.task.cancel)
                return result
            with patch.object(checkpoints, "finish", side_effect=commit_and_cancel):
                receipt = await self.submit(sid, owner, Model(ids))
                await self.drain(owner)
            self.assertEqual("succeeded", self.db.get(GroupRoundOperation, receipt["operation_id"]).status)
            self.assertEqual("awaiting_confirmation", self.candidate(receipt).status)
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_late_candidate_revision_does_not_borrow_revision_or_leave_operation_running(self):
        sid, ids = self.group()
        async def scenario(owner):
            async def race(stage, parameters):
                if stage == "role_generation":
                    with self.sessions() as other:
                        candidate = other.query(GroupRoundCandidate).filter_by(session_id=sid).one()
                        candidate.revision += 10
                        other.commit()
                return await model(stage, parameters)
            model = Model(ids)
            receipt = await self.submit(sid, owner, race)
            await self.drain(owner)
            self.assertEqual("version_conflict", self.db.get(GroupRoundOperation, receipt["operation_id"]).error_code)
            self.assertEqual(12, self.candidate(receipt).revision)
            self.assertEqual(0, self.db.query(GroupContentItem).filter_by(candidate_id=receipt["accepted"]["candidate_id"], kind="utterance").count())
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_duplicate_active_receipt_does_not_dispatch_more_calls_or_extend_deadline(self):
        sid, ids = self.group()
        request_id = str(uuid4())
        async def scenario(owner):
            entered, release = asyncio.Event(), asyncio.Event()
            model = Model(ids)
            async def wait(stage, parameters):
                if stage == "user_visibility":
                    entered.set()
                    await release.wait()
                return await model(stage, parameters)
            seen, revision = self.observed(sid)
            receipt = await background.submit_group_operation(sid, request_id, "send", revision, self.db,
                runtime=owner, call_model=wait, **seen, user_content="hello", model="fixture")
            await entered.wait()
            self.db.expire_all()
            operation = self.db.get(GroupRoundOperation, receipt["operation_id"])
            deadline, count = operation.deadline_at, operation.call_count
            duplicate = await background.submit_group_operation(sid, request_id, "send", revision, self.db,
                runtime=owner, call_model=wait, **seen, user_content="hello", model="fixture")
            self.assertEqual(receipt["operation_id"], duplicate["operation_id"])
            self.assertEqual(1, len(owner.tasks))
            self.assertEqual((deadline, count), (operation.deadline_at, operation.call_count))
            release.set()
            await self.drain(owner)
            self.assertEqual(5, self.db.get(GroupRoundOperation, receipt["operation_id"]).call_count)
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))
    def test_cancelled_database_commits_preserve_accepted_round_and_saved_utterance(self):
        for phase in ("accept", "save"):
            sid, ids = self.group()
            async def scenario(owner):
                loop = asyncio.get_running_loop()
                if phase == "accept":
                    original = operations._accept
                    def commit_and_cancel(*args, **kwargs):
                        result = original(*args, **kwargs)
                        worker = next(iter(owner.executions))
                        loop.call_soon_threadsafe(worker.cancel)
                        return result
                    module, name = operations, "_accept"
                else:
                    original = generation._save
                    def commit_and_cancel(*args, **kwargs):
                        result = original(*args, **kwargs)
                        loop.call_soon_threadsafe(kwargs["scope"].execution.task.cancel)
                        return result
                    module, name = generation, "_save"
                with patch.object(module, name, side_effect=commit_and_cancel):
                    receipt = await self.submit(sid, owner, Model(ids), max_steps=1)
                    await self.drain(owner)
                candidate = self.candidate(receipt)
                self.assertEqual("failed", candidate.status)
                self.assertEqual("user_visibility" if phase == "accept" else "finish", candidate.checkpoint)
                self.assertEqual(0 if phase == "accept" else 1,
                    self.db.query(GroupContentItem).filter_by(candidate_id=candidate.id, kind="utterance").count())
                after = Model(ids)
                await self.submit(sid, owner, after, "resume", target_candidate_id=candidate.id,
                                  target_candidate_revision=candidate.revision)
                await self.drain(owner)
                self.assertEqual([] if phase == "save" else ["user_visibility", "next_action", "role_generation", "utterance_visibility"],
                                 [stage for stage, _ in after.calls])
            with group_runtime(self.engine) as owner:
                asyncio.run(scenario(owner))

    def test_scope_cannot_be_forged_borrowed_or_used_by_legacy_writer(self):
        from dataclasses import replace
        from services.conversation import group_history_service as history
        sid, ids = self.group()
        async def scenario(owner):
            model = Model(ids)
            captured = []
            async def inspect(stage, parameters):
                execution = owner.executions[asyncio.current_task()]
                scope = execution.target_scope
                captured.append(scope)
                with self.sessions() as db:
                    candidate = db.get(GroupRoundCandidate, scope.candidate_id)
                    revision = candidate.revision
                    self.assertFalse(db.connection().connection.driver_connection.in_transaction)
                    with self.assertRaises(SessionKindConflict):
                        history._writable(sid, candidate.id, revision, db)
                    async def borrow():
                        with self.assertRaises(RuntimeError):
                            await generation._database(checkpoints.progress, scope, revision, db)
                        with self.assertRaises(SessionKindConflict):
                            checkpoints.target(scope, sid, candidate.id, revision, db)
                    await asyncio.create_task(borrow())
                    with self.assertRaises(RuntimeError):
                        await generation._database(checkpoints.progress, replace(scope), revision, db)
                return await model(stage, parameters)
            receipt = await self.submit(sid, owner, inspect)
            await self.drain(owner)
            self.assertEqual("done", self.candidate(receipt).checkpoint)
            with self.assertRaises(RuntimeError):
                await generation._database(checkpoints.progress, captured[0], self.candidate(receipt).revision, self.db)
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_connection_start_failure_has_failed_receipt_and_no_calls(self):
        from contextlib import asynccontextmanager
        sid, ids = self.group()
        @asynccontextmanager
        async def broken(*args, **kwargs):
            raise RuntimeError("client startup")
            yield
        async def scenario(owner):
            with patch.object(background, "group_model_session", broken):
                receipt = await self.submit(sid, owner, None)
                await self.drain(owner)
            operation = self.db.get(GroupRoundOperation, receipt["operation_id"])
            self.assertEqual(("failed", 0), (operation.status, operation.call_count))
            self.assertEqual("failed", self.candidate(receipt).status)
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_dispatch_consumes_durable_budget_before_call_and_does_not_refund(self):
        sid, ids = self.group()
        async def scenario(owner):
            model = Model(ids)
            async def limit(stage, parameters):
                with self.sessions() as db:
                    operation = db.query(GroupRoundOperation).filter_by(session_id=sid, status="running").one()
                    self.assertEqual(len(model.calls)+1, operation.call_count)
                    operation.call_limit = 1
                    db.commit()
                return await model(stage, parameters)
            receipt = await self.submit(sid, owner, limit)
            await self.drain(owner)
            self.assertEqual(["user_visibility"], [stage for stage, _ in model.calls])
            candidate = self.candidate(receipt)
            self.assertEqual(("failed", "call_budget"), (candidate.status, candidate.error_code))
            operation = self.db.get(GroupRoundOperation, receipt["operation_id"])
            self.assertEqual(1, operation.call_count)
            self.assertEqual("failed", operation.status)
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_next_send_confirms_selected_success_even_with_failed_sibling(self):
        sid, ids = self.group()
        async def scenario(owner):
            first = await self.submit(sid, owner, Model(ids))
            await self.drain(owner)
            await self.submit(sid, owner, Model(ids, fail="role_generation"), "regenerate")
            await self.drain(owner)
            await self.submit(sid, owner, Model(ids, fail="user_visibility"))
            await self.drain(owner)
            round_ = self.db.get(GroupRound, first["accepted"]["round_id"])
            self.assertIsNotNone(round_.confirmed_at)
            self.assertEqual(first["accepted"]["candidate_id"], round_.selected_candidate_id)
            self.assertEqual("awaiting_confirmation", self.candidate(first).status)
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))
    def test_resume_freezes_parameters_but_allows_same_provider_key_rotation(self):
        from core.config import settings
        from services.conversation.group_call_snapshot import restore_group_calls
        sid, ids = self.group()
        async def scenario(owner):
            receipt = await self.submit(sid, owner, Model(ids, fail="role_generation"), max_steps=3)
            await self.drain(owner)
            candidate = self.candidate(receipt)
            saved = json.loads(candidate.call_snapshot_json)
            with patch.multiple(settings, CHAT_API_KEY="rotated-test-key", LLM_MAX_TOKENS=98765,
                    LLM_MODEL_PROFILES=[{"id": "fixture", "adapter": "reasoning"}], LLM_TIMEOUT=999):
                snapshot, _ = restore_group_calls(candidate, set(ids))
                self.assertEqual("rotated-test-key", snapshot.connection.api_key)
                after = Model(ids)
                resumed = await self.submit(sid, owner, after, "resume", target_candidate_id=candidate.id,
                                            target_candidate_revision=candidate.revision)
                await self.drain(owner)
                for _, parameters in after.calls:
                    self.assertEqual(saved["director"]["max_tokens"], parameters["max_tokens"])
                    self.assertLessEqual(parameters["timeout"], saved["call_timeout"])
                self.assertEqual("done", self.candidate(resumed).checkpoint)
                self.assertNotIn("rotated-test-key", self.candidate(resumed).call_snapshot_json)
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_restart_converges_unfinished_sibling_without_changing_successful_selection(self):
        from application.group_runtime import fail_interrupted_group_candidates
        from services.conversation.group_call_snapshot import capture_group_calls
        sid, ids = self.group()
        async def scenario(owner):
            first = await self.submit(sid, owner, Model(ids))
            await self.drain(owner)
            seen, revision = self.observed(sid)
            # 模拟已接受后进程退出；不创建后台任务，不自动派发模型。
            snapshot = capture_group_calls(sid, self.db, model="fixture")
            queued = await operations.accept_group_operation(sid, str(uuid4()), "regenerate", revision, self.db,
                **seen, model="fixture", call_snapshot=snapshot)
            fail_interrupted_group_candidates(owner)
            fail_interrupted_group_candidates(owner)
            self.db.expire_all()
            self.assertEqual("process_interrupted", self.db.get(GroupRoundOperation, queued["operation_id"]).error_code)
            self.assertEqual("failed", self.candidate(queued).status)
            self.assertEqual(first["accepted"]["candidate_id"], self.db.get(GroupRound, first["accepted"]["round_id"]).selected_candidate_id)
            self.assertFalse(owner.tasks)
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_expired_budget_commit_prevents_model_dispatch_without_refunding_consumption(self):
        sid, ids = self.group()
        model = Model(ids)
        async def scenario(owner):
            with self.delayed_budget_clock(301):
                receipt = await self.submit(sid, owner, model)
                await self.drain(owner)
            self.assertEqual([], model.calls)
            operation = self.db.get(GroupRoundOperation, receipt["operation_id"])
            self.assertEqual(("failed", 1), (operation.status, operation.call_count))
            self.assertEqual("call_budget", self.candidate(receipt).error_code)
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_budget_commit_time_reduces_actual_provider_timeout(self):
        sid, ids = self.group()
        model = Model(ids, steps=0)
        async def scenario(owner):
            with self.delayed_budget_clock(299):
                receipt = await self.submit(sid, owner, model)
                await self.drain(owner)
            self.assertEqual("done", self.candidate(receipt).checkpoint)
            self.assertEqual(2, len(model.calls))
            for _, parameters in model.calls:
                self.assertGreater(parameters["timeout"], 0)
                self.assertLessEqual(parameters["timeout"], 1)
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_late_response_is_rejected_against_the_persistent_deadline(self):
        sid, ids = self.group()
        model = Model(ids)
        async def scenario(owner):
            with self.delayed_budget_clock(299) as clock:
                async def late(stage, parameters):
                    response = await model(stage, parameters)
                    clock.now += timedelta(seconds=2)
                    return response
                receipt = await self.submit(sid, owner, late)
                await self.drain(owner)
            candidate = self.candidate(receipt)
            self.assertEqual(("failed", "timeout", "user_visibility"),
                             (candidate.status, candidate.error_code, candidate.checkpoint))
            self.assertEqual(1, len(model.calls))
            self.assertEqual(1, self.db.get(GroupRoundOperation, receipt["operation_id"]).call_count)
            self.assertEqual(0, self.db.query(GroupDirectorStep).filter_by(candidate_id=candidate.id).count())
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))
