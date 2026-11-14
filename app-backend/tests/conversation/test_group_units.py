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
from services.conversation.group import history_service as history, generation_service as generation
from services.conversation.group import audit_service as audit
from services.conversation.group import session_service as groups
from services.conversation.session_access import SessionKindConflict
from services.conversation.group.context_service import build_member_context
from services.conversation.group.director_service import NextAction, build_director_context
from services.conversation.group.session_service import create_group_session
from services.conversation.group.unit_protocol import (ContentUnit, UnitPlan, GroupUnitError, parse_user_units,
    parse_unit_visibility, load_object)


def grounding(messages):
    marker = '【本次发言依据】\n'
    return next(json.loads(row['content'].split(marker, 1)[1].split('\n', 1)[0])
                for row in messages if marker in row['content'])
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

    def test_typed_personal_history_preserves_authorship_without_private_units(self):
        self.group()
        self.append()
        author = self.personal(self.a)[-1]
        listener = self.personal(self.b)[-1]
        self.assertEqual([("speech", "桥坏了。"), ("thought", "PRIVATE_THOUGHT")],
                         [(unit.kind, unit.text) for unit in author.visible_units])
        self.assertEqual([("speech", "桥坏了。")], [(unit.kind, unit.text) for unit in listener.visible_units])
        own = json.loads(build_member_context(self.sid, self.a, self.target["candidate_id"],
            self.target["revision"], self.db).messages_json)
        from services.parse import extract_xml_block
        own_reply = next(row['content'] for row in own if row['role'] == 'assistant')
        self.assertEqual('桥坏了。PRIVATE_THOUGHT', extract_xml_block(own_reply)['reply'])
        self.assertTrue(own_reply.startswith('<reply>'))
        other = json.loads(build_member_context(self.sid, self.b, self.target["candidate_id"],
            self.target["revision"], self.db).messages_json)
        event = next(json.loads(row["content"].split("\n")[-1]) for row in other
                     if row["role"] == "system" and row["content"].startswith("【其他成员的可见历史资料】"))
        self.assertEqual(self.a, event["speaker_persona_id"])
        self.assertEqual([{"kind": "speech", "text": "桥坏了。"}], event["units"])
        self.assertNotIn("PRIVATE_THOUGHT", json.dumps(other))
        self.assertNotIn("recipients", json.dumps(other))
        self.assertEqual(["😀公开。"], [row["content"] for row in other if row["role"] == "user"])
        boundary = grounding(other)
        self.assertEqual(self.b, boundary["speaker_persona_id"])
        self.assertEqual([self.a], boundary["visible_current_turn_speakers"])

    def test_visible_timeline_does_not_reveal_hidden_or_windowed_events(self):
        self.group()
        self.append()
        # B 的第二次发言只给自己看，A 的第三次发言才公开。
        private = UnitPlan((ContentUnit("speech", "HIDDEN_EVENT"),), ((self.b,),))
        saved = history._append(self.sid, self.target["candidate_id"], self.b, "HIDDEN_EVENT",
            (self.b,), self.target["revision"], self.db, unit_plan=private, model="fixture")
        self.target["revision"] = saved["revision"]
        self.append()
        context = build_member_context(self.sid, self.a, self.target["candidate_id"],
            self.target["revision"], self.db, history_limit=1)
        messages = json.loads(context.messages_json)
        marker = '【个人可见历史顺序】\n'
        timeline = next(json.loads(row['content'].split(marker, 1)[1].split('\n', 1)[0])
                        for row in messages if marker in row['content'])
        self.assertEqual(1, timeline[0]['order'])
        self.assertTrue(next(row['content'] for row in messages if row['role'] == 'assistant').startswith('<reply>'))
        self.assertNotIn("HIDDEN_EVENT", context.messages_json)
        combined = "\n".join(row["content"] for row in messages)
        self.assertNotIn('"sequence"', combined)
        self.assertIn('"turn": "current"', combined)
        self.assertNotIn('"source": "user"', combined)

    def test_first_role_grounding_does_not_invent_other_speakers(self):
        self.group()
        context = build_member_context(self.sid, self.b, self.target["candidate_id"],
            self.target["revision"], self.db)
        messages = json.loads(context.messages_json)
        boundary = grounding(messages)
        self.assertEqual([], boundary["visible_current_turn_speakers"])
        self.assertEqual("user", boundary["latest_visible_source"])
        self.assertEqual(self.b, boundary["speaker_persona_id"])
        self.assertNotIn("秘密", messages[-1]["content"])

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

    def test_old_v2_candidate_uses_single_chat_xml_and_preserves_phi(self):
        self.group()
        self.db.get(Character, 1).post_history_instructions = "PHI {{char}}"
        self.db.commit()
        ctx = build_member_context(self.sid, self.a, self.target["candidate_id"], 1, self.db)
        last = json.loads(ctx.messages_json)[-1]["content"]
        self.assertIn("PHI actor1", last)
        self.assertNotIn('群聊单元输出协议', ctx.messages_json)
        self.assertNotIn('仅输出一个 JSON 对象', ctx.messages_json)
        self.assertIn('<reply>', last)
        self.assertIn('<state_update>', last)
        self.assertIn('自闭合', last)
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

    def test_lorebook_and_prompt_preserve_only_contiguous_visible_user_text(self):
        group = asyncio.run(create_group_session(self.cards, self.db))
        sid = group["session_id"]
        a, b = (member["persona_id"] for member in group["members"])
        content = "北门【密】口令{{char}}"
        units = tuple(ContentUnit("user", start=start, end=end)
                      for start, end in ((0, 1), (1, 2), (2, 5), (5, len(content))))
        plan = UnitPlan(units, ((a, b), (a, b), (a,), (a, b)))
        target = history._prepare(sid, content, (a,), self.db, unit_plan=plan, model="fixture")
        entries = [{"keys": [key], "content": label, "enabled": True} for key, label in (
            ("北门", "ADJACENT_OK"), ("口令{{char}}", "LITERAL_OK"), ("北门口令", "FALSE_JOIN"),
            (r"/北门\s*口令/", "FALSE_REGEX"), ("北门【密】口令", "FULL_INPUT_ONLY"))]
        for cid in (1, 2):
            self.db.get(Character, cid).extensions = json.dumps({"character_book": {"scan_depth": 0, "entries": entries}})
        self.db.commit()
        for pid, expected in ((a, content), (b, "北门\n口令{{char}}")):
            ctx = build_member_context(sid, pid, target["candidate_id"], target["revision"], self.db)
            messages = json.loads(ctx.messages_json)
            self.assertEqual([expected], [row["content"] for row in messages if row["role"] == "user"])
            self.assertIn("ADJACENT_OK", ctx.messages_json)
            self.assertIn("LITERAL_OK", ctx.messages_json)
            self.assertNotIn("FALSE_JOIN", ctx.messages_json)
            self.assertNotIn("FALSE_REGEX", ctx.messages_json)
            self.assertEqual(pid == a, "FULL_INPUT_ONLY" in ctx.messages_json)
            self.assertEqual(pid == a, "【密】" in ctx.messages_json)

    def test_lorebook_depth_limits_utterance_history_separately_from_current_input(self):
        self.group()
        self.append()
        card = self.db.get(Character, 2)
        entries = [{"keys": [key], "content": label, "enabled": True}
                   for key, label in (("公开", "CURRENT_LORE"), ("桥坏了", "PAST_LORE"))]
        for depth in (0, 1):
            with self.subTest(depth=depth):
                card.extensions = json.dumps({"character_book": {"scan_depth": depth, "entries": entries}})
                self.db.commit()
                ctx = build_member_context(self.sid, self.b, self.target["candidate_id"], self.target["revision"], self.db)
                self.assertIn("CURRENT_LORE", ctx.messages_json)
                self.assertEqual(bool(depth), "PAST_LORE" in ctx.messages_json)

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
        messages = json.loads(ctx.messages_json)
        self.assertTrue(any(row['role'] == 'assistant' and '<reply>' in row['content'] for row in messages))
        self.assertFalse(any('【虚构风格示例资料】' in row['content'] for row in messages))
        from services.conversation.prompting.compiler import compile_dialogue_examples
        self.assertTrue(any(row['role'] == 'assistant' and '<reply>' in row['content']
                            for row in compile_dialogue_examples(card)))
        self.assertNotIn("LEAKED_LORE", ctx.messages_json)
        self.assertNotIn("PRIVATE_THOUGHT", ctx.messages_json)
