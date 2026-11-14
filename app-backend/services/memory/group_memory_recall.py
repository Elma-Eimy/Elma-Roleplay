"""从发言成员自己的入群快照召回与本次话题重合的记忆。"""
import heapq
import re

from sqlalchemy import func

from core.models import GroupInheritedMemorySnapshot
from services.conversation.session_access import check_chat_arguments, group_session_operation


_WORDS = re.compile(r"[\u3400-\u9fff]+|(?:(?![\u3400-\u9fff])[^\W_])+")
_MAX_CARDS = 3
_MAX_CARD_CHARS = 1000


def _terms(text):
    terms = set()
    # 先切中英文，再在连续汉字内取二元组；跨片段和标点都不能拼词。
    for word in _WORDS.findall(text.casefold()):
        if "\u3400" <= word[0] <= "\u9fff":
            terms.update(word[i:i + 2] for i in range(len(word) - 1))
        elif len(word) > 1:
            terms.add(word)
    return terms


@group_session_operation
def recall_inherited_memories(persona_id, passages, db):
    check_chat_arguments({"persona_id": persona_id}, db, kind="group")
    query_terms = set()
    for passage in passages:
        query_terms.update(_terms(passage[:2400]))
    if not query_terms:
        return []

    snapshot = GroupInheritedMemorySnapshot
    cards = db.query(snapshot.id, snapshot.content, snapshot.memory_type, snapshot.importance_score,
                     snapshot.temporal_status, snapshot.temporal_note).filter(
                         snapshot.persona_id == persona_id, func.length(snapshot.content) <= _MAX_CARD_CHARS)

    def matches():
        for card in cards.yield_per(256):
            overlap = len(query_terms.intersection(_terms(card.content)))
            if overlap:
                yield (overlap, card.importance_score or 0, card.id), card

    best = heapq.nlargest(_MAX_CARDS, matches(), key=lambda hit: hit[0])
    return [{"content": card.content, "memory_type": card.memory_type, "temporal_status": card.temporal_status,
             "temporal_note": card.temporal_note} for _, card in best]
