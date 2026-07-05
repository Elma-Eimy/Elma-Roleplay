"""
会话上下文装配服务 (Session Context Assembler Service)

本服务承载角色扮演记忆系统中的“上下文装配（Context Assembly）”核心逻辑，具体包括：
1. 提取当前会话相关实体（Session、Persona、Character）并准备用户消息实体（如果是重新生成，则召回上一条消息）。
2. 从向量库中跨继承链查询检索 RAG 记忆卡片。
3. 从图数据库（基于 Graph RAG）中检索角色/实体知识背景。
4. 获取继承链历史消息并过滤出激活的历史轮次。
5. 调用 Prompt 编译器（prompt_compiler）拼装大模型所能直接消费的 System + Message 完整格式。

本模块将原本散落在路由层与执行引擎中的检索、排列和装配职责统一收拢，
实现了表示层（Router）、状态装配层（Assembler）以及超参执行层（chat_engine）的清晰解耦。
"""

from typing import Optional, Tuple, List, Dict, Any
from sqlalchemy.orm import Session as DBSession
from fastapi import HTTPException
from core import models
from core.models import Session as SessionModel, SessionPersona, ChatMessage, Character, MessageRole
from core.config import settings
import services.memory_manager as memory_manager
import services.session_service as session_service
from services.prompt_compiler import _build_chat_messages
from services.graph_service import retrieve_graph_context


def prepare_chat_context(
    session_id: int,
    db: DBSession,
    user_message: Optional[str] = None,
    is_regenerate: bool = False
) -> Tuple[SessionModel, SessionPersona, Character, ChatMessage, Optional[ChatMessage]]:
    """
    第一阶段：提取核心数据库实体并安全入库/召回用户消息。
    
    Args:
        session_id: 当前会话的 ID
        db: SQLAlchemy 数据库会话
        user_message: 用户发送的文本内容
        is_regenerate: 是否为重新生成（Swipe）模式
        
    Returns:
        元组 (session, persona, character, user_msg, old_reply)
    """
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    persona = session.persona
    if not persona:
        raise HTTPException(status_code=404, detail="Session has no persona")

    character = persona.character
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    old_reply = None
    if is_regenerate:
        # 在再生模式下，召回最近的一条激活的用户消息
        user_msg = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.session_id == session_id,
                ChatMessage.role == MessageRole.user,
                ChatMessage.is_active == True
            )
            .order_by(ChatMessage.id.desc())
            .first()
        )
        if not user_msg:
            raise HTTPException(status_code=400, detail="No user message found to regenerate")

        # 召回该用户消息下最近的激活的 AI 回复以便后续 Swipe 逻辑使用
        old_reply = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.session_id == session_id,
                ChatMessage.role == MessageRole.assistant,
                ChatMessage.parent_id == user_msg.id,
                ChatMessage.is_active == True
            )
            .first()
        )
    else:
        # 在正常对话模式下，为用户新发的消息创建实体并持久化
        if not user_message:
            raise HTTPException(status_code=400, detail="User message cannot be empty")
        user_msg = ChatMessage(
            session_id=session_id,
            role=MessageRole.user,
            content=user_message,
            is_active=True
        )
        db.add(user_msg)
        db.commit()
        db.refresh(user_msg)

    return session, persona, character, user_msg, old_reply


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
    第二阶段：执行混合 RAG 检索（ChromaDB + Graph DB）并编译组装发送给大模型的 Messages 消息列表。
    
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
    rag_query = user_msg.content

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

    # 3. 提取历史记录轮次
    recent_records = session_service.get_session_history_with_inheritance(
        session_id, db, settings.APP_CONTEXT_HISTORY_LIMIT
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

    # 4. 组装最终 messages Payload 格式 (大模型可以直接消费的结构)
    messages = await _build_chat_messages(
        character=character,
        persona=persona,
        recent_history=recent_history,
        user_message=user_msg.content,
        retrieved_memories=memories,
        graph_knowledge=graph_knowledge,
        db=db,
        user_nickname=user_nickname
    )

    return messages
