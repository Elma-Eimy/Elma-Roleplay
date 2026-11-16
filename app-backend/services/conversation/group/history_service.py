"""群聊内容归属和个人历史；兼容旧单步执行，不调用模型。"""
import json
from datetime import datetime

from sqlalchemy import func, text

from core.models import GroupRound, GroupRoundCandidate, GroupContentItem, SessionPersona
from services.conversation.session_access import group_session_operation, SessionKindConflict
from .session_service import _begin_write, _locked_write, GroupSessionNotFound, GroupSessionValidationError
from . import unit_service as units, audit_service as audit
from . import candidate_state as candidate_state
from . import dispatch_service as dispatches
from .execution_scope import has_active_operation

# 保留旧调用方的内部入口；共用实现由下层模块维护。
from .guards import (
    require_group as _require_group,
    require_clean_transaction as _require_clean_transaction,
    positive as _positive,
    member_ids as _members,
    write_visibility as _visibility,
    require_history_target as _target,
    require_writable_candidate as _writable,
)
from .history_projection import (GroupHistoryItem, logger, content_scope as _content_scope,
    content_query as _content_query, member_history as _member_history)
from .state_projection import group_state as _state
from .prefix_validation import validate_prefix, saved_steps


@group_session_operation
async def prepare_group_round(session_id, user_content, visible_to, db):
    _require_group(session_id, db)
    _require_clean_transaction(db)
    if not isinstance(user_content, str) or not user_content.strip():
        raise GroupSessionValidationError("用户输入不能为空")
    return await _locked_write([session_id], _prepare, session_id, user_content, visible_to, db)


def _prepare(session_id, user_content, visible_to, db, *, unit_plan=None, model=None, call_snapshot_json=None):
    try:
        _begin_write(db)
        group = _require_group(session_id, db)
        if has_active_operation(session_id, db):
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
                                        protocol_version=2 if unit_plan is not None else 1,
                                        call_snapshot_json=call_snapshot_json,
                                        dispatch_version=1 if json.loads(call_snapshot_json or "{}").get("shared_chat") else 0,
                                        checkpoint='next_action' if call_snapshot_json else 'done')
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
        group.updated_at = datetime.utcnow()
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
        if scope is not None or candidate.dispatch_version == 1:
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
        count = None
        if scope is not None or candidate.dispatch_version == 1:
            count = saved_steps(candidate_id, db)
        if candidate.dispatch_version == 1:
            dispatches.complete(candidate, sequence, speaker, db)
        candidate_state.utterance_saved(candidate, completed_steps=count)
        _require_group(session_id, db).updated_at = datetime.utcnow()
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
        round_, candidate = _writable(session_id, candidate_id, revision, db)
        if candidate.protocol_version == 2 and not failed:
            audit.record(candidate, "finish", finish_reason, model, db)
        if failed:
            candidate_state.fail(candidate, "execution_failed")
        else:
            if candidate.dispatch_version == 1:
                validate_prefix(round_, candidate, db)
            candidate_state.finish(candidate, finish_reason, persistent=candidate.dispatch_version == 1)
        group = _require_group(session_id, db)
        group.group_revision += 1
        group.updated_at = datetime.utcnow()
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
        if (scope is not None or candidate.dispatch_version == 1) and candidate.checkpoint != "next_action":
            raise SessionKindConflict("调度检查点已变化")
        if action.speaker_persona_id not in _members(session_id, db):
            raise GroupSessionValidationError("调度成员不属于本群")
        from .turn_plan import _planning, _validate_basis
        if action.basis is not None or _planning(candidate, db) or json.loads(candidate.call_snapshot_json or '{}').get('reply_target'):
            before = (db.query(func.max(GroupContentItem.sequence)).filter_by(candidate_id=candidate_id).scalar() or 0) + 1
            _validate_basis(session_id, action.speaker_persona_id, round_, candidate, before, action.basis, db)
        if candidate.dispatch_version == 1:
            dispatches.accept(candidate, action, db)
        audit.record(candidate, "next_action", action, model, db)
        candidate_state.action_saved(candidate, persistent=scope is not None or candidate.dispatch_version == 1)
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
        pending = {}
        for row in rounds:
            if row.confirmed_at is not None:
                continue
            newest = db.query(GroupRoundCandidate).filter_by(round_id=row.id).order_by(GroupRoundCandidate.version.desc()).first()
            if (newest and newest.id != row.selected_candidate_id and newest.status in ('generating', 'failed')
                    and json.loads(newest.call_snapshot_json or '{}').get('shared_chat')):
                pending[row.id] = newest
                ids.append(newest.id)
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
            preview = pending.get(row.id)
            result[-1]['pending_candidate'] = ({'candidate_id': preview.id, 'status': preview.status,
                'error_code': preview.error_code, 'utterances': by_candidate.get(preview.id, [])} if preview else None)
        return {"current": _state(_require_group(session_id, db), db),
                "rounds": result, "total": total, "limit": limit, "offset": offset,
                "has_more": offset + len(result) < total}
    finally:
        db.rollback()
