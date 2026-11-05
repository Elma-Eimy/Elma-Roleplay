"""单元隔离、一次状态重放和导演审计的临时库回归。"""
import asyncio
from datetime import datetime
import json
import unittest
from unittest.mock import patch


from application.group_runtime import group_runtime
from core.models import (Character, GroupRound, GroupRoundCandidate, GroupContentItem, GroupContentVisibility,
                         GroupContentUnit, GroupUnitVisibility, GroupDirectorStep)
from core.models import ChatMessage, MessageRole
from services.conversation import group_history_service as history, group_generation_service as generation
from services.conversation import group_audit_service as audit
from services.conversation import group_session_service as groups
from services.conversation.session_access import SessionKindConflict
from services.conversation.group_context_service import build_member_context
from services.conversation.group_director_service import NextAction, build_director_context
from services.conversation.group_round_service import run_group_round
from services.conversation.group_session_service import create_group_session
from services.conversation.group_unit_protocol import (ContentUnit, UnitPlan, GroupUnitError, parse_user_units,
    parse_unit_visibility, load_object)
from scripts.group_chat_prototype.worker import _response
from tests.conversation import test_group_session_service as fixtures


class GroupUnitTests(unittest.TestCase):
    setUp = fixtures.GroupSessionServiceTests.setUp

    def group(self, user="😀公开。秘密{{char}}<raw>"):
        result = asyncio.run(create_group_session(self.imported, self.db))
        self.sid = result["session_id"]
        self.a, self.b = [row["persona_id"] for row in result["members"]]
        self.user = user
        self.plan = UnitPlan((ContentUnit("user", start=0, end=4), ContentUnit("user", start=4, end=len(user))),
                             ((self.a, self.b), (self.a,)))
        self.target = history._prepare(self.sid, user, (self.a,), self.db, unit_plan=self.plan, model="fixture")

    def append(self, speaker=None, *, patch_value=None, affection=2):
        speaker = speaker or self.a
        plan = UnitPlan((ContentUnit("speech", "桥坏了。"), ContentUnit("thought", "PRIVATE_THOUGHT")),
                        ((self.a, self.b), (speaker,)))
        result = history._append(self.sid, self.target["candidate_id"], speaker,
            "桥坏了。PRIVATE_THOUGHT", (speaker,), self.target["revision"], self.db,
            emotion_tag="紧张", affection_change=affection, role_state_patch=patch_value, unit_plan=plan, model="fixture")
        self.target["revision"] = result["revision"]
        return result

    def personal(self, pid, **kwargs):
        return history.get_member_history(self.sid, pid, self.target["candidate_id"], 100, self.db, **kwargs)

    def test_mixed_user_is_original_codepoint_slices_and_hidden_text_never_enters_prompt(self):
        self.group()
        self.assertEqual(self.user, self.personal(self.a)[0].content)
        self.assertEqual("😀公开。", self.personal(self.b)[0].content)
        ctx = build_member_context(self.sid, self.b, self.target["candidate_id"], 1, self.db)
        messages = json.loads(ctx.messages_json)
        self.assertEqual(["😀公开。"], [row["content"] for row in messages if row["role"] == "user"])
        self.assertNotIn("秘密{{char}}<raw>", ctx.messages_json)
        self.assertNotIn("unit_index", ctx.messages_json)
        self.assertEqual(self.user, self.db.get(GroupRound, self.target["round_id"]).user_content)

    def test_public_speech_survives_and_private_thought_is_filtered_before_limit(self):
        self.group()
        self.append()
        self.assertEqual(["桥坏了。"], [row.content for row in self.personal(self.b, limit=1)])
        self.assertEqual("桥坏了。PRIVATE_THOUGHT", self.personal(self.a)[-1].content)
        ctx = build_member_context(self.sid, self.b, self.target["candidate_id"], 2, self.db)
        self.assertIn("桥坏了。", ctx.messages_json)
        self.assertNotIn("PRIVATE_THOUGHT", ctx.messages_json)
        self.assertNotIn("decision_json", ctx.messages_json)
        scene = build_director_context(self.sid, self.db, candidate_id=self.target["candidate_id"], expected_revision=2)
        self.assertIn("PRIVATE_THOUGHT", scene.payload_json)
        self.assertNotIn("decision_json", scene.payload_json)

    def test_missing_units_or_grants_never_fall_back_to_parent_fulltext(self):
        self.group()
        self.append()
        self.db.query(GroupUnitVisibility).filter_by(recipient_persona_id=self.b).delete()
        self.db.commit()
        # 即使父项被误标为公开，也不能覆盖 v2 权限。
        self.db.query(GroupContentVisibility).filter_by(recipient_persona_id=self.b).update({"decision": "visible"})
        self.db.commit()
        self.assertEqual((), self.personal(self.b))
        self.db.query(GroupContentUnit).delete()
        self.db.commit()
        self.assertEqual((), self.personal(self.a))

    def test_thought_is_author_only_even_if_storage_has_invalid_grant(self):
        self.group()
        self.append()
        thought = self.db.query(GroupContentUnit).filter_by(kind="thought").one()
        self.db.query(GroupUnitVisibility).filter_by(unit_id=thought.id, recipient_persona_id=self.b).update({"decision": "visible"})
        self.db.commit()
        self.assertNotIn("PRIVATE_THOUGHT", "".join(row.content for row in self.personal(self.b)))

    def test_a_b_a_replays_each_parent_state_once_and_missing_own_grant_hides_state(self):
        self.group()
        first = self.append(patch_value='{"scene":"UNIQUE_STATE"}')
        self.append(self.b)
        self.append()
        ctx = build_member_context(self.sid, self.a, self.target["candidate_id"], self.target["revision"], self.db)
        self.assertEqual("UNIQUE_STATE", json.loads(ctx.state_json)["scene"])
        # 起点 37，两次 A 调用各 +2，单元数量不影响好感。
        self.assertIn("41", ctx.messages_json)
        unit = self.db.query(GroupContentUnit).filter_by(item_id=first["item_id"], kind="thought").one()
        self.db.query(GroupUnitVisibility).filter_by(unit_id=unit.id, recipient_persona_id=self.a).delete()
        self.db.commit()
        ctx = build_member_context(self.sid, self.a, self.target["candidate_id"], self.target["revision"], self.db)
        self.assertNotIn("UNIQUE_STATE", ctx.state_json)

    def test_v2_contract_replaces_xml_and_preserves_phi(self):
        self.group()
        self.db.get(Character, 1).post_history_instructions = "PHI {{char}}"
        self.db.commit()
        ctx = build_member_context(self.sid, self.a, self.target["candidate_id"], 1, self.db)
        last = json.loads(ctx.messages_json)[-1]["content"]
        self.assertIn("PHI actor1", last)
        self.assertIn("群聊单元输出协议 v2", last)
        self.assertNotIn("<reply>", last)
        self.assertNotIn("<state_update>", last)
        self.assertNotIn("自闭合", last)
        self.assertIn("不能复述或重演自己的上一条", ctx.messages_json)

    def test_user_and_role_protocol_reject_incomplete_duplicate_or_cross_member_decisions(self):
        members = (101, 102)
        rec = [{"persona_id": pid, "decision": "visible"} for pid in members]
        valid = {"units": [{"start": 0, "end": 2, "recipients": rec}]}
        self.assertEqual(2, parse_user_units(json.dumps(valid), "😀字", members).units[0].end)
        bad = [dict(start=0, end=3, recipients=rec), dict(start=True, end=2, recipients=rec),
               dict(start=1, end=2, recipients=rec), dict(start=0, end=1, recipients=rec),
               dict(start=0, end=2, recipients=rec[:1]), dict(start=0, end=2, recipients=rec + rec[:1])]
        for row in bad:
            with self.subTest(row=row), self.assertRaises(GroupUnitError):
                parse_user_units(json.dumps({"units": [row]}), "😀字", members)
        with self.assertRaises(GroupUnitError):
            parse_unit_visibility(json.dumps({"units": [{"unit_index": 0, "recipients": rec}]}),
                                  (ContentUnit("thought", "secret"),), members, 101)
        for raw in ('{"units":[],"units":[]}', '{"value":NaN}', '```{}', '[]'):
            with self.subTest(raw=raw), self.assertRaises(GroupUnitError):
                load_object(raw)

    def test_invalid_role_output_is_not_repaired_and_other_actor_state_is_rejected(self):
        self.group()
        ctx = build_member_context(self.sid, self.a, self.target["candidate_id"], 1, self.db)
        valid = {"units": [{"kind": "speech", "text": "text"}], "status": {"emotion": "平静", "affection_change": 1}}
        self.assertEqual("text", generation._parse(json.dumps(valid), ctx)[0])
        invalid = [dict(valid, units=[]), dict(valid, units=[{"kind": "speech", "text": " "}]),
                   dict(valid, status={"emotion": "平静", "affection_change": True}),
                   dict(valid, state_update={"characters": {"actor2": {"posture": "standing"}}}),
                   dict(valid, reasoning="secret")]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(generation.GroupGenerationError):
                generation._parse(json.dumps(value), ctx)

    def test_audit_failure_rolls_back_parent_units_visibility_and_state_together(self):
        self.group()
        original = audit.record
        def fail(candidate, stage, *args, **kwargs):
            original(candidate, stage, *args, **kwargs)
            if stage == "utterance_visibility":
                raise RuntimeError("injected audit failure")
        with patch.object(audit, "record", side_effect=fail), self.assertRaises(RuntimeError):
            self.append(patch_value='{"scene":"not committed"}')
        self.assertEqual(1, self.db.query(GroupContentItem).count())
        self.assertEqual(2, self.db.query(GroupContentUnit).count())
        self.assertEqual(1, self.db.query(GroupDirectorStep).count())
        self.assertEqual(1, self.db.get(GroupRoundCandidate, self.target["candidate_id"]).revision)

    def test_unit_boundary_follows_selected_confirmed_candidates(self):
        self.group()
        self.append()
        history._finish(self.sid, self.target["candidate_id"], 2, False, self.db, finish_reason="wait_user", model="fixture")
        self.db.get(GroupRound, self.target["round_id"]).confirmed_at = datetime.now()
        sibling = GroupRoundCandidate(round_id=self.target["round_id"], session_id=self.sid, version=2, status="awaiting_confirmation")
        self.db.add(sibling)
        self.db.flush()
        self.db.add(GroupContentItem(candidate_id=sibling.id, session_id=self.sid, sequence=1,
            kind="utterance", speaker_persona_id=self.a, content="SIBLING_SECRET"))
        self.db.commit()
        plan = UnitPlan((ContentUnit("user", start=0, end=4),), ((self.a, self.b),))
        self.target = history._prepare(self.sid, "next", (self.a, self.b), self.db, unit_plan=plan, model="fixture")
        text = "".join(row.content for row in self.personal(self.b))
        self.assertIn("桥坏了。", text)
        self.assertNotIn("PRIVATE_THOUGHT", text)
        self.assertNotIn("SIBLING_SECRET", text)

    def run_round(self, *, fail_stage=None, max_steps=2, initial_visible=True):
        result = asyncio.run(create_group_session(self.cards, self.db))
        sid = result["session_id"]
        ids = tuple(row["persona_id"] for row in result["members"])
        calls, role_calls = [], 0
        def rec(visible):
            return [{"persona_id": pid, "decision": "visible" if pid in visible else "hidden"} for pid in ids]
        async def model(stage, kwargs):
            nonlocal role_calls
            calls.append(stage)
            self.assertFalse(self.db.connection().connection.driver_connection.in_transaction)
            if stage == fail_stage:
                return _response('{"bad":"PRIVATE_REASONING"}')
            if stage == "user_visibility":
                raw = {"units": [{"start": 0, "end": 4, "recipients": rec(ids if initial_visible else ())}]}
            elif stage == "next_action":
                raw = ({"action": "speak", "speaker_persona_id": ids[role_calls % 2], "reason_code": "follow_up"}
                       if role_calls < 1 else {"action": "end", "reason_code": "wait_user"})
            elif stage == "role_generation":
                steps = self.db.query(GroupDirectorStep).order_by(GroupDirectorStep.id).all()
                self.assertEqual("next_action", steps[-1].stage)
                raw = {"units": [{"kind": "speech", "text": "桥坏了。"}, {"kind": "thought", "text": "PRIVATE_THOUGHT"}],
                       "status": {"emotion": "平静", "affection_change": 2}}
                role_calls += 1
            else:
                raw = {"units": [{"unit_index": 0, "recipients": rec(ids)}, {"unit_index": 1, "recipients": rec(ids[:1])}]}
            return _response(json.dumps(raw, ensure_ascii=False))
        with group_runtime(self.engine) as owner:
            result = asyncio.run(run_group_round(sid, "user", self.db, runtime=owner, model="fixture", call_model=model,
                collect_inputs=True, max_steps=max_steps))
        return sid, ids, result, calls

    def test_v2_round_persists_revision_chain_terminal_reason_and_sanitized_audit(self):
        sid, ids, result, calls = self.run_round()
        self.assertIsNone(result["error_code"])
        self.assertEqual(5, len(calls))
        steps = self.db.query(GroupDirectorStep).order_by(GroupDirectorStep.step_index).all()
        self.assertEqual(["user_visibility", "next_action", "utterance_visibility", "finish"], [row.stage for row in steps])
        self.assertEqual([(0, 1), (1, 2), (2, 3), (3, 4)], [(row.expected_revision, row.result_revision) for row in steps])
        self.assertTrue(all(row.model == "fixture" and row.policy_version == 2 for row in steps))
        payload = "".join(row.decision_json for row in steps)
        self.assertNotIn("PRIVATE", payload)
        self.assertNotIn("桥坏", payload)
        self.assertEqual("wait_user", self.db.get(GroupRoundCandidate, result["candidate_id"]).finish_reason)
        self.assertNotIn("PRIVATE_THOUGHT", json.dumps(result["personal_inputs"][str(ids[1])], ensure_ascii=False))
        self.assertNotIn("decision_json", json.dumps(history.list_group_rounds(sid, self.db)))

    def test_program_stops_persist_reasons_without_extra_calls(self):
        for initial, limit, expected, count in ((False, 2, "no_visible_basis", 1), (True, 1, "step_limit", 4)):
            with self.subTest(expected=expected):
                _, _, result, calls = self.run_round(max_steps=limit, initial_visible=initial)
                self.assertIsNone(result["error_code"])
                self.assertEqual(expected, result["finish_reason"])
                self.assertEqual(count, len(calls))
                candidate = self.db.get(GroupRoundCandidate, result["candidate_id"])
                self.assertEqual(expected, candidate.finish_reason)
                self.assertEqual("awaiting_confirmation", candidate.status)

    def test_failed_postcheck_keeps_accepted_schedule_and_no_partial_utterance(self):
        _, _, result, calls = self.run_round(fail_stage="utterance_visibility")
        candidate = self.db.get(GroupRoundCandidate, result["candidate_id"])
        self.assertEqual("failed", candidate.status)
        self.assertIsNone(candidate.finish_reason)
        self.assertEqual("invalid_output", candidate.error_code)
        self.assertEqual(candidate.revision, result["revision"])
        self.assertEqual(3, result["revision"])
        self.assertEqual(4, len(calls))
        self.assertEqual(["user_visibility", "next_action"], [row.stage for row in self.db.query(GroupDirectorStep).order_by(GroupDirectorStep.id)])
        self.assertEqual(1, self.db.query(GroupContentItem).count())

    def test_director_and_role_failures_return_only_the_committed_failure_revision(self):
        for stage, expected in (("next_action", 2), ("role_generation", 3)):
            with self.subTest(stage=stage):
                _, _, result, _ = self.run_round(fail_stage=stage)
                candidate = self.db.get(GroupRoundCandidate, result["candidate_id"])
                self.assertEqual(("failed", expected), (candidate.status, candidate.revision))
                self.assertEqual(expected, result["revision"])

    def test_revision_competition_does_not_adopt_another_writers_version(self):
        original = generation._generate_with_execution
        async def compete(*args, **kwargs):
            async def late_call(parameters):
                candidate = self.db.get(GroupRoundCandidate, args[1])
                candidate.revision += 10
                self.db.commit()
                return _response('{"bad":"late output"}')
            return await original(*args, **{**kwargs, "call_model": late_call})
        with patch.object(generation, "_generate_with_execution", side_effect=compete):
            _, _, result, _ = self.run_round()
        candidate = self.db.get(GroupRoundCandidate, result["candidate_id"])
        self.assertEqual(("generating", 12), (candidate.status, candidate.revision))
        self.assertEqual(2, result["revision"])
        self.assertIsNone(candidate.error_code)

    def test_failure_marker_error_never_fabricates_a_committed_revision(self):
        with patch.object(generation, "_fail", side_effect=RuntimeError("marker unavailable")):
            _, _, result, _ = self.run_round(fail_stage="utterance_visibility")
        candidate = self.db.get(GroupRoundCandidate, result["candidate_id"])
        self.assertEqual(("generating", 2), (candidate.status, candidate.revision))
        self.assertEqual(2, result["revision"])
        self.assertEqual("invalid_output", result["error_code"])
        self.assertIsNone(candidate.error_code)

    def test_cancel_after_utterance_commit_marks_failure_at_the_saved_revision(self):
        original = generation._database
        async def cancel_after(operation, *args, **kwargs):
            result = await original(operation, *args, **kwargs)
            if operation is generation._save:
                raise generation._DatabaseCancelled(result)
            return result
        with patch.object(generation, "_database", side_effect=cancel_after), self.assertRaises(asyncio.CancelledError):
            self.run_round()
        candidate = self.db.query(GroupRoundCandidate).one()
        self.assertEqual(("failed", "cancelled", 4), (candidate.status, candidate.error_code, candidate.revision))
        self.assertEqual(2, self.db.query(GroupContentItem).count())
        self.assertEqual("utterance_visibility", self.db.query(GroupDirectorStep).order_by(GroupDirectorStep.id.desc()).first().stage)

    def test_cancel_after_schedule_commit_keeps_audit_and_marks_new_revision_failed(self):
        original = generation._database
        async def cancel_after(operation, *args, **kwargs):
            result = await original(operation, *args, **kwargs)
            if operation is history._accept_action:
                raise generation._DatabaseCancelled(result)
            return result
        with patch.object(generation, "_database", side_effect=cancel_after), self.assertRaises(asyncio.CancelledError):
            self.run_round()
        candidate = self.db.query(GroupRoundCandidate).one()
        self.assertEqual(("failed", "cancelled", 3), (candidate.status, candidate.error_code, candidate.revision))
        self.assertEqual(["user_visibility", "next_action"], [row.stage for row in self.db.query(GroupDirectorStep).order_by(GroupDirectorStep.id)])
        self.assertEqual(1, self.db.query(GroupContentItem).count())

    def test_final_commit_wins_late_cancellation_with_terminal_audit(self):
        original = generation._database
        async def cancel_after(operation, *args, **kwargs):
            result = await original(operation, *args, **kwargs)
            if operation is history._finish:
                raise generation._DatabaseCancelled(result)
            return result
        with patch.object(generation, "_database", side_effect=cancel_after):
            _, _, result, _ = self.run_round()
        self.assertIsNone(result["error_code"])
        candidate = self.db.get(GroupRoundCandidate, result["candidate_id"])
        self.assertEqual(("awaiting_confirmation", "wait_user", 4), (candidate.status, candidate.finish_reason, candidate.revision))
        self.assertEqual("finish", self.db.query(GroupDirectorStep).order_by(GroupDirectorStep.id.desc()).first().stage)

    def test_stale_utterance_or_action_cannot_append_audit_or_units(self):
        self.group()
        action = NextAction("speak", self.a, "direct_response")
        accepted = history._accept_action(self.sid, self.target["candidate_id"], 1, action, "fixture", self.db)
        self.assertEqual(2, accepted["revision"])
        with self.assertRaises(SessionKindConflict):
            self.append()
        with self.assertRaises(SessionKindConflict):
            history._accept_action(self.sid, self.target["candidate_id"], 1, action, "fixture", self.db)
        self.assertEqual(2, self.db.query(GroupDirectorStep).count())
        self.assertEqual(2, self.db.query(GroupContentUnit).count())

    def test_outbox_failure_restores_units_and_audit_then_successful_delete_cascades(self):
        self.group()
        self.append()
        self.db.add(ChatMessage(session_id=self.sid, role=MessageRole.assistant, content="audio", audio_path="fixture.mp3"))
        self.db.commit()
        with patch.object(groups, "OutboxJob", side_effect=RuntimeError("outbox failed")), self.assertRaises(RuntimeError):
            asyncio.run(groups.delete_group_session(self.sid, self.db))
        self.assertEqual(4, self.db.query(GroupContentUnit).count())
        self.assertEqual(2, self.db.query(GroupDirectorStep).count())
        asyncio.run(groups.delete_group_session(self.sid, self.db))
        self.assertEqual(0, self.db.query(GroupContentUnit).count())
        self.assertEqual(0, self.db.query(GroupUnitVisibility).count())
        self.assertEqual(0, self.db.query(GroupDirectorStep).count())

    def test_worldbook_scans_visible_units_only_and_keeps_card_examples(self):
        self.group()
        self.append()
        card = self.db.get(Character, 2)
        card.extensions = json.dumps({"character_book": {"entries": [
            {"keys": ["PRIVATE_THOUGHT"], "content": "LEAKED_LORE", "enabled": True},
            {"keys": ["桥坏了"], "content": "VISIBLE_LORE", "enabled": True}]}})
        card.mes_example = "<START>\n{{user}}: example\n{{char}}: example reply"
        self.db.commit()
        ctx = build_member_context(self.sid, self.b, self.target["candidate_id"], 2, self.db)
        self.assertIn("VISIBLE_LORE", ctx.messages_json)
        self.assertIn("example reply", ctx.messages_json)
        self.assertNotIn("LEAKED_LORE", ctx.messages_json)
        self.assertNotIn("PRIVATE_THOUGHT", ctx.messages_json)
