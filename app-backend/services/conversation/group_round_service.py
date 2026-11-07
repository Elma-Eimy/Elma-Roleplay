"""持有任务执行权串行推进群聊，按冻结策略重试无效格式。"""
import asyncio
import json
import logging
import math
import time
from datetime import datetime
from dataclasses import replace

from core.locking import group_execution, require_group_execution, require_group_runtime
from services.conversation import group_director_service as director, group_generation_service as generation
from services.conversation import group_history_service as history
from services.conversation import group_checkpoint_service as checkpoints
from services.conversation.group_call_snapshot import capture_group_calls
from services.conversation.group_context_service import build_member_context
from services.conversation.session_access import group_session_operation
from services.infrastructure.llm_provider import group_model_session
from services.conversation.group_unit_protocol import parse_user_units, parse_unit_visibility, GroupUnitError
from services.conversation.group_output_retry import validated_output

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
                          reasoning_effort=None, max_steps=4, timeout=300, call_model=None, collect_inputs=False,
                          protocol_version=2):
    history._require_group(session_id, db)
    history._require_clean_transaction(db)
    require_group_runtime(runtime, db.get_bind())
    if type(protocol_version) is not int or protocol_version not in (1, 2):
        raise ValueError("群聊协议版本无效")
    if not isinstance(user_content, str) or not user_content.strip():
        raise ValueError("用户输入不能为空")
    # 参数在取得锁后和任何调用前验证；预算从执行权取得时开始计时。
    async with group_execution(session_id, db.get_bind(), runtime) as execution:
        budget = GroupRoundBudget(max_steps, timeout, timeout)
        snapshot = await generation._database(capture_group_calls, session_id, db, model=model,
                                             thinking_mode=thinking_mode, reasoning_effort=reasoning_effort)
        if protocol_version == 1:
            members = []
            for pid, encoded in snapshot.members:
                parameters = json.loads(encoded)
                parameters.pop("response_format", None)
                members.append((pid, json.dumps(parameters, ensure_ascii=False)))
            snapshot = replace(snapshot, turn_policy=0, members=tuple(members), output_attempts=1)
        if not math.isfinite(snapshot.call_timeout) or snapshot.call_timeout <= 0:
            raise ValueError("单次模型超时无效")
        budget.call_timeout = snapshot.call_timeout
        if call_model is not None:
            return await _execute_round(session_id, user_content, db, execution, snapshot, budget, call_model, collect_inputs, protocol_version)
        async with group_model_session(snapshot.connection, timeout=snapshot.call_timeout) as client:
            async def invoke(stage, kwargs):
                return await client.chat.completions.create(**kwargs)
            return await _execute_round(session_id, user_content, db, execution, snapshot, budget, invoke, collect_inputs, protocol_version)


async def _execute_round(session_id, user_content, db, execution, snapshot, budget, call_model, collect_inputs, protocol_version,
                         *, target=None, scope=None, progress=None):
    calls = []
    runtime = execution.owner
    model = json.loads(snapshot.director_json)["model"]
    selected_sources = None
    budget.limit *= snapshot.output_attempts

    async def call(stage, parameters, persona_id=None):
        require_group_execution(execution, session_id, db.get_bind())
        wait = budget.consume()
        deadline = None
        if scope is not None:
            deadline = await generation._database(checkpoints.consume, scope, target["revision"], db)
            # 预算提交也会消耗整轮时间，不能把提交前的剩余时长带到提交后。
            remaining = (deadline - datetime.utcnow()).total_seconds()
            if remaining <= 0:
                raise director.GroupDirectorError("call_budget")
            wait = min(wait, budget.remaining(), remaining)
        call_deadline = time.monotonic() + wait
        entry = {"stage": stage, "speaker_persona_id": persona_id}
        if collect_inputs:
            entry["messages"] = parameters["messages"]
        calls.append(entry)
        response = await asyncio.wait_for(call_model(stage, {**parameters, "timeout": wait}), wait)
        budget.remaining()
        if time.monotonic() >= call_deadline or (deadline is not None and datetime.utcnow() >= deadline):
            raise TimeoutError
        return response

    async def scene():
        require_group_execution(execution, session_id, db.get_bind())
        return await generation._database(director.build_director_context, session_id, db,
            candidate_id=target["candidate_id"] if target else None, expected_revision=target["revision"] if target else None,
            **({"scope": scope} if scope is not None else {}), turn_policy=snapshot.turn_policy)

    async def decide(context, stage, validate, **kwargs):
        nonlocal selected_sources
        messages = director.build_director_messages(context, stage, protocol_version=protocol_version,
            turn_policy=snapshot.turn_policy, **kwargs)
        if stage == "next_action":
            selected_sources = json.loads(messages[1]["content"]).get("response_sources")
        attempted = False
        async def invoke(parameters):
            nonlocal attempted
            if attempted and target is not None and scope is None:
                await generation._database(generation._check_retry_target, session_id, target["candidate_id"],
                                           target["revision"], db)
            attempted = True
            return await call(stage, parameters)
        _, value = await validated_output(invoke, {**json.loads(snapshot.director_json), "messages": messages},
                                          validate, snapshot.output_attempts)
        return value

    try:
        if scope is None or progress["checkpoint"] == "user_visibility":
            context = await scene()
            plan = None
            if protocol_version == 2:
                def user_plan(answer):
                    plan = parse_user_units(answer.message.content, user_content, context.member_ids,
                        finish_reason=answer.finish_reason, require_meaning=bool(snapshot.turn_policy),
                        require_reply_mode=snapshot.turn_policy >= 2)
                    if not snapshot.turn_policy and any(unit.meaning for unit in plan.units):
                        raise GroupUnitError()
                    return plan
                plan = await decide(context, "user_visibility", user_plan, user_content=user_content)
                visible_to = tuple(sorted(set.intersection(*(set(ids) for ids in plan.audiences))))
            else:
                visible_to = await decide(context, "user_visibility", lambda answer: director.parse_visibility(
                    answer.message.content, context.member_ids, finish_reason=answer.finish_reason).visible_to,
                    user_content=user_content)
            try:
                if scope is None:
                    target = await generation._database(history._prepare, session_id, user_content, visible_to, db,
                                                        unit_plan=plan, model=model)
                else:
                    saved_user = await generation._database(checkpoints.save_user, scope, target["revision"], plan, model, db)
                    target.update(saved_user)
            except generation._DatabaseCancelled as exc:
                if isinstance(exc.result, dict):
                    if target is None:
                        target = exc.result
                    else:
                        target.update(exc.result)
                raise
        finish_reason = "step_limit"
        pending_speaker = progress["speaker"] if scope is not None else None
        iterations = progress["remaining"] if scope is not None else budget.max_steps
        for _ in range(iterations):
            context = await scene()
            if pending_speaker is not None:
                action = director.NextAction("speak", pending_speaker, "follow_up")
                pending_speaker = None
            else:
                if not context.eligible_ids:
                    finish_reason = "no_visible_basis"
                    break
                action = await decide(context, "next_action", lambda answer: director.parse_next_action(
                    answer.message.content, context.member_ids, context.eligible_ids,
                    finish_reason=answer.finish_reason, response_sources=selected_sources))
                if action.action == "end":
                    finish_reason = action.reason_code
                    break
                if protocol_version == 2:
                    try:
                        accepted = await generation._database(history._accept_action, session_id, target["candidate_id"],
                            target["revision"], action, model, db, **({"scope": scope} if scope is not None else {}))
                    except generation._DatabaseCancelled as exc:
                        if isinstance(exc.result, dict):
                            target["revision"] = exc.result["revision"]
                        raise
                    target["revision"] = accepted["revision"]
            async def audience(proposed):
                try:
                    if protocol_version == 2:
                        return await decide(context, "utterance_visibility", lambda answer: parse_unit_visibility(
                            answer.message.content, proposed.units, context.member_ids,
                            proposed.speaker_persona_id, finish_reason=answer.finish_reason,
                            require_review=bool(snapshot.turn_policy),
                            reply_mode=(proposed.response_request or {}).get("reply_mode")), proposed=proposed)
                    return await decide(context, "utterance_visibility", lambda answer: director.parse_visibility(
                        answer.message.content, context.member_ids,
                        author_id=proposed.speaker_persona_id, finish_reason=answer.finish_reason).visible_to, proposed=proposed)
                except TimeoutError:
                    raise generation.GroupGenerationError("timeout") from None
                except (director.GroupDirectorError, GroupUnitError) as exc:
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
                generation_parameters_json=snapshot.member_parameters(action.speaker_persona_id),
                history_limit=snapshot.history_limit, fail_candidate=False,
                output_attempts=snapshot.output_attempts,
                **({"scope": scope} if scope is not None else {}))
            target["revision"] = saved["revision"]
        personal_inputs = {}
        diagnostic_error_code = None
        if collect_inputs:
            try:
                context = await scene()
                for pid in context.eligible_ids:
                    personal = await generation._database(build_member_context, session_id, pid, target["candidate_id"],
                        target["revision"], db, generation_parameters_json=snapshot.member_parameters(pid), history_limit=snapshot.history_limit,
                        **({"scope": scope} if scope is not None else {}))
                    personal_inputs[str(pid)] = json.loads(personal.messages_json)
            except Exception as exc:
                # 诊断读取不改变业务终态；取消仍交给外层等待持久化并清理。
                personal_inputs = {}
                diagnostic_error_code = exc.code if isinstance(exc, director.GroupDirectorError) else "input_collection_failed"
                logger.warning("群聊输入诊断未完成 error_type=%s", type(exc).__name__)
        try:
            if scope is None:
                done = await generation._database(history._finish, session_id, target["candidate_id"], target["revision"], False, db,
                    **({"finish_reason": finish_reason, "model": model} if protocol_version == 2 else {}))
            else:
                done = await generation._database(checkpoints.finish, scope, target["revision"], finish_reason, model, db)
        except generation._DatabaseCancelled as exc:
            if not isinstance(exc.result, dict):
                raise
            done = exc.result
        target["revision"] = done["revision"]
        return {**target, "finish_reason": finish_reason, "calls": calls, "error_code": None,
                "personal_inputs": personal_inputs, "diagnostic_error_code": diagnostic_error_code}
    except BaseException as exc:
        if target:
            if isinstance(exc, generation._DatabaseCancelled) and exc.committed_revision is not None:
                target["revision"] = exc.committed_revision
            code = "cancelled" if isinstance(exc, asyncio.CancelledError) else (
                exc.code if isinstance(exc, (director.GroupDirectorError, generation.GroupGenerationError, GroupUnitError))
                else "timeout" if isinstance(exc, TimeoutError) else "execution_failed")
            try:
                if scope is None:
                    failed_revision = await generation._database(generation._fail, session_id, target["candidate_id"],
                                                                 target["revision"], db, runtime, code)
                else:
                    failed_revision = await generation._database(checkpoints.fail, scope, target["revision"], code, db)
                if failed_revision is not None:
                    target["revision"] = failed_revision
            except Exception as marker_error:
                logger.warning("群聊轮次失败标记未保存 error_type=%s", type(marker_error).__name__)
        if isinstance(exc, asyncio.CancelledError):
            raise
        code = exc.code if isinstance(exc, (director.GroupDirectorError, generation.GroupGenerationError, GroupUnitError)) else (
            "timeout" if isinstance(exc, TimeoutError) else "execution_failed")
        return {**(target or {}), "finish_reason": "failed", "calls": calls, "error_code": code}
