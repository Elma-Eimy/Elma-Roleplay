"""在同一读快照中装配个人历史、自己的候选状态和模型参数。"""
import json
from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy import and_, func, text

from services.memory.group_member_insights import member_insights
from services.memory.group_memory_index import SemanticQuery, unified_memories
from services.memory.group_memory_recall import recall_inherited_memories
from core.config import settings
from core.models import GroupContentItem, GroupContentVisibility, GroupRound, GroupRoundCandidate, SessionPersona
from services.conversation.group_unit_service import _complete_author_visibility
from services.conversation import group_history_service as history
from services.conversation.chat_engine import _prepare_generation_kwargs
from services.conversation.prompt_compiler import build_group_messages
from services.conversation.role_state_schema import decode_state, merge_state
from services.conversation.session_access import group_session_operation
from services.conversation.group_session_service import GroupSessionValidationError


@dataclass(frozen=True)
class GroupMemberContext:
    candidate_id: int
    revision: int
    next_sequence: int
    speaker_name: str
    state_json: str
    messages_json: str
    generation_json: str
    protocol_version: int = 1
    response_request: dict | None = None
    experience_evidence_json: str | None = None
    current_mood: str | None = None


def _member_state(persona, group, round_, candidate, before_sequence, db):
    if persona.group_origin is None:
        raise GroupSessionValidationError("群聊成员缺少人格起点")
    initial = json.loads(persona.group_origin.initial_state_json)
    state = initial["role_state"]
    if group.shared_setting:
        # 共同设定可长达 20000 字，是背景文本，不能塞入限长 300 字的 scene。
        state.pop("scene", None)
    affection, mood = initial["affection_score"] or 0, initial["current_mood"]
    rows = history._content_query(group.id, round_, candidate, before_sequence, db).join(
        GroupContentVisibility, and_(GroupContentVisibility.item_id == GroupContentItem.id,
            GroupContentVisibility.recipient_persona_id == persona.id,
            GroupContentVisibility.decision == "visible")).filter(
        GroupContentItem.speaker_persona_id == persona.id).order_by(
        GroupRound.round_index, GroupContentItem.sequence).all()
    for item, _ in rows:
        if db.get(GroupRoundCandidate, item.candidate_id).protocol_version == 2 and not _complete_author_visibility(item, db):
            continue
        if item.role_state_patch:
            state = merge_state(state, decode_state(item.role_state_patch))
        affection += item.affection_change or 0
        if item.emotion_tag:
            mood = item.emotion_tag
    return state, SimpleNamespace(parent_persona_id=None, cognition_state=initial["cognition_state"],
        affection_score=affection, current_mood=mood,
        current_scenario_override=group.shared_setting or initial["current_scenario_override"])


def _member_memories(persona_id, round_, candidate, rows, requests, basis, db, distances):
    # 持久候选沿用接受时的策略；内部 v2 原型没有调用快照。
    if candidate.protocol_version != 2:
        return []
    policy = json.loads(candidate.call_snapshot_json) if candidate.call_snapshot_json else {}
    if candidate.call_snapshot_json and not policy.get("inherited_recall", False):
        return []
    if basis:
        passages = [unit["text"] for unit in basis["units"]] if "units" in basis else [basis["content"]]
    else:
        passages = [request["content"] for request in requests]
        for row in rows[-3:]:
            if row.round_id == round_.id:
                parts = row.visible_passages if row.kind == "user" else tuple(unit.text for unit in row.visible_units)
                passages.extend(parts or (row.content,))
    if "group_card_limit" in policy:
        return unified_memories(persona_id, round_.round_index, policy["group_card_limit"], passages, db, distances,
                                facts=policy.get('fact_recall', False))
    return recall_inherited_memories(persona_id, passages, db)


@group_session_operation
def build_member_context(session_id, persona_id, candidate_id, expected_revision, db, *, model=None,
                         generation_parameters_json=None, history_limit=None, scope=None):
    def read(distances):
        return _read_context(session_id, persona_id, candidate_id, expected_revision, db, model,
                             generation_parameters_json, history_limit, scope, distances)
    context = read(None)
    if isinstance(context, SemanticQuery):
        # Embedding 期间不持有数据库事务，重读时复核候选 revision 与成员归属。
        return read(context.distances())
    return context


def _read_context(session_id, persona_id, candidate_id, expected_revision, db, model,
                  generation_parameters_json, history_limit, scope, distances):
    history._require_group(session_id, db)
    history._require_clean_transaction(db)
    history._positive(persona_id, "成员")
    db.rollback()
    db.expire_all()
    db.execute(text("BEGIN"))
    try:
        round_, candidate = history._writable(session_id, candidate_id, expected_revision, db, scope=scope)
        persona = db.get(SessionPersona, persona_id)
        if persona is None or persona.session_id != session_id:
            raise GroupSessionValidationError("发言成员不属于本群")
        group = history._require_group(session_id, db)
        last_sequence = db.query(func.max(GroupContentItem.sequence)).filter_by(candidate_id=candidate_id).scalar()
        if last_sequence is None:
            raise GroupSessionValidationError("候选缺少用户内容项")
        before = last_sequence + 1
        rows = history._member_history(session_id, persona_id, round_, candidate, before,
            min(500, max(1, settings.APP_CONTEXT_HISTORY_LIMIT if history_limit is None else history_limit)), db)
        from services.conversation.group_turn_plan import _pending_requests, _current_basis
        requests = _pending_requests(round_, candidate, persona_id, before, db)
        basis = _current_basis(session_id, persona_id, round_, candidate, before, db)
        if not rows and not requests:
            raise GroupSessionValidationError("没有可见内容，不能生成角色发言")
        state, state_persona = _member_state(persona, group, round_, candidate, before, db)
        speaker_ids = {row.speaker_persona_id for row in rows if row.speaker_persona_id is not None}
        names = {member.id: member.character.name for member in db.query(SessionPersona).filter(
            SessionPersona.id.in_(speaker_ids)).all()}
        memories = _member_memories(persona.id, round_, candidate, rows, requests, basis, db, distances)
        if isinstance(memories, SemanticQuery):
            return memories
        from services.conversation.group_session_service import public_greetings
        greetings = public_greetings(group)
        policy = json.loads(candidate.call_snapshot_json or '{}')
        evidence = None
        if candidate.protocol_version == 2 and policy.get('experience_guard'):
            from services.conversation.group_experience_guard import experience_evidence
            evidence = experience_evidence(persona_id, rows, memories, requests)
            evidence["sources"].extend({"ref": f"greeting:{entry['persona_id']}", "kind": "opening",
                "speaker_id": entry["persona_id"], "text": entry["content"]} for entry in greetings)
        messages = build_group_messages(persona.character, state_persona, rows, names,
            persona_id=persona_id, user_nickname=group.user_nickname,
            shared_setting=group.shared_setting, greetings=greetings, current_role_state=state, protocol_version=candidate.protocol_version,
            current_round_id=round_.id, turn_requests=requests, response_basis=basis, inherited_memories=memories,
            insights=member_insights(persona.id, round_, candidate, db), experience_evidence=evidence)
        # 所有 ORM 读取与参数准备在事务内完成，外部调用仅使用序列化快照。
        kwargs = (_prepare_generation_kwargs(persona.character, messages, model=model) if generation_parameters_json is None
                  else {**json.loads(generation_parameters_json), "messages": messages})
        return GroupMemberContext(candidate.id, candidate.revision, before, persona.character.name,
            json.dumps(state, ensure_ascii=False), json.dumps(messages, ensure_ascii=False), json.dumps(kwargs, ensure_ascii=False), candidate.protocol_version,
            basis if basis and basis.get("reply_mode") else None,
            json.dumps(evidence, ensure_ascii=False) if evidence is not None else None, state_persona.current_mood)
    finally:
        db.rollback()
