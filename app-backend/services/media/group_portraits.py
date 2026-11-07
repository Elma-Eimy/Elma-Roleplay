"""群聊立绘选择属于成员与候选，不修改不可变的入群起点。"""
import json

from core.models import CharacterPortrait, GroupRoundCandidate, SessionPersona
from services.conversation.group_session_service import (
    GroupSessionNotFound, GroupSessionValidationError, _begin_write, _locked_write)
from services.conversation.session_access import check_chat_arguments, group_session_operation, SessionKindConflict


def _members(session_id, db):
    return db.query(SessionPersona).filter_by(session_id=session_id).order_by(SessionPersona.member_slot).all()


def _candidate_choices(candidate, members):
    if candidate.portrait_selections_json is None:
        return {str(m.id): json.loads(m.group_origin.initial_state_json).get('portrait_base', 0) or 0 for m in members}
    try:
        values = json.loads(candidate.portrait_selections_json)
    except (ValueError, TypeError) as exc:
        raise GroupSessionValidationError('成员立绘快照无效') from exc
    if (not isinstance(values, dict) or set(values) != {str(m.id) for m in members}
            or any(type(v) is not int or v < 0 for v in values.values())):
        raise GroupSessionValidationError('成员立绘快照无效')
    return values


def _current_choices(session_id, db):
    from services.conversation.group_operation_service import _latest
    latest = _latest(session_id, db)
    members = _members(session_id, db)
    candidate = db.get(GroupRoundCandidate, latest.selected_candidate_id) if latest else None
    return (_candidate_choices(candidate, members) if candidate else
            {str(m.id): m.portrait_base or 0 for m in members})


def _freeze_current_choices(session_id, db):
    return json.dumps(_current_choices(session_id, db), sort_keys=True)


def _serialize(member, selected, db):
    row = db.query(CharacterPortrait).filter_by(id=selected, character_id=member.character_id).first() if selected else None
    return {'persona_id': member.id, 'portrait_id': row.id if row else None,
            'image_path': row.image_path if row else member.character.avatar_path or ''}


def _candidate_portraits(session_id, candidate, db):
    members = _members(session_id, db)
    choices = _candidate_choices(candidate, members)
    return [_serialize(member, choices[str(member.id)], db) for member in members]


def _current_portraits(session_id, db):
    choices = _current_choices(session_id, db)
    return [_serialize(member, choices[str(member.id)], db) for member in _members(session_id, db)]


@group_session_operation
async def update_group_portrait(session_id, persona_id, portrait_id, expected, db):
    from services.conversation import group_history_service as history
    with db.no_autoflush:
        check_chat_arguments({'session_id': session_id, 'persona_id': persona_id}, db, kind='group')
        history._require_group(session_id, db)
    history._require_clean_transaction(db)
    if portrait_id is not None and (type(portrait_id) is not int or portrait_id <= 0):
        raise GroupSessionValidationError('立绘 ID 必须是正整数或 null')
    return await _locked_write([session_id], _update, session_id, persona_id, portrait_id, expected, db)


def _update(session_id, persona_id, portrait_id, expected, db):
    from services.conversation import group_history_service as history, group_operation_service as operations
    try:
        _begin_write(db)
        group = history._require_group(session_id, db)
        member = db.get(SessionPersona, persona_id)
        if member is None or member.session_id != session_id:
            raise GroupSessionNotFound('成员不属于本群或不存在')
        latest = operations._latest(session_id, db)
        selected = operations._observed(group, latest, expected, db)
        if latest and (latest.confirmed_at is not None or selected is None):
            raise SessionKindConflict('只能修改入群前或最新未确认采用候选的立绘')
        if portrait_id is not None and db.query(CharacterPortrait.id).filter_by(
                id=portrait_id, character_id=member.character_id).first() is None:
            raise GroupSessionValidationError('立绘不属于该成员角色或已删除')
        if selected:
            values = _candidate_choices(selected, _members(session_id, db))
            values[str(persona_id)] = portrait_id or 0
            selected.portrait_selections_json = json.dumps(values, sort_keys=True)
            selected.revision += 1
        else:
            member.portrait_base = portrait_id or 0
        group.group_revision += 1
        result = {'session_id': session_id, 'persona_id': persona_id,
                  'portrait_id': portrait_id, 'group_revision': group.group_revision}
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise
