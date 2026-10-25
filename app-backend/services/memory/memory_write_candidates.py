"""写入查重候选：语义距离召回与 SQLite 近期卡补偿。"""

import logging
import math
from sqlalchemy import or_

from core.config import settings
from core.models import MemoryChunk
from services.memory.memory_facts import compatible_temporal_statuses
from services.memory.memory_manager import get_character_collection
from services.memory.memory_visibility import memory_view


logger = logging.getLogger("uvicorn.error.memory_extraction")


def retrieve_write_candidates(persona_id, character_id, query, db, *, memory_type,
                              temporal_status, temporal_note, batch_ids=(), release_read=None):
    """返回同类型、兼容时间状态的可见卡，不使用聊天召回的重要性与衰减排名。"""
    visible, hidden = memory_view(persona_id, db)
    allowed_statuses = compatible_temporal_statuses(memory_type, temporal_status)
    note_filter = (
        MemoryChunk.temporal_note.is_(None)
        if temporal_note is None
        else or_(MemoryChunk.temporal_note == temporal_note, MemoryChunk.temporal_note.is_(None))
    )
    eligible = db.query(MemoryChunk).filter(
        visible, MemoryChunk.id.not_in(hidden),
        MemoryChunk.memory_type == memory_type,
        MemoryChunk.temporal_status.in_(allowed_statuses),
        note_filter,
    )
    # 本批和近期卡直接来自 SQLite，向量同步延迟不会让它们消失。
    recent = eligible.order_by(MemoryChunk.id.desc()).limit(12).all()
    batch = eligible.filter(MemoryChunk.id.in_(batch_ids)).all() if batch_ids else []
    selected = {row.id: row for row in batch + recent}
    distances = {}
    references = eligible.with_entities(MemoryChunk.id, MemoryChunk.chroma_doc_id).all()
    by_doc = {row.chroma_doc_id: row.id for row in references if row.chroma_doc_id}
    selected_payload = {row.id: {"id": row.id, "content": row.content,
        "memory_type": row.memory_type.value, "importance_score": row.importance_score, "event_id": row.event_id,
        "temporal_status": row.temporal_status, "temporal_note": row.temporal_note,
        "source_start_message_id": row.source_start_message_id,
        "source_message_id": row.source_message_id_bound or row.source_message_id} for row in selected.values()}
    if release_read:
        release_read()
    if by_doc and not set(by_doc.values()) <= selected.keys():
        try:
            older_docs = {doc for doc, memory_id in by_doc.items() if memory_id not in selected}
            result = get_character_collection(character_id).query(
                query_texts=[query], ids=sorted(older_docs), n_results=min(6, len(older_docs)),
                include=["distances"],
            )
            ranked = sorted((distance, by_doc[doc])
                            for doc, distance in zip(result["ids"][0], result["distances"][0])
                            if doc in older_docs and isinstance(distance, (int, float)) and not isinstance(distance, bool)
                            and math.isfinite(distance) and distance >= 0)
            # 距离只选比较对象。不同向量度量下也至少比较两个最近邻，不直接判定重复。
            distances = {memory_id: distance for rank, (distance, memory_id) in enumerate(ranked)
                         if rank < 2 or distance < settings.APP_DEDUP_WRITE_THRESHOLD}
            for row in eligible.filter(MemoryChunk.id.in_(distances)).all():
                selected_payload[row.id] = {"id": row.id, "content": row.content,
                    "memory_type": row.memory_type.value, "importance_score": row.importance_score, "event_id": row.event_id,
                    "temporal_status": row.temporal_status, "temporal_note": row.temporal_note,
                    "source_start_message_id": row.source_start_message_id,
                    "source_message_id": row.source_message_id_bound or row.source_message_id}
        except Exception as exc:
            # 不能把索引故障解释成“没有旧记忆”，否则会静默制造重复卡。
            logger.warning("[MEMORY EXTRACTION] candidate_lookup_failed persona_id=%s error_type=%s",
                           persona_id, type(exc).__name__)
            raise RuntimeError("memory candidate lookup unavailable") from None
    if release_read:
        release_read()
    return [{**item, "distance": distances.get(item["id"])} for item in selected_payload.values()]
