"""群聊公开操作与查询契约；真实后台服务、隔离数据库与模型替身。"""
import asyncio
from contextlib import asynccontextmanager
import json
import time
import unittest
from uuid import uuid4
from unittest.mock import patch
from fastapi.testclient import TestClient
from application.factory import create_app
from application.group_runtime import group_runtime
from core.database import get_db
from core.config import settings
from core.locking import stop_group_executions
from core.models import GroupRoundOperation, GroupRound, GroupRoundCandidate, Session
from schemas import SQLITE_INT_MAX
from services.conversation import group_background_service as background
from tests.conversation import test_group_session_service as fixtures, test_group_background as models


class GroupOperationRoutesTests(unittest.TestCase):
    def setUp(self):
        fixtures.GroupSessionServiceTests.setUp(self)
        self.app = create_app()
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.fail_stage = None
        self.models = []
        @asynccontextmanager
        async def lifespan(app):
            with group_runtime(self.engine) as owner:
                app.state.group_runtime_owner = owner
                try:
                    yield
                finally:
                    await stop_group_executions(owner)
        self.app.router.lifespan_context = lifespan
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        async def dispatch(session_id, request_id, kind, revision, db, **options):
            from services.conversation import group_history_service as history, group_operation_service as operations
            with self.sessions() as read:
                ids = tuple(sorted(history._members(session_id, read)))
                latest = operations._latest(session_id, read)
                content = options.get("user_content", latest.user_content if latest else "hello")
            model = models.Model(ids, fail=self.fail_stage, text=f"REPLY_{len(self.models)}", user=content)
            self.models.append(model)
            async def shared(stage, parameters):
                if stage == 'role_generation' and stage != model.fail:
                    model.calls.append((stage, parameters))
                    model.saved += 1
                    return models._response(f'<reply>{model.text}</reply><status emotion="平静" affection_change="2"/>')
                return await model(stage, parameters)
            return await background.submit_group_operation(session_id, request_id, kind, revision, db, call_model=shared, **options)
        dispatch_patch = patch("routers.group_sessions.submit_group_operation", side_effect=dispatch)
        dispatch_patch.start()
        self.addCleanup(dispatch_patch.stop)
        self.sid = self.create()

    def create(self):
        result = self.client.post("/group-sessions", json={"members": [
            {"character_id": 1, "origin": {"mode": "card"}}, {"character_id": 2, "origin": {"mode": "card"}}]})
        self.assertEqual(200, result.status_code, result.text)
        return result.json()["session_id"]

    def command(self, sid=None, **changes):
        sid = sid or self.sid
        state = self.client.get(f"/group-sessions/{sid}/rounds").json()["current"]
        seen = state["latest"] or {}
        return {"client_request_id": str(uuid4()), "expected_group_revision": state["group_revision"],
                "observed_round_id": seen.get("round_id"), "observed_candidate_id": seen.get("candidate_id"),
                "observed_candidate_revision": seen.get("candidate_revision"), **changes}

    def send(self, **changes):
        body = self.command(user_content="  hello  ", model="fixture", **changes)
        response = self.client.post(f"/group-sessions/{self.sid}/rounds", json=body)
        self.assertEqual(202, response.status_code, response.text)
        return body, response.json()

    def done(self, request_id, sid=None):
        for _ in range(300):
            response = self.client.get(f"/group-sessions/{sid or self.sid}/requests/{request_id}")
            self.assertEqual(200, response.status_code, response.text)
            result = response.json()
            if result["status"] in ("succeeded", "failed"):
                return result
            time.sleep(0.01)
        self.fail("background operation did not finish")

    def test_stale_delete_cannot_target_replacement_group(self):
        old_url = f"/group-sessions/{self.sid}/delete"
        self.assertEqual(200, self.client.post(old_url).status_code)
        new_id = self.create()
        self.assertNotEqual(self.sid, new_id)
        self.assertEqual(404, self.client.post(old_url).status_code)
        self.assertEqual(200, self.client.get(f"/group-sessions/{new_id}").status_code)

    def test_send_receipt_readonly_query_and_candidate_projection(self):
        body, receipt = self.send()
        result = self.done(body["client_request_id"])
        self.assertEqual("succeeded", result["status"])
        rid, cid = receipt["accepted"]["round_id"], receipt["accepted"]["candidate_id"]
        self.assertEqual("  hello  ", result["round"]["user_content"])
        self.assertTrue(result["can_generate"])
        before = (result["revision"], result["call_count"], result["deadline_at"], result["current"]["group_revision"])
        for _ in range(2):
            query = self.client.get(f"/group-sessions/{self.sid}/requests/{body['client_request_id']}").json()
            self.assertEqual(before, (query["revision"], query["call_count"], query["deadline_at"], query["current"]["group_revision"]))
        view = self.client.get(f"/group-sessions/{self.sid}/rounds/{rid}/candidates/{cid}").json()
        self.assertEqual(cid, view["state_preview"]["candidate_id"])
        self.assertEqual(2, view["state_preview"]["members"][0]["affection_score"])
        self.assertEqual(0, self.client.get(f"/group-sessions/{self.sid}").json()["members"][0]["state"]["affection_score"])
        for field in ("call_snapshot_json", "provider_fingerprint", "decision_json", "role_state_patch", "recipients", "reasoning_content"):
            self.assertNotIn(field, json.dumps(view))
        duplicate = self.client.post(f"/group-sessions/{self.sid}/rounds", json=body)
        self.assertEqual(202, duplicate.status_code)
        self.assertEqual(receipt["operation_id"], duplicate.json()["operation_id"])
        changed = {**body, "user_content": "changed"}
        self.assertEqual(409, self.client.post(f"/group-sessions/{self.sid}/rounds", json=changed).status_code)

    def test_member_prompt_reuses_xml_context_and_old_resume_is_frozen(self):
        self.assertEqual(422, self.client.get(f'/group-sessions/{self.sid}/members/1/compile_prompt').status_code)
        body, receipt = self.send()
        self.done(body['client_request_id'])
        member = self.client.get(f'/group-sessions/{self.sid}').json()['members'][0]['persona_id']
        path = f'/group-sessions/{self.sid}/members/{member}/compile_prompt'
        response = self.client.get(path)
        self.assertEqual(200, response.status_code, response.text)
        self.assertIn('<reply>', json.dumps(response.json()['messages']))
        self.assertEqual(422, self.client.get(f'/group-sessions/{self.sid}/members/999999/compile_prompt').status_code)
        with patch.object(settings, 'ACCESS_API_KEY', 'test-key'):
            self.assertEqual(403, self.client.get(path).status_code)
        cid = receipt['accepted']['candidate_id']
        self.db.expire_all()
        candidate = self.db.get(GroupRoundCandidate, cid)
        frozen = json.loads(candidate.call_snapshot_json)
        frozen.pop('shared_chat')
        candidate.call_snapshot_json = json.dumps(frozen)
        self.db.commit()
        calls = sum(len(model.calls) for model in self.models)
        response = self.client.post(f"/group-sessions/{self.sid}/rounds/{candidate.round_id}/resume",
            json=self.command(target_candidate_id=cid, target_candidate_revision=candidate.revision))
        self.assertEqual(409, response.status_code, response.text)
        self.assertIn('冻结', response.json()['detail'])
        self.assertEqual(calls, sum(len(model.calls) for model in self.models))

    def test_regenerate_resume_select_and_discard_preserve_identities_and_old_receipts(self):
        body, first = self.send()
        self.done(body["client_request_id"])
        rid, a = first["accepted"]["round_id"], first["accepted"]["candidate_id"]
        prefix = f"/group-sessions/{self.sid}/rounds/{rid}"
        self.fail_stage = "role_generation"
        command = self.command(model="fixture")
        failed = self.client.post(prefix+"/regenerate", json=command)
        self.assertEqual(202, failed.status_code, failed.text)
        failure = self.done(command["client_request_id"])
        b = failure["candidate"]["candidate_id"]
        self.assertTrue(failure["candidate"]["can_resume"])
        self.assertEqual(a, failure["current"]["latest"]["candidate_id"])
        self.fail_stage = None
        resume = self.command(target_candidate_id=b, target_candidate_revision=failure["candidate"]["revision"])
        result = self.client.post(prefix+"/resume", json=resume)
        self.assertEqual(202, result.status_code, result.text)
        success = self.done(resume["client_request_id"])
        self.assertEqual(b, success["current"]["latest"]["candidate_id"])
        view = self.client.get(prefix+f"/candidates/{b}").json()
        self.assertEqual(2, view["state_preview"]["members"][0]["affection_score"])
        a_revision = self.client.get(prefix+f"/candidates/{a}").json()["candidate"]["revision"]
        select = self.command(target_candidate_id=a, target_candidate_revision=a_revision)
        self.assertEqual(200, self.client.post(prefix+"/select-candidate", json=select).status_code)
        self.assertEqual(409, self.client.post(prefix+"/select-candidate", json={**select,"client_request_id":str(uuid4())}).status_code)
        discard = self.command()
        self.assertEqual(200, self.client.post(prefix+"/discard", json=discard).status_code)
        self.assertEqual(0, self.client.get(f"/group-sessions/{self.sid}/rounds").json()["total"])
        old = self.client.get(f"/group-sessions/{self.sid}/requests/{body['client_request_id']}").json()
        self.assertIsNotNone(old["round"]["discarded_at"])
        self.assertEqual(202, self.client.post(f"/group-sessions/{self.sid}/rounds", json=body).status_code)
        self.assertEqual(0, self.client.get(f"/group-sessions/{self.sid}/rounds").json()["total"])

    def test_bad_structures_do_not_accept_or_confirm(self):
        base = self.command(user_content="hello")
        for change in ({"client_request_id":"bad"}, {"expected_group_revision":True}, {"user_content":" "},
                       {"user_content":"x"*20001}, {"max_steps":7}, {"max_steps":True}, {"extra":1},
                       {"observed_candidate_id":9}, {"thinking_mode":"unknown"}):
            with self.subTest(change=list(change)):
                response = self.client.post(f"/group-sessions/{self.sid}/rounds", json={**base, **change})
                self.assertEqual(422, response.status_code, response.text)
        self.db.expire_all()
        self.assertEqual(0, self.db.query(GroupRoundOperation).count())

    def test_group_round_and_candidate_ownership_and_stale_versions(self):
        body, first = self.send()
        self.done(body["client_request_id"])
        rid, cid = first["accepted"]["round_id"], first["accepted"]["candidate_id"]
        other = self.create()
        path = f"/group-sessions/{other}/rounds/{rid}"
        self.assertEqual(404, self.client.get(path+"/candidates").status_code)
        self.assertEqual(404, self.client.get(f"/group-sessions/{other}/requests/{body['client_request_id']}").status_code)
        command = self.command(other, observed_round_id=rid, observed_candidate_id=cid, observed_candidate_revision=1)
        self.assertEqual(404, self.client.post(path+"/discard", json=command).status_code)
        bad = self.command(target_candidate_id=99999, target_candidate_revision=0)
        self.assertEqual(404, self.client.post(f"/group-sessions/{self.sid}/rounds/{rid}/resume", json=bad).status_code)
        stale = self.command(user_content="next", expected_group_revision=0)
        self.assertEqual(409, self.client.post(f"/group-sessions/{self.sid}/rounds", json=stale).status_code)
        self.assertEqual(404, self.client.get(f"/group-sessions/{self.sid}/rounds/{rid}/candidates/99999").status_code)
        self.assertEqual(409, self.client.get("/group-sessions/10/rounds/1/candidates").status_code)
        self.assertEqual(404, self.client.get(f"/group-sessions/{self.sid}/requests/{uuid4()}").status_code)

    def test_authentication_covers_all_new_routes_and_runtime_unavailability(self):
        base = f"/group-sessions/{self.sid}"
        routes = [("POST",base+suffix) for suffix in ("/rounds", "/rounds/1/regenerate", "/rounds/1/resume", "/rounds/1/select-candidate", "/rounds/1/discard")]
        routes += [("GET",base+suffix) for suffix in (f"/requests/{uuid4()}", "/rounds/1/candidates", "/rounds/1/candidates/1")]
        with patch.object(settings, "ACCESS_API_KEY", "test-key"):
            for method, path in routes:
                self.assertEqual(403, self.client.request(method, path).status_code)
            self.assertEqual(200, self.client.get(base, headers={"X-API-Key":"test-key"}).status_code)
        owner = self.app.state.group_runtime_owner
        with patch.object(owner, "active", False):
            self.assertFalse(self.client.get(base).json()["can_generate"])
            self.assertEqual(503, self.client.post(base+"/rounds", json=self.command(user_content="hello")).status_code)

    def test_active_task_blocks_new_writes_but_allows_reads_and_exact_replay(self):
        import threading
        entered = threading.Event()
        async def make_gate():
            return asyncio.Event()
        release = self.client.portal.call(make_gate)
        async def dispatch(session_id, request_id, kind, revision, db, **options):
            from services.conversation.group_history_service import _members
            with self.sessions() as read:
                model = models.Model(tuple(sorted(_members(session_id, read))), user=options["user_content"])
            async def hold(stage, parameters):
                if stage == "next_action":
                    entered.set()
                    await release.wait()
                if stage == 'role_generation':
                    model.saved += 1
                    return models._response('<reply>回复</reply><status emotion="平静" affection_change="2"/>')
                return await model(stage, parameters)
            return await background.submit_group_operation(session_id, request_id, kind, revision, db, call_model=hold, **options)
        body = self.command(user_content="hello", model="fixture")
        base = f"/group-sessions/{self.sid}"
        with patch("routers.group_sessions.submit_group_operation", side_effect=dispatch):
            try:
                first = self.client.post(base+"/rounds", json=body)
                self.assertEqual(202, first.status_code, first.text)
                self.assertTrue(entered.wait(3))
                status = self.client.get(base+f"/requests/{body['client_request_id']}").json()
                self.assertFalse(status["current"]["capabilities"]["can_send"])
                duplicate = self.client.post(base+"/rounds", json=body)
                self.assertEqual(first.json()["operation_id"], duplicate.json()["operation_id"])
                rid = first.json()["accepted"]["round_id"]
                self.assertEqual(200, self.client.get(base+f"/rounds/{rid}/candidates").status_code)
                pending = self.command()
                self.assertEqual(409, self.client.post(base+f"/rounds/{rid}/discard", json=pending).status_code)
                self.assertEqual(409, self.client.post(base+"/delete").status_code)
                send = self.command(user_content="new", model="fixture")
                self.assertEqual(409, self.client.post(base+"/rounds", json=send).status_code)
                self.assertEqual(404, self.client.get(base+f"/requests/{send['client_request_id']}").status_code)
                later = self.client.get(base+f"/requests/{body['client_request_id']}").json()
                self.assertEqual((status["deadline_at"],status["call_count"]), (later["deadline_at"],later["call_count"]))
            finally:
                self.client.portal.call(release.set)
            self.assertEqual("succeeded", self.done(body["client_request_id"])["status"])

    def test_cross_round_candidate_rejects_before_acceptance(self):
        body, first = self.send()
        self.done(body["client_request_id"])
        body2, second = self.send()
        self.done(body2["client_request_id"])
        rid = second["accepted"]["round_id"]
        command = self.command(target_candidate_id=first["accepted"]["candidate_id"], target_candidate_revision=1)
        response = self.client.post(f"/group-sessions/{self.sid}/rounds/{rid}/select-candidate", json=command)
        self.assertEqual(404, response.status_code, response.text)
        self.db.expire_all()
        self.assertEqual(2, self.db.query(GroupRoundOperation).count())
        old = self.client.get(f"/group-sessions/{self.sid}/rounds/{first['accepted']['round_id']}/candidates").json()
        self.assertFalse(old["candidates"][0]["can_select"])

    def test_invalid_model_does_not_confirm_or_consume_uuid_and_corrected_request_can_accept(self):
        body, first = self.send()
        self.done(body["client_request_id"])
        command = self.command(user_content="next", model="o3", thinking_mode="disabled")
        response = self.client.post(f"/group-sessions/{self.sid}/rounds", json=command)
        self.assertEqual(422, response.status_code, response.text)
        self.db.expire_all()
        self.assertIsNone(self.db.get(GroupRound, first["accepted"]["round_id"]).confirmed_at)
        command["model"] = "fixture"
        corrected = self.client.post(f"/group-sessions/{self.sid}/rounds", json=command)
        self.assertEqual(202, corrected.status_code, corrected.text)
        self.done(command["client_request_id"])

    def test_integer_body_limits_reject_before_dispatch_or_confirmation(self):
        body, first = self.send()
        self.done(body["client_request_id"])
        rid = first["accepted"]["round_id"]
        command = self.command(user_content="next", model="fixture")
        selected = self.command(target_candidate_id=first["accepted"]["candidate_id"], target_candidate_revision=4)
        baseline_models = len(self.models)
        for value in (SQLITE_INT_MAX+1, 2**80):
            for field in ("expected_group_revision", "observed_round_id", "observed_candidate_id", "observed_candidate_revision"):
                with self.subTest(field=field, value=value):
                    response = self.client.post(f"/group-sessions/{self.sid}/rounds", json={**command, field:value})
                    self.assertEqual(422, response.status_code, response.text)
                    self.assertIn(["body", field], [error["loc"] for error in response.json()["detail"]])
            for field in ("target_candidate_id", "target_candidate_revision"):
                for operation in ("resume", "select-candidate"):
                    with self.subTest(field=field, operation=operation):
                        response = self.client.post(f"/group-sessions/{self.sid}/rounds/{rid}/{operation}", json={**selected, field:value})
                        self.assertEqual(422, response.status_code, response.text)
        self.db.expire_all()
        self.assertIsNone(self.db.get(GroupRound, rid).confirmed_at)
        self.assertEqual(1, self.db.query(GroupRoundOperation).count())
        self.assertEqual(baseline_models, len(self.models))
        self.assertEqual(404, self.client.get(f"/group-sessions/{self.sid}/requests/{command['client_request_id']}").status_code)

    def test_integer_path_and_offset_limits_return_422_and_accept_the_maximum(self):
        body, first = self.send()
        self.done(body["client_request_id"])
        rid, cid = first["accepted"]["round_id"], first["accepted"]["candidate_id"]
        base = f"/group-sessions/{self.sid}"
        for value in (SQLITE_INT_MAX+1, 2**80):
            paths = (f"/group-sessions/{value}", f"/group-sessions/{value}/requests/{body['client_request_id']}",
                     base+f"/rounds/{value}/candidates", base+f"/rounds/{rid}/candidates/{value}",
                     f"/group-sessions?offset={value}", base+f"/rounds?offset={value}",
                     base+f"/rounds/{rid}/candidates?offset={value}")
            for path in paths:
                with self.subTest(path=path):
                    self.assertEqual(422, self.client.get(path).status_code)
            self.assertEqual(422, self.client.post(f"/group-sessions/{value}/rounds", json=self.command(user_content="next")).status_code)
            self.assertEqual(422, self.client.post(base+f"/rounds/{value}/discard", json=self.command()).status_code)
        for path in (f"/group-sessions/{SQLITE_INT_MAX}", base+f"/rounds/{SQLITE_INT_MAX}/candidates",
                     base+f"/rounds/{rid}/candidates/{SQLITE_INT_MAX}"):
            self.assertEqual(404, self.client.get(path).status_code)
        for path in (f"/group-sessions?offset={SQLITE_INT_MAX}", base+f"/rounds?offset={SQLITE_INT_MAX}",
                     base+f"/rounds/{rid}/candidates?offset={SQLITE_INT_MAX}"):
            response = self.client.get(path)
            self.assertEqual(200, response.status_code, response.text)
            self.assertFalse(response.json()["has_more"])
        selection = self.command(target_candidate_id=SQLITE_INT_MAX, target_candidate_revision=0)
        self.assertEqual(404, self.client.post(base+f"/rounds/{rid}/select-candidate", json=selection).status_code)

    def test_integer_member_and_source_ids_are_validated_before_resource_loading(self):
        for value in (SQLITE_INT_MAX+1, 2**80):
            for member in ({"character_id":value,"origin":{"mode":"card"}},
                           {"character_id":1,"origin":{"mode":"single_snapshot","session_id":value}}):
                response = self.client.post("/group-sessions", json={"members":[member,
                    {"character_id":2,"origin":{"mode":"card"}}]})
                self.assertEqual(422, response.status_code, response.text)
        self.db.expire_all()
        self.assertEqual(1, self.db.query(Session).filter_by(kind="group").count())
