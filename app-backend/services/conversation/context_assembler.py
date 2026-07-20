"""
会话上下文装配服务 (Session Context Assembler Service)

本服务承载角色扮演记忆系统中的“上下文装配（Context Assembly）”核心逻辑，具体包括：
1. 从向量库中跨继承链查询检索 RAG 记忆卡片。
2. 从图数据库（基于 Graph RAG）中检索角色/实体知识背景。
3. 获取当前会话历史与分支点之前的父会话示例。
4. 调用纯 Prompt 编译器拼装大模型所能直接消费的消息格式。

本模块将原本散落在路由层与执行引擎中的检索、排列和装配职责统一收拢，
实现了表示层（Router）、状态装配层（Assembler）以及超参执行层（chat_engine）的清晰解耦。
"""

from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session as DBSession
from fastapi.concurrency import run_in_threadpool
import core.models as models
from core.models import SessionPersona, ChatMessage, Character, MessageRole
import services.memory.memory_manager as memory_manager
import services.conversation.session_service as session_service
from services.memory.memory_extraction_service import get_memory_handoff_history_limit
from services.conversation.prompt_compiler import build_chat_messages
from services.memory.graph_service import retrieve_graph_context
from services.conversation.retrieval_query_service import build_contextual_retrieval_query
from services.conversation.prompt_token_estimator import (
    estimate_prompt_tokens,
    format_prompt_metrics_log,
)


def get_parent_history_examples(
    persona: SessionPersona,
    db: DBSession,
) -> list[dict]:
    """查询父分支点之前的最后四条示例，旧数据缺少边界时不注入。"""
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
    user_nickname: str = "用户"
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
    # Resolve pronouns and ellipsis with a small, branch-local context window.
    # The same semantic query is shared by vector memory and graph retrieval.
    rag_query = build_contextual_retrieval_query(session_id, user_msg, db)

    # 1. 跨继承链 RAG 向量检索
    memories = memory_manager.retrieve_memories(
        persona_id=persona.id,
        character_id=character.id,
        query=rag_query,
        db=db,
    )

    # 2. 知识图谱 Graph RAG 检索
    graph_knowledge = retrieve_graph_context(
        persona_id=persona.id,
        query_text=rag_query,
        db=db
    )

    # 3. 提取历史记录轮次。后台长期记忆提纯完成前，临时扩大窗口以保留
    # 尚未总结的消息，避免它们先离开短期上下文形成记忆空档。
    history_limit = get_memory_handoff_history_limit(session_id, db)
    if old_reply is not None:
        # 再生时旧的激活回复位于 user_msg 之后，会占用一次历史查询名额但随后
        # 被 id 边界过滤，因此额外补一个名额。
        history_limit += 1
    recent_records = session_service.get_session_history_with_inheritance(
        session_id, db, history_limit
    )

    recent_history = [
        {
            "role": r.role.value,
            "content": r.content,
            "emotion_tag": getattr(r, "emotion_tag", "平静"),
            "affection_change": getattr(r, "affection_change", 0)
        }
        for r in recent_records
        if r.id < user_msg.id 
        and r.role.value in ("user", "assistant")
    ]

    # 4. 在装配层显式查询父分支示例，Prompt 编译器不再访问数据库。
    parent_history = await run_in_threadpool(get_parent_history_examples, persona, db)

    # 5. 组装最终 messages Payload 格式 (大模型可以直接消费的结构)
    messages = build_chat_messages(
        character=character,
        persona=persona,
        recent_history=recent_history,
        user_message=user_msg.content,
        retrieved_memories=memories,
        graph_knowledge=graph_knowledge,
        parent_history=parent_history,
        user_nickname=user_nickname
    )

    # Observation only: never rewrite or trim the model payload here.
    prompt_estimate = estimate_prompt_tokens(messages)
    print(format_prompt_metrics_log(session_id, prompt_estimate))

    return messages
