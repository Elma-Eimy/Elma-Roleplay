"""
聊天接口路由 (Chat Endpoints Router)

负责接收并响应前端的对话请求（包括非流式与流式 SSE 接口）。
本路由层遵循解耦架构：
1. 仅负责 HTTP 请求接收、输入校验、锁调度（以防止会话内请求并发冲突）以及 SSE 数据分块组装推送。
2. 将数据读取、RAG 混合检索、图谱检索与 Prompt 上下文装配职责全部委托给
   [context_assembler.py](file:///app-backend/services/context_assembler.py)。
3. 将最终模型推理与超参解析职责委托给 [chat_engine.py](file:///app-backend/services/chat_engine.py)。
"""

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
import services.context_assembler as context_assembler
import re
from core.locking import get_session_lock

router = APIRouter()


@router.post("")
async def chat(request: ChatRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    基于 Session 的对话端点。
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
        # ── Step 1: 在线程池中准备实体上下文与保存用户新消息 ──
        def run_prepare():
            return context_assembler.prepare_chat_context(
                session_id=request.session_id,
                db=db,
                user_message=None if request.is_regenerate else request.user_message,
                is_regenerate=request.is_regenerate
            )
        session, persona, character, user_msg, old_reply = await run_in_threadpool(run_prepare)

        try:
            # ── Step 2: 统一调用装配器进行 RAG、图谱检索并拼装消息列表 ──
            messages = await context_assembler.assemble_prompt_context(
                session_id=session.id,
                character=character,
                persona=persona,
                user_msg=user_msg,
                old_reply=old_reply,
                db=db,
                user_nickname=request.user_nickname
            )

            # ── Step 3: 调用模型生成引擎获取回复 ──
            response_data = await chat_engine.generate_reply(
                character=character,
                messages=messages,
                use_reasoning=request.use_reasoning,
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
            reasoning_content = response_data.get("reasoning_content", "")

            # ── Step 4: 保存 AI 回复与更新状态 ──
            import services.session_service as session_service

            def run_save():
                return session_service.save_chat_response(
                    session_id=request.session_id,
                    persona_id=persona.id,
                    user_msg_id=user_msg.id,
                    reply_text=reply_text,
                    reasoning_content=reasoning_content,
                    emotion_tag=emotion_tag,
                    affection_change=affection_change,
                    is_regenerate=request.is_regenerate,
                    old_reply_id=old_reply.id if old_reply else None,
                    db=db
                )

            ai_msg_id, final_affection_score, candidates_list = await run_in_threadpool(run_save)
        except Exception as e:
            if not request.is_regenerate:
                def run_cleanup():
                    try:
                        db_msg = db.get(models.ChatMessage, user_msg.id)
                        if db_msg:
                            db.delete(db_msg)
                            db.commit()
                    except Exception as cleanup_err:
                        print(f"[WARN] Failed to cleanup user message: {cleanup_err}")
                await run_in_threadpool(run_cleanup)
            raise e

        # ── Step 5: 后台触发提纯检查 ──
        background_tasks.add_task(run_auto_trigger_checks, request.session_id, persona.id)

        return {
            "reply": reply_text,
            "emotion_tag": emotion_tag,
            "affection_change": affection_change,
            "affection_score": final_affection_score,
            "model_used": response_data.get("model_used"),
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
    lock = get_session_lock(session_id)
    try:
        await asyncio.wait_for(lock.acquire(), timeout=30.0)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=429,
            detail="Another request is currently processing for this session."
        )

    try:
        # ── Step 1: 准备实体上下文 ──
        def run_prepare():
            return context_assembler.prepare_chat_context(
                session_id=session_id,
                db=db,
                user_message=None if request.is_regenerate else request.user_message,
                is_regenerate=request.is_regenerate
            )
        session, persona, character, user_msg, old_reply = await run_in_threadpool(run_prepare)

        try:
            # ── Step 2: 统一调用装配器进行 RAG、图谱检索并拼装消息列表 ──
            messages = await context_assembler.assemble_prompt_context(
                session_id=session.id,
                character=character,
                persona=persona,
                user_msg=user_msg,
                old_reply=old_reply,
                db=db,
                user_nickname=request.user_nickname
            )

            # ── Step 3: 调用模型生成引擎获取流 ──
            try:
                stream, model = await chat_engine.generate_reply_stream(
                    character=character,
                    messages=messages,
                    use_reasoning=request.use_reasoning,
                    temperature=request.temperature,
                    top_p=request.top_p,
                    presence_penalty=request.presence_penalty,
                    frequency_penalty=request.frequency_penalty,
                    repetition_penalty=request.repetition_penalty,
                    reasoning_effort=request.reasoning_effort,
                )
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed to start stream: {e}")
        except Exception as e:
            if not request.is_regenerate:
                def run_cleanup():
                    try:
                        db_msg = db.get(models.ChatMessage, user_msg.id)
                        if db_msg:
                            db.delete(db_msg)
                            db.commit()
                    except Exception as cleanup_err:
                        print(f"[WARN] Failed to cleanup user message: {cleanup_err}")
                await run_in_threadpool(run_cleanup)
            raise e

        async def event_generator():
            accumulated_text = ""
            reply_text = ""
            reasoning_text = ""
            
            in_reply_mode = False
            fallback_mode = False
            reply_closed = False
            last_sent_index = 0
            
            try:
                async for chunk in stream:
                    delta = chunk.choices[0].delta.content or ""
                    reasoning_delta = getattr(chunk.choices[0].delta, "reasoning_content", None) or ""
                    
                    if reasoning_delta:
                        reasoning_text += reasoning_delta
                        yield f"data: {json.dumps({'reasoning_chunk': reasoning_delta}, ensure_ascii=False)}\n\n"
                        continue

                    if not delta:
                        continue
                    accumulated_text += delta
                    
                    if not in_reply_mode and not fallback_mode:
                        match_open = re.search(r'<\s*reply\s*>', accumulated_text, re.IGNORECASE)
                        if match_open:
                            in_reply_mode = True
                            last_sent_index = match_open.end()
                        elif len(accumulated_text.strip()) >= 40:
                            fallback_mode = True
                            last_sent_index = 0
                    
                    if in_reply_mode:
                        match_close = re.search(r'</\s*reply\s*>', accumulated_text, re.IGNORECASE)
                        if match_close:
                            close_idx = match_close.start()
                            chunk_to_send = accumulated_text[last_sent_index:close_idx]
                            if chunk_to_send:
                                reply_text += chunk_to_send
                                yield f"data: {json.dumps({'chunk': chunk_to_send}, ensure_ascii=False)}\n\n"
                            in_reply_mode = False
                            fallback_mode = True
                            reply_closed = True
                            last_sent_index = len(accumulated_text)
                        else:
                            safe_len = len(accumulated_text) - 12
                            if safe_len > last_sent_index:
                                chunk_to_send = accumulated_text[last_sent_index:safe_len]
                                reply_text += chunk_to_send
                                yield f"data: {json.dumps({'chunk': chunk_to_send}, ensure_ascii=False)}\n\n"
                                last_sent_index = safe_len
                                
                    elif fallback_mode:
                        if not reply_closed:
                            if last_sent_index < len(accumulated_text):
                                chunk_to_send = accumulated_text[last_sent_index:]
                                reply_text += chunk_to_send
                                yield f"data: {json.dumps({'chunk': chunk_to_send}, ensure_ascii=False)}\n\n"
                                last_sent_index = len(accumulated_text)
                            else:
                                reply_text += delta
                                yield f"data: {json.dumps({'chunk': delta}, ensure_ascii=False)}\n\n"
                                last_sent_index = len(accumulated_text)

                if in_reply_mode:
                    if len(accumulated_text) > last_sent_index:
                        chunk_to_send = accumulated_text[last_sent_index:]
                        reply_text += chunk_to_send
                        yield f"data: {json.dumps({'chunk': chunk_to_send}, ensure_ascii=False)}\n\n"
                elif not reply_closed and not in_reply_mode:
                    if len(accumulated_text) > last_sent_index:
                        chunk_to_send = accumulated_text[last_sent_index:]
                        reply_text += chunk_to_send
                        yield f"data: {json.dumps({'chunk': chunk_to_send}, ensure_ascii=False)}\n\n"

                from services.parse import _extract_xml_block
                
                result = _extract_xml_block(accumulated_text)
                emotion_tag = result["emotion_tag"]
                affection_change = result["affection_change"]
                
                if not reply_text.strip() and result["reply"]:
                    reply_text = result["reply"]
                    
                if not reply_text.strip():
                    reply_text = "（大模型未生成有效回复）"

                # 保存 AI 回复与更新状态
                import services.session_service as session_service

                def run_save():
                    return session_service.save_chat_response(
                        session_id=session_id,
                        persona_id=persona.id,
                        user_msg_id=user_msg.id,
                        reply_text=reply_text,
                        reasoning_content=reasoning_text,
                        emotion_tag=emotion_tag,
                        affection_change=affection_change,
                        is_regenerate=request.is_regenerate,
                        old_reply_id=old_reply.id if old_reply else None,
                        db=db
                    )

                ai_msg_id, final_affection_score, candidates_list = await run_in_threadpool(run_save)
 
                background_tasks.add_task(run_auto_trigger_checks, session_id, persona.id)
 
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
                if not request.is_regenerate:
                    def run_cleanup():
                        try:
                            db_msg = db.get(models.ChatMessage, user_msg.id)
                            if db_msg:
                                db.delete(db_msg)
                                db.commit()
                        except Exception as cleanup_err:
                            print(f"[WARN] Failed to cleanup user message: {cleanup_err}")
                    await run_in_threadpool(run_cleanup)
                yield f"data: {json.dumps({'error': str(generator_err)}, ensure_ascii=False)}\n\n"
            finally:
                lock.release()

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "X-Accel-Buffering": "no",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )

    except Exception as e:
        lock.release()
        raise e


def run_auto_trigger_checks(session_id: int, persona_id: int):
    """
    后台任务：自动检查并执行记忆提纯和认知更新。
    使用独立的数据库会话，避免与主请求线程的 Session 冲突。
    """
    db = SessionLocal()
    try:
        unsummarized = memory_manager.get_unsummarized_count(session_id, db)
        if unsummarized >= settings.APP_MEMORY_EXTRACT_LIMIT:
            count = memory_manager.summarize_and_store_memory(session_id, db)
            print(f"[INFO] 自动记忆提纯: 提取了 {count} 条记忆 (session_id={session_id})")
    except Exception as e:
        print(f"[WARN] 自动记忆提纯失败: {e}")

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
    
    persona = db.query(models.SessionPersona).filter(
        models.SessionPersona.session_id == session_id
    ).first()
    
    old_active = db.query(models.ChatMessage).filter(
        models.ChatMessage.session_id == session_id,
        models.ChatMessage.role == MessageRole.assistant,
        models.ChatMessage.parent_id == msg.parent_id,
        models.ChatMessage.is_active == True
    ).first()
    
    db.query(models.ChatMessage).filter(
        models.ChatMessage.session_id == session_id,
        models.ChatMessage.role == MessageRole.assistant,
        models.ChatMessage.parent_id == msg.parent_id
    ).update({"is_active": False})
    
    msg.is_active = True
    
    if persona:
        if old_active and old_active.affection_change is not None:
            persona.affection_score -= old_active.affection_change
        if msg.affection_change is not None:
            persona.affection_score += msg.affection_change
        persona.affection_score = max(0, min(100, persona.affection_score))
        persona.current_mood = msg.emotion_tag or "平静"
        
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
