"""旧候选的裁决审计与前缀读取，仅用于历史兼容。"""
import json

from core.models import (GroupContentItem, GroupDirectorStep, GroupContentUnit, GroupUnitVisibility, GroupContentVisibility)
from .unit_protocol import (parse_user_units, parse_role_units, parse_unit_visibility, ContentUnit, UnitPlan)
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
    if candidate.dispatch_version == 1:
        return 0
    if candidate.call_snapshot_json:
        return json.loads(candidate.call_snapshot_json).get("turn_policy", 0)
    item = db.query(GroupContentItem).filter_by(candidate_id=candidate.id, sequence=0).one_or_none()
    if item is None:
        return False
    step = db.query(GroupDirectorStep).filter_by(item_id=item.id, stage="user_visibility").one_or_none()
    return bool(step and any("meaning" in row for row in json.loads(step.decision_json)["units"]))


def _pending_requests(round_, candidate, persona_id, before_sequence, db):
    if not _planning(candidate, db):
        return []
    item = db.query(GroupContentItem).filter_by(candidate_id=candidate.id, sequence=0).one_or_none()
    if item is None:
        return []
    plan = _user_plan(item, round_, db)
    if plan is None or not plan.request_targets:
        return []
    fulfilled = set()
    steps = db.query(GroupDirectorStep).filter_by(candidate_id=candidate.id).order_by(GroupDirectorStep.step_index).all()
    for index, step in enumerate(steps[:-1]):
        following = steps[index + 1]
        if (step.stage == "next_action" and step.speaker_persona_id == persona_id
                and following.stage == "utterance_visibility"):
            utterance = db.get(GroupContentItem, following.item_id)
            outcome = json.loads(following.decision_json).get("request_result")
            if utterance and utterance.sequence < before_sequence and outcome != "pending":
                fulfilled.add(json.loads(step.decision_json).get("basis"))
    result = []
    for index, (unit, targets) in enumerate(zip(plan.units, plan.request_targets)):
        reference = f"request:{item.id}:{index}"
        if unit.meaning == "request" and persona_id in targets and reference not in fulfilled:
            result.append({"reference": reference, "source": "user_request", "meaning": "request",
                **({"reply_mode": unit.reply_mode} if unit.reply_mode else {}),
                "content": round_.user_content[unit.start:unit.end]})
    return result



def validate_prefix(round_, candidate, db):
    """校验整个持久前缀，不以当前 revision 大于旧审计为重复调度依据。"""
    def invalid():
        raise SessionKindConflict("候选检查点与前缀不一致，请整轮重生成或撤回")
    from .turn_plan import _validate_basis
    from . import history_service as history
    turn_policy = _planning(candidate, db)

    def action_valid(step, before):
        value = json.loads(step.decision_json)
        base = {"action": "speak", "speaker_persona_id": step.speaker_persona_id, "reason_code": step.reason_code}
        if value != {**base, **({"basis": value["basis"]} if "basis" in value else {})}:
            invalid()
        if "basis" in value or turn_policy or json.loads(candidate.call_snapshot_json or '{}').get('reply_target'):
            return _validate_basis(candidate.session_id, step.speaker_persona_id, round_, candidate, before, value.get("basis"), db)
    if candidate.protocol_version != 2 or candidate.checkpoint not in (
            "user_visibility", "next_action", "role_generation", "finish"):
        invalid()
    members = history._members(candidate.session_id, db)
    items = db.query(GroupContentItem).filter_by(candidate_id=candidate.id).order_by(GroupContentItem.sequence).all()
    steps = db.query(GroupDirectorStep).filter_by(candidate_id=candidate.id).order_by(GroupDirectorStep.step_index).all()
    if not items or [i.sequence for i in items] != list(range(len(items))) or items[0].kind != "user":
        invalid()
    if candidate.checkpoint == "user_visibility":
        if len(items) != 1 or steps or db.query(GroupContentUnit).filter_by(candidate_id=candidate.id).count() or db.query(
                GroupContentVisibility).filter_by(item_id=items[0].id).count():
            invalid()
        return None
    if [s.step_index for s in steps] != list(range(1, len(steps) + 1)):
        invalid()
    expected_stages = ["user_visibility"]
    for _ in items[1:]:
        expected_stages.extend(("next_action", "utterance_visibility"))
    if candidate.checkpoint == "role_generation":
        expected_stages.append("next_action")
    if [s.stage for s in steps] != expected_stages:
        invalid()
    for index, step in enumerate(steps):
        if (step.policy_version != 2 or step.result_revision > candidate.revision
                or (index and step.expected_revision < steps[index-1].result_revision)):
            invalid()
        if step.stage == "next_action" and (step.reason_code not in ("direct_response", "follow_up")
                or step.speaker_persona_id not in members):
            invalid()
    for index, item in enumerate(items):
        stage = steps[0 if index == 0 else 2 * index]
        if (stage.item_id != item.id or item.kind != ("user" if index == 0 else "utterance")
                or stage.speaker_persona_id != item.speaker_persona_id):
            invalid()
        rows = db.query(GroupContentUnit).filter_by(item_id=item.id).order_by(GroupContentUnit.unit_index).all()
        if not rows or [row.unit_index for row in rows] != list(range(len(rows))):
            invalid()
        audiences = []
        for row in rows:
            grants = dict(db.query(GroupUnitVisibility.recipient_persona_id, GroupUnitVisibility.decision).filter_by(unit_id=row.id))
            if set(grants) != members:
                invalid()
            visible = tuple(sorted(pid for pid, decision in grants.items() if decision == "visible"))
            if item.kind != "user" and (item.speaker_persona_id not in visible
                    or row.kind == "thought" and set(visible) != {item.speaker_persona_id}):
                invalid()
            audiences.append(visible)
        stage_value = json.loads(stage.decision_json)
        plan = UnitPlan(tuple(ContentUnit(row.kind, row.text, row.source_start, row.source_end) for row in rows), tuple(audiences))
        if item.kind == "user":
            try:
                plan = parse_user_units(json.dumps({"units": [{k: v for k, v in row.items() if k != "unit_index"}
                    for row in stage_value["units"]]}), round_.user_content, tuple(sorted(members)),
                    require_meaning=bool(turn_policy),
                    require_reply_mode=(turn_policy >= 2 if candidate.call_snapshot_json else None))
                if ([(unit.start, unit.end) for unit in plan.units] != [(row.source_start, row.source_end) for row in rows]
                        or plan.audiences != tuple(audiences) or any(row.kind != "user" for row in rows)):
                    invalid()
            except ValueError:
                invalid()
        else:
            try:
                checked_units = parse_role_units([{"kind": row.kind, "text": row.text} for row in rows])
                basis = action_valid(steps[2*index-1], item.sequence) or {}
                plan = parse_unit_visibility(json.dumps(stage_value), checked_units, tuple(sorted(members)),
                    item.speaker_persona_id, require_review=bool(turn_policy), reply_mode=basis.get("reply_mode"))
                if plan.audiences != tuple(audiences):
                    invalid()
            except ValueError:
                invalid()
            if "".join(row.text for row in rows) != item.content or steps[2*index-1].speaker_persona_id != item.speaker_persona_id:
                invalid()
        if stage_value != plan.decision(members):
            invalid()
        parents = dict(db.query(GroupContentVisibility.recipient_persona_id, GroupContentVisibility.decision).filter_by(item_id=item.id))
        common = set.intersection(*(set(audience) for audience in audiences))
        if item.speaker_persona_id is not None:
            common.add(item.speaker_persona_id)
        if parents != {pid: "visible" if pid in common else "hidden" for pid in members}:
            invalid()
    if candidate.checkpoint == "role_generation":
        step = steps[-1]
        payload = json.loads(step.decision_json)
        if step.speaker_persona_id not in members:
            invalid()
        action_valid(step, len(items))
        from .turn_plan import _sources
        if not _sources(candidate.session_id, step.speaker_persona_id, round_, candidate, 2**63-1, db):
            invalid()
        return step.speaker_persona_id
    return None



def _current_basis(session_id, persona_id, round_, candidate, before_sequence, db):
    from .turn_plan import _validate_basis
    step = db.query(GroupDirectorStep).filter_by(candidate_id=candidate.id).order_by(GroupDirectorStep.step_index.desc()).first()
    if step and step.stage == "next_action" and step.speaker_persona_id == persona_id:
        basis = json.loads(step.decision_json).get("basis")
        if basis is not None:
            return _validate_basis(session_id, persona_id, round_, candidate, before_sequence, basis, db)
    return None
