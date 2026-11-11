"""操作者的候选与请求快照；读取不派发模型，不改变选择或期限。"""
import json
from contextlib import contextmanager
from sqlalchemy import text
from core.locking import is_session_locked
from core.models import GroupRound, GroupRoundCandidate, GroupRoundOperation, GroupContentItem, SessionPersona
from services.conversation import group_history_service as history, group_operation_service as operations
from services.conversation.group_call_snapshot import restore_group_calls, require_executable_calls
from services.conversation.group_checkpoint_service import validate_prefix, saved_steps
from services.conversation.group_context_service import _member_state
from services.memory.group_member_insights import member_insights
from services.conversation.group_session_service import GroupSessionNotFound
from services.conversation.session_access import group_session_operation, SessionKindConflict


@contextmanager
def _read(session_id, db):
    history._require_group(session_id, db)
    history._require_clean_transaction(db)
    db.rollback()
    db.expire_all()
    db.execute(text("BEGIN"))
    try:
        yield history._require_group(session_id, db)
    finally:
        db.rollback()


def _operation(row):
    return {"operation_id": row.id, "request_id": row.client_request_id, "kind": row.kind,
            "status": row.status, "revision": row.revision, "round_id": row.round_id,
            "candidate_id": row.candidate_id, "call_count": row.call_count, "call_limit": row.call_limit,
            "created_at": row.created_at.isoformat(), "started_at": _iso(row.started_at),
            "deadline_at": _iso(row.deadline_at), "finished_at": _iso(row.finished_at), "error_code": row.error_code}


def _iso(value):
    return value.isoformat() if value else None


def _state(group, db):
    latest = operations._latest(group.id, db)
    selected = db.get(GroupRoundCandidate, latest.selected_candidate_id) if latest else None
    active = db.query(GroupRoundOperation).filter(GroupRoundOperation.session_id == group.id,
        GroupRoundOperation.status.in_(("queued", "running"))).first()
    idle = not active and not is_session_locked(group.id) and (not selected or selected.status != "generating")
    pending = bool(latest and latest.confirmed_at is None)
    successful = bool(pending and db.query(GroupRoundCandidate.id).filter_by(
        round_id=latest.id, status="awaiting_confirmation").first())
    return {"group_revision": group.group_revision,
            "latest": {"round_id": latest.id, "candidate_id": selected.id if selected else None,
                       "candidate_revision": selected.revision if selected else None,
                       "confirmed": latest.confirmed_at is not None} if latest else None,
            "active_operation": _operation(active) if active else None,
            "capabilities": {"can_send": bool(idle and (not pending or selected and selected.status == "awaiting_confirmation")),
                             "can_regenerate": bool(idle and pending), "can_select": bool(idle and successful),
                             "can_discard": bool(idle and pending)}}


def _round(session_id, round_id, db):
    row = db.get(GroupRound, round_id)
    if row is None or row.session_id != session_id:
        raise GroupSessionNotFound("轮次不属于本群或不存在")
    return row


def _round_view(row):
    return {"round_id": row.id, "round_index": row.round_index, "user_content": row.user_content,
            "selected_candidate_id": row.selected_candidate_id, "confirmed": row.confirmed_at is not None,
            "discarded_at": _iso(row.discarded_at), "created_at": _iso(row.created_at)}


def _candidate(row, round_, state, db):
    pending = bool(state["latest"] and state["latest"]["round_id"] == round_.id
                   and not round_.confirmed_at and not round_.discarded_at)
    idle = bool(pending and state["capabilities"]["can_regenerate"])
    resumable = False
    if idle and row.status == "failed":
        try:
            snapshot, maximum = restore_group_calls(row, history._members(row.session_id, db))
            require_executable_calls(snapshot)
            validate_prefix(round_, row, db)
            count = saved_steps(row.id, db)
            resumable = snapshot.shared_chat and count <= maximum and (row.checkpoint == "finish") == (count == maximum)
        except (ValueError, TypeError, KeyError, SessionKindConflict):
            pass
    return {"candidate_id": row.id, "version": row.version, "revision": row.revision,
            "status": row.status, "checkpoint": row.checkpoint, "protocol_version": row.protocol_version,
            "selected": row.id == round_.selected_candidate_id, "finish_reason": row.finish_reason,
            "error_code": row.error_code, "can_select": bool(idle and row.status == "awaiting_confirmation"),
            "can_resume": bool(resumable)}


@group_session_operation
def get_group_state(session_id, db):
    with _read(session_id, db) as group:
        return _state(group, db)


@group_session_operation
def compile_member_prompt(session_id, persona_id, db):
    """复用生成装配入口预览当前所选候选，不派发生成或改变检查点。"""
    from services.conversation.group_context_service import build_member_context
    from services.conversation.prompt_token_estimator import estimate_prompt_tokens
    with _read(session_id, db) as group:
        latest = operations._latest(session_id, db)
        if latest is None or latest.selected_candidate_id is None:
            raise history.GroupSessionValidationError('尚无群聊轮次，请发送首条消息后查看')
        candidate = db.get(GroupRoundCandidate, latest.selected_candidate_id)
        cid, revision = candidate.id, candidate.revision
        policy = json.loads(candidate.call_snapshot_json or '{}')
        parameters = next((json.dumps(row['parameters']) for row in policy.get('members', [])
                           if row['persona_id'] == persona_id), None)
        limit = policy.get('history_limit')
    context = build_member_context(session_id, persona_id, cid, revision, db,
        generation_parameters_json=parameters, history_limit=limit, preview=True)
    messages = json.loads(context.messages_json)
    return {'messages': messages, 'token_estimate': estimate_prompt_tokens(messages),
            'candidate_id': cid, 'revision': revision}


@group_session_operation
def require_shared_resume(session_id, candidate_id, db):
    """冻结旧裁决任务，不把原候选静默改成全文共享。"""
    with _read(session_id, db):
        candidate = db.get(GroupRoundCandidate, candidate_id)
        if candidate is None or candidate.session_id != session_id:
            raise GroupSessionNotFound('候选不属于本群或不存在')
        if not json.loads(candidate.call_snapshot_json or '{}').get('shared_chat', False):
            raise SessionKindConflict('旧候选的裁决执行已冻结，已保存内容保留；请重新生成共同群聊候选')


@group_session_operation
def get_group_request(session_id, client_request_id, db):
    with _read(session_id, db) as group:
        operation = db.query(GroupRoundOperation).filter_by(session_id=session_id, client_request_id=client_request_id).first()
        if operation is None:
            raise GroupSessionNotFound("请求尚未接受或不存在")
        round_ = _round(session_id, operation.round_id, db)
        candidate = db.get(GroupRoundCandidate, operation.candidate_id)
        state = _state(group, db)
        return {**_operation(operation), "accepted": json.loads(operation.accepted_result_json),
                "round": _round_view(round_), "candidate": _candidate(candidate, round_, state, db), "current": state}


@group_session_operation
def list_group_candidates(session_id, round_id, db, *, limit=20, offset=0):
    history._positive(limit, "分页条数")
    history._positive(offset, "分页位置", 0)
    if limit > 100:
        raise history.GroupSessionValidationError("分页条数最多 100")
    with _read(session_id, db) as group:
        round_ = _round(session_id, round_id, db)
        state = _state(group, db)
        query = db.query(GroupRoundCandidate).filter_by(round_id=round_id, session_id=session_id)
        total = query.count()
        rows = query.order_by(GroupRoundCandidate.version.desc()).offset(offset).limit(limit).all()
        return {"round": _round_view(round_), "candidates": [_candidate(row, round_, state, db) for row in rows],
                "current": state, "total": total, "limit": limit, "offset": offset, "has_more": offset+len(rows) < total}


@group_session_operation
def get_group_candidate(session_id, round_id, candidate_id, db):
    with _read(session_id, db) as group:
        round_ = _round(session_id, round_id, db)
        candidate = db.get(GroupRoundCandidate, candidate_id)
        if candidate is None or candidate.session_id != session_id or candidate.round_id != round_id:
            raise GroupSessionNotFound("候选不属于本群本轮或不存在")
        state = _state(group, db)
        members = db.query(SessionPersona).filter_by(session_id=session_id).order_by(SessionPersona.member_slot).all()
        names = {member.id: member.character.name for member in members}
        items = db.query(GroupContentItem).filter_by(candidate_id=candidate_id, kind="utterance").order_by(GroupContentItem.sequence).all()
        preview = []
        from services.media.group_portraits import _candidate_portraits
        portraits = {row['persona_id']: row for row in _candidate_portraits(session_id, candidate, db)}
        for member in members:
            role_state, persona = _member_state(member, group, round_, candidate, 2**63-1, db)
            insights = member_insights(member.id, round_, candidate, db)
            preview.append({"persona_id": member.id, "role_state": role_state,
                            "affection_score": persona.affection_score, "current_mood": persona.current_mood,
                            "cognition_state": persona.cognition_state,
                            "portrait": portraits[member.id],
                            "insights": [{"kind": row["kind"], "content": row["content"],
                                "target_persona_id": row.get("persona_id"), "target_name": row.get("name")}
                                for row in insights]})
        return {"round": _round_view(round_), "candidate": _candidate(candidate, round_, state, db), "current": state,
                "utterances": [{"item_id": item.id, "sequence": item.sequence,
                    "speaker_persona_id": item.speaker_persona_id, "speaker_name": names[item.speaker_persona_id],
                    "content": item.content, "created_at": _iso(item.created_at)} for item in items],
                "state_preview": {"candidate_id": candidate_id, "members": preview}}


@group_session_operation
def get_group_portraits(session_id, db):
    from services.media.group_portraits import _current_portraits
    with _read(session_id, db) as group:
        state = _state(group, db)
        latest = state['latest']
        return {'session_id': session_id, 'current': state, 'members': _current_portraits(session_id, db),
                'can_update': bool(state['capabilities']['can_send'] if latest is None else
                                   state['capabilities']['can_regenerate'] and latest['candidate_id'] is not None)}
