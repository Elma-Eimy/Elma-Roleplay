"""持有会话执行权完成一次群聊发言，复用单聊 XML 解析并原子保存。"""
import asyncio
import json
import logging
from dataclasses import dataclass
from functools import partial

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text

from core.locking import group_execution, require_group_execution, require_group_runtime
from services.conversation import group_history_service as history
from services.conversation import group_candidate_state as candidate_state
from services.conversation.group_execution_scope import GroupTargetScope
from services.conversation.group_context_service import build_member_context
from services.conversation.group_session_service import GroupSessionValidationError
from services.conversation.role_state_schema import merge_state, encode_state
from services.conversation.session_access import group_session_operation, SessionKindConflict
from services.infrastructure.llm_provider import get_llm_provider
from services.conversation.group_unit_protocol import UnitPlan

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
        self.committed_revision = None


async def _database(operation, *args, **kwargs):
    scope = kwargs.get("scope") or next((arg for arg in args if isinstance(arg, GroupTargetScope)), None)
    if scope is not None:
        require_group_execution(scope.execution, scope.session_id, scope.execution.owner.engine)
        if getattr(scope.execution, "target_scope", None) is not scope:
            raise RuntimeError("持久目标作用域不属于当前执行")
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
    from services.parse import extract_xml_block
    if not isinstance(raw, str):
        raise GroupGenerationError('invalid_output')
    if isinstance(raw, str) and raw.lstrip().startswith('{'):
        try:
            retired = json.loads(raw)
        except ValueError:
            retired = None
        if isinstance(retired, dict) and {'units', 'status'} <= retired.keys():
            raise GroupGenerationError('invalid_output')
    parsed = extract_xml_block(raw)
    if not parsed['reply'].strip():
        raise GroupGenerationError('invalid_output')
    patch = parsed.get('role_state_patch')
    if patch and set(patch.get('characters', {})) - {context.speaker_name}:
        patch = None
    if patch:
        merge_state(json.loads(context.state_json), patch)
    return (parsed['reply'], parsed['emotion_tag'], max(-5, min(5, parsed['affection_change'])),
            encode_state(patch) if patch else None)


def _save(session_id, candidate_id, persona_id, revision, result, visible_to, db, runtime, *, model=None, scope=None):
    require_group_runtime(runtime, db.get_bind())
    body, emotion, affection, patch = result[:4]
    plan = visible_to if isinstance(visible_to, UnitPlan) else None
    if plan:
        visible_to = tuple(sorted(set.intersection(*(set(ids) for ids in plan.audiences))))
    return history._append(session_id, candidate_id, persona_id, body, visible_to, revision, db,
        emotion_tag=emotion, affection_change=affection, role_state_patch=patch, unit_plan=plan, model=model, scope=scope)


def _fail(session_id, candidate_id, revision, db, runtime, code):
    require_group_runtime(runtime, db.get_bind())
    try:
        history._begin_write(db)
        _, candidate = history._writable(session_id, candidate_id, revision, db)
        candidate_state.fail(candidate, code)
        history._require_group(session_id, db).group_revision += 1
        committed_revision = candidate.revision
        db.commit()
        return committed_revision
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
    async with group_execution(session_id, db.get_bind(), runtime) as execution:
        return await _generate_with_execution(session_id, candidate_id, speaker_persona_id, expected_revision,
            db, execution=execution, decide_visibility=decide_visibility, model=model)


async def _generate_with_execution(session_id, candidate_id, speaker_persona_id, expected_revision,
                                   db, *, execution, decide_visibility, model=None, call_model=None,
                                   generation_parameters_json=None, history_limit=None, fail_candidate=True, scope=None):
    require_group_execution(execution, session_id, db.get_bind())
    if scope is not None and scope.execution is not execution:
        raise RuntimeError("不能借用其他任务的持久目标")
    runtime = execution.owner
    failure_revision = expected_revision
    prepared = False
    try:
        context = await _database(build_member_context, session_id, speaker_persona_id,
            candidate_id, expected_revision, db, model=model, generation_parameters_json=generation_parameters_json,
            history_limit=history_limit, **({"scope": scope} if scope is not None else {}))
        if context.protocol_version == 2 and not context.shared_chat:
            raise GroupSessionValidationError("旧群聊生成链路已移除，请重新生成共同群聊候选")
        prepared = True
        parameters = json.loads(context.generation_json)
        if 'response_format' in parameters:
            raise GroupSessionValidationError("角色生成只支持单聊 XML，不能附加 JSON 格式参数")
        response = await (get_llm_provider().generate_async(**parameters, _group_no_retry=True)
                          if call_model is None else call_model(parameters))
        choice = response.choices[0]
        if choice.finish_reason not in (None, "stop"):
            raise GroupGenerationError("incomplete_output")
        result = _parse(choice.message.content, context)
        audience = await decide_visibility(ProposedGroupUtterance(speaker_persona_id, result[0]))
        try:
            saved = await _database(_save, session_id, candidate_id, speaker_persona_id,
                expected_revision, result, audience, db, runtime,
                **({"model": parameters.get("model")} if context.protocol_version == 2 else {}),
                **({"scope": scope} if scope is not None else {}))
        except _DatabaseCancelled as exc:
            if isinstance(exc.result, dict):
                failure_revision = exc.result["revision"]
                exc.committed_revision = failure_revision
            raise
        return saved
    except BaseException as exc:
        # 参数或归属校验未通过时不结束其他成员正在使用的候选。
        if isinstance(exc, _DatabaseCancelled) and not prepared:
            prepared = hasattr(exc.result, "candidate_id")
        # 整轮调用由外层统一结束候选，避免内外两次失败写入丢失提交版本。
        if fail_candidate and prepared and runtime.active:
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
