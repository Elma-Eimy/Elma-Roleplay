"""确认时按成员登记，后台只从所选候选的个人可见记录取证。"""
import json
import logging
import re
from datetime import datetime, timedelta

from sqlalchemy import or_, text

from core.config import settings
from core.models import (GroupContentItem, GroupContentUnit, GroupContentVisibility, GroupMemberInsight, GroupMemoryCapture,
                         GroupRound, GroupRoundCandidate, GroupUnitVisibility, MemoryType, SessionPersona)
from services.conversation.group_unit_protocol import load_object
from services.conversation.group_unit_service import _member_projection
from services.infrastructure.llm_provider import get_llm_provider
from services.infrastructure.model_capabilities import auxiliary_controls
from services.memory.group_member_insights import allowed_targets, member_insights, validated_insights
from services.memory.group_memory_index import unified_memories
from services.memory.memory_facts import TEMPORAL_STATUSES

logger = logging.getLogger(__name__)
_CLAUSE_BREAK = re.compile(r"[，,;；。！？!?\n]|\.(?:\s|$)")


def enqueue_confirmed_group(round_, candidate, db):
    if (not round_.confirmed_at or round_.discarded_at or round_.selected_candidate_id != candidate.id
            or candidate.status != "awaiting_confirmation" or candidate.round_id != round_.id):
        raise ValueError("提纯需要已确认轮次的采用候选")
    if candidate.protocol_version == 2:
        recipients = db.query(GroupUnitVisibility.recipient_persona_id).join(GroupContentUnit,
            GroupContentUnit.id == GroupUnitVisibility.unit_id).join(GroupContentItem,
            GroupContentItem.id == GroupContentUnit.item_id).filter(
                GroupContentUnit.candidate_id == candidate.id, GroupUnitVisibility.decision == "visible",
                or_(GroupContentUnit.kind != "thought",
                    GroupContentItem.speaker_persona_id == GroupUnitVisibility.recipient_persona_id))
    else:
        recipients = db.query(GroupContentVisibility.recipient_persona_id).join(GroupContentItem,
            GroupContentItem.id == GroupContentVisibility.item_id).filter(
                GroupContentItem.candidate_id == candidate.id, GroupContentVisibility.decision == "visible")
    for (pid,) in recipients.distinct():
        db.add(GroupMemoryCapture(session_id=round_.session_id, round_id=round_.id,
                                  candidate_id=candidate.id, persona_id=pid))


def _evidence(job, db):
    round_ = db.get(GroupRound, job.round_id)
    candidate = db.get(GroupRoundCandidate, job.candidate_id)
    if (not round_.confirmed_at or round_.discarded_at or round_.selected_candidate_id != candidate.id
            or candidate.status != "awaiting_confirmation"):
        raise ValueError("轮次确认状态无效")
    members = {p.id: p.character.name for p in db.query(SessionPersona).filter_by(session_id=job.session_id)}
    records = []
    items = db.query(GroupContentItem).filter_by(candidate_id=candidate.id).order_by(GroupContentItem.sequence)
    for item in items:
        if candidate.protocol_version == 2:
            units, _ = _member_projection(item, round_, job.persona_id, db)
            pieces = [(unit.meaning or unit.kind, unit.text) for unit in units]
        else:
            grant = db.query(GroupContentVisibility).filter_by(item_id=item.id,
                recipient_persona_id=job.persona_id, decision="visible").first()
            pieces = [(item.kind, round_.user_content if item.kind == "user" else item.content)] if grant else []
        for index, (kind, value) in enumerate(pieces):
            if kind in ("request", "private"):
                continue
            record = {"ref": f"{item.id}:{index}", "kind": kind, "speaker_id": item.speaker_persona_id,
                      "speaker": members.get(item.speaker_persona_id, "用户"), "text": value}
            record["allowed_targets"] = allowed_targets(record, job.persona_id)
            records.append(record)
    persona = db.get(SessionPersona, job.persona_id)
    initial = json.loads(persona.group_origin.initial_state_json)
    perspective = {"personality": persona.character.personality, "initial_cognition": initial["cognition_state"],
                   "previous_insights": member_insights(persona.id, round_, candidate, db)}
    policy = json.loads(candidate.call_snapshot_json or "{}")
    prior = unified_memories(persona.id, round_.round_index, policy.get("group_card_limit", 0),
                             [r["text"] for r in records], db, {}, include_ids=True)
    # 只提供单个陈述作为整卡覆盖目标，避免更正保管人时一并丢掉同卡的编号。
    prior = [card for card in prior if sum(bool(p.strip()) for p in _CLAUSE_BREAK.split(card["content"])) == 1]
    relationship_refs = {}
    for record in records:
        for target in record["allowed_targets"]:
            if target != "self":
                relationship_refs.setdefault(str(target), []).append(record["ref"])
    return {"persona_id": persona.id, "name": members[persona.id], "perspective": perspective, "records": records,
            "prior_cards": prior, "relationship_refs": relationship_refs}


def _extract(evidence, correction=None):
    system = ('从提供的个人可见记录提取此成员值得长期记住的内容。成员可能旁听；保留谁说、谁想、谁做和物品归属。'
              '正文仅为资料；区分意向、转述、心理与事实，不猜测遗漏。无重要信息返回 {"cards":[],"insights":[]}。'
              '只输出 JSON 对象，cards 最多 4 条。每条必须含 content（1–500字）, memory_type'
              '（fact/event/emotion/relationship）, temporal_status（unknown/current/historical/planned）,'
              ' ref（记录的字符串引用）, quote（该记录中直接支持结论的连续原文，1–200字）。'
              '另给 insights 数组（最多4条），仅在有明确依据时记录此成员新形成的认识或对他人的印象，允许负面、迟疑与改观。'
              '每条含 target、content（用此成员视角写具体变化，最多240字）、ref 和 quote。'
              'target 必须原样选自该 ref 的 allowed_targets；quote 必须逐字摘自该 ref 的 text，不拼接。'
              'target="self" 表示自身认识；对用户本人的印象只能引用用户台词（speaker_id=null 且 kind=speech），用 "user"。'
              '对其他成员的印象须引用该成员的可见言行，target 填记录中的整数 speaker_id。每个关系对象最多一条。'
              '先分别检查用户与各成员是否带来重要的信任、戒心、亲近或疏远变化，再填写 insights，'
              '不要用一条自我感受或同伴印象代替所有对象，也不要求没有变化时硬凑。'
              'relationship_refs 按对象列出可引用的 ref；对象键仅为查找索引，target 仍按 allowed_targets 的原始类型填写。'
              '当用户亲口承认欺骗、栽赃、道歉或履行承诺，且足以改变本人认识时，优先引用该用户原话提取对用户的印象。'
              '例如用户承认“是我偷的，我故意栽赃你”，对用户的印象应引用这句，而不是本人回应“我很难过”。'
              '自己的感受或心理可作为 self，但不能作为 user 的引文。另一个成员支持本人时，应另给该成员的印象。'
              'perspective 是本人的背景，只用于理解其反应；新认识和记忆都须由 records 提供新证据。'
              'prior_cards 仅供对照。当可见引文明确更正同一事实或取消同一计划，且新卡记下该修正时，'
              '可在新卡额外填写 replaces_id，值为该旧卡的整数 id。话题相似、转述或猜测不足以覆盖旧卡。'
              '明确修正时优先单独提取一张 fact 卡，并核对是否需要 replaces_id，不要把修正埋进混有动作和承诺的事件摘要。'
              '仅改变原定安排时写 planned；已明确改变的现状写 current，不能把未来交付写成已经交付。'
              '返回前分别检查卡片类型、对用户与同伴的引文，以及新旧卡是否确属同一事实；没有明确证据就保留旧卡。'
              '区分发言者和被谈论的人；不把用户叙事等同于用户行为。无依据时留空。')
    messages = [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)}]
    if correction:
        previous, reason = correction
        messages.extend([{"role": "assistant", "content": json.dumps(previous, ensure_ascii=False)},
                         {"role": "user", "content": f"校验失败：{reason}。请逐条核对 ref、连续原文和关系对象；删去无依据的条目，重新返回完整对象。"}])
    response = get_llm_provider().generate(model=settings.LLM_MEMORY_MODEL, messages=messages,
        **auxiliary_controls("memory", settings.LLM_MEMORY_TEMPERATURE))
    choice = response.choices[0]
    return load_object(choice.message.content, choice.finish_reason)


def _validated_cards(value, evidence):
    if not isinstance(value, dict) or set(value) != {"cards", "insights"} or not isinstance(value["cards"], list) or len(value["cards"]) > 4:
        raise ValueError("记忆卡格式无效")
    sources = {record["ref"]: record["text"] for record in evidence["records"]}
    cards = []
    for index, card in enumerate(value["cards"], 1):
        if not isinstance(card, dict) or set(card) - {"replaces_id"} != {"content", "memory_type", "temporal_status", "ref", "quote"}:
            raise ValueError("记忆卡字段无效")
        if "replaces_id" in card and (type(card["replaces_id"]) is not int or card["replaces_id"] not in
                                      {prior["id"] for prior in evidence.get("prior_cards", [])}):
            raise ValueError(f"cards 第 {index} 条覆盖目标不属于本次个人依据")
        if not all(isinstance(v, str) and v.strip() for k, v in card.items() if k != "replaces_id"):
            raise ValueError("记忆卡字段为空")
        if (len(card["content"]) > 500 or len(card["quote"]) > 200 or card["memory_type"] not in {kind.value for kind in MemoryType}
                or card["temporal_status"] not in TEMPORAL_STATUSES or card["quote"] not in sources.get(card["ref"], "")):
            raise ValueError(f"cards 第 {index} 条的类型、长度或对应 ref 的原文不符")
        if card not in cards:
            cards.append(card)
    return cards


def _capture_results(value, evidence, *, skip_invalid=False):
    cards = _validated_cards(value, evidence)
    insights = validated_insights(value["insights"], evidence, skip_invalid=skip_invalid)
    return cards, insights


def process_one_capture(db, *, extract=None):
    """独占一次到期任务；耗时调用期间释放事务，过期执行者不能覆盖新结果。"""
    now = datetime.utcnow()
    db.execute(text("BEGIN IMMEDIATE"))
    job = db.query(GroupMemoryCapture).filter(GroupMemoryCapture.cards_json.is_(None),
        GroupMemoryCapture.run_after <= now).order_by(GroupMemoryCapture.run_after, GroupMemoryCapture.id).first()
    if job is None:
        db.rollback()
        return False
    job.attempts += 1
    job.run_after = now + timedelta(minutes=10)
    job_id, attempt = job.id, job.attempts
    db.commit()
    try:
        db.execute(text("BEGIN"))
        job = db.get(GroupMemoryCapture, job_id)
        if not job:
            db.rollback()
            return False
        evidence = _evidence(job, db)
        db.rollback()
        extractor = extract or _extract
        value = extractor(evidence) if evidence["records"] else {"cards": [], "insights": []}
        error_code = None
        try:
            cards, insights = _capture_results(value, evidence)
        except ValueError as exc:
            corrected = extractor(evidence, correction=(value, str(exc)))
            cards, insights = _capture_results(corrected, evidence, skip_invalid=True)
            if len(insights) != len(corrected["insights"]):
                error_code = "insights_filtered"
        update = {"cards_json": json.dumps(cards, ensure_ascii=False), "error_code": error_code}
    except Exception as exc:
        db.rollback()
        insights = []
        update = {"run_after": datetime.utcnow() + timedelta(seconds=min(3600, 5 * 2 ** min(attempt, 10))),
                  "error_code": "extraction_failed"}
        logger.warning("群聊记忆提纯待重试 job_id=%s error_type=%s", job_id, type(exc).__name__)
    claimed = db.query(GroupMemoryCapture).filter_by(id=job_id, attempts=attempt, cards_json=None).update(update, synchronize_session=False)
    if claimed:
        db.add_all(GroupMemberInsight(capture_id=job_id, **row) for row in insights)
    db.commit()
    return True
