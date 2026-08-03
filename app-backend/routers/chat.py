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
from core.database import get_db
from schemas import ChatRequest, SwitchCandidateRequest
import services.conversation.chat_engine as chat_engine
import services.conversation.context_assembler as context_assembler
import services.conversation.chat_turn_service as chat_turn_service
import services.conversation.message_service as message_service
from services.parse import _extract_xml_block, extract_stream_reply_prefix
from core.locking import get_session_lock

router = APIRouter()


async def _prepare_turn_and_messages(request: ChatRequest, db: Session):
    """共用聊天回合准备流程，并在模型调用前结束数据库读取事务。"""
    def run_prepare():
        return chat_turn_service.prepare_chat_turn(
            session_id=request.session_id,
            db=db,
            user_message=None if request.is_regenerate else request.user_message,
            is_regenerate=request.is_regenerate,
        )

    try:
        turn = await run_in_threadpool(run_prepare)
    except chat_turn_service.ChatTurnError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    try:
        messages = await context_assembler.assemble_prompt_context(
            session_id=turn.session.id,
            character=turn.character,
            persona=turn.persona,
            user_msg=turn.user_message,
            old_reply=turn.old_reply,
            db=db,
            user_nickname=request.user_nickname,
        )
        await run_in_threadpool(chat_turn_service.release_prompt_read_transaction, db)
        return turn, messages
    except BaseException:
        await run_in_threadpool(chat_turn_service.abort_chat_turn, turn, db)
        raise


async def _complete_turn(
    turn,
    db: Session,
    reply_text: str,
    reasoning_content: str,
    emotion_tag: str,
    affection_change: int,
):
    return await run_in_threadpool(
        chat_turn_service.complete_chat_turn,
        turn,
        reply_text,
        reasoning_content,
        emotion_tag,
        affection_change,
        db,
    )


async def _abort_turn(turn, db: Session):
    await run_in_threadpool(chat_turn_service.abort_chat_turn, turn, db)


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
        turn, messages = await _prepare_turn_and_messages(request, db)

        try:
            # 调用模型生成引擎获取回复
            response_data = await chat_engine.generate_reply(
                character=turn.character,
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

            completed = await _complete_turn(
                turn,
                db,
                reply_text,
                reasoning_content,
                emotion_tag,
                affection_change,
            )
        except BaseException:
            await _abort_turn(turn, db)
            raise

        # ── Step 5: 后台触发提纯检查 ──
        background_tasks.add_task(
            chat_turn_service.run_post_turn_maintenance,
            request.session_id,
            turn.persona.id,
        )

        return {
            "reply": reply_text,
            "emotion_tag": emotion_tag,
            "affection_change": affection_change,
            "affection_score": completed.affection_score,
            "model_used": response_data.get("model_used"),
            "user_message_id": turn.user_message.id,
            "assistant_message_id": completed.assistant_message_id,
            "candidates": completed.candidates,
            "active_index": len(completed.candidates) - 1,
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
        try:
            turn, messages = await _prepare_turn_and_messages(request, db)

            try:
                stream, model = await chat_engine.generate_reply_stream(
                    character=turn.character,
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
        except Exception:
            if "turn" in locals():
                await _abort_turn(turn, db)
            raise

        async def event_generator():
            accumulated_text = ""
            reply_text = ""
            reasoning_text = ""
            turn_completed = False
            # 暂留足够长的尾部，避免把尚未接收完整的 XML 标签发送给前端。
            stream_guard_chars = 24
            
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

                    parsed_so_far = extract_stream_reply_prefix(accumulated_text)
                    safe_length = max(0, len(parsed_so_far) - stream_guard_chars)
                    if (
                        parsed_so_far.startswith(reply_text)
                        and safe_length > len(reply_text)
                    ):
                        chunk_to_send = parsed_so_far[len(reply_text):safe_length]
                        reply_text += chunk_to_send
                        yield f"data: {json.dumps({'chunk': chunk_to_send}, ensure_ascii=False)}\n\n"

                result = _extract_xml_block(accumulated_text)
                emotion_tag = result["emotion_tag"]
                affection_change = result["affection_change"]
                canonical_reply = result["reply"] or "（大模型未生成有效回复）"

                # 最终完整响应是落库的唯一真源。正常情况下只需发送尚未流出的
                # 尾部；若上游产生极端格式变化，也不能把流式临时缓冲写入历史。
                if canonical_reply.startswith(reply_text):
                    final_chunk = canonical_reply[len(reply_text):]
                    if final_chunk:
                        yield f"data: {json.dumps({'chunk': final_chunk}, ensure_ascii=False)}\n\n"
                reply_text = canonical_reply

                completed = await _complete_turn(
                    turn,
                    db,
                    reply_text,
                    reasoning_text,
                    emotion_tag,
                    affection_change,
                )
                turn_completed = True
 
                background_tasks.add_task(
                    chat_turn_service.run_post_turn_maintenance,
                    session_id,
                    turn.persona.id,
                )
 
                meta_payload = {
                    "emotion_tag": emotion_tag,
                    "affection_change": affection_change,
                    "affection_score": completed.affection_score,
                    "model_used": model,
                    "user_message_id": turn.user_message.id,
                    "assistant_message_id": completed.assistant_message_id,
                    "candidates": completed.candidates,
                    "active_index": len(completed.candidates) - 1,
                }
                yield f"data: {json.dumps(meta_payload, ensure_ascii=False)}\n\n"

            except Exception as generator_err:
                print(f"[ERROR] 发生流生成错误: {generator_err}")
                yield f"data: {json.dumps({'error': str(generator_err)}, ensure_ascii=False)}\n\n"
            finally:
                if not turn_completed:
                    await _abort_turn(turn, db)
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


@router.post("/switch_candidate")
async def switch_candidate(request: SwitchCandidateRequest, db: Session = Depends(get_db)):
    """
    切换同一轮对话下的激活 AI 候选回复版本，并同步调整好感度及心情。
    """
    try:
        return message_service.switch_candidate(request.message_id, db)
    except message_service.CandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except message_service.CandidateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
