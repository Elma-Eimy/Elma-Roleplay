r"""Offline tests for observational prompt token-range reporting."""

from __future__ import annotations

import asyncio
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from routers.sessions import compile_session_prompt
from services.conversation.prompt_token_estimator import (
    SECTION_ORDER,
    estimate_prompt_tokens,
    estimate_text_tokens,
)


class _EmptyQuery:
    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return None


class _PreviewDB:
    def __init__(self, session):
        self.session = session

    def get(self, model, key):
        return self.session

    def query(self, model):
        return _EmptyQuery()


class PromptTokenEstimatorTests(unittest.TestCase):
    def test_mixed_text_returns_honest_ordered_range(self):
        estimate = estimate_text_tokens("你好，world 123! 🌙")
        self.assertGreater(estimate["characters"], 0)
        self.assertLessEqual(estimate["lower_bound"], estimate["estimated_tokens"])
        self.assertLessEqual(estimate["estimated_tokens"], estimate["upper_bound"])

    def test_final_payload_is_measured_by_section_without_mutation(self):
        messages = [
            {"role": "system", "content": "【角色设定】\n冷静的调查员。"},
            {"role": "user", "content": "之前的问题"},
            {"role": "assistant", "content": "<reply>之前的回答</reply>"},
            {
                "role": "system",
                "content": (
                    "【当前回合动态背景】\n"
                    "<current_scenario>办公室</current_scenario>\n"
                    "<cognition_state>信任用户</cognition_state>\n"
                    "<current_status>当前心情: 平静</current_status>\n"
                    "<lorebook_knowledge>城市设定</lorebook_knowledge>\n"
                    "<recalled_memories>- 用户喜欢咖啡</recalled_memories>\n"
                    "<factual_relationships>用户 friend 角色</factual_relationships>"
                ),
            },
            {"role": "user", "content": "我们继续调查吧。"},
            {
                "role": "system",
                "content": "【后置扮演规则】\n保持简短。\n\n【重要：输出格式要求】",
            },
        ]
        original = copy.deepcopy(messages)

        report = estimate_prompt_tokens(messages)

        self.assertEqual(original, messages)
        self.assertEqual(list(SECTION_ORDER), list(report["sections"]))
        for section in (
            "character",
            "recent_history",
            "scenario",
            "cognition",
            "status",
            "lorebook",
            "long_term_memory",
            "graph",
            "current_user_message",
            "other",
        ):
            self.assertGreater(report["sections"][section]["estimated_tokens"], 0)

        self.assertEqual(
            report["estimated_tokens"],
            sum(
                section["estimated_tokens"]
                for section in report["sections"].values()
            ),
        )
        self.assertFalse(report["is_exact"])
        self.assertEqual("heuristic_v1", report["method"])
        self.assertGreater(
            report["sections"]["current_user_message"]["estimated_tokens"],
            0,
        )

    def test_opening_prompt_without_user_message_is_still_reported(self):
        character = SimpleNamespace()
        persona = SimpleNamespace(character=character)
        session = SimpleNamespace(persona=persona)
        db = _PreviewDB(session)

        with patch(
            "services.conversation.prompt_compiler.compile_system_prompt",
            return_value="固定角色提示词",
        ):
            response = asyncio.run(
                compile_session_prompt(
                    session_id=1,
                    user_nickname="用户",
                    db=db,
                )
            )

        self.assertEqual(
            [{"role": "system", "content": "固定角色提示词"}],
            response["messages"],
        )
        self.assertIn("token_estimate", response)
        self.assertGreater(response["token_estimate"]["estimated_tokens"], 0)

    def test_at_depth_user_after_current_message_is_counted_as_lorebook(self):
        messages = [
            {"role": "system", "content": "固定角色提示词"},
            {"role": "user", "content": "真正的当前问题"},
            {
                "role": "user",
                "content": (
                    '<lorebook_knowledge position="at_depth" depth="0">\n'
                    "用户角色的世界书资料\n"
                    "</lorebook_knowledge>"
                ),
            },
            {"role": "system", "content": "【重要：输出格式要求】"},
        ]

        report = estimate_prompt_tokens(messages)

        self.assertEqual(
            len("真正的当前问题"),
            report["sections"]["current_user_message"]["characters"],
        )
        self.assertGreater(report["sections"]["lorebook"]["characters"], 0)
        self.assertNotEqual(
            0,
            report["sections"]["current_user_message"]["estimated_tokens"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
