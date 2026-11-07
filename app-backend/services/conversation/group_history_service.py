"""群聊内容归属和个人历史；兼容旧单步执行，不调用模型。"""
import logging
import json
from dataclasses import dataclass

from sqlalchemy import and_, or_, func, text

from core.models import (GroupRound, GroupRoundCandidate, GroupContentItem,
                         GroupContentVisibility, SessionPersona)
from services.conversation.session_access import get_group_session, group_session_operation, SessionKindConflict
from services.conversation.group_session_service import (
    _begin_write, _locked_write, GroupSessionNotFound, GroupSessionValidationError,
)
from services.conversation import group_unit_service as units, group_audit_service as audit
from services.conversation.group_unit_protocol import ContentUnit

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
    emotion_tag: str | None = None
    affection_change: int | None = None
    visible_units: tuple[ContentUnit, ...] = ()
    visible_passages: tuple[str, ...] = ()


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
    if round_.selected_candidate_id != candidate.id or round_.confirmed_at is not None or round_.discarded_at is not None:
        raise SessionKindConflict("只能操作当前未确认的所选候选")
    if candidate.status == "failed":
        raise SessionKindConflict("失败候选不能继续执行或作为当前上下文")
    return round_, candidate


def _writable(session_id, candidate_id, expected_revision, db, *, scope=None):
    _positive(expected_revision, "候选版本", 0)
    if scope is not None:
        from services.conversation.group_checkpoint_service import target
        return target(scope, session_id, candidate_id, expected_revision, db)
    from services.conversation.group_operation_service import _active
    if _active(session_id, db):
        raise SessionKindConflict("持久任务不能通过旧执行入口写入")
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


def _prepare(session_id, user_content, visible_to, db, *, unit_plan=None, model=None):
    try:
        _begin_write(db)
        group = _require_group(session_id, db)
        from services.conversation.group_operation_service import _active
        if _active(session_id, db):
            raise SessionKindConflict("存在活动群聊操作")
        if db.query(GroupRound.id).filter_by(session_id=session_id, confirmed_at=None, discarded_at=None).first():
            raise SessionKindConflict("已有待处理或待确认轮次，当前不支持跨轮确认或恢复")
        index = (db.query(func.max(GroupRound.round_index)).filter_by(session_id=session_id).scalar() or 0) + 1
        from services.media.group_portraits import _freeze_current_choices
        portrait_snapshot = _freeze_current_choices(session_id, db)
        round_ = GroupRound(session_id=session_id, round_index=index, user_content=user_content)
        db.add(round_)
        db.flush()
        candidate = GroupRoundCandidate(round_id=round_.id, session_id=session_id,
                                        portrait_selections_json=portrait_snapshot,
                                        protocol_version=2 if unit_plan is not None else 1)
        db.add(candidate)
        db.flush()
        round_.selected_candidate_id = candidate.id
        item = GroupContentItem(session_id=session_id, candidate_id=candidate.id, sequence=0, kind="user")
        db.add(item)
        db.flush()
        _visibility(item, visible_to, _members(session_id, db), db)
        if unit_plan is not None:
            units._write_units(item, unit_plan, _members(session_id, db), user_content, db)
            audit.record(candidate, "user_visibility", unit_plan, model, db, item=item)
        group.group_revision += 1
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


def _append(session_id, candidate_id, speaker, content, visible_to, revision, db, *,
            emotion_tag=None, affection_change=None, role_state_patch=None, unit_plan=None, model=None, scope=None):
    try:
        _begin_write(db)
        round_, candidate = _writable(session_id, candidate_id, revision, db, scope=scope)
        if scope is not None:
            from services.conversation.group_checkpoint_service import validate_prefix
            if candidate.checkpoint != "role_generation" or validate_prefix(round_, candidate, db) != speaker:
                raise SessionKindConflict("发言不属于当前已接受调度")
        if (candidate.protocol_version == 2) != (unit_plan is not None):
            raise GroupSessionValidationError("不能混用全文和单元协议")
        members = _members(session_id, db)
        if speaker not in members:
            raise GroupSessionValidationError("发言成员不属于本群")
        sequence = db.query(func.max(GroupContentItem.sequence)).filter_by(candidate_id=candidate_id).scalar() + 1
        item = GroupContentItem(session_id=session_id, candidate_id=candidate_id, sequence=sequence,
                                kind="utterance", speaker_persona_id=speaker, content=content,
                                emotion_tag=emotion_tag, affection_change=affection_change,
                                role_state_patch=role_state_patch)
        db.add(item)
        db.flush()
        _visibility(item, visible_to, members, db)
        if unit_plan is not None:
            units._write_units(item, unit_plan, members, None, db)
            audit.record(candidate, "utterance_visibility", unit_plan, model, db, item=item)
        if scope is not None:
            from services.conversation.group_checkpoint_service import saved_steps
            # 检查点与本次完整发言同事务保存。
            count = saved_steps(candidate_id, db)
            maximum = json.loads(candidate.call_snapshot_json)["max_steps"]
            candidate.checkpoint = "finish" if count >= maximum else "next_action"
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


def _finish(session_id, candidate_id, revision, failed, db, *, finish_reason=None, model=None):
    try:
        _begin_write(db)
        _, candidate = _writable(session_id, candidate_id, revision, db)
        if candidate.protocol_version == 2 and not failed:
            audit.record(candidate, "finish", finish_reason, model, db)
        candidate.finish_reason = None if failed else finish_reason
        candidate.status = "failed" if failed else "awaiting_confirmation"
        _require_group(session_id, db).group_revision += 1
        candidate.error_code = "execution_failed" if failed else None
        candidate.revision += 1
        result = {"candidate_id": candidate.id, "revision": candidate.revision, "status": candidate.status}
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise


def _accept_action(session_id, candidate_id, revision, action, model, db, *, scope=None):
    try:
        _begin_write(db)
        round_, candidate = _writable(session_id, candidate_id, revision, db, scope=scope)
        if scope is not None and candidate.checkpoint != "next_action":
            raise SessionKindConflict("调度检查点已变化")
        if action.speaker_persona_id not in _members(session_id, db):
            raise GroupSessionValidationError("调度成员不属于本群")
        from services.conversation.group_turn_plan import _planning, _validate_basis
        if action.basis is not None or _planning(candidate, db):
            before = (db.query(func.max(GroupContentItem.sequence)).filter_by(candidate_id=candidate_id).scalar() or 0) + 1
            _validate_basis(session_id, action.speaker_persona_id, round_, candidate, before, action.basis, db)
        audit.record(candidate, "next_action", action, model, db)
        if scope is not None:
            candidate.checkpoint = "role_generation"
        candidate.revision += 1
        result = {"revision": candidate.revision}
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
        return _member_history(session_id, persona_id, round_, candidate, before_sequence, limit, db)
    finally:
        db.rollback()


def _content_scope(round_, candidate, before_sequence):
    return or_(
        and_(GroupRound.round_index < round_.round_index, GroupRound.confirmed_at.isnot(None), GroupRound.discarded_at.is_(None),
             GroupRound.selected_candidate_id == GroupRoundCandidate.id,
             GroupRoundCandidate.status == "awaiting_confirmation"),
        and_(GroupRoundCandidate.id == candidate.id, GroupContentItem.sequence < before_sequence),
    )


def _content_query(session_id, round_, candidate, before_sequence, db):
    return db.query(GroupContentItem, GroupRound).join(GroupRoundCandidate,
            GroupContentItem.candidate_id == GroupRoundCandidate.id).join(GroupRound,
            GroupRoundCandidate.round_id == GroupRound.id).filter(GroupRound.session_id == session_id,
                _content_scope(round_, candidate, before_sequence))


def _member_history(session_id, persona_id, round_, candidate, before_sequence, limit, db):
    query = _content_query(session_id, round_, candidate, before_sequence, db)
    legacy_visible = db.query(GroupContentVisibility.item_id).filter(
        GroupContentVisibility.item_id == GroupContentItem.id,
        GroupContentVisibility.recipient_persona_id == persona_id,
        GroupContentVisibility.decision == "visible").exists()
    visible = query.filter(or_(and_(GroupRoundCandidate.protocol_version == 1, legacy_visible),
        and_(GroupRoundCandidate.protocol_version == 2, units._has_visible_unit(persona_id, db))))
    # 缺行不兜底为公开；只向内部日志报告，不向个人 DTO 泄露隐藏项信息。
    missing = query.outerjoin(GroupContentVisibility, and_(GroupContentVisibility.item_id == GroupContentItem.id,
            GroupContentVisibility.recipient_persona_id == persona_id)).filter(GroupContentVisibility.item_id.is_(None)).first()
    if missing:
        logger.warning("群聊个人历史存在缺失知情记录，已按不可见处理")
    rows = visible.order_by(
            GroupRound.round_index.desc(), GroupContentItem.sequence.desc()).limit(limit).all()
    result = []
    for item, owner in reversed(rows):
        v2 = db.get(GroupRoundCandidate, item.candidate_id).protocol_version == 2
        visible_units, passages = units._member_projection(item, owner, persona_id, db) if v2 else ((), ())
        content = ("\n".join(passages) if v2 else
                   owner.user_content if item.kind == "user" else item.content)
        own_state_visible = item.speaker_persona_id == persona_id and (not v2 or units._complete_author_visibility(item, db))
        result.append(GroupHistoryItem(item.id, owner.id, item.candidate_id, owner.round_index,
            item.sequence, item.kind, item.speaker_persona_id, content,
            item.emotion_tag if own_state_visible else None, item.affection_change if own_state_visible else None,
            visible_units, passages))
    return tuple(result)


@group_session_operation
def list_group_rounds(session_id, db, *, limit=20, offset=0):
    """故事操作者的只读视图，不能作为角色个人输入。"""
    _require_group(session_id, db)
    _require_clean_transaction(db)
    _positive(limit, "分页条数")
    _positive(offset, "分页位置", 0)
    if limit > 100:
        raise GroupSessionValidationError("分页条数最多 100")
    db.rollback()
    db.expire_all()
    db.execute(text("BEGIN"))
    try:
        _require_group(session_id, db)
        query = db.query(GroupRound).filter_by(session_id=session_id, discarded_at=None)
        total = query.count()
        rounds = query.order_by(GroupRound.round_index.desc()).offset(offset).limit(limit).all()
        ids = [row.selected_candidate_id for row in rounds if row.selected_candidate_id is not None]
        candidates = {row.id: row for row in db.query(GroupRoundCandidate).filter(GroupRoundCandidate.id.in_(ids)).all()}
        items = db.query(GroupContentItem).filter(GroupContentItem.candidate_id.in_(ids),
            GroupContentItem.kind == "utterance").order_by(GroupContentItem.sequence).all()
        members = {row.id: row.character for row in db.query(SessionPersona).filter_by(session_id=session_id)}
        by_candidate = {cid: [] for cid in ids}
        for item in items:
            character = members[item.speaker_persona_id]
            by_candidate[item.candidate_id].append({"item_id": item.id, "sequence": item.sequence,
                "speaker_persona_id": item.speaker_persona_id, "speaker_name": character.name,
                "content": item.content, "created_at": item.created_at.isoformat()})
        result = []
        from services.media.group_portraits import _candidate_portraits
        for row in rounds:
            candidate = candidates.get(row.selected_candidate_id)
            result.append({"round_id": row.id, "round_index": row.round_index,
                "candidate_id": row.selected_candidate_id,
                "status": candidate.status if candidate else "failed", "confirmed": row.confirmed_at is not None,
                "revision": candidate.revision if candidate else None,
                "finish_reason": candidate.finish_reason if candidate else None,
                "error_code": candidate.error_code if candidate else None,
                "portraits": _candidate_portraits(session_id, candidate, db) if candidate else [],
                "user_content": row.user_content, "created_at": row.created_at.isoformat(),
                "utterances": by_candidate.get(row.selected_candidate_id, [])})
        from services.conversation.group_query_service import _state
        return {"current": _state(_require_group(session_id, db), db),
                "rounds": result, "total": total, "limit": limit, "offset": offset,
                "has_more": offset + len(result) < total}
    finally:
        db.rollback()
