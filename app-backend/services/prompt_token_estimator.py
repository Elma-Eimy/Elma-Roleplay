"""Heuristic prompt token-range estimation without model-specific tokenizers.

This module is observational only: it never rewrites or trims messages.
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
    r"recalled_memories|factual_relationships)>.*?</\1>",
    re.DOTALL,
)
CURRENT_USER_MARKER = "【当前用户的最新消息：】"


def estimate_text_tokens(text: str | None) -> dict[str, int]:
    """Return a deliberately broad token estimate for mixed Chinese/Latin text."""
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

    # The compiler appends this marker last. rfind avoids a lorebook or memory
    # quotation containing the same literal label from stealing the split point.
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

    has_final_user = bool(payload and payload[-1].get("role") == "user")
    history_end = len(payload) - 1 if has_final_user else len(payload)
    for message in payload[1:history_end]:
        _add_text(sections["recent_history"], str(message.get("content", "")))

    if has_final_user:
        final_content = str(payload[-1].get("content", ""))
        for section_name, fragment in _split_enhanced_user_content(final_content):
            _add_text(sections[section_name], fragment)

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
