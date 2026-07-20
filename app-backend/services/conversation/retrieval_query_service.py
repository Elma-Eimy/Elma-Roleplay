"""构建用于记忆和图谱检索的紧凑且分支安全的查询。"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session as DBSession

from core.config import settings
from core.models import ChatMessage, MessageRole


_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_text(value: str | None) -> str:
    return _WHITESPACE_RE.sub(" ", value or "").strip()


def _clip_middle(value: str, limit: int) -> str:
    """保留两端，因为主题和实际问题通常会不同。"""
    if len(value) <= limit:
        return value
    if limit <= 1:
        return value[:limit]

    marker = "\u2026"
    available = limit - len(marker)
    head = max(1, int(available * 0.6))
    tail = max(0, available - head)
    return value[:head] + marker + (value[-tail:] if tail else "")


def build_contextual_retrieval_query(
    session_id: int,
    user_msg: ChatMessage,
    db: DBSession,
) -> str:
    """将当前问题与少量的活跃本地历史记录相结合。

    仅考虑当前会话中且严格在 ``user_msg`` 之前的消息。
    由于分支本身已拥有一份复制的分支边界消息，在此处避免递归读取父会话，也能防止父会话的未来数据泄露。
    """
    max_chars = max(200, int(settings.APP_RETRIEVAL_QUERY_MAX_CHARS))
    context_turns = max(0, min(10, int(settings.APP_RETRIEVAL_CONTEXT_TURNS)))

    current_text = _normalize_text(user_msg.content)
    current_prefix = "\u5f53\u524d\u95ee\u9898\uff1a"
    current_text = _clip_middle(current_text, max_chars - len(current_prefix))
    current_block = current_prefix + current_text

    if context_turns == 0 or not current_text:
        return current_block

    # 一轮对话通常包含一条用户消息和一条活跃的助手回复。
    # 较宽的获取限制也能容纳助手开场白消息。
    fetch_limit = max(4, context_turns * 3 + 2)
    records_desc = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.session_id == session_id,
            ChatMessage.id < user_msg.id,
            ChatMessage.is_active == True,
            ChatMessage.role.in_((MessageRole.user, MessageRole.assistant)),
        )
        .order_by(ChatMessage.id.desc())
        .limit(fetch_limit)
        .all()
    )

    selected_desc: list[ChatMessage] = []
    seen_user_turns = 0
    for record in records_desc:
        selected_desc.append(record)
        if record.role == MessageRole.user:
            seen_user_turns += 1
            if seen_user_turns >= context_turns:
                break

    if not selected_desc:
        return current_block

    context_prefix = "\n\u8fd1\u671f\u5bf9\u8bdd\uff1a\n"
    remaining = max_chars - len(current_block) - len(context_prefix)
    if remaining <= 4:
        return current_block

    # 在将剩余容量分配给较新的消息之前，先分配一个公平的基础份额。
    # 冗长的角色扮演回复绝不能消耗掉所有预算，从而将配置好的三轮查询默默变成仅针对最后一轮的查询。
    line_specs: list[dict] = []
    for recency, record in enumerate(selected_desc):
        text = _normalize_text(record.content)
        if not text:
            continue
        role_label = (
            "\u7528\u6237" if record.role == MessageRole.user else "\u52a9\u624b"
        )
        line_specs.append({
            "prefix": f"{role_label}\uff1a",
            "text": text,
            "recency": recency,
            # 助手的回复同时包含动作和对话，在角色扮演对话中通常比用户发言要长得多。
            "cap": 320 if record.role == MessageRole.user else 640,
            "allocated": 0,
        })

    if not line_specs:
        return current_block

    separator_cost = max(0, len(line_specs) - 1)
    prefix_cost = sum(len(spec["prefix"]) for spec in line_specs)
    content_budget = remaining - separator_cost - prefix_cost
    if content_budget <= 0:
        return current_block

    # 每条被选中的消息首先会获得等额的代表性份额。
    base_share = max(1, content_budget // len(line_specs))
    for spec in line_specs:
        spec["allocated"] = min(len(spec["text"]), spec["cap"], base_share)

    spare = content_budget - sum(spec["allocated"] for spec in line_specs)
    # 按照从新到旧的顺序分发剩余容量，但前提是每条消息都已分得份额。这在保留时效性的同时，不会让最早被选中的那一轮对话分不到容量。
    for spec in sorted(line_specs, key=lambda item: item["recency"]):
        if spare <= 0:
            break
        expandable = min(len(spec["text"]), spec["cap"]) - spec["allocated"]
        if expandable <= 0:
            continue
        extra = min(spare, expandable)
        spec["allocated"] += extra
        spare -= extra

    newest_first_lines = [
        spec["prefix"] + _clip_middle(spec["text"], spec["allocated"])
        for spec in line_specs
        if spec["allocated"] > 0
    ]
    history_block = "\n".join(reversed(newest_first_lines))
    return current_block + context_prefix + history_block
