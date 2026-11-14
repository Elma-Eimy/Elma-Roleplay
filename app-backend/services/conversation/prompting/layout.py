"""消息前缀、历史转换和插入顺序；不获取会话状态。"""

from typing import Optional
from .templates import (
    DYNAMIC_CONTEXT_HEADER, replace_placeholders, _format_assistant_xml,
)
from .examples import (
    EXAMPLE_CONTEXT_NOTE, EXAMPLE_END_NOTE, _prompt_embeds_dialogue_examples, compile_dialogue_examples,
)
from .lorebook import (
    _compile_lorebook_block, _compile_lorebook_example_messages, _inject_lorebook_at_depth,
)

def compile_message_prefix(character, persona, prompt_result: dict, lorebook_res: dict,
                           user_nickname: str = "用户") -> list[dict]:
    """编译静态设定及示例前缀，保持普通请求的静态消息合并方式。"""
    char_name = character.name or "AI"
    user_name = user_nickname or "用户"
    system_sections = prompt_result.get("system_prompt_sections", {})
    core_prompt = system_sections.get("core", prompt_result["system_prompt"])
    character_definition = system_sections.get("character_definition", "")
    before_char_block = _compile_lorebook_block(
        lorebook_res.get("before_char", []),
        "before_char",
        char_name,
        user_name,
    )
    after_char_block = _compile_lorebook_block(
        lorebook_res.get("after_char", []),
        "after_char",
        char_name,
        user_name,
    )

    if before_char_block or after_char_block:
        messages = [{"role": "system", "content": core_prompt}]
        if before_char_block:
            messages.append({"role": "system", "content": before_char_block})
        if character_definition:
            messages.append(
                {"role": "system", "content": character_definition}
            )
        if after_char_block:
            messages.append({"role": "system", "content": after_char_block})
    else:
        messages = [{"role": "system", "content": prompt_result["system_prompt"]}]

    before_example_messages = _compile_lorebook_example_messages(
        lorebook_res.get("before_examples", []),
        char_name,
        user_name,
    )
    after_example_messages = _compile_lorebook_example_messages(
        lorebook_res.get("after_examples", []),
        char_name,
        user_name,
    )
    has_structured_examples = any(
        message.get("role") in {"user", "assistant"}
        for message in before_example_messages
    )
    messages.extend(before_example_messages)

    # 角色卡示例位于真实历史之前。保持既有的子会话策略：子会话使用父分支
    # 示例，不额外重复注入角色卡示例。模板显式引用示例宏时同样禁止自动注入。
    should_add_card_examples = not (persona and persona.parent_persona_id)
    if should_add_card_examples and not _prompt_embeds_dialogue_examples(character):
        example_messages = compile_dialogue_examples(character, user_nickname)
        if example_messages:
            # 无法结构化的兼容回退块合并进首条 system，避免产生连续 system
            # 消息；规范块则作为真正的 few-shot role 消息发送。
            fallback_blocks = [
                message["content"]
                for message in example_messages
                if message["role"] == "system"
            ]
            structured_examples = [
                message
                for message in example_messages
                if message["role"] != "system"
            ]
            messages[0]["content"] += "\n\n" + EXAMPLE_CONTEXT_NOTE
            if fallback_blocks:
                messages[0]["content"] += "\n\n" + "\n\n".join(fallback_blocks)
            messages.extend(structured_examples)
            has_structured_examples = (
                has_structured_examples or bool(structured_examples)
            )
    messages.extend(after_example_messages)
    has_structured_examples = has_structured_examples or any(
        message.get("role") in {"user", "assistant"}
        for message in after_example_messages
    )
    if has_structured_examples:
        if EXAMPLE_CONTEXT_NOTE not in messages[0]["content"]:
            messages[0]["content"] += "\n\n" + EXAMPLE_CONTEXT_NOTE
        messages.append(
            {
                "role": "system",
                "content": EXAMPLE_END_NOTE,
            }
        )

    return messages


def compile_history_messages(history: list[dict], char_name: str, user_name: str) -> list[dict]:
    """将单聊历史转换为消息；assistant 沿用统一 XML 格式。"""
    conversation_messages = []
    for msg in history:
        if msg["role"] == "assistant":
            content_str = replace_placeholders(msg["content"], char_name, user_name)
            emo = msg.get("emotion_tag") or "平静"
            change = msg.get("affection_change") or 0
            fallback_xml = _format_assistant_xml(content_str, emo, change)
            conversation_messages.append(
                {"role": "assistant", "content": fallback_xml}
            )
        else:
            content_str = replace_placeholders(msg["content"], char_name, user_name)
            conversation_messages.append(
                {"role": msg["role"], "content": content_str}
            )

    return conversation_messages


def assemble_conversation(
    conversation_messages: list[dict],
    current_user_message: dict,
    dynamic_context_blocks: list[str],
    depth_entries: list[dict],
    character_depth_prompt: Optional[dict],
    char_name: str,
    user_name: str,
) -> list[dict]:
    """集中处理深度插入与动态背景定位；保留当前输入的对象身份。"""
    conversation_messages = _inject_lorebook_at_depth(
        conversation_messages, depth_entries, char_name, user_name, character_depth_prompt,
    )
    # 普通动态背景保持紧邻当前 user 之前；@ Depth 0 仍可按定义位于 user
    # 之后。使用对象身份定位，避免把 role=user 的世界书注入误认成真实用户消息。
    if dynamic_context_blocks:
        current_user_index = next(
            index
            for index, message in enumerate(conversation_messages)
            if message is current_user_message
        )
        conversation_messages.insert(
            current_user_index,
            {
                "role": "system",
                "content": (
                    DYNAMIC_CONTEXT_HEADER
                    + "\n\n"
                    + "\n\n".join(dynamic_context_blocks)
                ),
            },
        )

    return conversation_messages
