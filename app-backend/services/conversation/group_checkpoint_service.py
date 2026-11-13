"""持久执行目标、检查点与请求终态；所有写入都受任务作用域保护。"""
import json
from datetime import datetime, timedelta
from core.models import (GroupRound, GroupRoundCandidate, GroupRoundOperation, GroupContentItem,
                         GroupContentUnit, GroupUnitVisibility, GroupContentVisibility, GroupDirectorStep)
from services.conversation import group_history_service as history, group_audit_service as audit
from services.conversation import group_candidate_state as candidate_state
from services.conversation.group_execution_scope import GroupTargetScope, bind_target, target, _authorize
from services.conversation import group_unit_service as units
from services.conversation.group_unit_protocol import parse_user_units, parse_role_units, parse_unit_visibility, ContentUnit, UnitPlan
from services.conversation.session_access import SessionKindConflict, group_session_operation


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
        if "basis" in value or turn_policy or json.loads(candidate.call_snapshot_json or '{}').get('reply_target'):
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
    continuous = json.loads(candidate.call_snapshot_json).get('director_ending', False)
    if continuous:
        if candidate.checkpoint == 'finish' and candidate.finish_reason not in ('wait_user', 'no_visible_basis'):
            raise SessionKindConflict('缺少已保存的结束决定')
        return dict(checkpoint=candidate.checkpoint, speaker=speaker, remaining=0 if candidate.checkpoint == 'finish' else 1,
                    finish_reason=candidate.finish_reason, revision=candidate.revision, user_content=round_.user_content)
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
        candidate_state.user_saved(candidate)
        result = dict(round_id=round_.id, candidate_id=candidate.id, revision=candidate.revision)
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise


def prepare_finish(scope, revision, reason, db):
    """先保存导演结束决定，最终提交失败后无需重新调度。"""
    try:
        _, candidate = _write(scope, revision, db)
        candidate_state.prepare_finish(candidate, reason)
        db.commit()
        return dict(revision=candidate.revision)
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
        candidate_state.finish(candidate, reason, persistent=True)
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
        candidate_state.fail(candidate, code, preserve_finish=True)
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
