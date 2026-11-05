"""群聊内容归属和个人历史；不调用模型或开放跨轮确认。"""
import logging
from dataclasses import dataclass

from sqlalchemy import and_, or_, func, text

from core.models import (GroupRound, GroupRoundCandidate, GroupContentItem,
                         GroupContentVisibility, SessionPersona)
from services.conversation.session_access import get_group_session, group_session_operation, SessionKindConflict
from services.conversation.group_session_service import (
    _begin_write, _locked_write, GroupSessionNotFound, GroupSessionValidationError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GroupHistoryItem:
    item_id: int
    round_id: int
    candidate_id: int
    round_index: int
    sequence: int
    kind: str
    speaker_persona_id: int | None
    content: str


def _require_group(session_id, db):
    # 类型预检查不能先 flush 调用方尚未提交的修改。
    with db.no_autoflush:
        group = get_group_session(session_id, db)
    if group is None:
        raise GroupSessionNotFound("群聊不存在")
    return group


def _require_clean_transaction(db):
    if db.new or db.dirty or db.deleted:
        raise GroupSessionValidationError("群聊操作需要没有待提交修改的数据库会话")
    # flush 后 ORM 集合可能已经为空；不能 rollback 调用方仍持有的 SQLite 事务。
    if db.connection().connection.driver_connection.in_transaction:
        raise GroupSessionValidationError("群聊操作需要没有活动 SQLite 事务的数据库会话")


def _positive(value, name, minimum=1):
    if type(value) is not int or value < minimum:
        raise GroupSessionValidationError(f"{name}无效")


def _members(session_id, db):
    return {row[0] for row in db.query(SessionPersona.id).filter_by(session_id=session_id)}


def _visibility(item, visible_to, members, db):
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


def _target(session_id, candidate_id, db):
    _require_group(session_id, db)
    _positive(candidate_id, "候选")
    candidate = db.get(GroupRoundCandidate, candidate_id)
    if candidate is None or candidate.session_id != session_id:
        raise GroupSessionNotFound("候选不属于本群或不存在")
    round_ = db.get(GroupRound, candidate.round_id)
    if round_.selected_candidate_id != candidate.id or round_.confirmed_at is not None:
        raise SessionKindConflict("只能操作当前未确认的所选候选")
    if candidate.status == "failed":
        raise SessionKindConflict("失败候选不能继续执行或作为当前上下文")
    return round_, candidate


def _writable(session_id, candidate_id, expected_revision, db):
    _positive(expected_revision, "候选版本", 0)
    round_, candidate = _target(session_id, candidate_id, db)
    if candidate.status != "generating" or candidate.revision != expected_revision:
        raise SessionKindConflict("候选状态或版本已变化")
    return round_, candidate


@group_session_operation
async def prepare_group_round(session_id, user_content, visible_to, db):
    _require_group(session_id, db)
    _require_clean_transaction(db)
    if not isinstance(user_content, str) or not user_content.strip():
        raise GroupSessionValidationError("用户输入不能为空")
    return await _locked_write([session_id], _prepare, session_id, user_content, visible_to, db)


def _prepare(session_id, user_content, visible_to, db):
    try:
        _begin_write(db)
        _require_group(session_id, db)
        if db.query(GroupRound.id).filter_by(session_id=session_id, confirmed_at=None).first():
            raise SessionKindConflict("已有待处理或待确认轮次，当前不支持跨轮确认或恢复")
        index = (db.query(func.max(GroupRound.round_index)).filter_by(session_id=session_id).scalar() or 0) + 1
        round_ = GroupRound(session_id=session_id, round_index=index, user_content=user_content)
        db.add(round_)
        db.flush()
        candidate = GroupRoundCandidate(round_id=round_.id, session_id=session_id)
        db.add(candidate)
        db.flush()
        round_.selected_candidate_id = candidate.id
        item = GroupContentItem(session_id=session_id, candidate_id=candidate.id, sequence=0, kind="user")
        db.add(item)
        db.flush()
        _visibility(item, visible_to, _members(session_id, db), db)
        candidate.revision = 1
        result = {"round_id": round_.id, "candidate_id": candidate.id, "revision": 1}
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise


@group_session_operation
async def append_group_utterance(session_id, candidate_id, speaker_persona_id, content,
                                 visible_to, expected_revision, db):
    """内部保存已完成正文；模型执行与状态增量接入留给 M2-B。"""
    _require_group(session_id, db)
    _require_clean_transaction(db)
    if not isinstance(content, str) or not content.strip():
        raise GroupSessionValidationError("角色正文不能为空")
    _positive(speaker_persona_id, "发言成员")
    return await _locked_write([session_id], _append, session_id, candidate_id, speaker_persona_id,
                              content, visible_to, expected_revision, db)


def _append(session_id, candidate_id, speaker, content, visible_to, revision, db):
    try:
        _begin_write(db)
        _, candidate = _writable(session_id, candidate_id, revision, db)
        members = _members(session_id, db)
        if speaker not in members:
            raise GroupSessionValidationError("发言成员不属于本群")
        sequence = db.query(func.max(GroupContentItem.sequence)).filter_by(candidate_id=candidate_id).scalar() + 1
        item = GroupContentItem(session_id=session_id, candidate_id=candidate_id, sequence=sequence,
                                kind="utterance", speaker_persona_id=speaker, content=content)
        db.add(item)
        db.flush()
        _visibility(item, visible_to, members, db)
        candidate.revision += 1
        result = {"item_id": item.id, "sequence": sequence, "revision": candidate.revision}
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise


@group_session_operation
async def finish_group_round(session_id, candidate_id, expected_revision, db, *, failed=False):
    """只结束当前候选，不确认轮次、不触发提纯或自动重试。"""
    _require_group(session_id, db)
    _require_clean_transaction(db)
    if type(failed) is not bool:
        raise GroupSessionValidationError("失败标识无效")
    return await _locked_write([session_id], _finish, session_id, candidate_id, expected_revision, failed, db)


def _finish(session_id, candidate_id, revision, failed, db):
    try:
        _begin_write(db)
        _, candidate = _writable(session_id, candidate_id, revision, db)
        candidate.status = "failed" if failed else "awaiting_confirmation"
        candidate.error_code = "execution_failed" if failed else None
        candidate.revision += 1
        result = {"candidate_id": candidate.id, "revision": candidate.revision, "status": candidate.status}
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise


@group_session_operation
def get_member_history(session_id, persona_id, candidate_id, before_sequence, db, *, limit=50):
    """在独立读快照内返回个人 DTO；读取不授予后续模型调用的执行权。"""
    _require_group(session_id, db)
    _require_clean_transaction(db)
    _positive(persona_id, "成员")
    _positive(candidate_id, "候选")
    _positive(before_sequence, "内容边界", 0)
    _positive(limit, "历史条数")
    if limit > 500:
        raise GroupSessionValidationError("历史条数最多 500")
    db.rollback()
    db.expire_all()
    db.execute(text("BEGIN"))
    try:
        round_, candidate = _target(session_id, candidate_id, db)
        if persona_id not in _members(session_id, db):
            raise GroupSessionValidationError("成员不属于本群")
        scope = or_(
            and_(GroupRound.round_index < round_.round_index, GroupRound.confirmed_at.isnot(None),
                 GroupRound.selected_candidate_id == GroupRoundCandidate.id,
                 GroupRoundCandidate.status == "awaiting_confirmation"),
            and_(GroupRoundCandidate.id == candidate.id, GroupContentItem.sequence < before_sequence),
        )
        query = db.query(GroupContentItem, GroupRound).join(GroupRoundCandidate,
            GroupContentItem.candidate_id == GroupRoundCandidate.id).join(GroupRound,
            GroupRoundCandidate.round_id == GroupRound.id).filter(GroupRound.session_id == session_id, scope)
        visible = query.join(GroupContentVisibility, and_(GroupContentVisibility.item_id == GroupContentItem.id,
            GroupContentVisibility.recipient_persona_id == persona_id))
        # 缺行不兜底为公开；只向内部日志报告，不向个人 DTO 泄露隐藏项信息。
        missing = query.outerjoin(GroupContentVisibility, and_(GroupContentVisibility.item_id == GroupContentItem.id,
            GroupContentVisibility.recipient_persona_id == persona_id)).filter(GroupContentVisibility.item_id.is_(None)).first()
        if missing:
            logger.warning("群聊个人历史存在缺失知情记录，已按不可见处理")
        rows = visible.filter(GroupContentVisibility.decision == "visible").order_by(
            GroupRound.round_index.desc(), GroupContentItem.sequence.desc()).limit(limit).all()
        return tuple(GroupHistoryItem(item.id, owner.id, item.candidate_id, owner.round_index,
            item.sequence, item.kind, item.speaker_persona_id,
            owner.user_content if item.kind == "user" else item.content) for item, owner in reversed(rows))
    finally:
        db.rollback()
