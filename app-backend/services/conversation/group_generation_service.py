"""持有会话执行权完成一次群聊发言；不提供导演或自动重试。"""
import asyncio
import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import partial

from fastapi.concurrency import run_in_threadpool

from core.locking import get_session_lock, require_group_runtime
from services.conversation import group_history_service as history
from services.conversation.group_context_service import build_member_context
from services.conversation.group_session_service import GroupSessionValidationError
from services.conversation.role_state_schema import validate_patch, merge_state, encode_state
from services.conversation.session_access import group_session_operation, SessionKindConflict
from services.infrastructure.llm_provider import get_llm_provider

logger = logging.getLogger(__name__)


class GroupGenerationError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__("群聊发言未完成：" + code)


@dataclass(frozen=True)
class ProposedGroupUtterance:
    speaker_persona_id: int
    content: str


class _DatabaseCancelled(asyncio.CancelledError):
    def __init__(self, result):
        self.result = result


async def _database(operation, *args, **kwargs):
    work = asyncio.create_task(run_in_threadpool(partial(operation, *args, **kwargs)))
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(work)
            break
        except asyncio.CancelledError:
            if work.cancelled():
                raise
            cancelled = True
        except Exception:
            # 已接受的取消优先；线程结束仍须被等待，不能变成可重试的生成错误。
            if cancelled:
                raise _DatabaseCancelled(None) from None
            raise
    if cancelled:
        raise _DatabaseCancelled(result)
    return result


def _parse(raw, context):
    if not isinstance(raw, str):
        raise GroupGenerationError("invalid_output")
    match = re.fullmatch(r'\s*<reply>(.*?)</reply>\s*(<status\s+[^<>]*?/>)\s*(?:<state_update>(.*?)</state_update>)?\s*', raw, re.S)
    if not match or not match[1].strip() or re.search(r'</?reply\b', match[1]):
        raise GroupGenerationError("invalid_output")
    try:
        status = ET.fromstring(match[2]).attrib
        if set(status) != {"emotion", "affection_change"} or not 1 <= len(status["emotion"].strip()) <= 50:
            raise ValueError("invalid status")
        if not re.fullmatch(r'-?[0-5]', status["affection_change"]):
            raise ValueError("invalid affection")
        patch = validate_patch(json.loads(match[3])) if match[3] is not None else None
        if patch and set(patch.get("characters", {})) - {context.speaker_name}:
            raise ValueError("state belongs to another actor")
        if patch:
            merge_state(json.loads(context.state_json), patch)
        return match[1].strip(), status["emotion"].strip(), int(status["affection_change"]), encode_state(patch) if patch else None
    except (ValueError, TypeError, ET.ParseError):
        raise GroupGenerationError("invalid_output") from None


def _save(session_id, candidate_id, persona_id, revision, result, visible_to, db, runtime):
    require_group_runtime(runtime, db.get_bind())
    body, emotion, affection, patch = result
    return history._append(session_id, candidate_id, persona_id, body, visible_to, revision, db,
        emotion_tag=emotion, affection_change=affection, role_state_patch=patch)


def _fail(session_id, candidate_id, revision, db, runtime, code):
    require_group_runtime(runtime, db.get_bind())
    try:
        history._begin_write(db)
        _, candidate = history._writable(session_id, candidate_id, revision, db)
        candidate.status = "failed"
        candidate.error_code = code
        candidate.revision += 1
        db.commit()
    except (SessionKindConflict, history.GroupSessionNotFound):
        db.rollback()
        # 外部已经结束、删除或推进候选时，旧请求不改写新状态。
    except BaseException:
        db.rollback()
        raise


@group_session_operation
async def generate_group_utterance(session_id, candidate_id, speaker_persona_id, expected_revision,
                                   db, *, runtime, decide_visibility, model=None):
    history._require_group(session_id, db)
    history._require_clean_transaction(db)
    require_group_runtime(runtime, db.get_bind())
    history._positive(speaker_persona_id, "发言成员")
    lock = get_session_lock(session_id)
    if lock.locked():
        raise SessionKindConflict("群聊正在处理")
    await lock.acquire()
    failure_revision = expected_revision
    prepared = False
    try:
        context = await _database(build_member_context, session_id, speaker_persona_id,
            candidate_id, expected_revision, db, model=model)
        prepared = True
        parameters = json.loads(context.generation_json)
        response = await get_llm_provider().generate_async(**parameters)
        if response.choices[0].finish_reason not in (None, "stop"):
            raise GroupGenerationError("incomplete_output")
        result = _parse(response.choices[0].message.content, context)
        audience = await decide_visibility(ProposedGroupUtterance(speaker_persona_id, result[0]))
        try:
            saved = await _database(_save, session_id, candidate_id, speaker_persona_id,
                expected_revision, result, audience, db, runtime)
        except _DatabaseCancelled as exc:
            if isinstance(exc.result, dict):
                failure_revision = exc.result["revision"]
            raise
        return saved
    except BaseException as exc:
        # 参数或归属校验未通过时不结束其他成员正在使用的候选。
        if isinstance(exc, _DatabaseCancelled) and not prepared:
            prepared = hasattr(exc.result, "candidate_id")
        if prepared and runtime.active:
            code = "cancelled" if isinstance(exc, asyncio.CancelledError) else (
                exc.code if isinstance(exc, GroupGenerationError) else "execution_failed")
            try:
                await _database(_fail, session_id, candidate_id, failure_revision, db, runtime, code)
            except Exception as marker_error:
                # 失败标记不可写时，仍保留原始错误/取消，不向调用方暴露数据库正文参数。
                logger.warning("群聊失败标记未保存 error_type=%s", type(marker_error).__name__)
        if isinstance(exc, (asyncio.CancelledError, SessionKindConflict, GroupSessionValidationError, GroupGenerationError)):
            raise
        raise GroupGenerationError("execution_failed") from None
    finally:
        lock.release()
