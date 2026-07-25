"""无特定模型分词器（Tokenizer）的启发式 Prompt Token 范围估算。

本模块仅用于观察/测量：绝不会重写或裁剪消息。
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable


ESTIMATION_METHOD = "heuristic_v1"
SECTION_ORDER = (
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
)

TAG_TO_SECTION = {
    "current_scenario": "scenario",
    "cognition_state": "cognition",
    "current_status": "status",
    "lorebook_knowledge": "lorebook",
    "recalled_memories": "long_term_memory",
    "factual_relationships": "graph",
}
TAG_BLOCK_RE = re.compile(
    r"<(current_scenario|cognition_state|current_status|lorebook_knowledge|"
    r"recalled_memories|factual_relationships)(?:\s[^>]*)?>.*?</\1>",
    re.DOTALL,
)
GENERATED_LOREBOOK_RE = re.compile(
    r"<lorebook_knowledge\s+position=",
    re.IGNORECASE,
)
CURRENT_USER_MARKER = "【当前用户的最新消息：】"


def estimate_text_tokens(text: str | None) -> dict[str, int]:
    """针对混合中文/拉丁文文本，返回一个故意放宽的 Token 估算值。"""
    value = text or ""
    if not value:
        return {
            "characters": 0,
            "estimated_tokens": 0,
            "lower_bound": 0,
            "upper_bound": 0,
        }

    cjk_count = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", value))
    latin_count = len(re.findall(r"[A-Za-z0-9]", value))
    nonspace_count = len(re.findall(r"\S", value))
    other_count = max(0, nonspace_count - cjk_count - latin_count)

    lower = math.ceil(cjk_count * 0.50 + latin_count / 5.0 + other_count * 0.25)
    estimated = math.ceil(cjk_count * 0.80 + latin_count / 4.0 + other_count * 0.60)
    upper = math.ceil(cjk_count * 1.50 + latin_count / 3.0 + other_count * 2.0)

    lower = max(1, lower)
    estimated = max(lower, estimated)
    upper = max(estimated, upper)
    return {
        "characters": len(value),
        "estimated_tokens": estimated,
        "lower_bound": lower,
        "upper_bound": upper,
    }


def _empty_estimate() -> dict[str, int]:
    return {
        "characters": 0,
        "estimated_tokens": 0,
        "lower_bound": 0,
        "upper_bound": 0,
    }


def _add_estimate(target: dict[str, int], addition: dict[str, int]) -> None:
    for key in ("characters", "estimated_tokens", "lower_bound", "upper_bound"):
        target[key] += addition[key]


def _add_text(section: dict[str, int], text: str | None) -> None:
    _add_estimate(section, estimate_text_tokens(text))


def _split_enhanced_user_content(content: str) -> Iterable[tuple[str, str]]:
    """Yield non-overlapping ``(section, exact_text_fragment)`` pairs."""
    spans = []
    for match in TAG_BLOCK_RE.finditer(content):
        spans.append((match.start(), match.end(), TAG_TO_SECTION[match.group(1)]))

    # 编译器会在最后附加此标记。使用 rfind 可避免包含相同字面量标签的世界书或记忆引用抢占分割点。
    marker_index = content.rfind(CURRENT_USER_MARKER)
    if marker_index >= 0:
        spans.append((marker_index, len(content), "current_user_message"))

    spans.sort(key=lambda item: item[0])
    cursor = 0
    for start, end, section in spans:
        if start < cursor:
            continue
        if start > cursor:
            yield "other", content[cursor:start]
        yield section, content[start:end]
        cursor = end
    if cursor < len(content):
        yield "other", content[cursor:]


def estimate_prompt_tokens(messages: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Estimate a final chat payload and break it down by prompt section."""
    payload = messages or []
    sections = {name: _empty_estimate() for name in SECTION_ORDER}

    if payload:
        _add_text(sections["character"], str(payload[0].get("content", "")))

    # 正常聊天 Payload 以 PHI / 输出契约 system 消息收尾。它仍属于提示指令，
    # 计入 character 区段；随后再定位其前方真正的当前 user 消息。
    has_post_history_system = bool(
        len(payload) > 1 and payload[-1].get("role") == "system"
    )
    conversation_end = len(payload) - 1 if has_post_history_system else len(payload)
    if has_post_history_system:
        _add_text(sections["character"], str(payload[-1].get("content", "")))

    # @ Depth 0 世界书可能位于真实用户消息之后，其角色本身也可能是 user。
    # 从后向前跳过带生成标记的世界书消息，定位本轮真正的用户原话。
    final_user_index = None
    for index in range(conversation_end - 1, -1, -1):
        message = payload[index]
        content = str(message.get("content", ""))
        if (
            message.get("role") == "user"
            and not GENERATED_LOREBOOK_RE.search(content)
        ):
            final_user_index = index
            break

    # 角色定义可能因 before/after_char 注入而成为首条 system 后的独立
    # system。在首个非 system 消息前，非动态 system 仍属于角色提示区。
    leading_system_indexes = set()
    for index in range(1, conversation_end):
        message = payload[index]
        if message.get("role") != "system":
            break
        content = str(message.get("content", ""))
        if TAG_BLOCK_RE.search(content):
            for section_name, fragment in _split_enhanced_user_content(content):
                _add_text(sections[section_name], fragment)
        else:
            _add_text(sections["character"], content)
        leading_system_indexes.add(index)

    for index, message in enumerate(payload[1:conversation_end], start=1):
        if index in leading_system_indexes or index == final_user_index:
            continue
        content = str(message.get("content", ""))
        # @ Depth 世界书可以使用任意角色，所以按标签而非 role 识别；
        # 同时继续兼容旧版增强 user 中相同的 XML 动态块。
        if TAG_BLOCK_RE.search(content):
            for section_name, fragment in _split_enhanced_user_content(content):
                _add_text(sections[section_name], fragment)
        else:
            _add_text(sections["recent_history"], content)

    if final_user_index is not None:
        final_content = str(payload[final_user_index].get("content", ""))
        if CURRENT_USER_MARKER in final_content:
            for section_name, fragment in _split_enhanced_user_content(final_content):
                _add_text(sections[section_name], fragment)
        else:
            _add_text(sections["current_user_message"], final_content)

    # Chat APIs add role/separator framing that is not present in content.
    # Keep it visible under "other" instead of pretending the section sum is exact.
    message_count = len(payload)
    sections["other"]["estimated_tokens"] += message_count * 4 + (2 if payload else 0)
    sections["other"]["lower_bound"] += message_count * 3 + (1 if payload else 0)
    sections["other"]["upper_bound"] += message_count * 8 + (4 if payload else 0)

    total = _empty_estimate()
    for estimate in sections.values():
        _add_estimate(total, estimate)

    return {
        **total,
        "method": ESTIMATION_METHOD,
        "is_exact": False,
        "sections": sections,
    }


def format_prompt_metrics_log(session_id: int, estimate: dict[str, Any]) -> str:
    active_sections = ", ".join(
        f"{name}={values['estimated_tokens']}"
        for name, values in estimate["sections"].items()
        if values["estimated_tokens"] > 0
    )
    return (
        f"[PROMPT METRICS] session_id={session_id} "
        f"estimated={estimate['estimated_tokens']} "
        f"range={estimate['lower_bound']}-{estimate['upper_bound']} "
        f"characters={estimate['characters']} sections=[{active_sections}]"
    )
