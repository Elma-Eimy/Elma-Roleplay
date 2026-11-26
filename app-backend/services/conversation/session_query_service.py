"""单聊会话列表、详情与当前故事历史；沿用调用方数据库会话。"""
from sqlalchemy.orm import Session as DBSession, aliased
from sqlalchemy.sql import func
from core.models import Character, ChatMessage, MessageRole, Session as SessionModel, SessionPersona
from .session_access import get_single_session


def get_recent_sessions(limit: int, offset: int, db: DBSession) -> dict:
    """
    分页获取首页所需的最近会话聚合数据。

    查询次数固定为两次：一次统计总数，一次联表获取当前页及每个会话最后一条
    active 消息，避免随着会话数量增加产生 N+1 查询。
    """
    total = (
        db.query(func.count(SessionModel.id))
        .join(SessionPersona, SessionPersona.session_id == SessionModel.id)
        .filter(SessionModel.kind == "single")
        .join(Character, Character.id == SessionPersona.character_id)
        .scalar()
        or 0
    )

    latest_message = aliased(ChatMessage)
    latest_message_id = (
        db.query(ChatMessage.id)
        .filter(
            ChatMessage.session_id == SessionModel.id,
            ChatMessage.is_active.is_(True),
        )
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .correlate(SessionModel)
        .limit(1)
        .scalar_subquery()
    )

    rows = (
        db.query(SessionModel, SessionPersona, Character, latest_message)
        .join(SessionPersona, SessionPersona.session_id == SessionModel.id)
        .filter(SessionModel.kind == "single")
        .join(Character, Character.id == SessionPersona.character_id)
        .outerjoin(latest_message, latest_message.id == latest_message_id)
        .order_by(SessionModel.updated_at.desc(), SessionModel.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    sessions = []
    for session, persona, character, last_message in rows:
        sessions.append(
            {
                "id": session.id,
                "title": session.title,
                "parent_session_id": session.parent_session_id,
                "created_at": session.created_at.isoformat() if session.created_at else None,
                "updated_at": session.updated_at.isoformat() if session.updated_at else None,
                "persona": {
                    "id": persona.id,
                    "affection_score": persona.affection_score,
                    "current_mood": persona.current_mood,
                },
                "character": {
                    "id": character.id,
                    "name": character.name,
                    "avatar_path": character.avatar_path,
                },
                "last_message": (
                    {
                        "content": last_message.content,
                        "created_at": (
                            last_message.created_at.isoformat()
                            if last_message.created_at
                            else None
                        ),
                    }
                    if last_message
                    else None
                ),
            }
        )

    return {
        "sessions": sessions,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(sessions) < total,
    }


def get_character_sessions(
    *,
    character_id: int,
    include_last_message: bool,
    limit: int,
    offset: int,
    db: DBSession,
) -> dict:
    """Return one character's sessions with stable pagination and no N+1 queries."""
    total = (
        db.query(func.count(SessionModel.id))
        .join(SessionPersona, SessionPersona.session_id == SessionModel.id)
        .filter(SessionModel.kind == "single")
        .filter(SessionPersona.character_id == character_id)
        .scalar()
        or 0
    )

    if include_last_message:
        latest_message = aliased(ChatMessage)
        latest_message_id = (
            db.query(ChatMessage.id)
            .filter(
                ChatMessage.session_id == SessionModel.id,
                ChatMessage.is_active.is_(True),
            )
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .correlate(SessionModel)
            .limit(1)
            .scalar_subquery()
        )
        rows = (
            db.query(SessionModel, SessionPersona, latest_message)
            .join(SessionPersona, SessionPersona.session_id == SessionModel.id)
            .filter(SessionModel.kind == "single")
            .outerjoin(latest_message, latest_message.id == latest_message_id)
            .filter(SessionPersona.character_id == character_id)
            .order_by(SessionModel.updated_at.desc(), SessionModel.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
    else:
        rows = [
            (session, persona, None)
            for session, persona in (
                db.query(SessionModel, SessionPersona)
                .join(SessionPersona, SessionPersona.session_id == SessionModel.id)
                .filter(SessionModel.kind == "single")
                .filter(SessionPersona.character_id == character_id)
                .order_by(SessionModel.updated_at.desc(), SessionModel.id.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
        ]

    sessions = []
    for session, persona, last_message in rows:
        sessions.append(
            {
                "id": session.id,
                "title": session.title,
                "parent_session_id": session.parent_session_id,
                "fork_message_id": session.fork_message_id,
                "created_at": session.created_at.isoformat() if session.created_at else None,
                "updated_at": session.updated_at.isoformat() if session.updated_at else None,
                "persona": {
                    "id": persona.id,
                    "affection_score": persona.affection_score,
                    "current_mood": persona.current_mood,
                },
                "last_message": (
                    {
                        "content": last_message.content,
                        "created_at": (
                            last_message.created_at.isoformat()
                            if last_message.created_at
                            else None
                        ),
                    }
                    if last_message
                    else None
                ),
            }
        )

    return {
        "character_id": character_id,
        "sessions": sessions,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(sessions) < total,
    }


def get_session_history_page(session_id, db, limit, before_id=None):
    """历史与候选共用一次单聊加载。"""
    session = get_single_session(session_id, db)
    if session is None:
        return None
    messages = _history_for_session(session, db, limit, before_id)
    parent_ids = [message.parent_id for message in messages
                  if message.role == MessageRole.assistant and message.parent_id is not None]
    return messages, _candidates_for_session(session, parent_ids, db)


def get_session_history_with_inheritance(
    session_id: int,
    db: DBSession,
    limit: int,
    before_id: int = None
) -> list[ChatMessage]:
    """
    获取指定会话的聊天历史记录。
    按照时间正序排列（最旧的在前面，最新的在后面）。
    注：根据对齐后的颗粒度要求，开启子会话时不再合并父会话的原始消息记录，
    以便子会话独立于父会话重新起步，因此此处仅拉取当前会话的消息，不再递归向上追溯。
    """
    session = get_single_session(session_id, db)
    if session is None:
        return []
    return _history_for_session(session, db, limit, before_id)


def _history_for_session(session, db, limit, before_id=None):
    query = db.query(ChatMessage).filter(
        ChatMessage.session_id == session.id,
        ChatMessage.is_active == True
    )
    if before_id is not None:
        query = query.filter(ChatMessage.id < before_id)

    messages = (
        query.order_by(ChatMessage.id.desc())
        .limit(limit)
        .all()
    )
    messages.reverse()  # 反转以恢复时间正序
    return messages


def get_candidates_by_parent(
    session_id: int,
    parent_ids: list[int],
    db: DBSession,
) -> dict[int, list[ChatMessage]]:
    """在单次查询中获取历史页面中所有滑动候选（swipe candidates）。"""
    session = get_single_session(session_id, db)
    if session is None:
        return {}
    return _candidates_for_session(session, parent_ids, db)


def _candidates_for_session(session, parent_ids, db):
    if not parent_ids:
        return {}

    candidates = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.session_id == session.id,
            ChatMessage.role == MessageRole.assistant,
            ChatMessage.parent_id.in_(set(parent_ids)),
        )
        .order_by(ChatMessage.id)
        .all()
    )
    grouped: dict[int, list[ChatMessage]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.parent_id, []).append(candidate)
    return grouped


def get_session_detail(session_id: int, db: DBSession):
    """获取会话详情（含 Persona 完整状态 + Character 基本信息）"""
    session = get_single_session(session_id, db)
    if session is None:
        return None

    persona = session.persona
    character = persona.character if persona else None

    return {
        "id": session.id,
        "title": session.title,
        "parent_session_id": session.parent_session_id,
        "fork_message_id": session.fork_message_id,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
        "persona": {
            "id": persona.id,
            "character_id": persona.character_id,
            "affection_score": persona.affection_score,
            "cognition_state": persona.cognition_state,
            "current_mood": persona.current_mood,
            "current_scenario_override": persona.current_scenario_override,
        } if persona else None,
        "character": {
            "id": character.id,
            "name": character.name,
            "avatar_path": character.avatar_path,
        } if character else None,
    }
