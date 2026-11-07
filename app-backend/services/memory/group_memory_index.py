"""从群聊成员可见的 SQLite 来源读取正文，Chroma 只返回候选编号。"""
import logging
import math
from dataclasses import dataclass
from sqlalchemy import text

from services.conversation.session_access import check_chat_arguments, group_session_operation
from services.memory.group_memory_recall import _terms
from services.memory.group_memory_facts import effective_facts

logger = logging.getLogger(__name__)
COLLECTION = "group_memory_v1"
MAX_COSINE_DISTANCE = 0.50

# 即使索引尚未清理，角色输入也必须重新检查采用候选和成员归属。
CARD_ROWS = """
SELECT d.id, d.persona_id, d.indexed, d.parts_json, s.importance_score, s.temporal_note, r.round_index,
       json_extract(c.cards_json,'$[' || d.slot || '].claim_kind') AS claim_kind,
       json_extract(c.cards_json,'$[' || d.slot || '].replaces_part') AS revision_json,
       evidence.speaker_persona_id AS source_speaker, evidence.id IS NOT NULL AS source_known,
       coalesce(json_extract(c.cards_json,'$[' || d.slot || '].source_name'),
                CASE WHEN evidence.id IS NOT NULL AND evidence.speaker_persona_id IS NULL THEN '用户' ELSE '旧资料' END) AS source_name,
       coalesce(s.content, json_extract(c.cards_json,'$[' || d.slot || '].content')) AS content,
       coalesce(s.memory_type, json_extract(c.cards_json,'$[' || d.slot || '].memory_type')) AS memory_type,
       coalesce(s.temporal_status, json_extract(c.cards_json,'$[' || d.slot || '].temporal_status')) AS temporal_status
FROM group_recall_cards d
LEFT JOIN group_inherited_memory_snapshots s ON s.id=d.snapshot_id AND s.persona_id=d.persona_id
LEFT JOIN group_memory_captures c ON c.id=d.capture_id AND c.persona_id=d.persona_id
LEFT JOIN group_rounds r ON r.id=c.round_id AND r.session_id=c.session_id
LEFT JOIN group_round_candidates picked ON picked.id=c.candidate_id AND picked.round_id=r.id
LEFT JOIN group_content_items evidence ON evidence.candidate_id=c.candidate_id AND evidence.id=
       CAST(json_extract(c.cards_json,'$[' || d.slot || '].ref') AS INTEGER)
WHERE (s.id IS NOT NULL OR (r.confirmed_at IS NOT NULL AND r.discarded_at IS NULL
       AND r.selected_candidate_id=c.candidate_id AND picked.status='awaiting_confirmation'))
"""


@dataclass(frozen=True)
class SemanticQuery:
    persona_id: int
    ceiling: int
    passage: str

    def distances(self):
        from services.infrastructure.clients import get_chroma_client, get_embedding_function
        try:
            collection = get_chroma_client().get_collection(COLLECTION, embedding_function=get_embedding_function())
            hits = collection.query(query_texts=[self.passage], n_results=8,
                where={"$and": [{"persona_id": self.persona_id}, {"card_id": {"$lte": self.ceiling}}]},
                include=["distances"])
            result = {}
            for ids, distances in zip(hits["ids"], hits["distances"]):
                for key, distance in zip(ids, distances):
                    if key.startswith("gc_") and key[3:].isdecimal() and math.isfinite(distance) and distance <= MAX_COSINE_DISTANCE:
                        id_ = int(key[3:])
                        result[id_] = min(result.get(id_, math.inf), distance)
            return result
        except Exception as exc:
            logger.warning("群聊语义召回暂不可用 error_type=%s", type(exc).__name__)
            return {}


@group_session_operation
def unified_memories(persona_id, round_index, ceiling, passages, db, distances, *, include_ids=False, facts=False, limit=3):
    if type(limit) is not int or not 1 <= limit <= 12:
        raise ValueError('记忆候选数量需要在 1–12 之间')
    check_chat_arguments({"persona_id": persona_id}, db, kind="group")
    passages = tuple(dict.fromkeys(p[:2400] for p in passages if p.strip()))
    if not passages or not ceiling:
        return []
    if distances is None and db.execute(text("SELECT 1 FROM group_recall_cards WHERE persona_id=:pid "
            "AND id<=:ceiling AND indexed=1 LIMIT 1"), {"pid": persona_id, "ceiling": ceiling}).first():
        return SemanticQuery(persona_id, ceiling, max(passages, key=len))
    terms = set().union(*(_terms(p) for p in passages))
    best = {}
    view = CARD_ROWS + " AND d.persona_id=:pid AND d.id<=:ceiling AND (s.id IS NOT NULL OR r.round_index<:turn)"
    query = ("WITH visible AS (" + view + "), retired AS ("
        "SELECT trim(old.content) AS content, old.memory_type, old.temporal_status, coalesce(old.temporal_note,'') AS note, "
        "max(new.round_index) AS until_turn FROM group_recall_cards link "
        "JOIN visible new ON new.id=link.id JOIN visible old ON old.id=link.replaces_id "
        "WHERE link.replaces_id IS NOT NULL AND new.round_index>coalesce(old.round_index,0) "
        "GROUP BY trim(old.content),old.memory_type,old.temporal_status,coalesce(old.temporal_note,'')) "
        "SELECT v.* FROM visible v LEFT JOIN retired t ON t.content=trim(v.content) AND t.memory_type=v.memory_type "
        "AND t.temporal_status=v.temporal_status AND t.note=coalesce(v.temporal_note,'') "
        "WHERE t.until_turn IS NULL OR v.round_index>=t.until_turn")
    rows = db.execute(text(query), {"pid": persona_id, "ceiling": ceiling, "turn": round_index}).mappings()
    rows = effective_facts([dict(row) for row in rows]) if facts else rows
    for row in rows:
        content = row["content"]
        if not content or len(content) > 1000:
            continue
        tokens = _terms(content)
        overlap = len(terms & tokens)
        distance = (distances or {}).get(row["id"]) if row["indexed"] and not row.get('partially_retired') else None
        if not overlap and distance is None:
            continue
        similarity = overlap / math.sqrt(max(1, len(terms) * len(tokens)))
        # 词面命中与高置信语义命中都可独立入选，两者一致时优先。
        score = max(similarity, 1 - distance if distance is not None else 0) + min(similarity, 0.2) * (distance is not None)
        rank = (score, row["round_index"] or 0, row["importance_score"] or 0, row["id"])
        key = (content.strip(), row["memory_type"], row["temporal_status"], row["temporal_note"] or "")
        if facts:
            key += (row.get('claim_kind') or 'legacy', row['source_speaker'], bool(row['source_known']),
                    tuple(fragment['disputed'] for fragment in row['fact_fragments']))
        if key not in best or rank > best[key][0]:
            best[key] = (rank, dict(content=content, memory_type=row["memory_type"], temporal_status=row["temporal_status"],
                temporal_note=row["temporal_note"], source="group" if row["round_index"] else "inherited",
                round_index=row["round_index"], **({'claim_kind': row.get('claim_kind') or 'legacy',
                    'fact_fragments': row['fact_fragments'], 'source_speaker': row['source_speaker'],
                    'source_known': bool(row['source_known']),
                    **({'source_content': row['source_content'], 'parts_frozen': row['parts_frozen']} if include_ids else {})} if facts else {}),
                **({"id": row["id"]} if include_ids else {})))
            if len(best) > limit:
                del best[min(best, key=lambda k: best[k][0])]
    return [item for _, item in sorted(best.values(), key=lambda hit: hit[0], reverse=True)]


def sync_group_card(card_id, session_factory):
    from chromadb.errors import NotFoundError
    from core.models import GroupRecallCard
    from services.infrastructure.clients import get_chroma_client, get_embedding_function
    with session_factory() as db:
        row = db.execute(text(CARD_ROWS + " AND d.id=:id"), {"id": card_id}).mappings().first()
    client = get_chroma_client()
    key = f"gc_{card_id}"
    if not row or not row["content"] or len(row["content"]) > 1000:
        try:
            collection = client.get_collection(COLLECTION, embedding_function=get_embedding_function())
        except NotFoundError:
            return
        collection.delete(ids=[key])
        return
    collection = client.get_or_create_collection(COLLECTION, embedding_function=get_embedding_function(),
                                                metadata={"hnsw:space": "cosine"})
    collection.upsert(ids=[key], documents=[row["content"]],
                      metadatas=[{"persona_id": row["persona_id"], "card_id": card_id}])
    with session_factory() as db:
        exists = db.query(GroupRecallCard).filter_by(id=card_id).update({"indexed": True})
        db.commit()
    if not exists:
        collection.delete(ids=[key])


def rebuild_group_index(session_factory):
    from chromadb.errors import NotFoundError
    from services.infrastructure.clients import get_chroma_client
    try:
        get_chroma_client().delete_collection(COLLECTION)
    except NotFoundError:
        pass
    with session_factory() as db:
        db.execute(text("UPDATE group_recall_cards SET indexed=0"))
        db.execute(text("INSERT INTO outbox_jobs(task_type,payload,status,attempts,max_attempts,run_after) "
                        "SELECT 'sync_group_card',json_object('id',id),'pending',0,5,CURRENT_TIMESTAMP FROM group_recall_cards"))
        db.commit()
