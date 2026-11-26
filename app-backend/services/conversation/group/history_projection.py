"""个人历史的可见范围与不可变投影；调用方持有读写事务。"""
import logging
from dataclasses import dataclass
from sqlalchemy import and_, or_
from core.models import GroupRound, GroupRoundCandidate, GroupContentItem, GroupContentVisibility
from services.conversation.session_access import group_session_operation
from .guards import require_group
from .unit_protocol import ContentUnit
from . import unit_service as units

logger = logging.getLogger("services.conversation.group.history_service")


@dataclass(frozen=True)
class GroupHistoryItem:
    item_id: int
    round_id: int
    candidate_id: int
    round_index: int
    sequence: int
    kind: str
    speaker_persona_id: int | None
    content: str
    emotion_tag: str | None = None
    affection_change: int | None = None
    visible_units: tuple[ContentUnit, ...] = ()
    visible_passages: tuple[str, ...] = ()


def content_scope(round_, candidate, before_sequence):
    return or_(
        and_(GroupRound.round_index < round_.round_index, GroupRound.confirmed_at.isnot(None), GroupRound.discarded_at.is_(None),
             GroupRound.selected_candidate_id == GroupRoundCandidate.id,
             GroupRoundCandidate.status == "awaiting_confirmation"),
        and_(GroupRoundCandidate.id == candidate.id, GroupContentItem.sequence < before_sequence),
    )


@group_session_operation
def content_query(session_id, round_, candidate, before_sequence, db):
    require_group(session_id, db)
    return db.query(GroupContentItem, GroupRound).join(GroupRoundCandidate,
            GroupContentItem.candidate_id == GroupRoundCandidate.id).join(GroupRound,
            GroupRoundCandidate.round_id == GroupRound.id).filter(GroupRound.session_id == session_id,
                content_scope(round_, candidate, before_sequence))


@group_session_operation
def member_history(session_id, persona_id, round_, candidate, before_sequence, limit, db):
    query = content_query(session_id, round_, candidate, before_sequence, db)
    legacy_visible = db.query(GroupContentVisibility.item_id).filter(
        GroupContentVisibility.item_id == GroupContentItem.id,
        GroupContentVisibility.recipient_persona_id == persona_id,
        GroupContentVisibility.decision == "visible").exists()
    visible = query.filter(or_(and_(GroupRoundCandidate.protocol_version == 1, legacy_visible),
        and_(GroupRoundCandidate.protocol_version == 2, units._has_visible_unit(persona_id, db))))
    # 缺行不兜底为公开；只向内部日志报告，不向个人 DTO 泄露隐藏项信息。
    missing = query.outerjoin(GroupContentVisibility, and_(GroupContentVisibility.item_id == GroupContentItem.id,
            GroupContentVisibility.recipient_persona_id == persona_id)).filter(GroupContentVisibility.item_id.is_(None)).first()
    if missing:
        logger.warning("群聊个人历史存在缺失知情记录，已按不可见处理")
    rows = visible.order_by(
            GroupRound.round_index.desc(), GroupContentItem.sequence.desc()).limit(limit).all()
    result = []
    for item, owner in reversed(rows):
        v2 = db.get(GroupRoundCandidate, item.candidate_id).protocol_version == 2
        visible_units, passages = units._member_projection(item, owner, persona_id, db) if v2 else ((), ())
        content = ("\n".join(passages) if v2 else
                   owner.user_content if item.kind == "user" else item.content)
        own_state_visible = item.speaker_persona_id == persona_id and (not v2 or units._complete_author_visibility(item, db))
        result.append(GroupHistoryItem(item.id, owner.id, item.candidate_id, owner.round_index,
            item.sequence, item.kind, item.speaker_persona_id, content,
            item.emotion_tag if own_state_visible else None, item.affection_change if own_state_visible else None,
            visible_units, passages))
    return tuple(result)
