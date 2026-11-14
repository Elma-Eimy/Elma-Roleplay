"""共同群聊的已接受调度与完成标记；调用方持有执行权和写事务。"""
import json

from sqlalchemy import func
from core.models import (GroupDispatch, GroupContentItem, GroupContentUnit,
                         GroupContentVisibility, GroupUnitVisibility, SessionPersona)
from services.conversation.session_access import SessionKindConflict


def _invalid():
    raise SessionKindConflict("候选调度与前缀不一致，请整轮重生成或撤回")


def accept(candidate, action, db):
    if candidate.checkpoint != "next_action" or db.query(GroupDispatch.id).filter_by(
            candidate_id=candidate.id, completed_revision=None).first():
        _invalid()
    sequence = db.query(func.max(GroupContentItem.sequence)).filter_by(candidate_id=candidate.id).scalar() + 1
    db.add(GroupDispatch(candidate_id=candidate.id, session_id=candidate.session_id, sequence=sequence,
        speaker_persona_id=action.speaker_persona_id, response_reference=action.basis, reason_code=action.reason_code,
        expected_revision=candidate.revision, result_revision=candidate.revision + 1))


def pending(candidate, sequence, db):
    decision = db.query(GroupDispatch).filter_by(candidate_id=candidate.id, session_id=candidate.session_id,
        sequence=sequence, completed_revision=None).one_or_none()
    if candidate.checkpoint == "role_generation":
        if decision is None or decision.result_revision > candidate.revision:
            _invalid()
        if json.loads(candidate.call_snapshot_json or '{}').get('reply_target') and decision.response_reference is None:
            _invalid()
    return decision


def complete(candidate, sequence, speaker, db):
    decision = pending(candidate, sequence, db)
    if decision is None or decision.speaker_persona_id != speaker:
        _invalid()
    decision.completed_revision = candidate.revision + 1


def validate_prefix(round_, candidate, db, *, resolve_basis):
    """依据内容、权限和业务调度恢复执行，不读取审计表。"""
    policy = json.loads(candidate.call_snapshot_json or '{}')
    if (candidate.protocol_version != 2 or not policy.get('shared_chat') or candidate.checkpoint not in
            ('user_visibility', 'next_action', 'role_generation', 'finish')):
        _invalid()
    members = {row[0] for row in db.query(SessionPersona.id).filter_by(session_id=candidate.session_id)}
    items = db.query(GroupContentItem).filter_by(candidate_id=candidate.id).order_by(GroupContentItem.sequence).all()
    decisions = db.query(GroupDispatch).filter_by(candidate_id=candidate.id).order_by(GroupDispatch.sequence).all()
    units = db.query(GroupContentUnit).filter_by(candidate_id=candidate.id).order_by(GroupContentUnit.unit_index).all()
    parents = db.query(GroupContentVisibility).join(GroupContentItem,
        GroupContentVisibility.item_id == GroupContentItem.id).filter(GroupContentItem.candidate_id == candidate.id).all()
    grants = db.query(GroupUnitVisibility).join(GroupContentUnit,
        GroupUnitVisibility.unit_id == GroupContentUnit.id).filter(GroupContentUnit.candidate_id == candidate.id).all()
    if (not items or [item.sequence for item in items] != list(range(len(items))) or items[0].kind != 'user'
            or any(item.session_id != candidate.session_id for item in items)):
        _invalid()
    if candidate.checkpoint == 'user_visibility':
        if len(items) != 1 or decisions or units or parents or grants:
            _invalid()
        return None
    by_item = {}
    for unit in units:
        by_item.setdefault(unit.item_id, []).append(unit)
    parent_grants, unit_grants = {}, {}
    for row in parents:
        parent_grants.setdefault(row.item_id, {})[row.recipient_persona_id] = row.decision
    for row in grants:
        unit_grants.setdefault(row.unit_id, {})[row.recipient_persona_id] = row.decision
    audience = {pid: 'visible' for pid in members}
    for index, item in enumerate(items):
        rows = by_item.get(item.id, ())
        if len(rows) != 1 or rows[0].unit_index != 0 or parent_grants.get(item.id) != audience:
            _invalid()
        unit = rows[0]
        if unit_grants.get(unit.id) != audience:
            _invalid()
        if index == 0:
            if unit.kind != 'user' or (unit.source_start, unit.source_end) != (0, len(round_.user_content)):
                _invalid()
        elif item.kind != 'utterance' or unit.kind != 'speech' or unit.text != item.content:
            _invalid()
    expected = len(items) - 1 + (candidate.checkpoint == 'role_generation')
    if [decision.sequence for decision in decisions] != list(range(1, expected + 1)):
        _invalid()
    previous_revision = 0
    for decision in decisions:
        completed = decision.sequence < len(items)
        if (decision.session_id != candidate.session_id or decision.speaker_persona_id not in members
                or decision.reason_code not in ('direct_response', 'follow_up')
                or decision.result_revision != decision.expected_revision + 1
                or decision.expected_revision < previous_revision or decision.result_revision > candidate.revision):
            _invalid()
        if decision.response_reference is not None or policy.get('reply_target'):
            resolve_basis(candidate.session_id, decision.speaker_persona_id, round_, candidate,
                          decision.sequence, decision.response_reference, db)
        if completed:
            if (items[decision.sequence].speaker_persona_id != decision.speaker_persona_id
                    or decision.completed_revision is None or not
                    decision.result_revision < decision.completed_revision <= candidate.revision):
                _invalid()
            previous_revision = decision.completed_revision
        elif decision.completed_revision is not None:
            _invalid()
    return decisions[-1].speaker_persona_id if candidate.checkpoint == 'role_generation' else None
