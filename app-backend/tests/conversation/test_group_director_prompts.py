"""导演阶段契约、原文位置参照与在线失败样本的离线回归。"""
import json
import unittest

from services.conversation import group_director_service as director
from services.conversation.group_generation_service import ProposedGroupUtterance
from services.conversation.group_unit_protocol import ContentUnit, GroupUnitError, parse_user_units


class DirectorPromptTests(unittest.TestCase):
    def context(self, *, max_chars=24000):
        payload = {"members": [{"persona_id": 7, "name": "同名"}, {"persona_id": 9, "name": "同名"}],
                   "history": [], "eligible_persona_ids": [7, 9], "history_incomplete": False}
        return director.DirectorContext(json.dumps(payload, ensure_ascii=False), (7, 9), (7, 9), max_chars)

    def test_each_stage_has_only_its_own_output_contract(self):
        context = self.context()
        proposed = ProposedGroupUtterance(7, "公开。私密。", (ContentUnit("speech", "公开。"), ContentUnit("thought", "私密。")))
        stages = (("user_visibility", {"user_content": "用户原文"}, '"start"', ('"action"', '"unit_index"')),
                  ("next_action", {}, '"action"', ('"start"', '"recipients"', '"unit_index"')),
                  ("utterance_visibility", {"proposed": proposed}, '"unit_index"', ('"action"', '"start"')))
        for stage, kwargs, required, absent in stages:
            with self.subTest(stage=stage):
                messages = director.build_director_messages(context, stage, protocol_version=2, **kwargs)
                system = messages[0]["content"]
                self.assertIn(stage, system)
                self.assertIn(required, system)
                for field in absent:
                    self.assertNotIn(field, system)
                self.assertNotIn("101", system)
                self.assertEqual(stage, json.loads(messages[1]["content"])["stage"])

    def test_unicode_offsets_are_server_computed_without_rewriting_source(self):
        source = '😀公开。私密e\u0301。\r\n"重复"{{char}}<raw>'
        messages = director.build_director_messages(self.context(), "user_visibility", user_content=source, protocol_version=2)
        payload = json.loads(messages[1]["content"])
        self.assertEqual(source, payload["pending_user_content"])
        self.assertEqual(len(source), payload["pending_user_length"])
        self.assertEqual(list(enumerate(source)), [tuple(row) for row in payload["pending_user_codepoints"]])
        self.assertIn(f'"end": {len(source)}', messages[0]["content"])
        self.assertIn("不自行估算", messages[0]["content"])

    def test_large_source_keeps_exact_length_and_bounded_position_reference(self):
        source = "甲" * 5000 + "（秘密）" + "乙" * 5000
        messages = director.build_director_messages(self.context(), "user_visibility", user_content=source, protocol_version=2)
        payload = json.loads(messages[1]["content"])
        self.assertEqual(source, payload["pending_user_content"])
        self.assertEqual(len(source), payload["pending_user_length"])
        self.assertLessEqual(len(payload["pending_user_codepoints"]), 256)
        for index, char in payload["pending_user_codepoints"]:
            self.assertEqual(char, source[index])
        positions = {row[0] for row in payload["pending_user_codepoints"]}
        self.assertTrue({5000, 5001, 5003, 5004} <= positions)
        self.assertLessEqual(len(messages[1]["content"]), 24000)

    def test_dense_delimiters_cannot_expand_the_position_reference_without_bound(self):
        source = "（甲）" * 300
        messages = director.build_director_messages(self.context(), "user_visibility", user_content=source, protocol_version=2)
        positions = json.loads(messages[1]["content"])["pending_user_codepoints"]
        self.assertLessEqual(len(positions), 256)
        self.assertEqual([0, "（"], positions[0])
        self.assertEqual([len(source) - 1, "）"], positions[-1])
        self.assertTrue(all(source[index] == char for index, char in positions))

    def test_source_reference_is_counted_in_context_budget(self):
        source = "秘密😀" * 10
        full = director.build_director_messages(self.context(), "user_visibility", user_content=source, protocol_version=2)
        size = len(full[1]["content"])
        director.build_director_messages(self.context(max_chars=size), "user_visibility", user_content=source, protocol_version=2)
        with self.assertRaisesRegex(director.GroupDirectorError, "context_budget"):
            director.build_director_messages(self.context(max_chars=size - 1), "user_visibility", user_content=source, protocol_version=2)

    def test_observed_wrong_ranges_and_mixed_stage_objects_still_fail(self):
        source = "我只告诉阿岚：SECRET_VAULT_731。请不要转述密码。"
        recipients = [{"persona_id": 7, "decision": "visible"}, {"persona_id": 9, "decision": "hidden"}]
        for end in (1, 29, len(source) + 1):
            with self.subTest(end=end), self.assertRaises(GroupUnitError):
                parse_user_units(json.dumps({"units": [{"start": 0, "end": end, "recipients": recipients}]}), source, (7, 9))
        for value in ({"units": [{"start": 0, "end": 8, "recipients": recipients}]},
                      {"utterance_visibility": {"units": []}, "next_action": {"action": "end", "reason_code": "wait_user"}}):
            with self.subTest(value=value), self.assertRaises(director.GroupDirectorError):
                director.parse_next_action(json.dumps(value), (7, 9), (7, 9))

    def test_legacy_visibility_contract_stays_fulltext_and_stage_specific(self):
        messages = director.build_director_messages(self.context(), "user_visibility", user_content="旧版原文")
        self.assertIn('"recipients"', messages[0]["content"])
        self.assertNotIn('"units"', messages[0]["content"])
        self.assertNotIn('"action"', messages[0]["content"])
        self.assertNotIn("pending_user_codepoints", messages[1]["content"])

    def test_action_contract_counts_current_round_not_confirmed_history(self):
        from dataclasses import replace
        context = replace(self.context(), current_item_count=2)
        payload = json.loads(context.payload_json)
        payload["history"] = [{"kind": "utterance", "content": "旧轮发言"}] * 20
        context = replace(context, payload_json=json.dumps(payload))
        messages = director.build_director_messages(context, "next_action", protocol_version=2)
        self.assertIn("本轮已经保存 1 条角色发言", messages[0]["content"])
        self.assertIn("等待用户决定", messages[0]["content"])
