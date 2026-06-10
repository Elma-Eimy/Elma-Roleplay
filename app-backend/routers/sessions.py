from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from core.database import get_db
from core import models
from core.models import MessageRole
from schemas import SessionCreate, SessionTitleUpdate, MessageUpdate
import services.memory_manager as memory_manager
from core.config import settings
from core.locking import cleanup_session_lock

router = APIRouter()

def get_session_history_with_inheritance(session_id: int, db: Session, limit: int, before_id: int = None) -> list[models.ChatMessage]:
    """
    获取指定会话的聊天历史记录。
    按照时间正序排列（最旧的在前面，最新的在后面）。
    注：根据对齐后的颗粒度要求，开启子会话时不再合并父会话的原始消息记录，
    以便子会话独立于父会话重新起步，因此此处仅拉取当前会话的消息，不再递归向上追溯。
    """
    query = db.query(models.ChatMessage).filter(
        models.ChatMessage.session_id == session_id,
        models.ChatMessage.is_active == True
    )
    if before_id is not None:
        query = query.filter(models.ChatMessage.id < before_id)

    messages = (
        query.order_by(models.ChatMessage.id.desc())
        .limit(limit)
        .all()
    )
    messages.reverse()  # 反转以恢复时间正序
    return messages

@router.post("/create")
def create_session(request: SessionCreate, db: Session = Depends(get_db)):
    """
    创建新的对话会话。

    - 不指定 parent_session_id：从角色蓝图全新创建（affection=0，无认知）
    - 指定 parent_session_id：从父会话继承（复制好感度、认知状态、场景、心情）

    自动插入角色的 first_mes 作为第一条 AI 消息。
    """
    # 验证角色存在
    character = db.get(models.Character, request.character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # 创建 Session
    session = models.Session(
        parent_session_id=request.parent_session_id,
        title=request.title,
    )
    db.add(session)
    db.flush()  # 获取 session.id

    # 创建 SessionPersona
    if request.parent_session_id:
        # ── 继承模式 ──
        parent_session = db.get(models.Session, request.parent_session_id)
        if not parent_session or not parent_session.persona:
            db.rollback()
            raise HTTPException(status_code=404, detail="Parent session or its persona not found")

        parent_persona = parent_session.persona
        # 验证 character_id 一致
        if parent_persona.character_id != request.character_id:
            db.rollback()
            raise HTTPException(
                status_code=400,
                detail="character_id must match the parent session's character",
            )

        persona = models.SessionPersona(
            session_id=session.id,
            character_id=parent_persona.character_id,
            parent_persona_id=parent_persona.id,
            affection_score=parent_persona.affection_score,
            cognition_state=parent_persona.cognition_state,
            current_scenario_override=parent_persona.current_scenario_override,
            current_mood=parent_persona.current_mood,
        )
    else:
        # ── 全新模式 ──
        persona = models.SessionPersona(
            session_id=session.id,
            character_id=request.character_id,
            parent_persona_id=None,
            affection_score=0,
        )

    db.add(persona)

    # 仅在非继承（全新）模式下，插入第一条 AI 消息作为开场白
    if not request.parent_session_id:
        first_content = character.first_mes
        scenario_override = None

        if request.greeting_index is not None and character.extensions:
            try:
                import json
                ext = json.loads(character.extensions) if isinstance(character.extensions, str) else character.extensions
                alt_greetings = ext.get("alternate_greetings", [])
                if 0 <= request.greeting_index < len(alt_greetings):
                    first_content = alt_greetings[request.greeting_index]
            except Exception as e:
                print(f"[WARN] Failed to parse alternate greeting: {e}")

        # 强兼容性场景/地点解析算法
        if first_content:
            try:
                import re
                
                # 规则 1：匹配以常见地点、地图、交通、建筑类 Emoji 开头的三级标题（置于首位以防关键字干扰）
                # 例如：### 📍 Abandoned Warehouse, ### 🗺️ Tokyo Port | Night, ### 🏠 Safehouse
                emoji_match = re.search(
                    r'###\s*(?:[📍🗺️🌐⚔️🏠🏢🏫🌄🌅🌇🌆🌃🧭🎪🎡🎢])\s*([^\n|#]+)',
                    first_content
                )
                if emoji_match:
                    scenario_override = emoji_match.group(1).strip()
                
                # 规则 2：匹配高优先级地点/场景关键字（支持 ### 标题、[中括号] 或纯文本开头）
                # 例如：### Location: Shinjuku | Night, [地点: 学校], Scene: Bar
                if not scenario_override:
                    loc_kw_match = re.search(
                        r'(?:###\s*|\[\s*|\b)(?:Location|Scene|地点|当前地点)\s*[:：]\s*([^\n|#\]\)]+)',
                        first_content,
                        re.IGNORECASE
                    )
                    if loc_kw_match:
                        scenario_override = loc_kw_match.group(1).strip()
                
                # 规则 3：低优先级退避规则：匹配 Scenario / 场景关键字
                # 例如：### Scenario: Fighting in Shinjuku
                if not scenario_override:
                    scen_kw_match = re.search(
                        r'(?:###\s*|\[\s*|\b)(?:Scenario|Scenario\s*\d+|场景|当前场景)\s*[:：]\s*([^\n|#\]\)]+)',
                        first_content,
                        re.IGNORECASE
                    )
                    if scen_kw_match:
                        scenario_override = scen_kw_match.group(1).strip()
            except Exception as e:
                print(f"[WARN] Failed to extract location from opening message: {e}")

        if scenario_override:
            persona.current_scenario_override = scenario_override

        if first_content:
            first_message = models.ChatMessage(
                session_id=session.id,
                role=MessageRole.assistant,
                content=first_content,
                emotion_tag="平静",
                affection_change=0,
                parent_id=None,
                is_active=True,
            )
            db.add(first_message)

    db.commit()
    db.refresh(session)

    return {
        "message": "Session created successfully",
        "session_id": session.id,
        "persona_id": persona.id,
        "character_id": request.character_id,
        "inherited": request.parent_session_id is not None,
        "title": session.title,
    }

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

    messages = get_session_history_with_inheritance(session_id, db, fetch_limit, before_id)

    session_history = []
    for m in messages:
        msg_dict = {
            "id": m.id,
            "role": m.role.value,
            "content": m.content,
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

    - 自动重连子会话的继承链（避免链断裂）
    - 清理 ChromaDB 中的对应记忆
    - CASCADE 删除 Persona + Messages + MemoryChunks
    """
    try:
        result = memory_manager.safe_delete_session(session_id, db)
        # 清理内存中歘留的对应异步锁，防止长期运行后内存缓慢增长
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
    # 内容被修改，重置关联的 TTS 音频文件路径以防止播放旧音档导致音画不同步
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
    message = db.get(models.ChatMessage, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    deleted_id = message.id
    session_id = message.session_id

    # 1. 查找该会话关联的 SessionPersona 实体以执行状态回滚
    persona = db.query(models.SessionPersona).filter(
        models.SessionPersona.session_id == session_id
    ).first()

    if persona:
        # ── 1a. 好感度与心情回退 & Swipe 候选回退处理 ──
        if message.role == MessageRole.assistant:
            sibling = None
            if message.is_active:
                sibling = db.query(models.ChatMessage).filter(
                    models.ChatMessage.session_id == session_id,
                    models.ChatMessage.role == MessageRole.assistant,
                    models.ChatMessage.parent_id == message.parent_id,
                    models.ChatMessage.id != message_id
                ).order_by(models.ChatMessage.id.desc()).first()

            if sibling:
                # 激活替补候选版本
                sibling.is_active = True
                old_change = message.affection_change or 0
                new_change = sibling.affection_change or 0
                persona.affection_score = persona.affection_score - old_change + new_change
                persona.affection_score = max(0, min(100, persona.affection_score))
                persona.current_mood = sibling.emotion_tag or "平静"
            else:
                # 没有候选替补，常规回滚
                if message.affection_change is not None:
                    persona.affection_score -= message.affection_change
                    persona.affection_score = max(0, persona.affection_score)

                # ── 1b. 情绪状态回滚 ──
                # 查找在当前被删消息时间线之前的最近一条 assistant 消息
                prev_assistant_msg = db.query(models.ChatMessage).filter(
                    models.ChatMessage.session_id == session_id,
                    models.ChatMessage.role == MessageRole.assistant,
                    models.ChatMessage.id < message_id
                ).order_by(models.ChatMessage.id.desc()).first()

                if prev_assistant_msg:
                    persona.current_mood = prev_assistant_msg.emotion_tag or "平静"
                else:
                    persona.current_mood = "平静"
        elif message.role == MessageRole.user:
            # 找到将被级联删除的、当前处于激活状态的 AI 回复
            active_child = db.query(models.ChatMessage).filter(
                models.ChatMessage.session_id == session_id,
                models.ChatMessage.role == MessageRole.assistant,
                models.ChatMessage.parent_id == message_id,
                models.ChatMessage.is_active == True
            ).first()
            if active_child and active_child.affection_change is not None:
                persona.affection_score -= active_child.affection_change
                persona.affection_score = max(0, persona.affection_score)
            
            # 回滚情绪状态至上一轮对话的最近一条 AI 消息
            prev_assistant_msg = db.query(models.ChatMessage).filter(
                models.ChatMessage.session_id == session_id,
                models.ChatMessage.role == MessageRole.assistant,
                models.ChatMessage.id < message_id
            ).order_by(models.ChatMessage.id.desc()).first()
            if prev_assistant_msg:
                persona.current_mood = prev_assistant_msg.emotion_tag or "平静"
            else:
                persona.current_mood = "平静"

        # ── 1c. 记忆提纯与认知指针安全降级保护 ──
        # 如果被删的消息 ID 刚好等于分界指针，安全寻找上一条消息 ID 进行向前递减
        if persona.last_summarized_msg_id == message_id:
            prev_msg = db.query(models.ChatMessage).filter(
                models.ChatMessage.session_id == session_id,
                models.ChatMessage.id < message_id
            ).order_by(models.ChatMessage.id.desc()).first()
            persona.last_summarized_msg_id = prev_msg.id if prev_msg else None

        if persona.last_cognition_update_msg_id == message_id:
            prev_msg = db.query(models.ChatMessage).filter(
                models.ChatMessage.session_id == session_id,
                models.ChatMessage.id < message_id
            ).order_by(models.ChatMessage.id.desc()).first()
            persona.last_cognition_update_msg_id = prev_msg.id if prev_msg else None

    # 2. 物理删除消息记录
    db.delete(message)
    session = db.get(models.Session, session_id)
    if session:
        session.updated_at = func.now()
    db.commit()

    return {
        "message": "Message deleted and state rolled back successfully",
        "message_id": deleted_id,
        "affection_score": persona.affection_score if persona else None,
        "current_mood": persona.current_mood if persona else None
    }
