"""管理一次聊天回合从用户消息入库到回复完成或失败清理的生命周期。"""

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session as DBSession

from core.config import settings
from core.database import SessionLocal
from core.models import (
    Character,
    ChatMessage,
    MessageRole,
    Session as SessionModel,
    SessionPersona,
)
import services.conversation.session_service as session_service
import services.memory.cognition_service as cognition_service
import services.memory.memory_extraction_service as memory_extraction_service


class ChatTurnError(Exception):
    """可由 HTTP 层转换为对应响应的聊天回合校验错误。"""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class ChatTurn:
    session: SessionModel
    persona: SessionPersona
    character: Character
    user_message: ChatMessage
    old_reply: Optional[ChatMessage]
    is_regenerate: bool


@dataclass(frozen=True)
class CompletedChatTurn:
    assistant_message_id: int
    affection_score: int
    candidates: list[dict]


def prepare_chat_turn(
    session_id: int,
    db: DBSession,
    user_message: Optional[str] = None,
    is_regenerate: bool = False,
) -> ChatTurn:
    """校验会话并创建新用户消息，或定位待重新生成的现有回合。"""
    session = db.get(SessionModel, session_id)
    if not session:
        raise ChatTurnError(404, "Session not found")

    persona = session.persona
    if not persona:
        raise ChatTurnError(404, "Session has no persona")

    character = persona.character
    if not character:
        raise ChatTurnError(404, "Character not found")

    old_reply = None
    if is_regenerate:
        user_msg = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.session_id == session_id,
                ChatMessage.role == MessageRole.user,
                ChatMessage.is_active == True,
            )
            .order_by(ChatMessage.id.desc())
            .first()
        )
        if not user_msg:
            raise ChatTurnError(400, "No user message found to regenerate")

        old_reply = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.session_id == session_id,
                ChatMessage.role == MessageRole.assistant,
                ChatMessage.parent_id == user_msg.id,
                ChatMessage.is_active == True,
            )
            .first()
        )
    else:
        if not user_message:
            raise ChatTurnError(400, "User message cannot be empty")
        user_msg = ChatMessage(
            session_id=session_id,
            role=MessageRole.user,
            content=user_message,
            is_active=True,
        )
        try:
            db.add(user_msg)
            db.commit()
            db.refresh(user_msg)
        except Exception:
            db.rollback()
            raise

    return ChatTurn(
        session=session,
        persona=persona,
        character=character,
        user_message=user_msg,
        old_reply=old_reply,
        is_regenerate=is_regenerate,
    )


def release_prompt_read_transaction(db: DBSession) -> None:
    """在外部模型调用前显式结束 Prompt 查询阶段的 SQLite 事务。"""
    db.commit()


def complete_chat_turn(
    turn: ChatTurn,
    reply_text: str,
    reasoning_content: str,
    emotion_tag: str,
    affection_change: int,
    db: DBSession,
) -> CompletedChatTurn:
    """原子保存助手回复、候选版本及 Persona 状态。"""
    assistant_id, affection_score, candidates = session_service.save_chat_response(
        session_id=turn.session.id,
        persona_id=turn.persona.id,
        user_msg_id=turn.user_message.id,
        reply_text=reply_text,
        reasoning_content=reasoning_content,
        emotion_tag=emotion_tag,
        affection_change=affection_change,
        is_regenerate=turn.is_regenerate,
        old_reply_id=turn.old_reply.id if turn.old_reply else None,
        db=db,
    )
    return CompletedChatTurn(
        assistant_message_id=assistant_id,
        affection_score=affection_score,
        candidates=candidates,
    )


def abort_chat_turn(turn: ChatTurn, db: DBSession) -> bool:
    """回滚未完成操作，并删除本回合新建但尚无有效回复的用户消息。"""
    db.rollback()
    if turn.is_regenerate:
        return False

    try:
        db_message = db.get(ChatMessage, turn.user_message.id)
        if not db_message:
            return False
        db.delete(db_message)
        db.commit()
        return True
    except Exception as exc:
        db.rollback()
        print(f"[WARN] 清理失败聊天回合时发生异常: {exc}")
        return False


def run_post_turn_maintenance(session_id: int, persona_id: int) -> None:
    """在独立数据库会话中执行回合后的记忆提纯与认知更新检查。"""
    db = SessionLocal()
    try:
        try:
            unsummarized = memory_extraction_service.get_unsummarized_count(
                session_id, db
            )
            effective_limit = (
                memory_extraction_service.get_effective_memory_extract_limit()
            )
            if unsummarized >= effective_limit:
                count = memory_extraction_service.summarize_and_store_memory(
                    session_id, db
                )
                print(
                    f"[INFO] 自动记忆提纯: 提取了 {count} 条记忆 "
                    f"(session_id={session_id}, trigger={effective_limit})"
                )
        except Exception as exc:
            db.rollback()
            print(f"[WARN] 自动记忆提纯失败: {exc}")

        try:
            cognition_unseen = cognition_service.get_cognition_unseen_count(
                persona_id, session_id, db
            )
            if cognition_unseen >= settings.APP_COGNITION_UPDATE_INTERVAL:
                cognition_service.update_cognition_state(persona_id, db)
                print(f"[INFO] 自动认知更新完成 (persona_id={persona_id})")
        except Exception as exc:
            db.rollback()
            print(f"[WARN] 自动认知更新失败: {exc}")
    finally:
        db.close()
