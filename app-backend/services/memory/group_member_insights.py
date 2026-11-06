"""将已确认的个人认识按发生轮次投影到本人的角色输入。"""
from sqlalchemy import func

from core.models import GroupMemberInsight, GroupMemoryCapture, GroupRound, SessionPersona
from services.conversation.session_access import check_chat_arguments, group_session_operation


def allowed_targets(record, persona_id):
    speaker = record["speaker_id"]
    if speaker is None and record["kind"] == "speech":
        return ["self", "user"]
    if speaker is not None and speaker != persona_id and record["kind"] in ("speech", "action", "utterance"):
        return ["self", speaker]
    return ["self"]


def _validated_insight(row, records, persona_id, index):
    if not isinstance(row, dict) or set(row) != {"target", "content", "ref", "quote"}:
        raise ValueError("个人认知字段无效")
    content, ref, quote = (row[key] for key in ("content", "ref", "quote"))
    if not all(isinstance(v, str) and v.strip() for v in (content, ref, quote)):
        raise ValueError("个人认知缺少文本")
    source = records.get(ref)
    if not source or len(content) > 240 or len(quote) > 200 or quote not in source["text"]:
        raise ValueError(f"insights 第 {index} 条长度或引文与 ref 不符")
    target = row["target"]
    if source["speaker_id"] is not None and target == str(source["speaker_id"]):
        target = source["speaker_id"]
    if type(target) not in (str, int) or target not in allowed_targets(source, persona_id):
        raise ValueError(f"insights 第 {index} 条 target 不在所引用记录的 allowed_targets 内")
    target_id = None
    if target == "self":
        kind = "cognition"
    elif target == "user":
        kind = "user"
    else:
        kind, target_id = "member", target
    return dict(kind=kind, target_persona_id=target_id, content=content, ref=ref, quote=quote)


def validated_insights(rows, evidence, *, skip_invalid=False):
    if not isinstance(rows, list) or len(rows) > 4:
        raise ValueError("个人认知数量无效")
    records = {record["ref"]: record for record in evidence["records"]}
    result = []
    targets = set()
    for index, row in enumerate(rows, 1):
        try:
            insight = _validated_insight(row, records, evidence["persona_id"], index)
            target = insight["kind"], insight["target_persona_id"]
            if insight["kind"] != "cognition" and target in targets:
                raise ValueError("同轮关系对象重复")
        except ValueError:
            if not skip_invalid:
                raise
            continue
        targets.add(target)
        result.append(insight)
    return result


@group_session_operation
def member_insights(persona_id, round_, candidate, db):
    check_chat_arguments({"persona_id": persona_id}, db, kind="group")
    if not candidate.insight_watermark:
        return []
    insight, capture = GroupMemberInsight, GroupMemoryCapture
    # 重试可能晚于后续轮次完成，按故事顺序选各关系对象最近的印象。
    rank = func.row_number().over(partition_by=(insight.kind, insight.target_persona_id),
        order_by=(GroupRound.round_index.desc(), insight.id.desc())).label("rank")
    ranked = (db.query(insight.id.label("id"), insight.kind.label("kind"), rank)
        .join(capture, capture.id == insight.capture_id).join(GroupRound, GroupRound.id == capture.round_id)
        .filter(capture.session_id == round_.session_id, capture.persona_id == persona_id,
                GroupRound.round_index < round_.round_index, GroupRound.confirmed_at.isnot(None),
                GroupRound.discarded_at.is_(None), GroupRound.selected_candidate_id == capture.candidate_id,
                insight.id <= candidate.insight_watermark).subquery())
    rows = (db.query(insight, SessionPersona).join(ranked, ranked.c.id == insight.id)
        .outerjoin(SessionPersona, SessionPersona.id == insight.target_persona_id)
        .filter((ranked.c.rank == 1) | ((ranked.c.kind == "cognition") & (ranked.c.rank <= 4)))
        .order_by(insight.kind, ranked.c.rank.desc(), insight.target_persona_id).all())
    return [dict(kind=row.kind, content=row.content,
                 **({"persona_id": target.id, "name": target.character.name} if target else {}))
            for row, target in rows]
