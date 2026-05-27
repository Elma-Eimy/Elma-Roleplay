import json
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from core.database import get_db, SessionLocal
from core import models
from core.models import MessageRole
from schemas import ChatRequest
from core.config import settings
import services.chat_engine as chat_engine
import services.memory_manager as memory_manager
from routers.sessions import get_session_history_with_inheritance

import threading
from collections import defaultdict

router = APIRouter()

# 会话级并发锁映射，确保相同会话的并发聊天请求顺序执行
session_locks = defaultdict(threading.Lock)

@router.post("")
def chat(request: ChatRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
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
    # ── 引入会话并发锁 ──
    lock = session_locks[request.session_id]
    acquired = lock.acquire(timeout=30.0)
    if not acquired:
        raise HTTPException(
            status_code=429,
            detail="Another request is currently processing for this session."
        )

    try:
        # ── Step 1: 获取完整的 Session → Persona → Character 链 ──
        session = db.get(models.Session, request.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        persona = session.persona
        if not persona:
            raise HTTPException(status_code=404, detail="Session has no persona")

        character = persona.character
        if not character:
            raise HTTPException(status_code=404, detail="Character not found")

        # ── Step 2: 保存用户消息 ──
        user_msg = models.ChatMessage(
            session_id=session.id,
            role=MessageRole.user,
            content=request.user_message,
        )
        db.add(user_msg)
        db.commit()

        # ── Step 3: 检索相关记忆（RAG） ──
        memories = memory_manager.retrieve_memories(
            persona_id=persona.id,
            character_id=character.id,
            query=request.user_message,
            db=db,
        )

        # ── Step 4: 获取最近对话历史 ──
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

        # ── Step 5: 生成 AI 回复 ──
        response_data = chat_engine.generate_reply(
            character=character,
            persona=persona,
            recent_history=recent_history,
            user_message=request.user_message,
            retrieved_memories=memories,
            db=db,
            use_reasoning=request.use_reasoning,  # None 则走 config.yaml 默认配置
        )

        reply_text = response_data.get("reply", "")
        emotion_tag = response_data.get("emotion_tag", "平静")
        affection_change = int(response_data.get("affection_change", 0))

        # ── Step 6: 保存 AI 回复 + 更新 Persona 状态 ──
        ai_msg = models.ChatMessage(
            session_id=session.id,
            role=MessageRole.assistant,
            content=reply_text,
            emotion_tag=emotion_tag,
            affection_change=affection_change,
        )
        db.add(ai_msg)

        persona.affection_score += affection_change
        persona.current_mood = emotion_tag
        db.commit()

        # ── Step 7: 自动触发检查（使用 BackgroundTasks，后台异步执行，不阻塞当前响应） ──
        background_tasks.add_task(run_auto_trigger_checks, session.id, persona.id)

        return {
            "reply": reply_text,
            "emotion_tag": emotion_tag,
            "affection_change": affection_change,
            "affection_score": persona.affection_score,
            "model_used": response_data.get("model_used"),  # 方便前端展示当前对话使用的模型
        }
    finally:
        lock.release()

@router.post("/stream")
@router.post("/stream")
def chat_stream(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    基于 Session 的流式对话端点。
    """
    session_id = request.session_id
    lock = session_locks[session_id]

    # ── 开启会话并发锁 ──
    acquired = lock.acquire(timeout=30.0)
    if not acquired:
        raise HTTPException(
            status_code=429,
            detail="Another request is currently processing for this session."
        )

    try:
        # ── Step 1: 获取完整的 Session → Persona → Character 链 ──
        session = db.get(models.Session, session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        persona = session.persona
        if not persona:
            raise HTTPException(status_code=404, detail="Session has no persona")

        character = persona.character
        if not character:
            raise HTTPException(status_code=404, detail="Character not found")

        # ── Step 2: 保存用户消息 ──
        user_msg = models.ChatMessage(
            session_id=session.id,
            role=MessageRole.user,
            content=request.user_message,
        )
        db.add(user_msg)
        db.commit()

        # ── Step 3: 检索相关记忆（RAG） ──
        memories = memory_manager.retrieve_memories(
            persona_id=persona.id,
            character_id=character.id,
            query=request.user_message,
            db=db,
        )

        # ── Step 4: 获取最近对话历史 ──
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

        try:
            stream, model = chat_engine.generate_reply_stream(
                character=character,
                persona=persona,
                recent_history=recent_history,
                user_message=request.user_message,
                retrieved_memories=memories,
                db=db,
                use_reasoning=request.use_reasoning,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to start stream: {e}")

        def event_generator():
            full_json_text = ""
            reply_text = ""
            state = 0  # 0: seeking "reply" key, 2: in "reply" value string, 3: done, 4: raw text fallback
            escape = False

            try:
                for chunk in stream:
                    delta = chunk.choices[0].delta.content or ""
                    if not delta:
                        continue
                    full_json_text += delta

                    if state == 0:
                        # 检查是否为非 JSON 格式的原始文本流
                        stripped = full_json_text.strip()
                        if stripped and not stripped.startswith('{'):
                            state = 4  # 进入原始文本备用流状态
                            reply_text += stripped
                            yield f"data: {json.dumps({'chunk': stripped}, ensure_ascii=False)}\n\n"
                        else:
                            idx = full_json_text.find('"reply"')
                            if idx != -1:
                                colon_idx = full_json_text.find(':', idx + 7)
                                if colon_idx != -1:
                                    quote_idx = full_json_text.find('"', colon_idx + 1)
                                    if quote_idx != -1:
                                        state = 2
                                        remaining = full_json_text[quote_idx + 1:]
                                        chunk_to_yield = ""
                                        for char in remaining:
                                            if escape:
                                                reply_text += char
                                                chunk_to_yield += char
                                                escape = False
                                            elif char == '\\':
                                                escape = True
                                            elif char == '"':
                                                state = 3
                                                break
                                            else:
                                                reply_text += char
                                                chunk_to_yield += char
                                        if chunk_to_yield:
                                            yield f"data: {json.dumps({'chunk': chunk_to_yield}, ensure_ascii=False)}\n\n"
                    elif state == 2:
                        chunk_to_yield = ""
                        for char in delta:
                            if escape:
                                reply_text += char
                                chunk_to_yield += char
                                escape = False
                            elif char == '\\':
                                escape = True
                            elif char == '"':
                                state = 3
                                break
                            else:
                                reply_text += char
                                chunk_to_yield += char
                        if chunk_to_yield:
                            yield f"data: {json.dumps({'chunk': chunk_to_yield}, ensure_ascii=False)}\n\n"
                    elif state == 4:
                        # 原始文本模式下，直接下发所有 chunk
                        reply_text += delta
                        yield f"data: {json.dumps({'chunk': delta}, ensure_ascii=False)}\n\n"
                    elif state == 3:
                        pass

                # 解析最终元数据
                emotion_tag = "平静"
                affection_change = 0
                try:
                    result = json.loads(full_json_text)
                    emotion_tag = result.get("emotion_tag", "平静")
                    affection_change = int(result.get("affection_change", 0))
                    if not reply_text and "reply" in result:
                        reply_text = result["reply"]
                except Exception as parse_err:
                    # 备用容错：如果 JSON 解析失败，但我们输出了原始文本，或者 full_json_text 有内容，作为 reply
                    if not reply_text:
                        reply_text = full_json_text.strip()

                    if not reply_text:
                        print(f"[INFO] 接口提示：大模型本次仅返回了空白字符，已自动采用兜底空回复处理。")
                    else:
                        print(f"[INFO] 接口提示：大模型返回了非标准 JSON 纯文本，已成功通过直出兜底机制安全提取内容。内容为: {repr(reply_text)}")

                # 保存 AI 回复与更新状态
                ai_msg = models.ChatMessage(
                    session_id=session.id,
                    role=MessageRole.assistant,
                    content=reply_text,
                    emotion_tag=emotion_tag,
                    affection_change=affection_change,
                )
                db.add(ai_msg)

                db.refresh(persona)
                persona.affection_score += affection_change
                persona.current_mood = emotion_tag
                db.commit()

                # 触发后台机制检查
                background_tasks.add_task(run_auto_trigger_checks, session.id, persona.id)

                # 发送最后一条元数据
                meta_payload = {
                    "emotion_tag": emotion_tag,
                    "affection_change": affection_change,
                    "affection_score": persona.affection_score,
                    "model_used": model
                }
                yield f"data: {json.dumps(meta_payload, ensure_ascii=False)}\n\n"

            except Exception as generator_err:
                print(f"[ERROR] 发生流生成错误: {generator_err}")
                yield f"data: {json.dumps({'error': str(generator_err)}, ensure_ascii=False)}\n\n"
            finally:
                # ── 流式传输结束或遭遇断连异常，释放并发锁 ──
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
