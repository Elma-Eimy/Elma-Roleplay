"""固定完整消息，检查编译器拆分前后的内容与顺序。"""

import copy
import json
from types import SimpleNamespace
import unittest

from services.conversation.prompting.compiler import build_chat_messages, build_group_messages
from services.conversation.prompting.layout import assemble_conversation
from tests import FIXTURES_DIR


def compilation_cases():
    character = dict(name="露娜", description="{{char}}守护月光城。", personality="冷静。",
                     scenario="城墙", mes_example="", system_prompt_override="",
                     post_history_instructions="", extensions="{}")
    persona = dict(parent_persona_id=None, current_scenario_override=None,
                   cognition_state="已见过用户", affection_score=12, current_mood="平静")
    history = [{"role": "user", "content": "{{char}}，检查怀表。"},
               {"role": "assistant", "content": "后盖已打开。", "emotion_tag": "认真", "affection_change": 1}]
    base = dict(character=character, persona=persona, recent_history=history,
                user_message="能保留原零件吗？", user_nickname="小明")
    cases = {"basic": copy.deepcopy(base)}
    cases["empty"] = dict(character=character, persona=None, recent_history=[], user_message="")
    examples = "<START>\n{{user}}: 晚上好\n{{char}}: 欢迎。\n<START>\n保持简短。"
    cases["examples"] = copy.deepcopy(base)
    cases["examples"]["character"].update(mes_example=examples)
    cases["macros"] = copy.deepcopy(base)
    cases["macros"]["character"].update(mes_example=examples,
        system_prompt_override="{{original}}\n{{description}}\n{{mesExamples}}",
        post_history_instructions="{{original}}\n回应{{user}}。")
    cases["branch"] = copy.deepcopy(cases["examples"])
    cases["branch"]["persona"]["parent_persona_id"] = 1
    cases["branch"]["parent_history"] = [{"role": "assistant", "content": "父线分叉之前。"}]
    cases["dynamic"] = copy.deepcopy(base)
    cases["dynamic"].update(current_role_state={"scene": "", "characters": {"露娜": {"location": "<店内>"}}},
        ongoing_events=[{"buffer_id": 7, "content": "检查<怀表>", "stage_status": "open"}],
        pending_memories=[{"content": "尚未修复"}], graph_knowledge="怀表属于{{user}}。",
        retrieved_memories=[{"content": "曾答应帮忙。", "memory_type": "event", "turns_passed": 2,
                             "temporal_status": "planned", "temporal_note": "明天"}, "旧记忆"])
    cases["scenario_override"] = copy.deepcopy(base)
    cases["scenario_override"]["persona"]["current_scenario_override"] = "钟表店"
    cases["lorebook"] = copy.deepcopy(cases["examples"])
    entries = [dict(content=f"位置{position}的资料", constant=True, position=position,
                    insertion_order=position) for position in (0, 1, 2, 3)]
    entries.extend([dict(content="{{user}}: 示例前问\n{{char}}: 示例前答", constant=True, position=5),
                    dict(content="不能识别发言者的示例后资料", constant=True, position=6)])
    for depth, role in ((0, 1), (1, 2), (99, 0)):
        entries.append(dict(content=f"深度{depth}资料", constant=True, position=4, depth=depth, role=role))
    cases["lorebook"]["character"]["extensions"] = json.dumps({
        "character_book": {"token_budget": 100000, "entries": entries},
        "depth_prompt": {"prompt": "深度角色指令{{char}}", "depth": 1, "role": "system"}}, ensure_ascii=False)
    return cases


def compile_case(case):
    values = copy.deepcopy(case)
    values["character"] = SimpleNamespace(**values["character"])
    if values.get("persona") is not None:
        values["persona"] = SimpleNamespace(**values["persona"])
    return build_chat_messages(**values)


def compile_group_case(protocol_version):
    case = compilation_cases()["lorebook"]
    history = [SimpleNamespace(kind="user", speaker_persona_id=None, content="检查<怀表>。",
        round_id=1, visible_passages=(), visible_units=(), emotion_tag=None, affection_change=0),
        SimpleNamespace(kind="assistant", speaker_persona_id=10, content="后盖已打开。",
        round_id=1, visible_units=(), emotion_tag="认真", affection_change=1),
        SimpleNamespace(kind="assistant", speaker_persona_id=20, content="我来看看。",
        round_id=2, visible_units=(SimpleNamespace(kind="speech", text="我来看看。", meaning=None),),
        emotion_tag="平静", affection_change=0)]
    return build_group_messages(SimpleNamespace(**case["character"]), SimpleNamespace(**case["persona"]),
        history, {10: "露娜", 20: "阿明"}, persona_id=10, user_nickname="小明", shared_setting="钟表店",
        current_role_state={"scene": "店内"}, protocol_version=protocol_version, current_round_id=2,
        greetings=[{"content": "欢迎"}], inherited_memories=[{"content": "怀表尚未修好", "source": "group"}],
        insights=[{"cognition": "检查中"}], response_basis={"source": "group_member", "content": "我来看看。"})


class PromptCompilationSnapshotTests(unittest.TestCase):
    def test_complete_messages_match_before_refactor(self):
        expected_path = FIXTURES_DIR / "prompt_compilation_snapshots.json"
        actual = {name: compile_case(case) for name, case in compilation_cases().items()}
        actual.update({f"group_v{version}": compile_group_case(version) for version in (1, 2)})
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        self.assertEqual(set(expected), set(actual))
        for name in expected:
            with self.subTest(case=name):
                self.assertEqual(expected[name], actual[name])

    def test_background_targets_current_message_even_with_identical_history_and_user_injection(self):
        historical = {"role": "user", "content": "继续"}
        current = {"role": "user", "content": "继续"}
        messages = assemble_conversation(
            [historical, current], current, ["自定义上下文"],
            [{"content": "深度零资料", "depth": 0, "role": "user"}], None, "露娜", "小明",
        )
        self.assertIs(messages[0], historical)
        self.assertEqual("system", messages[1]["role"])
        self.assertIn("自定义上下文", messages[1]["content"])
        self.assertIs(messages[2], current)
        self.assertEqual("user", messages[3]["role"])
        self.assertIn("深度零资料", messages[3]["content"])

    def test_compilation_preserves_input_records_and_context(self):
        case = copy.deepcopy(compilation_cases()["dynamic"])
        case["character"] = SimpleNamespace(**case["character"])
        case["persona"] = SimpleNamespace(**case["persona"])
        before = copy.deepcopy(case)
        first = build_chat_messages(**case)
        first[0]["content"] = "调用方修改输出"
        self.assertEqual(before, case)
        self.assertNotEqual(first, build_chat_messages(**case))


if __name__ == "__main__":
    unittest.main()
