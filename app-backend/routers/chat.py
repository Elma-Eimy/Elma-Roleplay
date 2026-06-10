import json
import asyncio
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from core.database import get_db, SessionLocal
from core import models
from core.models import MessageRole
from schemas import ChatRequest, SwitchCandidateRequest
from core.config import settings
import services.chat_engine as chat_engine
import services.memory_manager as memory_manager
import re
from routers.sessions import get_session_history_with_inheritance
from core.locking import get_session_lock

router = APIRouter()

@router.post("")
async def chat(request: ChatRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    基于 Session 的对话端点。

    流程：
      1. Session → Persona → Character
      2. 保存用户消息
      3. 检索相关记忆（RAG）
      4. 获取最近对话历史
      5. 生成 AI 回复
      6. 保存 AI 回复 + 更新 Persona 状态
      7. 自动检查是否触发记忆提纯 / 认知更新
    """
    # ── 获取会话异步锁，30 秒内未获得则返回 429 ──
    lock = get_session_lock(request.session_id)
    try:
        await asyncio.wait_for(lock.acquire(), timeout=30.0)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=429,
            detail="Another request is currently processing for this session."
        )

    try:
        # ── Step 1-4: 获取 Context (数据库读取与 RAG 检索跑在线程池中) ──
        def prepare_context():
            session = db.get(models.Session, request.session_id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")

            persona = session.persona
            if not persona:
                raise HTTPException(status_code=404, detail="Session has no persona")

            character = persona.character
            if not character:
                raise HTTPException(status_code=404, detail="Character not found")

            # 保存/获取用户消息
            if request.is_regenerate:
                user_msg = (
                    db.query(models.ChatMessage)
                    .filter(
                        models.ChatMessage.session_id == session.id,
                        models.ChatMessage.role == MessageRole.user,
                        models.ChatMessage.is_active == True
                    )
                    .order_by(models.ChatMessage.id.desc())
                    .first()
                )
                if not user_msg:
                    raise HTTPException(status_code=400, detail="No user message found to regenerate")

                # Swipe 候选支持：不删除旧回复，而是将其设为 inactive 并回退其好感度
                old_reply = (
                    db.query(models.ChatMessage)
                    .filter(
                        models.ChatMessage.session_id == session.id,
                        models.ChatMessage.role == MessageRole.assistant,
                        models.ChatMessage.parent_id == user_msg.id,
                        models.ChatMessage.is_active == True
                    )
                    .first()
                )
                if old_reply:
                    old_reply.is_active = False
                    if persona and old_reply.affection_change is not None:
                        persona.affection_score -= old_reply.affection_change
                        persona.affection_score = max(0, persona.affection_score)
                    db.commit()
            else:
                user_msg = models.ChatMessage(
                    session_id=session.id,
                    role=MessageRole.user,
                    content=request.user_message,
                    is_active=True
                )
                db.add(user_msg)
                db.commit()
                db.refresh(user_msg)

            # Bug2修复：再生模式用数据库中的用户消息内容做 RAG 查询，避免前端传空串
            rag_query = user_msg.content if request.is_regenerate else request.user_message

            # 检索相关记忆（RAG）
            memories = memory_manager.retrieve_memories(
                persona_id=persona.id,
                character_id=character.id,
                query=rag_query,
                db=db,
            )

            # 获取最近对话历史
            recent_records = get_session_history_with_inheritance(
                session.id, db, settings.APP_CONTEXT_HISTORY_LIMIT
            )

            recent_history = [
                {
                    "role": r.role.value,
                    "content": r.content,
                    "emotion_tag": getattr(r, "emotion_tag", "平静"),
                    "affection_change": getattr(r, "affection_change", 0)
                }
                for r in recent_records
                if r.id != user_msg.id and r.role.value in ("user", "assistant")
            ]

            return session, persona, character, user_msg, memories, recent_history

        session, persona, character, user_msg, memories, recent_history = await run_in_threadpool(prepare_context)

        # ── Step 5: 生成 AI 回复 (全异步网络 IO 请求) ──
        response_data = await chat_engine.generate_reply(
            character=character,
            persona=persona,
            recent_history=recent_history,
            user_message=user_msg.content if request.is_regenerate else request.user_message,
            retrieved_memories=memories,
            db=db,
            use_reasoning=request.use_reasoning,  # None 则走 config.yaml 默认配置
            user_nickname=request.user_nickname,
            temperature=request.temperature,
            top_p=request.top_p,
            presence_penalty=request.presence_penalty,
            frequency_penalty=request.frequency_penalty,
            repetition_penalty=request.repetition_penalty,
            reasoning_effort=request.reasoning_effort,
        )

        reply_text = response_data.get("reply", "")
        emotion_tag = response_data.get("emotion_tag", "平静")
        affection_change = int(response_data.get("affection_change", 0))

        # ── Step 6: 保存 AI 回复与更新状态 (跑在线程池中) ──
        def save_response_data():
            p = db.get(models.SessionPersona, persona.id)
            ai_msg = models.ChatMessage(
                session_id=request.session_id,
                role=MessageRole.assistant,
                content=reply_text,
                emotion_tag=emotion_tag,
                affection_change=affection_change,
                parent_id=user_msg.id,
                is_active=True
            )
            db.add(ai_msg)
            p.affection_score += affection_change
            p.current_mood = emotion_tag
            session_obj = db.get(models.Session, request.session_id)
            if session_obj:
                session_obj.updated_at = func.now()
            db.commit()
            db.refresh(ai_msg)
            db.refresh(p)
            
            # 查询候选列表
            candidates = db.query(models.ChatMessage).filter(
                models.ChatMessage.session_id == request.session_id,
                models.ChatMessage.role == MessageRole.assistant,
                models.ChatMessage.parent_id == user_msg.id
            ).order_by(models.ChatMessage.id).all()
            
            candidates_list = [
                {
                    "id": c.id,
                    "role": c.role.value,
                    "content": c.content,
                    "emotion_tag": c.emotion_tag,
                    "affection_change": c.affection_change,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "audio_path": c.audio_path,
                }
                for c in candidates
            ]
            return ai_msg.id, p.affection_score, candidates_list

        ai_msg_id, final_affection_score, candidates_list = await run_in_threadpool(save_response_data)

        # ── Step 7: 自动触发检查（使用 BackgroundTasks，后台异步执行，不阻塞当前响应） ──
        background_tasks.add_task(run_auto_trigger_checks, request.session_id, persona.id)

        return {
            "reply": reply_text,
            "emotion_tag": emotion_tag,
            "affection_change": affection_change,
            "affection_score": final_affection_score,
            "model_used": response_data.get("model_used"),  # 方便前端展示当前对话使用的模型
            "user_message_id": user_msg.id,
            "assistant_message_id": ai_msg_id,
            "candidates": candidates_list,
            "active_index": len(candidates_list) - 1,
        }
    finally:
        lock.release()

@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    基于 Session 的流式对话端点。
    """
    session_id = request.session_id
    # ── 获取会话异步锁，30 秒内未获得则返回 429 ──
    lock = get_session_lock(session_id)
    try:
        await asyncio.wait_for(lock.acquire(), timeout=30.0)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=429,
            detail="Another request is currently processing for this session."
        )

    try:
        # ── Step 1-4: 获取 Context (数据库读取与 RAG 检索跑在线程池中) ──
        def prepare_context():
            session = db.get(models.Session, session_id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")

            persona = session.persona
            if not persona:
                raise HTTPException(status_code=404, detail="Session has no persona")

            character = persona.character
            if not character:
                raise HTTPException(status_code=404, detail="Character not found")

            # 保存/获取用户消息
            if request.is_regenerate:
                user_msg = (
                    db.query(models.ChatMessage)
                    .filter(
                        models.ChatMessage.session_id == session.id,
                        models.ChatMessage.role == MessageRole.user,
                        models.ChatMessage.is_active == True
                    )
                    .order_by(models.ChatMessage.id.desc())
                    .first()
                )
                if not user_msg:
                    raise HTTPException(status_code=400, detail="No user message found to regenerate")

                # Swipe 候选支持：不删除旧回复，而是将其设为 inactive 并回退其好感度
                old_reply = (
                    db.query(models.ChatMessage)
                    .filter(
                        models.ChatMessage.session_id == session.id,
                        models.ChatMessage.role == MessageRole.assistant,
                        models.ChatMessage.parent_id == user_msg.id,
                        models.ChatMessage.is_active == True
                    )
                    .first()
                )
                if old_reply:
                    old_reply.is_active = False
                    if persona and old_reply.affection_change is not None:
                        persona.affection_score -= old_reply.affection_change
                        persona.affection_score = max(0, persona.affection_score)
                    db.commit()
            else:
                user_msg = models.ChatMessage(
                    session_id=session.id,
                    role=MessageRole.user,
                    content=request.user_message,
                    is_active=True
                )
                db.add(user_msg)
                db.commit()
                db.refresh(user_msg)

            # Bug2修复：再生模式用数据库中的用户消息内容做 RAG 查询，避免前端传空串
            rag_query = user_msg.content if request.is_regenerate else request.user_message

            # 检索相关记忆（RAG）
            memories = memory_manager.retrieve_memories(
                persona_id=persona.id,
                character_id=character.id,
                query=rag_query,
                db=db,
            )

            # 获取最近对话历史
            recent_records = get_session_history_with_inheritance(
                session.id, db, settings.APP_CONTEXT_HISTORY_LIMIT
            )

            recent_history = [
                {
                    "role": r.role.value,
                    "content": r.content,
                    "emotion_tag": getattr(r, "emotion_tag", "平静"),
                    "affection_change": getattr(r, "affection_change", 0)
                }
                for r in recent_records
                if r.id != user_msg.id and r.role.value in ("user", "assistant")
            ]

            return session, persona, character, user_msg, memories, recent_history

        session, persona, character, user_msg, memories, recent_history = await run_in_threadpool(prepare_context)

        try:
            stream, model = await chat_engine.generate_reply_stream(
                character=character,
                persona=persona,
                recent_history=recent_history,
                # Bug2补丁：再生模式下 request.user_message 是空串，应使用数据库中的实际内容
                user_message=user_msg.content if request.is_regenerate else request.user_message,
                retrieved_memories=memories,
                db=db,
                use_reasoning=request.use_reasoning,
                user_nickname=request.user_nickname,
                temperature=request.temperature,
                top_p=request.top_p,
                presence_penalty=request.presence_penalty,
                frequency_penalty=request.frequency_penalty,
                repetition_penalty=request.repetition_penalty,
                reasoning_effort=request.reasoning_effort,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to start stream: {e}")

        async def event_generator():
            accumulated_text = ""
            reply_text = ""
            
            in_reply_mode = False
            fallback_mode = False
            # Bug7修复：用独立布尔值记录 </reply> 已出现，避免在 fallback_mode 分支中对
            # accumulated_text 做 O(n²) 的全文 regex 扫描
            reply_closed = False
            last_sent_index = 0
            
            try:
                async for chunk in stream:
                    delta = chunk.choices[0].delta.content or ""
                    if not delta:
                        continue
                    accumulated_text += delta
                    
                    # 检测当前解析模式（不区分大小写，容忍空格）
                    if not in_reply_mode and not fallback_mode:
                        # 1. 发现 <reply> 标签，进入标准 XML 提取模式
                        match_open = re.search(r'<\s*reply\s*>', accumulated_text, re.IGNORECASE)
                        if match_open:
                            in_reply_mode = True
                            last_sent_index = match_open.end()
                        # 2. 如果前 40 字符均没有发现 <reply>，触发兜底直出模式
                        elif len(accumulated_text.strip()) >= 40:
                            fallback_mode = True
                            last_sent_index = 0
                    
                    # 模式 1：标准 XML 标签内容提取
                    if in_reply_mode:
                        match_close = re.search(r'</\s*reply\s*>', accumulated_text, re.IGNORECASE)
                        if match_close:
                            close_idx = match_close.start()
                            # 提取结束，发送到 </reply> 之前的文本分块
                            chunk_to_send = accumulated_text[last_sent_index:close_idx]
                            if chunk_to_send:
                                reply_text += chunk_to_send
                                yield f"data: {json.dumps({'chunk': chunk_to_send}, ensure_ascii=False)}\n\n"
                            in_reply_mode = False
                            fallback_mode = True  # 标记已完成，忽略后续的 status 标签文本流出
                            reply_closed = True   # 记录 </reply> 已出现，后续 fallback 分支直接跳过
                            last_sent_index = len(accumulated_text)
                        else:
                            # 暂未检测到 </reply>，保留最后 12 字符的滑动延迟窗，防止 </reply 局部或大小写字符泄露
                            safe_len = len(accumulated_text) - 12
                            if safe_len > last_sent_index:
                                chunk_to_send = accumulated_text[last_sent_index:safe_len]
                                reply_text += chunk_to_send
                                yield f"data: {json.dumps({'chunk': chunk_to_send}, ensure_ascii=False)}\n\n"
                                last_sent_index = safe_len
                                
                    # 模式 2：兜底直出或静默忽略后续标签阶段
                    elif fallback_mode:
                        # reply_closed=True 表示 </reply> 已出现（XML 模式已完成），静默忽略后续内容
                        # reply_closed=False 表示真正的兜底直出模式，继续分发原始 delta
                        if not reply_closed:
                            reply_text += delta
                            yield f"data: {json.dumps({'chunk': delta}, ensure_ascii=False)}\n\n"

                # ── 流式读取结束，如果仍处于 reply_mode（漏掉了 </reply>），冲刷发送剩余字符 ──
                if in_reply_mode:
                    if len(accumulated_text) > last_sent_index:
                        chunk_to_send = accumulated_text[last_sent_index:]
                        reply_text += chunk_to_send
                        yield f"data: {json.dumps({'chunk': chunk_to_send}, ensure_ascii=False)}\n\n"

                # ── 提取最终元数据 ──
                from services.chat_engine import _extract_xml_block
                
                result = _extract_xml_block(accumulated_text)
                emotion_tag = result["emotion_tag"]
                affection_change = result["affection_change"]
                
                if not reply_text.strip() and result["reply"]:
                    reply_text = result["reply"]
                    
                if not reply_text.strip():
                    reply_text = "（大模型未生成有效回复）"

                # 保存 AI 回复与更新状态 (跑在线程池中)
                def save_stream_response():
                    p = db.get(models.SessionPersona, persona.id)
                    ai_msg = models.ChatMessage(
                        session_id=session_id,
                        role=MessageRole.assistant,
                        content=reply_text,
                        emotion_tag=emotion_tag,
                        affection_change=affection_change,
                        parent_id=user_msg.id,
                        is_active=True
                    )
                    db.add(ai_msg)
                    p.affection_score += affection_change
                    p.current_mood = emotion_tag
                    session_obj = db.get(models.Session, session_id)
                    if session_obj:
                        session_obj.updated_at = func.now()
                    db.commit()
                    db.refresh(ai_msg)
                    db.refresh(p)

                    # 查询候选列表
                    candidates = db.query(models.ChatMessage).filter(
                        models.ChatMessage.session_id == session_id,
                        models.ChatMessage.role == MessageRole.assistant,
                        models.ChatMessage.parent_id == user_msg.id
                    ).order_by(models.ChatMessage.id).all()
                    
                    candidates_list = [
                        {
                            "id": c.id,
                            "role": c.role.value,
                            "content": c.content,
                            "emotion_tag": c.emotion_tag,
                            "affection_change": c.affection_change,
                            "created_at": c.created_at.isoformat() if c.created_at else None,
                            "audio_path": c.audio_path,
                        }
                        for c in candidates
                    ]
                    return ai_msg.id, p.affection_score, candidates_list

                ai_msg_id, final_affection_score, candidates_list = await run_in_threadpool(save_stream_response)
 
                # 触发后台机制检查
                background_tasks.add_task(run_auto_trigger_checks, session_id, persona.id)
 
                # 发送最后一条元数据
                meta_payload = {
                    "emotion_tag": emotion_tag,
                    "affection_change": affection_change,
                    "affection_score": final_affection_score,
                    "model_used": model,
                    "user_message_id": user_msg.id,
                    "assistant_message_id": ai_msg_id,
                    "candidates": candidates_list,
                    "active_index": len(candidates_list) - 1,
                }
                yield f"data: {json.dumps(meta_payload, ensure_ascii=False)}\n\n"

            except Exception as generator_err:
                print(f"[ERROR] 发生流生成错误: {generator_err}")
                yield f"data: {json.dumps({'error': str(generator_err)}, ensure_ascii=False)}\n\n"
            finally:
                # ── 流式传输结束或遭遇断连异常，释放异步锁 ──
                lock.release()

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    except Exception as e:
        lock.release()
        raise e

def run_auto_trigger_checks(session_id: int, persona_id: int):
    """
    后台任务：自动检查并执行记忆提纯和认知更新。
    使用独立的数据库会话，避免与主请求线程的 Session 冲突或在主请求结束后 Session 关闭。
    """
    db = SessionLocal()
    try:
        # 检查记忆提纯
        unsummarized = memory_manager.get_unsummarized_count(session_id, db)
        if unsummarized >= settings.APP_MEMORY_EXTRACT_LIMIT:
            count = memory_manager.summarize_and_store_memory(session_id, db)
            print(f"[INFO] 自动记忆提纯: 提取了 {count} 条记忆 (session_id={session_id})")
    except Exception as e:
        print(f"[WARN] 自动记忆提纯失败: {e}")

    # 检查认知更新
    try:
        cognition_unseen = memory_manager.get_cognition_unseen_count(
            persona_id, session_id, db
        )
        if cognition_unseen >= settings.APP_COGNITION_UPDATE_INTERVAL:
            memory_manager.update_cognition_state(persona_id, db)
            print(f"[INFO] 自动认知更新完成 (persona_id={persona_id})")
    except Exception as e:
        print(f"[WARN] 自动认知更新失败: {e}")
    finally:
        db.close()


@router.post("/switch_candidate")
async def switch_candidate(request: SwitchCandidateRequest, db: Session = Depends(get_db)):
    """
    切换同一轮对话下的激活 AI 候选回复版本，并同步调整好感度及心情。
    """
    msg = db.get(models.ChatMessage, request.message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
        
    if msg.role != MessageRole.assistant:
        raise HTTPException(status_code=400, detail="Only assistant messages can be switched")
        
    if msg.parent_id is None:
        raise HTTPException(status_code=400, detail="Cannot switch candidates for a message without a parent message")
        
    session_id = msg.session_id
    
    # 查找该会话关联的 SessionPersona 实体以执行状态回退与重新应用
    persona = db.query(models.SessionPersona).filter(
        models.SessionPersona.session_id == session_id
    ).first()
    
    # 查找当前该 turn 下已激活的回复
    old_active = db.query(models.ChatMessage).filter(
        models.ChatMessage.session_id == session_id,
        models.ChatMessage.role == MessageRole.assistant,
        models.ChatMessage.parent_id == msg.parent_id,
        models.ChatMessage.is_active == True
    ).first()
    
    # 将此 turn 的所有候选回复全部设为 is_active = False
    db.query(models.ChatMessage).filter(
        models.ChatMessage.session_id == session_id,
        models.ChatMessage.role == MessageRole.assistant,
        models.ChatMessage.parent_id == msg.parent_id
    ).update({"is_active": False})
    
    # 将新选择的回复设为 is_active = True
    msg.is_active = True
    
    # 更新好感度及心情
    if persona:
        if old_active and old_active.affection_change is not None:
            persona.affection_score -= old_active.affection_change
        if msg.affection_change is not None:
            persona.affection_score += msg.affection_change
        persona.affection_score = max(0, min(100, persona.affection_score))
        persona.current_mood = msg.emotion_tag or "平静"
        
    # Touch session updated_at
    session_obj = db.get(models.Session, session_id)
    if session_obj:
        session_obj.updated_at = func.now()
        
    db.commit()
    db.refresh(msg)
    if persona:
        db.refresh(persona)
        
    return {
        "message": "Candidate switched successfully",
        "message_id": msg.id,
        "is_active": msg.is_active,
        "affection_score": persona.affection_score if persona else None,
        "current_mood": persona.current_mood if persona else None
    }
