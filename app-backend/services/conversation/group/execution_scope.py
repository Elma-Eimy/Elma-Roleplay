"""群聊任务执行权与持久目标校验，不推进候选或接管事务。"""
import asyncio
from dataclasses import dataclass

from core.models import GroupRound, GroupRoundCandidate, GroupRoundOperation
from core.locking import require_group_execution, require_group_runtime, get_session_lock
from services.conversation.session_access import SessionKindConflict, group_session_operation, get_group_session


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


@group_session_operation
def has_active_operation(session_id, db):
    with db.no_autoflush:
        get_group_session(session_id, db)
    return db.query(GroupRoundOperation).filter(GroupRoundOperation.session_id == session_id,
        GroupRoundOperation.status.in_(("queued", "running"))).first() is not None
