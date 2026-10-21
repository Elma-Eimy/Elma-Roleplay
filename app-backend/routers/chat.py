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
from typing import Optional, Set
from core.database import SessionLocal, get_db
import services.conversation.session_service as session_service
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

    from services.infrastructure.model_capabilities import resolve_selection
    try:
        resolve_selection(request.model, request.thinking_mode, request.use_reasoning, request.reasoning_effort)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    role_state_patch=None,
):
    return await run_in_threadpool(
        chat_turn_service.complete_chat_turn,
        turn,
        reply_text,
        reasoning_content,
        emotion_tag,
        affection_change,
        db,
        role_state_patch,
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
                model=request.model,
                thinking_mode=request.thinking_mode,
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
                response_data.get("role_state_patch"),
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


_background_stream_tasks: Set[asyncio.Task] = set()


async def _finish_stream_operation(task: asyncio.Task):
    """延迟外部取消，直到数据库操作或清理结束，禁止并发访问同一 Session。"""
    cancelled = False
    while True:
        try:
            return await asyncio.shield(task), cancelled
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            cancelled = True


async def _run_stream_worker(
    turn: chat_turn_service.ChatTurn,
    stream,
    model: str,
    queue: asyncio.Queue,
    lock: asyncio.Lock,
    session_id: int,
    persona_id: int,
    user_message_id: int,
    old_reply_id: Optional[int],
    is_regenerate: bool,
):
    """
    后台大模型流式生成与落库 Worker。
    与客户端 HTTP/SSE 连接生命周期解耦：
    即使客户端断开连接，此任务仍会在后台将回复拉取完整并持久化到 SQLite 中，
    避免用户中途退出导致回合被意外回滚与消息丢失。
    """
    task_db = SessionLocal()
    accumulated_text = ""
    reply_text = ""
    reasoning_text = ""
    turn_completed = False
    stream_guard_chars = 24

    try:
        async for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            reasoning_delta = getattr(chunk.choices[0].delta, "reasoning_content", None) or ""

            if reasoning_delta:
                reasoning_text += reasoning_delta
                await queue.put({"type": "reasoning", "data": reasoning_delta})
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
                await queue.put({"type": "chunk", "data": chunk_to_send})

        result = _extract_xml_block(accumulated_text)
        emotion_tag = result["emotion_tag"]
        affection_change = result["affection_change"]
        canonical_reply = result["reply"] or "（大模型未生成有效回复）"

        if canonical_reply.startswith(reply_text):
            final_chunk = canonical_reply[len(reply_text):]
            if final_chunk:
                await queue.put({"type": "chunk", "data": final_chunk})
        reply_text = canonical_reply

        # 使用独立的 task_db 原子保存助手回复与状态更新
        save_task = asyncio.create_task(run_in_threadpool(
            session_service.save_chat_response,
            session_id=session_id,
            persona_id=persona_id,
            user_msg_id=user_message_id,
            reply_text=reply_text,
            reasoning_content=reasoning_text,
            emotion_tag=emotion_tag,
            affection_change=affection_change,
            is_regenerate=is_regenerate,
            old_reply_id=old_reply_id,
            db=task_db,
            role_state_patch=result.get("role_state_patch"),
        ))
        saved, cancelled = await _finish_stream_operation(save_task)
        assistant_id, affection_score, candidates = saved
        turn_completed = True
        if cancelled:
            raise asyncio.CancelledError()

        # 触发后台提纯与认知更新（独立任务）
        asyncio.create_task(
            run_in_threadpool(
                chat_turn_service.run_post_turn_maintenance,
                session_id,
                persona_id,
            )
        )

        meta_payload = {
            "emotion_tag": emotion_tag,
            "affection_change": affection_change,
            "affection_score": affection_score,
            "model_used": model,
            "user_message_id": user_message_id,
            "assistant_message_id": assistant_id,
            "candidates": candidates,
            "active_index": len(candidates) - 1,
        }
        await queue.put({"type": "meta", "data": meta_payload})

    except asyncio.CancelledError:
        # 服务关闭、重载或显式取消时捕获 CancelledError
        print(f"[INFO] 流式 Worker 任务被取消 (session_id={session_id})")
        raise
    except Exception as exc:
        print(f"[ERROR] 发生流生成或持久化错误: {exc}")
        try:
            await queue.put({"type": "error", "error": str(exc)})
        except Exception:
            pass
    finally:
        async def cleanup():
            try:
                if not turn_completed:
                    await run_in_threadpool(chat_turn_service.abort_chat_turn, turn, task_db)
            except Exception as abort_err:
                print(f"[WARN] 失败清理回合时异常: {abort_err}")
            finally:
                try:
                    task_db.close()
                finally:
                    lock.release()
                    queue.put_nowait(None)

        await _finish_stream_operation(asyncio.create_task(cleanup()))


async def cancel_all_stream_tasks(timeout: float = 5.0) -> None:
    """取消所有正在运行的后台流式 Worker 并等待其回滚清理完毕，供服务关闭阶段调用。"""
    tasks = [t for t in _background_stream_tasks if not t.done()]
    if not tasks:
        return
    for t in tasks:
        t.cancel()
    try:
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=timeout)
    except asyncio.TimeoutError:
        print(f"[WARN] 取消后台流式任务超时 ({timeout}s)")


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
                    model=request.model,
                    thinking_mode=request.thinking_mode,
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

        queue: asyncio.Queue = asyncio.Queue()

        # 启动独立于客户端连接的后台 Worker 任务，并将会话锁释放权移交 Worker
        worker_task = asyncio.create_task(
            _run_stream_worker(
                turn=turn,
                stream=stream,
                model=model,
                queue=queue,
                lock=lock,
                session_id=session_id,
                persona_id=turn.persona.id,
                user_message_id=turn.user_message.id,
                old_reply_id=turn.old_reply.id if turn.old_reply else None,
                is_regenerate=turn.is_regenerate,
            )
        )
        _background_stream_tasks.add(worker_task)
        worker_task.add_done_callback(_background_stream_tasks.discard)

        async def event_generator():
            try:
                while True:
                    event = await queue.get()
                    if event is None:
                        break
                    event_type = event.get("type")
                    if event_type == "chunk":
                        yield f"data: {json.dumps({'chunk': event['data']}, ensure_ascii=False)}\n\n"
                    elif event_type == "reasoning":
                        yield f"data: {json.dumps({'reasoning_chunk': event['data']}, ensure_ascii=False)}\n\n"
                    elif event_type == "meta":
                        yield f"data: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
                    elif event_type == "error":
                        yield f"data: {json.dumps({'error': event['error']}, ensure_ascii=False)}\n\n"
            except asyncio.CancelledError:
                # 客户端断开连接（如用户返回上一页、退出会话等）
                # 消费端直接优雅退出，后台 Worker 继续拉取并持久化数据
                pass

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
