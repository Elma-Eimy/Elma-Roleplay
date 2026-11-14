"""
会话上下文装配服务 (Session Context Assembler Service)

本服务承载角色扮演记忆系统中的“上下文装配（Context Assembly）”核心逻辑，具体包括：
1. 从向量库中跨继承链查询语义记忆种子。
2. 经图谱扩展回查 SQLite 事实卡，统一去重并限制预算。
3. 加载会话压缩摘要与尚未覆盖的原文，分支使用冻结的合法历史。
4. 调用纯 Prompt 编译器拼装大模型所能直接消费的消息格式。

本模块将原本散落在路由层与执行引擎中的检索、排列和装配职责统一收拢，
实现了表示层（Router）、状态装配层（Assembler）以及超参执行层（chat_engine）的清晰解耦。
"""

from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session as DBSession
import core.models as models
from core.models import SessionPersona, ChatMessage, Character, MessageRole
from services.conversation.session_access import get_single_session
from services.conversation.context_compression import _prepare_context
from services.conversation.prompt_compiler import build_chat_messages
from services.conversation.role_state_service import _resolve_state
from services.memory.joint_retrieval import retrieve_joint_memories
from services.memory.memory_event_buffer import load_event_snapshot, event_context
from services.memory.memory_extraction_jobs import pending_context
from services.conversation.retrieval_query_service import build_contextual_retrieval_query
from services.conversation.prompt_token_estimator import (
    estimate_prompt_tokens,
    format_prompt_metrics_log,
)


def get_parent_history_examples(
    persona: SessionPersona,
    db: DBSession,
) -> list[dict]:
    """兼容旧调用的父分支示例读取；聊天装配已改用冻结上下文。"""
    if not persona.parent_persona_id:
        return []

    parent_persona = db.get(SessionPersona, persona.parent_persona_id)
    child_session = db.get(models.Session, persona.session_id)
    fork_message_id = child_session.fork_message_id if child_session else None
    if not parent_persona or fork_message_id is None:
        return []

    fork_message_exists = db.query(ChatMessage.id).filter(
        ChatMessage.id == fork_message_id,
        ChatMessage.session_id == parent_persona.session_id,
    ).first()
    if not fork_message_exists:
        return []

    parent_messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == parent_persona.session_id,
        ChatMessage.id < fork_message_id,
        ChatMessage.role.in_([MessageRole.user, MessageRole.assistant]),
        ChatMessage.is_active == True,
    ).order_by(ChatMessage.id.desc()).limit(4).all()
    parent_messages.reverse()
    return [
        {
            "role": message.role.value,
            "content": message.content,
            "emotion_tag": getattr(message, "emotion_tag", "平静"),
            "affection_change": getattr(message, "affection_change", 0),
        }
        for message in parent_messages
    ]


async def assemble_prompt_context(
    session_id: int,
    character: Character,
    persona: SessionPersona,
    user_msg: ChatMessage,
    old_reply: Optional[ChatMessage],
    db: DBSession,
    user_nickname: str = "用户",
    *,
    compress_context: bool = False,
) -> List[Dict[str, Any]]:
    """
    执行混合 RAG 检索（ChromaDB + Graph DB）并组装发送给大模型的消息列表。
    
    Args:
        session_id: 当前会话的 ID
        character: 关联的角色实体
        persona: 关联的 Persona 运行态实体
        user_msg: 当前激活的用户消息实体
        old_reply: 要被覆盖的旧回复消息实体 (仅再生模式下非空)
        db: SQLAlchemy 数据库会话
        user_nickname: 用户昵称
        
    Returns:
        标准的 dict 形式 messages payload
    """
    session = get_single_session(session_id, db)
    if session is None or session.persona is None:
        raise LookupError("故事不存在")
    context = await _prepare_context(session, user_msg.id, db, compress=compress_context)
    # Resolve pronouns and ellipsis with a small, branch-local context window.
    # The same semantic query is shared by vector memory and graph retrieval.
    rag_query = build_contextual_retrieval_query(session_id, user_msg, db)

    # 1. 语义种子与图谱扩展共用 SQLite 事实，统一去重和预算。
    memories = retrieve_joint_memories(
        persona_id=persona.id,
        character_id=character.id,
        query=rag_query,
        db=db,
        before_message_id=user_msg.id,
    )

    # 摘要覆盖之后的原文全部保留，包括压缩失败或未满一个批次的待处理消息。
    recent_history = context.remaining

    # 5. 组装最终 messages Payload 格式 (大模型可以直接消费的结构)
    messages = build_chat_messages(
        character=character,
        persona=persona,
        recent_history=recent_history,
        user_message=user_msg.content,
        retrieved_memories=memories,
        graph_knowledge=None,
        parent_history=None,
        context_summary=context.summary,
        user_nickname=user_nickname,
        current_role_state=_resolve_state(session, db, before_id=user_msg.id + 1)[0]["state"],
        ongoing_events=event_context(load_event_snapshot(persona.id, db, before_message_id=user_msg.id)),
        pending_memories=pending_context(persona.id, db, user_msg.id),
    )

    # Observation only: never rewrite or trim the model payload here.
    prompt_estimate = estimate_prompt_tokens(messages)
    print(format_prompt_metrics_log(session_id, prompt_estimate))

    return messages
