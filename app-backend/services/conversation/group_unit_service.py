"""单元写入与个人投影；调用方负责父项事务。"""
import json

from sqlalchemy import and_, or_

from core.models import GroupContentItem, GroupContentUnit, GroupUnitVisibility
from services.conversation.group_unit_protocol import ContentUnit, UnitPlan, GroupUnitError, parse_role_units, parse_user_units


def _write_units(item, plan, members, user_content, db):
    if not isinstance(plan, UnitPlan) or len(plan.units) != len(plan.audiences):
        raise GroupUnitError()
    if ((any(unit.meaning for unit in plan.units) and len(plan.request_targets) != len(plan.units))
            or plan.review not in (None, "ok")):
        raise GroupUnitError()
    ids = tuple(sorted(members))
    if item.kind == "user":
        raw = {"units": [{key: value for key, value in row.items() if key != "unit_index"}
                         for row in plan.decision(ids)["units"]]}
        checked = parse_user_units(json.dumps(raw), user_content, ids)
        if checked.units != plan.units:
            raise GroupUnitError()
    else:
        parse_role_units([{"kind": unit.kind, "text": unit.text} for unit in plan.units])
        if "".join(unit.text for unit in plan.units) != item.content:
            raise GroupUnitError()
    for index, (unit, visible) in enumerate(zip(plan.units, plan.audiences)):
        if (not isinstance(visible, tuple) or any(type(pid) is not int for pid in visible)
                or len(set(visible)) != len(visible) or not set(visible) <= members
                or (item.speaker_persona_id is not None and item.speaker_persona_id not in visible)
                or (unit.kind == "thought" and set(visible) != {item.speaker_persona_id})):
            raise GroupUnitError()
        row = GroupContentUnit(item_id=item.id, candidate_id=item.candidate_id, session_id=item.session_id,
            unit_index=index, kind=unit.kind, text=unit.text, source_start=unit.start, source_end=unit.end)
        db.add(row)
        db.flush()
        for pid in ids:
            db.add(GroupUnitVisibility(unit_id=row.id, session_id=item.session_id, recipient_persona_id=pid,
                                      decision="visible" if pid in visible else "hidden"))


def _visible_clause(persona_id):
    return and_(GroupContentUnit.item_id == GroupContentItem.id,
        GroupContentUnit.session_id == GroupContentItem.session_id,
        GroupContentUnit.candidate_id == GroupContentItem.candidate_id,
        GroupUnitVisibility.recipient_persona_id == persona_id, GroupUnitVisibility.decision == "visible",
        or_(GroupContentUnit.kind != "thought", GroupContentItem.speaker_persona_id == persona_id))


def _has_visible_unit(persona_id, db):
    return db.query(GroupContentUnit.id).join(GroupUnitVisibility,
        and_(GroupUnitVisibility.unit_id == GroupContentUnit.id,
             GroupUnitVisibility.session_id == GroupContentUnit.session_id)).filter(_visible_clause(persona_id)).exists()


def _member_projection(item, owner, persona_id, db):
    rows = db.query(GroupContentUnit).join(GroupUnitVisibility,
        and_(GroupUnitVisibility.unit_id == GroupContentUnit.id,
             GroupUnitVisibility.session_id == GroupContentUnit.session_id)).filter(
        GroupContentUnit.item_id == item.id, GroupContentUnit.candidate_id == item.candidate_id,
        GroupContentUnit.session_id == item.session_id, GroupUnitVisibility.recipient_persona_id == persona_id,
        GroupUnitVisibility.decision == "visible",
        or_(GroupContentUnit.kind != "thought", item.speaker_persona_id == persona_id)).order_by(GroupContentUnit.unit_index).all()
    from services.conversation.group_turn_plan import _user_plan
    plan = _user_plan(item, owner, db) if item.kind == "user" else None
    units = []
    passages = []
    previous_index = None
    for row in rows:
        value = owner.user_content[row.source_start:row.source_end] if row.kind == "user" else row.text
        units.append(ContentUnit(row.kind, value, meaning=plan.units[row.unit_index].meaning if plan else None))
        if previous_index is not None and row.unit_index == previous_index + 1:
            passages[-1] += value
        else:
            passages.append(value)
        previous_index = row.unit_index
    return tuple(units), tuple(passages)


def _complete_author_visibility(item, db):
    units = db.query(GroupContentUnit).filter_by(item_id=item.id).all()
    if not units:
        return False
    visible = db.query(GroupUnitVisibility).filter(GroupUnitVisibility.unit_id.in_([unit.id for unit in units]),
        GroupUnitVisibility.recipient_persona_id == item.speaker_persona_id,
        GroupUnitVisibility.decision == "visible").count()
    return visible == len(units)
