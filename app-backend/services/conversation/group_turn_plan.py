"""读取可见来源和已冻结回应目标，旧候选通过兼容层读取审计。"""
import json

from core.models import GroupContentItem
from services.conversation.group_legacy_protocol import _user_plan, _planning, _pending_requests, _current_basis as _legacy_basis
from services.conversation import group_dispatch_service as dispatches
from services.conversation.session_access import SessionKindConflict


def _sources(session_id, persona_id, round_, candidate, before_sequence, db):
    from services.conversation import group_history_service as history
    from core.config import settings
    limit = (json.loads(candidate.call_snapshot_json)["history_limit"] if candidate.call_snapshot_json else
             min(500, max(1, settings.APP_CONTEXT_HISTORY_LIMIT)))
    reply_target = json.loads(candidate.call_snapshot_json or '{}').get('reply_target', False)
    if reply_target:
        current_count = db.query(GroupContentItem.id).filter_by(candidate_id=candidate.id).filter(
            GroupContentItem.sequence < before_sequence).count()
        limit = max(limit, current_count)
    rows = history._member_history(session_id, persona_id, round_, candidate, before_sequence, limit, db)
    sources = {}
    for row in rows:
        if row.kind == "user" and row.visible_units and all(unit.meaning == "request" for unit in row.visible_units):
            continue
        source = "user" if row.kind == "user" else "self" if row.speaker_persona_id == persona_id else "group_member"
        if reply_target and source == 'self':
            continue
        entry = {"source": source, "speaker_persona_id": row.speaker_persona_id,
                 "meanings": [unit.meaning for unit in row.visible_units if unit.meaning]}
        if reply_target:
            entry['turn'] = 'current' if row.round_id == round_.id else 'previous'
        if row.kind != "user" and row.visible_units:
            entry["units"] = [{"kind": unit.kind, "text": unit.text} for unit in row.visible_units]
        else:
            entry["content"] = row.content
        sources[f"item:{row.item_id}"] = entry
    for request in _pending_requests(round_, candidate, persona_id, before_sequence, db):
        sources[request["reference"]] = {key: value for key, value in request.items() if key != "reference"}
    return sources


def _validate_basis(session_id, persona_id, round_, candidate, before_sequence, basis, db):
    if not isinstance(basis, str) or len(basis) > 80:
        raise SessionKindConflict("承接依据无效")
    source = _sources(session_id, persona_id, round_, candidate, before_sequence, db).get(basis)
    if source is None:
        raise SessionKindConflict("承接依据不可见、已回应或不属于当前候选历史")
    return source


def _current_basis(session_id, persona_id, round_, candidate, before_sequence, db, *, preview=False):
    if candidate.dispatch_version == 1:
        decision = dispatches.pending(candidate, before_sequence, db)
        if decision is not None and decision.speaker_persona_id != persona_id:
            if preview:
                return None
            raise SessionKindConflict("发言成员不属于当前业务调度")
        if decision is not None and decision.response_reference is not None:
            return _validate_basis(session_id, persona_id, round_, candidate, before_sequence, decision.response_reference, db)
        return None
    return _legacy_basis(session_id, persona_id, round_, candidate, before_sequence, db)
