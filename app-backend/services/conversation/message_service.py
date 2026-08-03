"""管理消息编辑、删除以及候选回复切换的完整生命周期。"""

import json

from sqlalchemy.orm import Session as DBSession
from sqlalchemy.sql import func

from core.models import ChatMessage, MessageRole, OutboxJob, Session, SessionPersona


class CandidateNotFoundError(ValueError):
    """目标候选消息不存在。"""


class CandidateValidationError(ValueError):
    """目标消息不满足候选切换条件。"""


def update_message(message_id: int, content: str, db: DBSession) -> dict:
    """更新消息内容，并通过 Outbox 异步清理已经失效的旧音频。"""
    message = db.get(ChatMessage, message_id)
    if message is None:
        raise ValueError("Message not found")

    old_audio_path = message.audio_path
    message.content = content
    message.audio_path = None

    session = db.get(Session, message.session_id)
    if session is not None:
        session.updated_at = func.now()

    if old_audio_path:
        db.add(
            OutboxJob(
                task_type="delete_audio",
                payload=json.dumps({"file_paths": [old_audio_path]}),
            )
        )

    try:
        db.commit()
        db.refresh(message)
    except Exception:
        db.rollback()
        raise

    return {
        "message": "Message updated successfully",
        "message_id": message.id,
        "content": message.content,
    }


def delete_message(message_id: int, db: DBSession) -> dict:
    """删除消息，同时回滚候选状态、角色状态和记忆处理指针。"""
    message = db.get(ChatMessage, message_id)
    if message is None:
        raise ValueError("Message not found")

    deleted_id = message.id
    session_id = message.session_id
    persona = (
        db.query(SessionPersona)
        .filter(SessionPersona.session_id == session_id)
        .first()
    )

    if persona is not None:
        if message.role == MessageRole.assistant:
            if message.is_active:
                sibling = (
                    db.query(ChatMessage)
                    .filter(
                        ChatMessage.session_id == session_id,
                        ChatMessage.role == MessageRole.assistant,
                        ChatMessage.parent_id == message.parent_id,
                        ChatMessage.id != message_id,
                    )
                    .order_by(ChatMessage.id.desc())
                    .first()
                )

                if sibling is not None:
                    # 删除当前激活候选时，自动启用最近的替补版本。
                    sibling.is_active = True
                    old_change = message.affection_change or 0
                    new_change = sibling.affection_change or 0
                    persona.affection_score = max(
                        0,
                        min(
                            100,
                            persona.affection_score - old_change + new_change,
                        ),
                    )
                    persona.current_mood = sibling.emotion_tag or "平静"
                else:
                    if message.affection_change is not None:
                        persona.affection_score = max(
                            0,
                            persona.affection_score - message.affection_change,
                        )
                    persona.current_mood = _find_previous_mood(
                        session_id, message_id, db
                    )

        elif message.role == MessageRole.user:
            active_child = (
                db.query(ChatMessage)
                .filter(
                    ChatMessage.session_id == session_id,
                    ChatMessage.role == MessageRole.assistant,
                    ChatMessage.parent_id == message_id,
                    ChatMessage.is_active.is_(True),
                )
                .first()
            )
            if active_child and active_child.affection_change is not None:
                persona.affection_score = max(
                    0,
                    persona.affection_score - active_child.affection_change,
                )
            persona.current_mood = _find_previous_mood(session_id, message_id, db)

        # 指针恰好落在被删除消息上时，退回当前会话的上一条消息。
        if persona.last_summarized_msg_id == message_id:
            persona.last_summarized_msg_id = _find_previous_message_id(
                session_id, message_id, db
            )
        if persona.last_cognition_update_msg_id == message_id:
            persona.last_cognition_update_msg_id = _find_previous_message_id(
                session_id, message_id, db
            )

    audio_paths = []
    if message.audio_path:
        audio_paths.append(message.audio_path)
    if message.role == MessageRole.user:
        children = (
            db.query(ChatMessage)
            .filter(ChatMessage.parent_id == message_id)
            .all()
        )
        audio_paths.extend(child.audio_path for child in children if child.audio_path)

    db.delete(message)
    if audio_paths:
        db.add(
            OutboxJob(
                task_type="delete_audio",
                payload=json.dumps({"file_paths": audio_paths}),
            )
        )

    session = db.get(Session, session_id)
    if session is not None:
        session.updated_at = func.now()

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "message": "Message deleted and state rolled back successfully",
        "message_id": deleted_id,
        "affection_score": persona.affection_score if persona else None,
        "current_mood": persona.current_mood if persona else None,
    }


def switch_candidate(message_id: int, db: DBSession) -> dict:
    """切换当前激活候选，并原子更新好感度、心情和会话时间。"""
    message = db.get(ChatMessage, message_id)
    if message is None:
        raise CandidateNotFoundError("Message not found")
    if message.role != MessageRole.assistant:
        raise CandidateValidationError("Only assistant messages can be switched")
    if message.parent_id is None:
        raise CandidateValidationError(
            "Cannot switch candidates for a message without a parent message"
        )

    session_id = message.session_id
    latest_user = (
        db.query(ChatMessage.id)
        .filter(
            ChatMessage.session_id == session_id,
            ChatMessage.role == MessageRole.user,
            ChatMessage.is_active.is_(True),
        )
        .order_by(ChatMessage.id.desc())
        .first()
    )
    if latest_user is None or message.parent_id != latest_user[0]:
        raise CandidateValidationError(
            "Confirmed candidate groups cannot be switched; fork the session "
            "to change an earlier turn"
        )

    persona = (
        db.query(SessionPersona)
        .filter(SessionPersona.session_id == session_id)
        .first()
    )
    old_active = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.session_id == session_id,
            ChatMessage.role == MessageRole.assistant,
            ChatMessage.parent_id == message.parent_id,
            ChatMessage.is_active.is_(True),
        )
        .first()
    )

    db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id,
        ChatMessage.role == MessageRole.assistant,
        ChatMessage.parent_id == message.parent_id,
    ).update({ChatMessage.is_active: False}, synchronize_session=False)
    message.is_active = True

    if persona is not None:
        old_change = (old_active.affection_change or 0) if old_active else 0
        new_change = message.affection_change or 0
        persona.affection_score = max(
            0, min(100, persona.affection_score - old_change + new_change)
        )
        persona.current_mood = message.emotion_tag or "平静"

    session = db.get(Session, session_id)
    if session is not None:
        session.updated_at = func.now()

    try:
        db.commit()
        db.refresh(message)
        if persona is not None:
            db.refresh(persona)
    except Exception:
        db.rollback()
        raise

    return {
        "message": "Candidate switched successfully",
        "message_id": message.id,
        "is_active": message.is_active,
        "affection_score": persona.affection_score if persona else None,
        "current_mood": persona.current_mood if persona else None,
    }


def _find_previous_message_id(
    session_id: int, message_id: int, db: DBSession
) -> int | None:
    """返回当前会话中目标消息之前的最近消息 ID。"""
    previous = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.session_id == session_id,
            ChatMessage.id < message_id,
        )
        .order_by(ChatMessage.id.desc())
        .first()
    )
    return previous.id if previous else None


def _find_previous_mood(
    session_id: int, message_id: int, db: DBSession
) -> str:
    """返回目标消息之前最近一条助手消息的情绪。"""
    previous = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.session_id == session_id,
            ChatMessage.role == MessageRole.assistant,
            ChatMessage.id < message_id,
        )
        .order_by(ChatMessage.id.desc())
        .first()
    )
    return previous.emotion_tag or "平静" if previous else "平静"
