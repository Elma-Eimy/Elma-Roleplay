"""世界书内容编译和聊天深度定位，不负责触发检索。"""

import json
from typing import Optional
from .templates import replace_placeholders
from .examples import _split_example_blocks, _parse_example_block
from services.lorebook.parse_lorebook import normalize_lorebook_depth, normalize_lorebook_role

LOREBOOK_CONTEXT_NOTE = (
    "以下为本回合触发的世界书背景设定："
)


def _entry_order(entry: dict) -> int:
    """安全读取世界书排序值，异常值回退到默认顺序。"""
    try:
        return int(entry.get("insertion_order", entry.get("priority", 100)))
    except (TypeError, ValueError):
        return 100


def _compile_lorebook_block(
    entries: list[dict],
    position: str,
    char_name: str,
    user_name: str,
    *,
    depth: Optional[int] = None,
) -> str:
    """把同一注入位置的条目合并为带来源边界的知识块。"""
    contents = []
    for entry in sorted(entries, key=_entry_order):
        content = str(entry.get("content", "")).strip()
        if content:
            contents.append(
                replace_placeholders(content, char_name, user_name)
            )
    if not contents:
        return ""

    attributes = [f'position="{position}"']
    if depth is not None:
        attributes.append(f'depth="{depth}"')
    return (
        f"<lorebook_knowledge {' '.join(attributes)}>\n"
        f"{LOREBOOK_CONTEXT_NOTE}\n\n"
        + "\n\n".join(contents)
        + "\n</lorebook_knowledge>"
    )


def _compile_lorebook_example_messages(
    entries: list[dict],
    char_name: str,
    user_name: str,
) -> list[dict]:
    """把世界书的示例位置条目解析为真正的 few-shot 消息。"""
    compiled = []
    for entry in sorted(entries, key=_entry_order):
        raw_content = str(entry.get("content", "")).strip()
        if not raw_content:
            continue
        blocks = _split_example_blocks(raw_content)

        for block in blocks:
            block = block.strip()
            if not block:
                continue
            parsed = _parse_example_block(block, char_name, user_name)
            if parsed:
                compiled.extend(parsed)
            else:
                compiled.append(
                    {
                        "role": "system",
                        "content": _compile_lorebook_block(
                            [{"content": block}],
                            "example_fallback",
                            char_name,
                            user_name,
                        ),
                    }
                )
    return compiled


def _inject_lorebook_at_depth(
    conversation_messages: list[dict],
    entries: list[dict],
    char_name: str,
    user_name: str,
    character_depth_prompt: Optional[dict] = None,
) -> list[dict]:
    """
    按 SillyTavern 深度把世界书条目插入聊天消息。

    Depth 0 位于最后一条聊天消息之后，Depth 1 位于最后一条之前。深度超过
    当前聊天长度时固定在聊天顶部。同深度按 user、assistant、system 分组。
    """
    if not entries and not character_depth_prompt:
        return list(conversation_messages)

    message_count = len(conversation_messages)
    grouped: dict[tuple[int, str], list[dict]] = {}
    for entry in entries:
        try:
            raw_depth = int(entry.get("depth", 4))
        except (TypeError, ValueError):
            raw_depth = 4
        depth = max(0, min(raw_depth, 999))
        role = str(entry.get("role", "system")).lower()
        if role not in {"system", "user", "assistant"}:
            role = "system"
        grouped.setdefault((depth, role), []).append(entry)

    injections_by_boundary: dict[int, list[dict]] = {}
    role_order = {"user": 0, "assistant": 1, "system": 2}
    for (depth, role), grouped_entries in sorted(
        grouped.items(),
        key=lambda item: (
            max(0, message_count - min(item[0][0], message_count)),
            role_order[item[0][1]],
        ),
    ):
        boundary = max(0, message_count - min(depth, message_count))
        block = _compile_lorebook_block(
            grouped_entries,
            "at_depth",
            char_name,
            user_name,
            depth=depth,
        )
        if block:
            injections_by_boundary.setdefault(boundary, []).append(
                {"role": role, "content": block}
            )

    if character_depth_prompt:
        depth = character_depth_prompt["depth"]
        boundary = max(0, message_count - min(depth, message_count))
        injections_by_boundary.setdefault(boundary, []).append(
            {
                "role": character_depth_prompt["role"],
                "content": character_depth_prompt["content"],
            }
        )

    compiled = []
    for boundary in range(message_count + 1):
        compiled.extend(injections_by_boundary.get(boundary, []))
        if boundary < message_count:
            compiled.append(conversation_messages[boundary])
    return compiled


def _compile_character_depth_prompt(
    character,
    char_name: str,
    user_name: str,
) -> Optional[dict]:
    """Compile SillyTavern's ``extensions.depth_prompt`` without changing storage."""
    raw_extensions = getattr(character, "extensions", None)
    if isinstance(raw_extensions, str):
        try:
            extensions = json.loads(raw_extensions)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    elif isinstance(raw_extensions, dict):
        extensions = raw_extensions
    else:
        return None

    raw_depth_prompt = extensions.get("depth_prompt")
    if not isinstance(raw_depth_prompt, dict):
        return None

    prompt = raw_depth_prompt.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return None

    content = prompt.replace("\r\n", "\n").replace("\r", "\n").strip()
    content = replace_placeholders(content, char_name, user_name)
    return {
        "role": normalize_lorebook_role(
            raw_depth_prompt.get("role", "system")
        ),
        "depth": normalize_lorebook_depth(
            raw_depth_prompt.get("depth", 4)
        ),
        "content": content,
    }
