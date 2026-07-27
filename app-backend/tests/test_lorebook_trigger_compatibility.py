import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.lorebook.lorebook_engine import process_lorebook
from services.lorebook.parse_lorebook import parse_sillytavern_lorebook


def _character(entries, *, recursive_scanning=False):
    return SimpleNamespace(
        extensions=json.dumps(
            {
                "character_book": {
                    "scan_depth": 5,
                    "token_budget": 100000,
                    "recursive_scanning": recursive_scanning,
                    "entries": entries,
                }
            },
            ensure_ascii=False,
        ),
        lorebooks=[],
    )


def _triggered_contents(entries, text, *, recursive_scanning=False):
    result = process_lorebook(
        _character(entries, recursive_scanning=recursive_scanning),
        [],
        text,
    )
    return [
        entry["content"]
        for position_entries in result.values()
        for entry in position_entries
    ]


class LorebookTriggerParsingTests(unittest.TestCase):
    def test_sillytavern_alias_fields_are_normalized(self):
        parsed = parse_sillytavern_lorebook(
            {
                "scanDepth": "7",
                "tokenBudget": "2048",
                "recursiveScanning": True,
                "entries": [
                    {
                        "key": ["dragon"],
                        "keysecondary": ["red", "ancient"],
                        "content": "龙族资料",
                        "disable": True,
                        "caseSensitive": True,
                        "selective": True,
                        "selectiveLogic": 3,
                        "useRegex": True,
                        "probability": 35,
                        "useProbability": False,
                    },
                    {
                        "key": "/dragon(?:,| and )wyrm/i",
                        "content": "含逗号正则",
                    }
                ],
            }
        )
        entry = parsed["entries"][0]

        self.assertEqual(7, parsed["scan_depth"])
        self.assertEqual(2048, parsed["token_budget"])
        self.assertTrue(parsed["recursive_scanning"])
        self.assertEqual(["dragon"], entry["keys"])
        self.assertEqual(["red", "ancient"], entry["secondary_keys"])
        self.assertFalse(entry["enabled"])
        self.assertTrue(entry["case_sensitive"])
        self.assertEqual("and_all", entry["selective_logic"])
        self.assertTrue(entry["use_regex"])
        self.assertEqual(35, entry["probability"])
        self.assertFalse(entry["use_probability"])
        self.assertEqual(
            ["/dragon(?:,| and )wyrm/i"],
            parsed["entries"][1]["keys"],
        )


class LorebookOptionalFilterTests(unittest.TestCase):
    ENTRIES = [
        {
            "key": ["魔法"],
            "keysecondary": ["红色", "古老"],
            "content": "AND_ANY",
            "selective": True,
            "selectiveLogic": 0,
        },
        {
            "key": ["魔法"],
            "keysecondary": ["红色", "古老"],
            "content": "NOT_ALL",
            "selective": True,
            "selectiveLogic": 1,
        },
        {
            "key": ["魔法"],
            "keysecondary": ["红色", "古老"],
            "content": "NOT_ANY",
            "selective": True,
            "selectiveLogic": 2,
        },
        {
            "key": ["魔法"],
            "keysecondary": ["红色", "古老"],
            "content": "AND_ALL",
            "selective": True,
            "selectiveLogic": 3,
        },
    ]

    def test_one_secondary_key_matches_and_any_and_not_all(self):
        contents = _triggered_contents(self.ENTRIES, "红色魔法")

        self.assertIn("AND_ANY", contents)
        self.assertIn("NOT_ALL", contents)
        self.assertNotIn("NOT_ANY", contents)
        self.assertNotIn("AND_ALL", contents)

    def test_all_secondary_keys_match_and_any_and_and_all(self):
        contents = _triggered_contents(self.ENTRIES, "古老的红色魔法")

        self.assertIn("AND_ANY", contents)
        self.assertIn("AND_ALL", contents)
        self.assertNotIn("NOT_ANY", contents)
        self.assertNotIn("NOT_ALL", contents)

    def test_no_secondary_key_matches_negative_filters(self):
        contents = _triggered_contents(self.ENTRIES, "普通魔法")

        self.assertIn("NOT_ANY", contents)
        self.assertIn("NOT_ALL", contents)
        self.assertNotIn("AND_ANY", contents)
        self.assertNotIn("AND_ALL", contents)

    def test_empty_secondary_list_does_not_block_primary_match(self):
        contents = _triggered_contents(
            [
                {
                    "key": ["魔法"],
                    "keysecondary": [],
                    "content": "无过滤关键词",
                    "selective": True,
                    "selectiveLogic": 3,
                }
            ],
            "魔法",
        )

        self.assertIn("无过滤关键词", contents)


class LorebookRegexTests(unittest.TestCase):
    def test_javascript_regex_flags_and_use_regex_are_supported(self):
        entries = [
            {
                "key": ["/Mana\\s+Core/i"],
                "content": "显式正则",
            },
            {
                "key": ["龙[0-9]+"],
                "content": "use_regex 正则",
                "useRegex": True,
            },
        ]

        contents = _triggered_contents(entries, "mana   core 与 龙2048")

        self.assertIn("显式正则", contents)
        self.assertIn("use_regex 正则", contents)

    def test_regex_without_i_flag_remains_case_sensitive(self):
        entries = [
            {"key": ["/Mana/"], "content": "大小写敏感正则"},
            {"key": ["/Mana/i"], "content": "忽略大小写正则"},
        ]

        contents = _triggered_contents(entries, "mana")

        self.assertNotIn("大小写敏感正则", contents)
        self.assertIn("忽略大小写正则", contents)

    def test_invalid_regex_is_ignored_without_literal_fallback(self):
        contents = _triggered_contents(
            [{"key": ["/[未闭合/"], "content": "无效正则"}],
            "这里包含原始文本 /[未闭合/",
        )

        self.assertNotIn("无效正则", contents)


class LorebookProbabilityTests(unittest.TestCase):
    def test_zero_hundred_and_disabled_probability_boundaries(self):
        entries = [
            {"key": ["概率"], "content": "零概率", "probability": 0},
            {"key": ["概率"], "content": "百概率", "probability": 100},
            {
                "key": ["概率"],
                "content": "禁用概率检查",
                "probability": 0,
                "useProbability": False,
            },
        ]

        contents = _triggered_contents(entries, "概率")

        self.assertNotIn("零概率", contents)
        self.assertIn("百概率", contents)
        self.assertIn("禁用概率检查", contents)

    def test_probability_roll_is_deterministic_when_random_is_patched(self):
        entry = [{"key": ["概率"], "content": "五十概率", "probability": 50}]

        with patch(
            "services.lorebook.lorebook_engine.random.random",
            return_value=0.49,
        ):
            self.assertIn("五十概率", _triggered_contents(entry, "概率"))

        with patch(
            "services.lorebook.lorebook_engine.random.random",
            return_value=0.51,
        ):
            self.assertNotIn("五十概率", _triggered_contents(entry, "概率"))

    def test_recursive_scanning_does_not_reroll_rejected_entry(self):
        entries = [
            {
                "keys": [],
                "content": "递归钥匙",
                "constant": True,
                "probability": 100,
            },
            {
                "key": ["递归钥匙"],
                "content": "概率条目",
                "probability": 50,
            },
        ]

        with patch(
            "services.lorebook.lorebook_engine.random.random",
            return_value=0.99,
        ) as random_mock:
            contents = _triggered_contents(
                entries,
                "开始",
                recursive_scanning=True,
            )

        self.assertNotIn("概率条目", contents)
        self.assertEqual(1, random_mock.call_count)


if __name__ == "__main__":
    unittest.main(verbosity=2)
