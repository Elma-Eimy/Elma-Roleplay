"""群聊共用归属、输入和调用方事务校验；不提交或回滚。"""
from core.models import GroupRound, GroupRoundCandidate, GroupContentVisibility, SessionPersona
from services.conversation.session_access import get_group_session, group_session_operation, SessionKindConflict
from .session_service import GroupSessionNotFound, GroupSessionValidationError
from .execution_scope import target, has_active_operation


@group_session_operation
def require_group(session_id, db):
    # 类型预检查不能先 flush 调用方尚未提交的修改。
    with db.no_autoflush:
        group = get_group_session(session_id, db)
    if group is None:
        raise GroupSessionNotFound("群聊不存在")
    return group


def require_clean_transaction(db):
    if db.new or db.dirty or db.deleted:
        raise GroupSessionValidationError("群聊操作需要没有待提交修改的数据库会话")
    # flush 后 ORM 集合可能已经为空；不能 rollback 调用方仍持有的 SQLite 事务。
    if db.connection().connection.driver_connection.in_transaction:
        raise GroupSessionValidationError("群聊操作需要没有活动 SQLite 事务的数据库会话")


def positive(value, name, minimum=1):
    if type(value) is not int or value < minimum:
        raise GroupSessionValidationError(f"{name}无效")


@group_session_operation
def member_ids(session_id, db):
    require_group(session_id, db)
    return {row[0] for row in db.query(SessionPersona.id).filter_by(session_id=session_id)}


def write_visibility(item, visible_to, members, db):
    if not isinstance(visible_to, tuple) or any(type(pid) is not int for pid in visible_to):
        raise GroupSessionValidationError("知情成员必须是固定的 Persona ID 列表")
    if len(set(visible_to)) != len(visible_to) or not set(visible_to) <= members:
        raise GroupSessionValidationError("知情成员重复或不属于本群")
    visible = set(visible_to)
    if item.speaker_persona_id is not None:
        visible.add(item.speaker_persona_id)
    for pid in sorted(members):
        db.add(GroupContentVisibility(item_id=item.id, session_id=item.session_id,
            recipient_persona_id=pid, decision="visible" if pid in visible else "hidden"))


@group_session_operation
def require_history_target(session_id, candidate_id, db):
    require_group(session_id, db)
    positive(candidate_id, "候选")
    candidate = db.get(GroupRoundCandidate, candidate_id)
    if candidate is None or candidate.session_id != session_id:
        raise GroupSessionNotFound("候选不属于本群或不存在")
    round_ = db.get(GroupRound, candidate.round_id)
    if round_.selected_candidate_id != candidate.id or round_.confirmed_at is not None or round_.discarded_at is not None:
        raise SessionKindConflict("只能操作当前未确认的所选候选")
    if candidate.status == "failed":
        raise SessionKindConflict("失败候选不能继续执行或作为当前上下文")
    return round_, candidate


@group_session_operation
def require_writable_candidate(session_id, candidate_id, expected_revision, db, *, scope=None):
    positive(expected_revision, "候选版本", 0)
    if scope is not None:
        return target(scope, session_id, candidate_id, expected_revision, db)
    if has_active_operation(session_id, db):
        raise SessionKindConflict("持久任务不能通过旧执行入口写入")
    round_, candidate = require_history_target(session_id, candidate_id, db)
    if candidate.status != "generating" or candidate.revision != expected_revision:
        raise SessionKindConflict("候选状态或版本已变化")
    return round_, candidate
