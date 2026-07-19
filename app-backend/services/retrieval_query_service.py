"""Build a compact, branch-safe query for memory and graph retrieval."""

from __future__ import annotations

import re

from sqlalchemy.orm import Session as DBSession

from core.config import settings
from core.models import ChatMessage, MessageRole


_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_text(value: str | None) -> str:
    return _WHITESPACE_RE.sub(" ", value or "").strip()


def _clip_middle(value: str, limit: int) -> str:
    """Keep both ends because the subject and the actual question often differ."""
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
    """Combine the current question with a small amount of active local history.

    Only messages in the current session and strictly before ``user_msg`` are
    considered. A branch already owns a copied fork-boundary message, so avoiding
    recursive parent reads here also prevents parent-future leakage.
    """
    max_chars = max(200, int(settings.APP_RETRIEVAL_QUERY_MAX_CHARS))
    context_turns = max(0, min(10, int(settings.APP_RETRIEVAL_CONTEXT_TURNS)))

    current_text = _normalize_text(user_msg.content)
    current_prefix = "\u5f53\u524d\u95ee\u9898\uff1a"
    current_text = _clip_middle(current_text, max_chars - len(current_prefix))
    current_block = current_prefix + current_text

    if context_turns == 0 or not current_text:
        return current_block

    # A turn normally contains one user message and one active assistant reply.
    # The wider fetch limit also accommodates an opening assistant message.
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

    # Allocate a fair base share before giving spare capacity to newer messages.
    # Long role-play replies must not consume the entire budget and silently turn
    # a configured three-turn query into only the latest turn.
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
            # Assistant replies contain both actions and dialogue and are often
            # materially longer than user turns in role-play conversations.
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

    # Every selected message first receives an equal representative share.
    base_share = max(1, content_budget // len(line_specs))
    for spec in line_specs:
        spec["allocated"] = min(len(spec["text"]), spec["cap"], base_share)

    spare = content_budget - sum(spec["allocated"] for spec in line_specs)
    # Distribute spare capacity newest-first, but only after every message has a
    # share. This preserves recency without starving the oldest selected turn.
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
