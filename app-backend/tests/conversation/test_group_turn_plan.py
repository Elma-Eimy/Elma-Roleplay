"""请求通道、承接依据与提交前审查，使用隔离数据库和确定性模型。"""
import asyncio
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from application.group_runtime import group_runtime
from core.config import settings
from core.models import Character, GroupRound, GroupRoundCandidate, GroupContentItem, GroupDirectorStep
from scripts.group_chat_prototype.worker import _response
from services.conversation import group_history_service as history, group_session_service as groups
from services.conversation import group_background_service as background
from services.conversation.group_director_service import NextAction, parse_next_action, GroupDirectorError, DirectorContext, build_director_messages
from services.conversation.group_context_service import build_member_context
from services.conversation.group_round_service import run_group_round
from services.conversation.group_turn_plan import _sources
from services.conversation.group_unit_protocol import parse_user_units, parse_unit_visibility, GroupUnitError, UnitPlan, ContentUnit
from services.conversation.group_call_snapshot import capture_group_calls, persist_group_calls, restore_group_calls
from services.conversation.session_access import SessionKindConflict
from tests.conversation import test_group_units as fixtures


class GroupTurnPlanTests(unittest.TestCase):
    setUp = fixtures.GroupUnitTests.setUp

    def create(self):
        group = asyncio.run(groups.create_group_session(self.cards, self.db))
        self.sid = group["session_id"]
        self.ids = tuple(member["persona_id"] for member in group["members"])

    def plan(self, content="请甲接话。PRIVATE_93", *, meaning="request"):
        rows = [{"start": 0, "end": 5, "meaning": meaning, "request_to": [self.ids[0]] if meaning == "request" else [],
            "recipients": [{"persona_id": pid, "decision": "hidden"} for pid in self.ids]},
            {"start": 5, "end": len(content), "meaning": "private", "request_to": [],
             "recipients": [{"persona_id": pid, "decision": "hidden"} for pid in self.ids]}]
        return parse_user_units(json.dumps({"units": rows}), content, self.ids, require_meaning=True)

    def prepare(self):
        self.create()
        content = "请甲接话。PRIVATE_93"
        result = history._prepare(self.sid, content, (), self.db, unit_plan=self.plan(content), model="fixture")
        return result

    def test_request_is_available_without_granting_perception_or_private_text(self):
        target = self.prepare()
        round_ = self.db.get(GroupRound, target["round_id"])
        candidate = self.db.get(GroupRoundCandidate, target["candidate_id"])
        self.assertEqual((), history._member_history(self.sid, self.ids[0], round_, candidate, 99, 10, self.db))
        available = _sources(self.sid, self.ids[0], round_, candidate, 99, self.db)
        self.assertEqual(1, len(available))
        self.assertEqual("请甲接话。", next(iter(available.values()))["content"])
        self.assertEqual({}, _sources(self.sid, self.ids[1], round_, candidate, 99, self.db))
        self.db.rollback()
        context = build_member_context(self.sid, self.ids[0], candidate.id, candidate.revision, self.db)
        self.assertIn("请甲接话。", context.messages_json)
        self.assertNotIn("PRIVATE_93", context.messages_json)
        with self.assertRaises(groups.GroupSessionValidationError):
            build_member_context(self.sid, self.ids[1], candidate.id, candidate.revision, self.db)

    def test_private_units_cannot_become_requests_or_public_knowledge(self):
        self.create()
        plan = self.plan()
        value = plan.decision(self.ids)
        rows = [{key: field for key, field in row.items() if key != "unit_index"} for row in value["units"]]
        for changes in ({"request_to": [self.ids[1]]}, {"recipients": [
                {"persona_id": pid, "decision": "visible"} for pid in self.ids]}):
            with self.subTest(changes=changes), self.assertRaises(GroupUnitError):
                parse_user_units(json.dumps({"units": [rows[0], {**rows[1], **changes}]}), "请甲接话。PRIVATE_93", self.ids)

    def test_lorebook_uses_allowed_requests_without_scanning_private_fragments(self):
        target = self.prepare()
        self.db.get(Character, 1).extensions = json.dumps({"character_book": {"scan_depth": 0, "entries": [
            {"keys": ["请甲"], "content": "ALLOWED_REQUEST_LORE", "enabled": True},
            {"keys": ["PRIVATE_93"], "content": "FORBIDDEN_PRIVATE_LORE", "enabled": True}]}})
        self.db.commit()
        context = build_member_context(self.sid, self.ids[0], target["candidate_id"], target["revision"], self.db)
        self.assertIn("ALLOWED_REQUEST_LORE", context.messages_json)
        self.assertNotIn("FORBIDDEN_PRIVATE_LORE", context.messages_json)
        self.assertNotIn("PRIVATE_93", context.messages_json)

    def test_basis_must_be_accessible_and_is_persisted_before_generation(self):
        target = self.prepare()
        candidate = self.db.get(GroupRoundCandidate, target["candidate_id"])
        round_ = self.db.get(GroupRound, target["round_id"])
        reference = next(iter(_sources(self.sid, self.ids[0], round_, candidate, 99, self.db)))
        self.db.rollback()
        for pid, basis in ((self.ids[1], reference), (self.ids[0], "item:999999"), (self.ids[0], None)):
            with self.subTest(pid=pid, basis=basis), self.assertRaises(SessionKindConflict):
                history._accept_action(self.sid, candidate.id, candidate.revision, NextAction("speak", pid, "direct_response", basis), "fixture", self.db)
        self.assertEqual(1, self.db.query(GroupDirectorStep).count())
        self.db.rollback()
        accepted = history._accept_action(self.sid, candidate.id, candidate.revision,
            NextAction("speak", self.ids[0], "direct_response", reference), "fixture", self.db)
        context = build_member_context(self.sid, self.ids[0], candidate.id, accepted["revision"], self.db)
        self.assertIn("本次承接依据", context.messages_json)
        self.assertNotIn(reference, context.messages_json)
        plan = UnitPlan((ContentUnit("speech", "答复"),), ((self.ids[0],),), review="ok")
        saved = history._append(self.sid, candidate.id, self.ids[0], "答复", (self.ids[0],),
            accepted["revision"], self.db, unit_plan=plan, model="fixture")
        self.db.expire_all()
        sources = _sources(self.sid, self.ids[0], round_, candidate, 99, self.db)
        self.assertNotIn(reference, sources)
        self.db.rollback()
        with self.assertRaises(SessionKindConflict):
            history._accept_action(self.sid, candidate.id, saved["revision"],
                NextAction("speak", self.ids[0], "direct_response", reference), "fixture", self.db)
        follow_up = NextAction("speak", self.ids[0], "follow_up", next(iter(sources)))
        accepted = history._accept_action(self.sid, candidate.id, saved["revision"], follow_up, "fixture", self.db)
        context = build_member_context(self.sid, self.ids[0], candidate.id, accepted["revision"], self.db)
        self.assertIn("答复", context.messages_json)
        self.assertNotIn("请甲接话。", context.messages_json)

    def test_observed_nod_allows_follow_up_without_answering_spoken_request(self):
        self.create()
        a, b = self.ids[:2]
        recipients = [{"persona_id": pid, "decision": "hidden"} for pid in self.ids]
        content = "请甲说说理由。"
        raw = {"units": [{"start": 0, "end": len(content), "meaning": "request",
                          "reply_mode": "speech", "request_to": [a], "recipients": recipients}]}
        plan = parse_user_units(json.dumps(raw), content, self.ids, require_reply_mode=True)
        target = history._prepare(self.sid, content, (), self.db, unit_plan=plan, model="fixture")
        round_ = self.db.get(GroupRound, target["round_id"])
        candidate = self.db.get(GroupRoundCandidate, target["candidate_id"])
        ref, = _sources(self.sid, a, round_, candidate, 99, self.db)
        accepted = history._accept_action(self.sid, candidate.id, target["revision"],
            NextAction("speak", a, "direct_response", ref), "fixture", self.db)
        units = (ContentUnit("action", "点头"), ContentUnit("thought", "HIDDEN_THOUGHT_72"))
        visible = [{"persona_id": pid, "decision": "visible" if pid in (a, b) else "hidden"} for pid in self.ids]
        own = [{"persona_id": pid, "decision": "visible" if pid == a else "hidden"} for pid in self.ids]
        review = {"review": "ok", "request_result": "fulfilled", "units": [
            {"unit_index": 0, "recipients": visible}, {"unit_index": 1, "recipients": own}]}
        decision = parse_unit_visibility(json.dumps(review), units, self.ids, a, reply_mode="speech")
        self.assertEqual("pending", decision.request_result)
        self.assertEqual("fulfilled", parse_unit_visibility(json.dumps(review), units, self.ids, a, reply_mode="action").request_result)
        saved = history._append(self.sid, candidate.id, a, "点头HIDDEN_THOUGHT_72", (a,), accepted["revision"],
            self.db, unit_plan=decision, model="fixture")
        self.assertIn(ref, _sources(self.sid, a, round_, candidate, 99, self.db))
        options = _sources(self.sid, b, round_, candidate, 99, self.db)
        basis, = options
        self.assertEqual([{"kind": "action", "text": "点头"}], options[basis]["units"])
        accepted = history._accept_action(self.sid, candidate.id, saved["revision"],
            NextAction("speak", b, "follow_up", basis), "fixture", self.db)
        context = build_member_context(self.sid, b, candidate.id, accepted["revision"], self.db)
        messages = json.loads(context.messages_json)
        boundary = json.loads(messages[-1]["content"].split("\n")[1])
        self.assertEqual([], boundary["visible_current_turn_speakers"])
        self.assertNotIn("HIDDEN_THOUGHT_72", context.messages_json)
        self.assertNotIn(content, context.messages_json)

    def test_selector_rejects_a_forged_source_even_for_eligible_speaker(self):
        self.create()
        body = dict(action="speak", speaker_persona_id=self.ids[0], reason_code="direct_response", basis="item:99")
        with self.assertRaises(GroupDirectorError):
            parse_next_action(json.dumps(body), self.ids, self.ids,
                response_sources={str(self.ids[0]): {"item:1": {}}})

    def test_snapshot_restores_policy_after_configuration_changes(self):
        self.create()
        with patch.object(settings, "APP_GROUP_TURN_PLANNING", True):
            snapshot = capture_group_calls(self.sid, self.db, model="fixture")
        encoded, fingerprint = persist_group_calls(snapshot, 2, set(self.ids))
        candidate = GroupRoundCandidate(protocol_version=2, call_snapshot_json=encoded, provider_fingerprint=fingerprint)
        with patch.object(settings, "APP_GROUP_TURN_PLANNING", False):
            restored, maximum = restore_group_calls(candidate, set(self.ids))
        self.assertEqual((2, 2), (restored.turn_policy, maximum))
        legacy = json.loads(encoded)
        legacy["turn_policy"] = 1
        candidate.call_snapshot_json = json.dumps(legacy)
        self.assertEqual(1, restore_group_calls(candidate, set(self.ids))[0].turn_policy)
        legacy = json.loads(encoded)
        del legacy["turn_policy"]
        candidate.call_snapshot_json = json.dumps(legacy)
        restored, _ = restore_group_calls(candidate, set(self.ids))
        self.assertEqual(0, restored.turn_policy)

    def test_json_format_is_frozen_and_unknown_format_is_rejected(self):
        self.create()
        with patch.object(settings, "LLM_GROUP_JSON_MODE", True):
            snapshot = capture_group_calls(self.sid, self.db, model="fixture")
        encoded, fingerprint = persist_group_calls(snapshot, 2, set(self.ids))
        self.assertEqual({"type": "json_object"}, json.loads(encoded)["director"]["response_format"])
        value = json.loads(encoded)
        value["director"]["response_format"] = {"type": "untrusted"}
        candidate = GroupRoundCandidate(protocol_version=2, call_snapshot_json=json.dumps(value), provider_fingerprint=fingerprint)
        with self.assertRaises(groups.GroupSessionValidationError):
            restore_group_calls(candidate, set(self.ids))

    def test_trimming_history_also_trims_basis_options(self):
        history_rows = [{"reference": f"item:{index}", "content": "旧事件" * 20} for index in range(1, 20)]
        history_rows.append({"reference": "item:20", "content": "当前事实"})
        sources = {"7": {row["reference"]: {"source": "user"} for row in history_rows}, "9": {}}
        payload = {"history": history_rows, "history_incomplete": False, "eligible_persona_ids": [7], "response_sources": sources}
        context = DirectorContext(json.dumps(payload, ensure_ascii=False), (7, 9), (7,), 800, 1, sources)
        messages = build_director_messages(context, "next_action", protocol_version=2, turn_policy=1)
        actual = json.loads(messages[1]["content"])
        self.assertTrue(actual["history_incomplete"])
        self.assertEqual("item:20", actual["history"][-1]["reference"])
        self.assertEqual({row["reference"] for row in actual["history"]}, set(actual["response_sources"]["7"]))

    def test_explicit_legacy_protocol_keeps_xml_roles_with_new_settings(self):
        self.create()
        async def model(stage, parameters):
            if stage == "role_generation":
                self.assertNotIn("response_format", parameters)
                return _response('<reply>答复</reply><status emotion="平静" affection_change="0"/>')
            self.assertNotIn("request_to", parameters["messages"][0]["content"])
            if stage == "next_action":
                return _response(json.dumps(dict(action="speak", speaker_persona_id=self.ids[0], reason_code="direct_response")))
            return _response(json.dumps({"recipients": [{"persona_id": pid, "decision": "visible"} for pid in self.ids]}))
        with patch.object(settings, "APP_GROUP_TURN_PLANNING", True), patch.object(settings, "LLM_GROUP_JSON_MODE", True), group_runtime(self.engine) as owner:
            result = asyncio.run(run_group_round(self.sid, "你好", self.db, runtime=owner, model="fixture",
                max_steps=1, protocol_version=1, call_model=model))
        self.assertIsNone(result["error_code"])

    def test_rejected_reply_stays_uncommitted_and_resumes_with_original_basis(self):
        self.create()
        calls = []
        reject = True
        async def model(stage, parameters):
            nonlocal reject
            calls.append(stage)
            if stage == "user_visibility":
                return _response(json.dumps({"units": [{"start": 0, "end": 5, "meaning": "request", "reply_mode": "speech", "request_to": [self.ids[0]],
                    "recipients": [{"persona_id": pid, "decision": "hidden"} for pid in self.ids]}]}))
            if stage == "next_action":
                scene = json.loads(parameters["messages"][1]["content"])
                if len(scene["history"]) > 1:
                    return _response('{"action":"end","reason_code":"wait_user"}')
                return _response(json.dumps(dict(action="speak", speaker_persona_id=self.ids[0], reason_code="direct_response",
                    basis=next(iter(scene["response_sources"][str(self.ids[0])])))))
            if stage == "role_generation":
                self.assertIn("待执行安排", json.dumps(parameters["messages"], ensure_ascii=False))
                return _response('{"units":[{"kind":"speech","text":"我愿意。"}],"status":{"emotion":"平静","affection_change":1}}')
            return _response(json.dumps({"request_result": "fulfilled", "review": "agency_conflict" if reject else "ok", "units": [{"unit_index": 0,
                "recipients": [{"persona_id": pid, "decision": "visible"} for pid in self.ids]}]}))

        async def scenario(owner):
            first = await background.submit_group_operation(self.sid, str(uuid4()), "send", 0, self.db,
                runtime=owner, call_model=model, user_content="请甲接话。", max_steps=2, model="fixture")
            while owner.tasks:
                await asyncio.gather(*tuple(owner.tasks), return_exceptions=True)
            self.db.expire_all()
            cid = first["accepted"]["candidate_id"]
            candidate = self.db.get(GroupRoundCandidate, cid)
            self.assertEqual(("failed", "role_generation", "agency_conflict"), (candidate.status, candidate.checkpoint, candidate.error_code))
            self.assertEqual(0, self.db.query(GroupContentItem).filter_by(candidate_id=cid, kind="utterance").count())
            before = calls.count("user_visibility"), calls.count("next_action")
            group = history._require_group(self.sid, self.db)
            nonlocal reject
            reject = False
            with patch.object(settings, "APP_GROUP_TURN_PLANNING", False):
                await background.submit_group_operation(self.sid, str(uuid4()), "resume", group.group_revision, self.db,
                    runtime=owner, call_model=model, round_id=candidate.round_id, target_candidate_id=cid,
                    target_candidate_revision=candidate.revision, observed_round_id=candidate.round_id,
                    observed_candidate_id=cid, observed_candidate_revision=candidate.revision)
                while owner.tasks:
                    await asyncio.gather(*tuple(owner.tasks), return_exceptions=True)
            self.db.expire_all()
            self.assertEqual("awaiting_confirmation", self.db.get(GroupRoundCandidate, cid).status)
            self.assertEqual(before[0], calls.count("user_visibility"))
            self.assertEqual(before[1] + 1, calls.count("next_action"))
            self.assertEqual(1, self.db.query(GroupContentItem).filter_by(candidate_id=cid, kind="utterance").count())
        with patch.object(settings, "APP_GROUP_TURN_PLANNING", True), group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))
