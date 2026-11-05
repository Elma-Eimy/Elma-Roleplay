"""持有会话执行权完成一次群聊发言；不提供导演或自动重试。"""
import asyncio
import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import partial

from fastapi.concurrency import run_in_threadpool

from core.locking import group_execution, require_group_execution, require_group_runtime
from services.conversation import group_history_service as history
from services.conversation.group_context_service import build_member_context
from services.conversation.group_session_service import GroupSessionValidationError
from services.conversation.role_state_schema import validate_patch, merge_state, encode_state
from services.conversation.session_access import group_session_operation, SessionKindConflict
from services.infrastructure.llm_provider import get_llm_provider
from services.conversation.group_unit_protocol import load_object, parse_role_units, UnitPlan, GroupUnitError

logger = logging.getLogger(__name__)


class GroupGenerationError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__("群聊发言未完成：" + code)


@dataclass(frozen=True)
class ProposedGroupUtterance:
    speaker_persona_id: int
    content: str
    units: tuple = ()


class _DatabaseCancelled(asyncio.CancelledError):
    def __init__(self, result):
        self.result = result
        self.committed_revision = None


async def _database(operation, *args, **kwargs):
    from services.conversation.group_checkpoint_service import GroupTargetScope
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
    if getattr(context, "protocol_version", 1) == 2:
        try:
            value = load_object(raw)
            if set(value) - {"units", "status", "state_update"} or not {"units", "status"} <= set(value):
                raise ValueError("invalid fields")
            units = parse_role_units(value["units"])
            status = value["status"]
            if (not isinstance(status, dict) or set(status) != {"emotion", "affection_change"}
                    or not isinstance(status["emotion"], str) or not 1 <= len(status["emotion"].strip()) <= 50
                    or type(status["affection_change"]) is not int or not -5 <= status["affection_change"] <= 5):
                raise ValueError("invalid status")
            patch = validate_patch(value["state_update"]) if "state_update" in value else None
            if patch and set(patch.get("characters", {})) - {context.speaker_name}:
                raise ValueError("state belongs to another actor")
            if patch:
                merge_state(json.loads(context.state_json), patch)
            return ("".join(unit.text for unit in units), status["emotion"].strip(), status["affection_change"],
                    encode_state(patch) if patch else None, units)
        except (ValueError, TypeError):
            raise GroupGenerationError("invalid_output") from None
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


def _save(session_id, candidate_id, persona_id, revision, result, visible_to, db, runtime, *, model=None, scope=None):
    require_group_runtime(runtime, db.get_bind())
    body, emotion, affection, patch = result[:4]
    plan = visible_to if isinstance(visible_to, UnitPlan) else None
    if len(result) == 5 and (plan is None or plan.units != result[4]):
        raise GroupUnitError()
    if plan:
        visible_to = tuple(sorted(set.intersection(*(set(ids) for ids in plan.audiences))))
    return history._append(session_id, candidate_id, persona_id, body, visible_to, revision, db,
        emotion_tag=emotion, affection_change=affection, role_state_patch=patch, unit_plan=plan, model=model, scope=scope)


def _fail(session_id, candidate_id, revision, db, runtime, code):
    require_group_runtime(runtime, db.get_bind())
    try:
        history._begin_write(db)
        _, candidate = history._writable(session_id, candidate_id, revision, db)
        candidate.status = "failed"
        history._require_group(session_id, db).group_revision += 1
        candidate.error_code = code
        candidate.finish_reason = None
        candidate.revision += 1
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
        prepared = True
        parameters = json.loads(context.generation_json)
        response = await (get_llm_provider().generate_async(**parameters, _group_no_retry=True) if call_model is None else call_model(parameters))
        if response.choices[0].finish_reason not in (None, "stop"):
            raise GroupGenerationError("incomplete_output")
        result = _parse(response.choices[0].message.content, context)
        audience = await decide_visibility(ProposedGroupUtterance(speaker_persona_id, result[0], result[4] if len(result) == 5 else ()))
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
