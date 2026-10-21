"""按有效消息重放状态增量；候选、删除和分叉自然遵循剧情边界。"""

import hashlib
from sqlalchemy import text
from sqlalchemy.orm import load_only

from core.models import Session, ChatMessage
from services.conversation.role_state_schema import decode_state, encode_state, merge_state, validate_patch


class StateConflict(ValueError):
    pass


def resolve_state(session_id, db, before_id=None):
    session = db.get(Session, session_id)
    if session is None or session.persona is None:
        raise LookupError("故事不存在")
    base = session.persona.role_state_base
    state = decode_state(base)
    query = db.query(ChatMessage).options(load_only(ChatMessage.id, ChatMessage.role_state_patch, ChatMessage.role_state_manual)).filter(ChatMessage.session_id == session_id, ChatMessage.is_active.is_(True))
    if before_id is not None:
        query = query.filter(ChatMessage.id < before_id)
    messages = query.order_by(ChatMessage.id).all()
    revision_parts = [base]
    for message in messages:
        for encoded in (message.role_state_patch, message.role_state_manual):
            if encoded:
                state = merge_state(state, decode_state(encoded), check_limit=False)
        revision_parts.append([message.id, message.role_state_patch, message.role_state_manual])
    revision = hashlib.sha256(encode_state(revision_parts).encode("utf-8")).hexdigest()
    return {"session_id": session_id, "state": state, "revision": revision}, messages


def get_state(session_id, db):
    return resolve_state(session_id, db)[0]


def state_before_message(message, db):
    # 明确选择非激活候选分叉时，也只重放所选候选，而非其激活的兄弟消息。
    boundary = message.parent_id if message.parent_id is not None else message.id
    result, _ = resolve_state(message.session_id, db, before_id=boundary)
    state = result["state"]
    if message.parent_id is not None:
        parent = db.get(ChatMessage, message.parent_id)
        if parent and parent.role_state_manual:
            state = merge_state(state, decode_state(parent.role_state_manual), check_limit=False)
    return state


def state_at_message(message, db):
    state = state_before_message(message, db)
    for encoded in (message.role_state_patch, message.role_state_manual):
        if encoded:
            state = merge_state(state, decode_state(encoded), check_limit=False)
    return state


def update_state(session_id, patch, expected_revision, db):
    # 与不经过聊天锁的消息编辑/删除及候选切换也保持写入串行，校验与保存不可分离。
    try:
        db.execute(text("BEGIN IMMEDIATE"))
        return _update_state(session_id, patch, expected_revision, db)
    except Exception:
        db.rollback()
        raise


def _update_state(session_id, patch, expected_revision, db):
    current, messages = resolve_state(session_id, db)
    if current["revision"] != expected_revision:
        raise StateConflict("剧情或状态已变化，请重新加载后再修改")
    patch = validate_patch(patch, manual=True)
    merged = merge_state(current["state"], patch)
    if messages:
        anchor = messages[-1]
        manual = decode_state(anchor.role_state_manual)
        # 合并增量时必须保留 null 清除语义，不能用状态合并函数消掉 tombstone。
        if "scene" in patch:
            manual["scene"] = patch["scene"]
        actors = manual.setdefault("characters", {})
        for name, fields in patch.get("characters", {}).items():
            actors.setdefault(name, {}).update(fields)
        anchor.role_state_manual = encode_state(manual)
    else:
        db.get(Session, session_id).persona.role_state_base = encode_state(merged)
    try:
        db.flush()
        result = get_state(session_id, db)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def validated_model_patch(session_id, user_msg_id, patch, db):
    if patch is None:
        return None
    try:
        patch = validate_patch(patch)
        state = resolve_state(session_id, db, before_id=user_msg_id + 1)[0]["state"]
        merge_state(state, patch)
        return encode_state(patch)
    except (ValueError, TypeError):
        # 状态附属信息无效不影响正文落库，也不清空原状态。
        return None
