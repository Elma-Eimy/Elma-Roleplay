"""操作者轮次状态与请求回执投影；不接管事务、不修改候选。"""
from core.locking import is_session_locked
from core.models import GroupDispatch, GroupRound, GroupRoundCandidate, GroupRoundOperation
from services.conversation.session_access import group_session_operation
from .guards import require_group


@group_session_operation
def latest_round(session_id, db):
    require_group(session_id, db)
    return db.query(GroupRound).filter_by(session_id=session_id, discarded_at=None).order_by(
        GroupRound.round_index.desc()).first()


def operation_view(row):
    return {"operation_id": row.id, "request_id": row.client_request_id, "kind": row.kind,
            "status": row.status, "revision": row.revision, "round_id": row.round_id,
            "candidate_id": row.candidate_id, "call_count": row.call_count, "call_limit": row.call_limit,
            "created_at": row.created_at.isoformat(), "started_at": iso_time(row.started_at),
            "deadline_at": iso_time(row.deadline_at), "finished_at": iso_time(row.finished_at), "error_code": row.error_code}


def iso_time(value):
    return value.isoformat() if value else None


def _active_operation_view(operation, db):
    view = operation_view(operation)
    speaker_id = None
    if operation.status == "running":
        speaker_id = db.query(GroupDispatch.speaker_persona_id).join(
            GroupRoundCandidate, GroupDispatch.candidate_id == GroupRoundCandidate.id,
        ).filter(
            GroupDispatch.session_id == operation.session_id,
            GroupDispatch.candidate_id == operation.candidate_id,
            GroupDispatch.completed_revision.is_(None),
            GroupDispatch.result_revision <= GroupRoundCandidate.revision,
            GroupRoundCandidate.dispatch_version == 1,
            GroupRoundCandidate.status == "generating",
            GroupRoundCandidate.checkpoint == "role_generation",
        ).scalar()
    return {**view, "speaking_persona_id": speaker_id}


def group_state(group, db):
    latest = latest_round(group.id, db)
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
            "active_operation": _active_operation_view(active, db) if active else None,
            "capabilities": {"can_send": bool(idle and (not pending or selected and selected.status == "awaiting_confirmation")),
                             "can_regenerate": bool(idle and pending), "can_select": bool(idle and successful),
                             "can_discard": bool(idle and pending)}}
