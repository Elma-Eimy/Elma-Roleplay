"""从当前候选审计恢复请求与承接依据，不改变角色感知权限。"""
import json

from core.models import GroupContentItem, GroupDirectorStep
from services.conversation.group_unit_protocol import parse_user_units
from services.conversation.session_access import SessionKindConflict


def _user_plan(item, owner, db):
    step = db.query(GroupDirectorStep).filter_by(candidate_id=item.candidate_id,
        item_id=item.id, stage="user_visibility").one_or_none()
    if step is None:
        return None
    value = json.loads(step.decision_json)
    raw = {"units": [{key: field for key, field in row.items() if key != "unit_index"}
                     for row in value["units"]]}
    members = tuple(row["persona_id"] for row in raw["units"][0]["recipients"])
    return parse_user_units(json.dumps(raw), owner.user_content, members)


def _planning(candidate, db):
    if candidate.call_snapshot_json:
        return json.loads(candidate.call_snapshot_json).get("turn_policy", 0) == 1
    item = db.query(GroupContentItem).filter_by(candidate_id=candidate.id, sequence=0).one_or_none()
    if item is None:
        return False
    step = db.query(GroupDirectorStep).filter_by(item_id=item.id, stage="user_visibility").one_or_none()
    return bool(step and any("meaning" in row for row in json.loads(step.decision_json)["units"]))


def _requests(round_, candidate, persona_id, db, *, pending=False, before_sequence=2**63-1):
    if not _planning(candidate, db):
        return []
    item = db.query(GroupContentItem).filter_by(candidate_id=candidate.id, sequence=0).one_or_none()
    if item is None:
        return []
    plan = _user_plan(item, round_, db)
    if plan is None or not plan.request_targets:
        return []
    fulfilled = set()
    if pending:
        steps = db.query(GroupDirectorStep).filter_by(candidate_id=candidate.id).order_by(GroupDirectorStep.step_index).all()
        for index, step in enumerate(steps[:-1]):
            following = steps[index + 1]
            if (step.stage == "next_action" and step.speaker_persona_id == persona_id
                    and following.stage == "utterance_visibility"):
                utterance = db.get(GroupContentItem, following.item_id)
                if utterance and utterance.sequence < before_sequence:
                    fulfilled.add(json.loads(step.decision_json).get("basis"))
    result = []
    for index, (unit, targets) in enumerate(zip(plan.units, plan.request_targets)):
        reference = f"request:{item.id}:{index}"
        if unit.meaning == "request" and persona_id in targets and reference not in fulfilled:
            result.append({"reference": reference, "source": "user_request", "meaning": "request",
                "content": round_.user_content[unit.start:unit.end]})
    return result


def _sources(session_id, persona_id, round_, candidate, before_sequence, db):
    from services.conversation import group_history_service as history
    from core.config import settings
    limit = (json.loads(candidate.call_snapshot_json)["history_limit"] if candidate.call_snapshot_json else
             min(500, max(1, settings.APP_CONTEXT_HISTORY_LIMIT)))
    rows = history._member_history(session_id, persona_id, round_, candidate, before_sequence, limit, db)
    sources = {}
    for row in rows:
        if row.kind == "user" and row.visible_units and all(unit.meaning == "request" for unit in row.visible_units):
            continue
        sources[f"item:{row.item_id}"] = {"source": "user" if row.kind == "user" else "group_member",
            "speaker_persona_id": row.speaker_persona_id, "content": row.content,
            "meanings": [unit.meaning for unit in row.visible_units if unit.meaning]}
    for request in _requests(round_, candidate, persona_id, db, pending=True, before_sequence=before_sequence):
        sources[request["reference"]] = {key: value for key, value in request.items() if key != "reference"}
    return sources


def _validate_basis(session_id, persona_id, round_, candidate, before_sequence, basis, db):
    if not isinstance(basis, str) or len(basis) > 80:
        raise SessionKindConflict("承接依据无效")
    source = _sources(session_id, persona_id, round_, candidate, before_sequence, db).get(basis)
    if source is None:
        raise SessionKindConflict("承接依据不可见、已回应或不属于当前候选历史")
    return source


def _current_basis(session_id, persona_id, round_, candidate, before_sequence, db):
    step = db.query(GroupDirectorStep).filter_by(candidate_id=candidate.id).order_by(GroupDirectorStep.step_index.desc()).first()
    if step and step.stage == "next_action" and step.speaker_persona_id == persona_id:
        basis = json.loads(step.decision_json).get("basis")
        if basis is not None:
            return _validate_basis(session_id, persona_id, round_, candidate, before_sequence, basis, db)
    return None
