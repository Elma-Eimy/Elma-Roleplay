"""持久执行目标、检查点与请求终态；所有写入都受任务作用域保护。"""
import json
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from core.models import (GroupRound, GroupRoundCandidate, GroupRoundOperation, GroupContentItem,
                         GroupContentUnit, GroupUnitVisibility, GroupContentVisibility, GroupDirectorStep)
from core.locking import require_group_execution, require_group_runtime, get_session_lock
from services.conversation import group_history_service as history, group_audit_service as audit
from services.conversation import group_unit_service as units
from services.conversation.group_unit_protocol import parse_user_units, parse_role_units, parse_unit_visibility, ContentUnit, UnitPlan
from services.conversation.session_access import SessionKindConflict, group_session_operation


@dataclass(frozen=True)
class GroupTargetScope:
    execution: object
    operation_id: int
    session_id: int
    round_id: int
    candidate_id: int


def bind_target(execution, receipt, db):
    require_group_execution(execution, execution.session_id, db.get_bind())
    accepted = receipt["accepted"]
    scope = GroupTargetScope(execution, receipt["operation_id"], execution.session_id,
                             accepted["round_id"], accepted["candidate_id"])
    execution.target_scope = scope
    return scope


def _authorize(scope, session_id, candidate_id, db):
    if not isinstance(scope, GroupTargetScope):
        raise SessionKindConflict("缺少持久目标作用域")
    execution = scope.execution
    require_group_runtime(execution.owner, db.get_bind())
    try:
        caller = asyncio.current_task()
    except RuntimeError:
        caller = None
    if caller is not None and caller is not execution.task:
        raise SessionKindConflict("不能借用其他任务的持久目标")
    if (not execution.active or execution.owner.executions.get(execution.task) is not execution
            or getattr(execution, "target_scope", None) is not scope or not execution.lock.locked()
            or get_session_lock(session_id) is not execution.lock
            or (scope.session_id, scope.candidate_id) != (session_id, candidate_id)):
        raise SessionKindConflict("执行作用域已失效或不属于当前目标")


@group_session_operation
def target(scope, session_id, candidate_id, revision, db):
    _authorize(scope, session_id, candidate_id, db)
    operation = db.get(GroupRoundOperation, scope.operation_id)
    candidate = db.get(GroupRoundCandidate, candidate_id)
    round_ = db.get(GroupRound, scope.round_id)
    if (not operation or operation.status != "running" or operation.session_id != session_id
            or (operation.round_id, operation.candidate_id) != (scope.round_id, candidate_id)
            or not candidate or candidate.session_id != session_id or candidate.round_id != scope.round_id
            or candidate.status != "generating" or candidate.revision != revision
            or not round_ or round_.session_id != session_id or round_.confirmed_at or round_.discarded_at):
        raise SessionKindConflict("持久目标、操作状态或版本已变化")
    return round_, candidate


def _write(scope, revision, db):
    history._begin_write(db)
    return target(scope, scope.session_id, scope.candidate_id, revision, db)


def saved_steps(candidate_id, db):
    return db.query(GroupContentItem).filter_by(candidate_id=candidate_id, kind="utterance").count()


def validate_prefix(round_, candidate, db):
    """校验整个持久前缀，不以当前 revision 大于旧审计为重复调度依据。"""
    def invalid():
        raise SessionKindConflict("候选检查点与前缀不一致，请整轮重生成或撤回")
    from services.conversation.group_turn_plan import _planning, _validate_basis
    turn_policy = _planning(candidate, db)

    def action_valid(step, before):
        value = json.loads(step.decision_json)
        base = {"action": "speak", "speaker_persona_id": step.speaker_persona_id, "reason_code": step.reason_code}
        if value != {**base, **({"basis": value["basis"]} if "basis" in value else {})}:
            invalid()
        if "basis" in value or turn_policy:
            return _validate_basis(candidate.session_id, step.speaker_persona_id, round_, candidate, before, value.get("basis"), db)
    if candidate.protocol_version != 2 or candidate.checkpoint not in (
            "user_visibility", "next_action", "role_generation", "finish"):
        invalid()
    members = history._members(candidate.session_id, db)
    items = db.query(GroupContentItem).filter_by(candidate_id=candidate.id).order_by(GroupContentItem.sequence).all()
    steps = db.query(GroupDirectorStep).filter_by(candidate_id=candidate.id).order_by(GroupDirectorStep.step_index).all()
    if not items or [i.sequence for i in items] != list(range(len(items))) or items[0].kind != "user":
        invalid()
    if candidate.checkpoint == "user_visibility":
        if len(items) != 1 or steps or db.query(GroupContentUnit).filter_by(candidate_id=candidate.id).count() or db.query(
                GroupContentVisibility).filter_by(item_id=items[0].id).count():
            invalid()
        return None
    if [s.step_index for s in steps] != list(range(1, len(steps) + 1)):
        invalid()
    expected_stages = ["user_visibility"]
    for _ in items[1:]:
        expected_stages.extend(("next_action", "utterance_visibility"))
    if candidate.checkpoint == "role_generation":
        expected_stages.append("next_action")
    if [s.stage for s in steps] != expected_stages:
        invalid()
    for index, step in enumerate(steps):
        if (step.policy_version != 2 or step.result_revision > candidate.revision
                or (index and step.expected_revision < steps[index-1].result_revision)):
            invalid()
        if step.stage == "next_action" and (step.reason_code not in ("direct_response", "follow_up")
                or step.speaker_persona_id not in members):
            invalid()
    for index, item in enumerate(items):
        stage = steps[0 if index == 0 else 2 * index]
        if (stage.item_id != item.id or item.kind != ("user" if index == 0 else "utterance")
                or stage.speaker_persona_id != item.speaker_persona_id):
            invalid()
        rows = db.query(GroupContentUnit).filter_by(item_id=item.id).order_by(GroupContentUnit.unit_index).all()
        if not rows or [row.unit_index for row in rows] != list(range(len(rows))):
            invalid()
        audiences = []
        for row in rows:
            grants = dict(db.query(GroupUnitVisibility.recipient_persona_id, GroupUnitVisibility.decision).filter_by(unit_id=row.id))
            if set(grants) != members:
                invalid()
            visible = tuple(sorted(pid for pid, decision in grants.items() if decision == "visible"))
            if item.kind != "user" and (item.speaker_persona_id not in visible
                    or row.kind == "thought" and set(visible) != {item.speaker_persona_id}):
                invalid()
            audiences.append(visible)
        stage_value = json.loads(stage.decision_json)
        plan = UnitPlan(tuple(ContentUnit(row.kind, row.text, row.source_start, row.source_end) for row in rows), tuple(audiences))
        if item.kind == "user":
            try:
                plan = parse_user_units(json.dumps({"units": [{k: v for k, v in row.items() if k != "unit_index"}
                    for row in stage_value["units"]]}), round_.user_content, tuple(sorted(members)),
                    require_meaning=bool(turn_policy),
                    require_reply_mode=(turn_policy >= 2 if candidate.call_snapshot_json else None))
                if ([(unit.start, unit.end) for unit in plan.units] != [(row.source_start, row.source_end) for row in rows]
                        or plan.audiences != tuple(audiences) or any(row.kind != "user" for row in rows)):
                    invalid()
            except ValueError:
                invalid()
        else:
            try:
                checked_units = parse_role_units([{"kind": row.kind, "text": row.text} for row in rows])
                basis = action_valid(steps[2*index-1], item.sequence) or {}
                plan = parse_unit_visibility(json.dumps(stage_value), checked_units, tuple(sorted(members)),
                    item.speaker_persona_id, require_review=bool(turn_policy), reply_mode=basis.get("reply_mode"))
                if plan.audiences != tuple(audiences):
                    invalid()
            except ValueError:
                invalid()
            if "".join(row.text for row in rows) != item.content or steps[2*index-1].speaker_persona_id != item.speaker_persona_id:
                invalid()
        if stage_value != plan.decision(members):
            invalid()
        parents = dict(db.query(GroupContentVisibility.recipient_persona_id, GroupContentVisibility.decision).filter_by(item_id=item.id))
        common = set.intersection(*(set(audience) for audience in audiences))
        if item.speaker_persona_id is not None:
            common.add(item.speaker_persona_id)
        if parents != {pid: "visible" if pid in common else "hidden" for pid in members}:
            invalid()
    if candidate.checkpoint == "role_generation":
        step = steps[-1]
        payload = json.loads(step.decision_json)
        if step.speaker_persona_id not in members:
            invalid()
        action_valid(step, len(items))
        from services.conversation.group_turn_plan import _sources
        if not _sources(candidate.session_id, step.speaker_persona_id, round_, candidate, 2**63-1, db):
            invalid()
        return step.speaker_persona_id
    return None


def start(scope, revision, db):
    try:
        history._begin_write(db)
        operation = db.get(GroupRoundOperation, scope.operation_id)
        if operation.status != "queued":
            raise SessionKindConflict("请求已经启动或结束")
        operation.status = "running"
        operation.started_at = datetime.utcnow()
        operation.deadline_at = operation.started_at + timedelta(seconds=300)
        operation.revision += 1
        db.flush()
        round_, candidate = target(scope, scope.session_id, scope.candidate_id, revision, db)
        validate_prefix(round_, candidate, db)
        result = progress(scope, revision, db)
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise


def progress(scope, revision, db):
    round_, candidate = target(scope, scope.session_id, scope.candidate_id, revision, db)
    speaker = validate_prefix(round_, candidate, db)
    limit = json.loads(candidate.call_snapshot_json)["max_steps"]
    count = saved_steps(candidate.id, db)
    if count > limit or (candidate.checkpoint == "finish") != (count == limit):
        raise SessionKindConflict("候选步数与检查点不一致")
    return dict(checkpoint=candidate.checkpoint, speaker=speaker, remaining=limit-count,
                revision=candidate.revision, user_content=round_.user_content)


def consume(scope, revision, db):
    try:
        _write(scope, revision, db)
        operation = db.get(GroupRoundOperation, scope.operation_id)
        remaining = (operation.deadline_at - datetime.utcnow()).total_seconds()
        if remaining <= 0 or operation.call_count >= operation.call_limit:
            from services.conversation.group_director_service import GroupDirectorError
            raise GroupDirectorError("call_budget")
        operation.call_count += 1
        operation.revision += 1
        deadline = operation.deadline_at
        db.commit()
        return deadline
    except BaseException:
        db.rollback()
        raise


def save_user(scope, revision, plan, model, db):
    try:
        round_, candidate = _write(scope, revision, db)
        if candidate.checkpoint != "user_visibility":
            raise SessionKindConflict("初判已经保存")
        item = db.query(GroupContentItem).filter_by(candidate_id=candidate.id, sequence=0).one()
        visible = tuple(sorted(set.intersection(*(set(ids) for ids in plan.audiences))))
        history._visibility(item, visible, history._members(scope.session_id, db), db)
        units._write_units(item, plan, history._members(scope.session_id, db), round_.user_content, db)
        audit.record(candidate, "user_visibility", plan, model, db, item=item)
        candidate.checkpoint = "next_action"
        candidate.revision += 1
        result = dict(round_id=round_.id, candidate_id=candidate.id, revision=candidate.revision)
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise


def finish(scope, revision, reason, model, db):
    try:
        round_, candidate = _write(scope, revision, db)
        if candidate.checkpoint not in ("next_action", "finish"):
            raise SessionKindConflict("不能结束未保存完整步骤的候选")
        validate_prefix(round_, candidate, db)
        audit.record(candidate, "finish", reason, model, db)
        candidate.checkpoint = "done"
        candidate.status = "awaiting_confirmation"
        candidate.finish_reason = reason
        candidate.error_code = None
        candidate.revision += 1
        round_.selected_candidate_id = candidate.id
        history._require_group(scope.session_id, db).group_revision += 1
        operation = db.get(GroupRoundOperation, scope.operation_id)
        operation.status = "succeeded"
        operation.finished_at = datetime.utcnow()
        operation.revision += 1
        result = dict(candidate_id=candidate.id, revision=candidate.revision, status=candidate.status)
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise


def fail(scope, revision, code, db):
    try:
        history._begin_write(db)
        operation = db.get(GroupRoundOperation, scope.operation_id)
        candidate = db.get(GroupRoundCandidate, scope.candidate_id)
        # 最终提交已经获胜时不再覆盖成功；启动客户端失败也能收敛 queued 回执。
        _authorize(scope, scope.session_id, scope.candidate_id, db)
        if not operation or operation.status not in ("queued", "running"):
            db.rollback()
            return None
        if candidate.revision != revision or candidate.status != "generating":
            operation.status = "failed"
            operation.error_code = "version_conflict"
            operation.finished_at = datetime.utcnow()
            operation.revision += 1
            history._require_group(scope.session_id, db).group_revision += 1
            db.commit()
            return None
        if operation.status == "queued":
            operation.status = "running"
            db.flush()
        target(scope, scope.session_id, scope.candidate_id, revision, db)
        candidate.status = "failed"
        candidate.error_code = code
        candidate.revision += 1
        operation.status = "failed"
        operation.error_code = code
        operation.finished_at = datetime.utcnow()
        operation.revision += 1
        history._require_group(scope.session_id, db).group_revision += 1
        result = candidate.revision
        db.commit()
        return result
    except SessionKindConflict:
        db.rollback()
        return None
    except BaseException:
        db.rollback()
        raise
