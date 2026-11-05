"""持有任务执行权串行推进内部群聊；细分可见单元与持久审计待 M3-C。"""
import asyncio
import json
import logging
import math
import time

from core.locking import group_execution, require_group_execution, require_group_runtime
from services.conversation import group_director_service as director, group_generation_service as generation
from services.conversation import group_history_service as history
from services.conversation.group_call_snapshot import capture_group_calls
from services.conversation.group_context_service import build_member_context
from services.conversation.session_access import group_session_operation
from services.infrastructure.llm_provider import group_model_session

logger = logging.getLogger(__name__)


class GroupRoundBudget:
    def __init__(self, max_steps, timeout, call_timeout):
        if (type(max_steps) is not int or not 1 <= max_steps <= 6
                or any(type(value) not in (int, float) or not math.isfinite(value) or value <= 0 for value in (timeout, call_timeout))):
            raise ValueError("群聊调用预算无效")
        self.max_steps = max_steps
        self.limit = 3 * max_steps + 1
        self.used = 0
        self.deadline = time.monotonic() + timeout
        self.call_timeout = call_timeout

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise director.GroupDirectorError("call_budget")
        return remaining

    def consume(self):
        remaining = self.remaining()
        if self.used >= self.limit:
            raise director.GroupDirectorError("call_budget")
        self.used += 1
        return min(remaining, self.call_timeout)


@group_session_operation
async def run_group_round(session_id, user_content, db, *, runtime, model=None, thinking_mode=None,
                          reasoning_effort=None, max_steps=4, timeout=300, call_model=None, collect_inputs=False):
    history._require_group(session_id, db)
    history._require_clean_transaction(db)
    require_group_runtime(runtime, db.get_bind())
    if not isinstance(user_content, str) or not user_content.strip():
        raise ValueError("用户输入不能为空")
    # 参数在取得锁后和任何调用前验证；预算从执行权取得时开始计时。
    async with group_execution(session_id, db.get_bind(), runtime) as execution:
        budget = GroupRoundBudget(max_steps, timeout, timeout)
        snapshot = await generation._database(capture_group_calls, session_id, db, model=model,
                                             thinking_mode=thinking_mode, reasoning_effort=reasoning_effort)
        if not math.isfinite(snapshot.call_timeout) or snapshot.call_timeout <= 0:
            raise ValueError("单次模型超时无效")
        budget.call_timeout = snapshot.call_timeout
        if call_model is not None:
            return await _execute_round(session_id, user_content, db, execution, snapshot, budget, call_model, collect_inputs)
        async with group_model_session(snapshot.connection, timeout=snapshot.call_timeout) as client:
            async def invoke(stage, kwargs):
                return await client.chat.completions.create(**kwargs)
            return await _execute_round(session_id, user_content, db, execution, snapshot, budget, invoke, collect_inputs)


async def _execute_round(session_id, user_content, db, execution, snapshot, budget, call_model, collect_inputs):
    target = None
    calls = []
    runtime = execution.owner

    async def call(stage, parameters, persona_id=None):
        require_group_execution(execution, session_id, db.get_bind())
        wait = budget.consume()
        call_deadline = time.monotonic() + wait
        entry = {"stage": stage, "speaker_persona_id": persona_id}
        if collect_inputs:
            entry["messages"] = parameters["messages"]
        calls.append(entry)
        response = await asyncio.wait_for(call_model(stage, {**parameters, "timeout": wait}), wait)
        budget.remaining()
        if time.monotonic() >= call_deadline:
            raise TimeoutError
        return response

    async def scene():
        require_group_execution(execution, session_id, db.get_bind())
        return await generation._database(director.build_director_context, session_id, db,
            candidate_id=target["candidate_id"] if target else None, expected_revision=target["revision"] if target else None)

    async def decide(context, stage, **kwargs):
        messages = director.build_director_messages(context, stage, **kwargs)
        response = await call(stage, {**json.loads(snapshot.director_json), "messages": messages})
        return response.choices[0]

    try:
        context = await scene()
        answer = await decide(context, "user_visibility", user_content=user_content)
        visible = director.parse_visibility(answer.message.content, context.member_ids, finish_reason=answer.finish_reason)
        try:
            target = await generation._database(history._prepare, session_id, user_content, visible.visible_to, db)
        except generation._DatabaseCancelled as exc:
            if isinstance(exc.result, dict):
                target = exc.result
            raise
        finish_reason = "step_limit"
        for _ in range(budget.max_steps):
            context = await scene()
            if not context.eligible_ids:
                finish_reason = "no_visible_basis"
                break
            answer = await decide(context, "next_action")
            action = director.parse_next_action(answer.message.content, context.member_ids, context.eligible_ids,
                                                finish_reason=answer.finish_reason)
            if action.action == "end":
                finish_reason = action.reason_code
                break
            async def audience(proposed):
                try:
                    answer = await decide(context, "utterance_visibility", proposed=proposed)
                    return director.parse_visibility(answer.message.content, context.member_ids,
                        author_id=proposed.speaker_persona_id, finish_reason=answer.finish_reason).visible_to
                except TimeoutError:
                    raise generation.GroupGenerationError("timeout") from None
                except director.GroupDirectorError as exc:
                    raise generation.GroupGenerationError(exc.code) from None
            async def role_call(parameters):
                try:
                    return await call("role_generation", parameters, action.speaker_persona_id)
                except TimeoutError:
                    raise generation.GroupGenerationError("timeout") from None
                except director.GroupDirectorError as exc:
                    raise generation.GroupGenerationError(exc.code) from None
            saved = await generation._generate_with_execution(session_id, target["candidate_id"], action.speaker_persona_id,
                target["revision"], db, execution=execution, decide_visibility=audience, call_model=role_call,
                generation_parameters_json=snapshot.member_parameters(action.speaker_persona_id), history_limit=snapshot.history_limit)
            target["revision"] = saved["revision"]
        personal_inputs = {}
        diagnostic_error_code = None
        if collect_inputs:
            try:
                context = await scene()
                for pid in context.eligible_ids:
                    personal = await generation._database(build_member_context, session_id, pid, target["candidate_id"],
                        target["revision"], db, generation_parameters_json=snapshot.member_parameters(pid), history_limit=snapshot.history_limit)
                    personal_inputs[str(pid)] = json.loads(personal.messages_json)
            except Exception as exc:
                # 诊断读取不改变业务终态；取消仍交给外层等待持久化并清理。
                personal_inputs = {}
                diagnostic_error_code = exc.code if isinstance(exc, director.GroupDirectorError) else "input_collection_failed"
                logger.warning("群聊输入诊断未完成 error_type=%s", type(exc).__name__)
        try:
            done = await generation._database(history._finish, session_id, target["candidate_id"], target["revision"], False, db)
        except generation._DatabaseCancelled as exc:
            if not isinstance(exc.result, dict):
                raise
            done = exc.result
        target["revision"] = done["revision"]
        return {**target, "finish_reason": finish_reason, "calls": calls, "error_code": None,
                "personal_inputs": personal_inputs, "diagnostic_error_code": diagnostic_error_code}
    except BaseException as exc:
        if target:
            code = "cancelled" if isinstance(exc, asyncio.CancelledError) else "execution_failed"
            try:
                await generation._database(generation._fail, session_id, target["candidate_id"], target["revision"], db, runtime, code)
            except Exception as marker_error:
                logger.warning("群聊轮次失败标记未保存 error_type=%s", type(marker_error).__name__)
        if isinstance(exc, asyncio.CancelledError):
            raise
        code = exc.code if isinstance(exc, (director.GroupDirectorError, generation.GroupGenerationError)) else (
            "timeout" if isinstance(exc, TimeoutError) else "execution_failed")
        return {**(target or {}), "finish_reason": "failed", "calls": calls, "error_code": code}
