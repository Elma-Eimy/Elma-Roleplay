"""
会话接口路由 (Session Endpoints Router)

负责接收并响应前端关于会话管理、聊天历史记录、消息管理（编辑/删除/Swipe 切换）
以及 RAG 记忆操作等所有的 RESTful HTTP 请求。

本路由层采用解耦设计：
1. 仅负责 HTTP 路由定义（REST API Path）、接口输入校验模型校验、HTTP 权限/异常控制与 JSON 序列化返回。
2. 具体的业务逻辑处理（如会话继承深拷贝、消息删除状态回滚、音频异步清除等）委托给
   [session_service.py](file:///app-backend/services/session_service.py) 业务层执行。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from core.database import get_db
from core import models
from core.models import MessageRole
from schemas import SessionCreate, SessionTitleUpdate, MessageUpdate, MemoryCreateRequest, MemoryUpdateRequest
import services.memory_manager as memory_manager
from core.config import settings
from core.locking import cleanup_session_lock
import services.session_service as session_service
import json

router = APIRouter()


@router.post("/create")
def create_session(request: SessionCreate, db: Session = Depends(get_db)):
    """
    创建新的对话会话。
    不指定 parent_session_id 则从角色设定全新创建；指定则从父会话分支继承。
    """
    try:
        result = session_service.create_session_service(
            character_id=request.character_id,
            parent_session_id=request.parent_session_id,
            title=request.title,
            greeting_index=request.greeting_index,
            start_message_id=request.start_message_id,
            db=db
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("")
def list_sessions(
    character_id: int = Query(..., description="筛选指定角色的会话"),
    db: Session = Depends(get_db),
):
    """获取某个角色的所有会话列表"""
    sessions = (
        db.query(models.Session)
        .join(models.SessionPersona)
        .filter(models.SessionPersona.character_id == character_id)
        .order_by(models.Session.updated_at.desc())
        .all()
    )

    result = []
    for s in sessions:
        result.append({
            "id": s.id,
            "title": s.title,
            "parent_session_id": s.parent_session_id,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            "persona": {
                "id": s.persona.id,
                "affection_score": s.persona.affection_score,
                "current_mood": s.persona.current_mood,
            } if s.persona else None,
        })

    return {"character_id": character_id, "sessions": result}


@router.get("/{session_id}")
def get_session_detail(session_id: int, db: Session = Depends(get_db)):
    """获取会话详情（含 Persona 完整状态 + Character 基本信息）"""
    session = db.get(models.Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    persona = session.persona
    character = persona.character if persona else None

    return {
        "id": session.id,
        "title": session.title,
        "parent_session_id": session.parent_session_id,
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


@router.get("/{session_id}/history")
def get_session_history(
    session_id: int,
    limit: int = Query(None, ge=1, description="获取聊天历史记录的条数限制"),
    before_id: int = Query(None, description="仅获取此消息ID之前的历史消息"),
    db: Session = Depends(get_db),
):
    """获取会话的聊天历史"""
    session = db.get(models.Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 动态应用配置文件的默认拉取值与上限控制
    fetch_limit = limit if limit is not None else settings.APP_HISTORY_FETCH_DEFAULT
    fetch_limit = min(fetch_limit, settings.APP_HISTORY_FETCH_MAX)

    messages = session_service.get_session_history_with_inheritance(session_id, db, fetch_limit, before_id)

    session_history = []
    for m in messages:
        msg_dict = {
            "id": m.id,
            "role": m.role.value,
            "content": m.content,
            "reasoning_content": m.reasoning_content,
            "emotion_tag": m.emotion_tag,
            "affection_change": m.affection_change,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "parent_id": m.parent_id,
            "is_active": m.is_active,
            "audio_path": m.audio_path,
        }
        
        if m.role.value == "assistant":
            # 查找此轮对话的所有候选回复列表
            candidates = db.query(models.ChatMessage).filter(
                models.ChatMessage.session_id == session_id,
                models.ChatMessage.role == MessageRole.assistant,
                models.ChatMessage.parent_id == m.parent_id
            ).order_by(models.ChatMessage.id).all()
            
            if not candidates:
                candidates = [m]
                
            msg_dict["candidates"] = [
                {
                    "id": c.id,
                    "content": c.content,
                    "reasoning_content": c.reasoning_content,
                    "emotion_tag": c.emotion_tag,
                    "affection_change": c.affection_change,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "audio_path": c.audio_path,
                }
                for c in candidates
            ]
            
            active_idx = 0
            for idx, c in enumerate(candidates):
                if c.id == m.id:
                    active_idx = idx
                    break
            msg_dict["active_index"] = active_idx
            
        session_history.append(msg_dict)

    return {
        "session_id": session_id,
        "messages": session_history,
    }


@router.put("/{session_id}/title")
def update_session_title(
    session_id: int,
    request: SessionTitleUpdate,
    db: Session = Depends(get_db)
):
    """更新指定会话的标题"""
    session = db.get(models.Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.title = request.title
    db.commit()

    return {
        "message": "Session title updated successfully",
        "session_id": session_id,
        "title": session.title,
    }


@router.delete("/{session_id}")
@router.post("/{session_id}/delete")
def delete_session(session_id: int, db: Session = Depends(get_db)):
    """
    安全删除会话。
    直接导入会话业务层的 safe_delete_session 执行。
    """
    try:
        result = session_service.safe_delete_session(session_id, db)
        # 清理内存中残留的对应异步锁，防止长期运行后内存缓慢增长
        cleanup_session_lock(session_id)
        return {"message": "Session deleted successfully", **result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{session_id}/trigger_summary")
def trigger_memory_summary(session_id: int, db: Session = Depends(get_db)):
    """手动触发指定会话的记忆提纯流程"""
    session = db.get(models.Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    extracted_count = memory_manager.summarize_and_store_memory(session_id, db)

    return {
        "message": "记忆提纯流程已完成",
        "session_id": session_id,
        "extracted_count": extracted_count,
    }


@router.post("/{session_id}/trigger_cognition")
def trigger_cognition_update(session_id: int, db: Session = Depends(get_db)):
    """手动触发指定会话的认知状态更新"""
    session = db.get(models.Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.persona:
        raise HTTPException(status_code=404, detail="Session has no persona")

    new_cognition = memory_manager.update_cognition_state(session.persona.id, db)

    return {
        "message": "认知更新已完成",
        "session_id": session_id,
        "cognition_state": new_cognition,
    }


@router.put("/messages/{message_id}")
def update_message(message_id: int, request: MessageUpdate, db: Session = Depends(get_db)):
    """编辑/更新单条聊天消息内容"""
    message = db.get(models.ChatMessage, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    message.content = request.content
    message.audio_path = None
    
    session = db.get(models.Session, message.session_id)
    if session:
        session.updated_at = func.now()
    db.commit()
    db.refresh(message)
    return {
        "message": "Message updated successfully",
        "message_id": message_id,
        "content": message.content
    }


@router.delete("/messages/{message_id}")
@router.post("/messages/{message_id}/delete")
def delete_message(message_id: int, db: Session = Depends(get_db)):
    """
    删除单条聊天消息，并执行好感度与心情回滚缓冲，同时提供未提纯和认知指针的安全降级保护。
    """
    try:
        result = session_service.delete_message_service(message_id, db)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{session_id}/memories")
def get_session_memories(
    session_id: int,
    q: str = Query(None, description="搜索关键词"),
    limit: int = Query(20, ge=1, description="获取记忆卡片的条数限制"),
    offset: int = Query(0, ge=0, description="获取记忆卡片的偏移量"),
    db: Session = Depends(get_db)
):
    """获取指定会话可调用的全部向量记忆（支持分页与检索）"""
    session = db.get(models.Session, session_id)
    if not session or not session.persona:
        raise HTTPException(status_code=404, detail="Session or Persona not found")

    ancestor_ids = memory_manager.get_ancestor_persona_ids(session.persona.id, db)
    query = db.query(models.MemoryChunk).filter(
        models.MemoryChunk.persona_id.in_(ancestor_ids)
    )
    if q and q.strip():
        query = query.filter(models.MemoryChunk.content.contains(q.strip()))

    chunks = query.order_by(models.MemoryChunk.created_at.desc()).offset(offset).limit(limit).all()

    return [
        {
            "id": c.id,
            "content": c.content,
            "memory_type": c.memory_type.value if c.memory_type else "fact",
            "importance_score": c.importance_score,
            "is_local": c.persona_id == session.persona.id,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "origin_session_id": c.origin_session_id
        } for c in chunks
    ]


@router.post("/{session_id}/memories")
def create_session_memory(session_id: int, request: MemoryCreateRequest, db: Session = Depends(get_db)):
    """手动在指定会话下添加一条事实记忆（写入 SQLite 和 ChromaDB）"""
    session = db.get(models.Session, session_id)
    if not session or not session.persona:
        raise HTTPException(status_code=404, detail="Session or Persona not found")

    try:
        m_type = models.MemoryType(request.memory_type)
    except ValueError:
        m_type = models.MemoryType.fact

    chunk = memory_manager.add_memory_chunk(
        persona_id=session.persona.id,
        character_id=session.persona.character_id,
        content=request.content,
        memory_type=m_type,
        importance_score=request.importance_score or 0.8,
        origin_session_id=session_id,
        source_message_id=None,
        db=db
    )

    return {
        "message": "Memory added successfully",
        "memory": {
            "id": chunk.id,
            "content": chunk.content,
            "memory_type": chunk.memory_type.value,
            "importance_score": chunk.importance_score,
            "is_local": True,
            "created_at": chunk.created_at.isoformat() if chunk.created_at else None,
            "origin_session_id": chunk.origin_session_id
        }
    }


@router.put("/{session_id}/memories/{memory_id}")
def update_session_memory(session_id: int, memory_id: int, request: MemoryUpdateRequest, db: Session = Depends(get_db)):
    """更新某条属于当前会话的本地记忆（继承的只读记忆不允许在此更新）"""
    session = db.get(models.Session, session_id)
    if not session or not session.persona:
        raise HTTPException(status_code=404, detail="Session or Persona not found")

    chunk = db.get(models.MemoryChunk, memory_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="Memory not found")

    # 权限检查：只允许更新当前会话关联的本地记忆
    if chunk.persona_id != session.persona.id:
        raise HTTPException(status_code=403, detail="Cannot edit inherited memories")

    try:
        updated_chunk = memory_manager.update_memory_chunk(
            chunk_id=memory_id,
            content=request.content,
            importance_score=request.importance_score,
            db=db
        )
        return {
            "message": "Memory updated successfully",
            "memory": {
                "id": updated_chunk.id,
                "content": updated_chunk.content,
                "importance_score": updated_chunk.importance_score
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{session_id}/memories/{memory_id}")
def delete_session_memory(session_id: int, memory_id: int, db: Session = Depends(get_db)):
    """删除属于当前会话的某条本地记忆（继承的只读记忆不允许在此删除）"""
    session = db.get(models.Session, session_id)
    if not session or not session.persona:
        raise HTTPException(status_code=404, detail="Session or Persona not found")

    chunk = db.get(models.MemoryChunk, memory_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="Memory not found")

    # 权限检查：只允许删除当前会话关联的本地记忆
    if chunk.persona_id != session.persona.id:
        raise HTTPException(status_code=403, detail="Cannot delete inherited memories")

    memory_manager.delete_memory_chunk(memory_id, db)
    return {"message": "Memory deleted successfully", "memory_id": memory_id}


@router.get("/{session_id}/compile_prompt")
async def compile_session_prompt(
    session_id: int,
    user_nickname: str = "用户",
    db: Session = Depends(get_db)
):
    """
    预览/编译当前会话的最近一次大模型 Prompt 组装。
    """
    import services.context_assembler as context_assembler
    from services.prompt_compiler import compile_system_prompt

    session = db.get(models.Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    persona = session.persona
    if not persona:
        raise HTTPException(status_code=404, detail="Session has no persona")
        
    character = persona.character
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # 1. 查找最后一条用户消息
    last_user_msg = (
        db.query(models.ChatMessage)
        .filter(
            models.ChatMessage.session_id == session_id,
            models.ChatMessage.role == models.MessageRole.user,
            models.ChatMessage.is_active == True
        )
        .order_by(models.ChatMessage.id.desc())
        .first()
    )

    if not last_user_msg:
        # 如果没有用户消息，只有系统开场白，直接组装 System Prompt 和首条消息
        system_prompt = compile_system_prompt(character, persona, user_nickname)
        first_assistant_msg = (
            db.query(models.ChatMessage)
            .filter(
                models.ChatMessage.session_id == session_id,
                models.ChatMessage.role == models.MessageRole.assistant,
                models.ChatMessage.is_active == True
            )
            .order_by(models.ChatMessage.id.asc())
            .first()
        )
        messages = [{"role": "system", "content": system_prompt}]
        if first_assistant_msg:
            emo = first_assistant_msg.emotion_tag or "平静"
            change = first_assistant_msg.affection_change or 0
            formatted_xml = f"<reply>{first_assistant_msg.content}</reply>\n<status emotion=\"{emo}\" affection_change=\"{int(change)}\"/>"
            messages.append({"role": "assistant", "content": formatted_xml})
        return {"messages": messages}

    # 2. 直接调用 context_assembler 进行 100% 同源拼装
    messages = await context_assembler.assemble_prompt_context(
        session_id=session_id,
        character=character,
        persona=persona,
        user_msg=last_user_msg,
        old_reply=None,
        db=db,
        user_nickname=user_nickname
    )

    return {"messages": messages}
