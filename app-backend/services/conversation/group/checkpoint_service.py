"""持久执行目标、检查点与请求终态；所有写入都受任务作用域保护。"""
import json
from datetime import datetime, timedelta
from core.models import GroupRoundCandidate, GroupRoundOperation, GroupContentItem
from . import history_service as history, audit_service as audit
from . import candidate_state as candidate_state
from . import dispatch_service as dispatches, legacy_protocol as legacy_protocol
from .execution_scope import GroupTargetScope, bind_target, target, _authorize
from . import unit_service as units
from services.conversation.session_access import SessionKindConflict


def _write(scope, revision, db):
    history._begin_write(db)
    return target(scope, scope.session_id, scope.candidate_id, revision, db)


def saved_steps(candidate_id, db):
    return db.query(GroupContentItem).filter_by(candidate_id=candidate_id, kind="utterance").count()


def validate_prefix(round_, candidate, db):
    from .turn_plan import _validate_basis
    if candidate.dispatch_version == 1:
        return dispatches.validate_prefix(round_, candidate, db, resolve_basis=_validate_basis)
    return legacy_protocol.validate_prefix(round_, candidate, db)


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
            from .director_service import GroupDirectorError
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
