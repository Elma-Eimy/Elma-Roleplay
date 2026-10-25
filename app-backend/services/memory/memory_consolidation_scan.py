"""手动整理的版本扫描记录；不召回旧卡，不执行语义聚类。"""

import hashlib
import json
from sqlalchemy import and_, func
from sqlalchemy.dialects.sqlite import insert
from core.models import MemoryChunk, MemoryConsolidationScan


def fingerprint(chunk):
    values = [chunk.id, chunk.persona_id, chunk.content, chunk.memory_type.value,
              chunk.importance_score, chunk.source_start_message_id,
              chunk.source_message_id, chunk.source_message_id_bound, chunk.supersedes_id]
    if chunk.temporal_status != "unknown" or chunk.temporal_note:
        values.extend([chunk.temporal_status, chunk.temporal_note])
    if chunk.event_id is not None:
        values.extend(["event_id", chunk.event_id])
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode("utf-8")).hexdigest()


def collect(query, mode="incremental", after_id=0):
    """逐页读取指纹所需字段，只保留本批最多 100 张；统计基于当前有效原卡。"""
    query = query.outerjoin(MemoryConsolidationScan, and_(
        MemoryConsolidationScan.persona_id == MemoryChunk.persona_id,
        MemoryConsolidationScan.memory_id == MemoryChunk.id,
    )).add_columns(MemoryConsolidationScan.fingerprint).order_by(MemoryChunk.id)
    eligible, checked, remaining = 0, 0, 0
    rows = []
    for chunk, previous in query.yield_per(256):
        eligible += 1
        unchanged = previous == fingerprint(chunk)
        checked += int(unchanged)
        candidate = not unchanged if mode == "incremental" else chunk.id > after_id
        if candidate:
            remaining += 1
            if len(rows) < 100:
                rows.append(chunk)
    return rows, remaining, {"eligible_count": eligible, "checked_count": checked,
                             "pending_count": eligible - checked}


def record_unchanged(persona_id, expected, query, db, groups=()):
    """短写事务内复核；过期建议的整组来源不推进，保留重试所需的同组卡。"""
    current = {chunk.id: fingerprint(chunk)
               for chunk in query.filter(MemoryChunk.id.in_(expected)).all()}
    unchanged = {memory_id for memory_id, value in current.items() if value == expected[memory_id]}
    deferred = {memory_id for group in groups if not set(group["source_ids"]) <= unchanged
                for memory_id in group["source_ids"]}
    count = 0
    for memory_id in unchanged:
        if memory_id in deferred:
            continue
        statement = insert(MemoryConsolidationScan).values(
            persona_id=persona_id, memory_id=memory_id, fingerprint=current[memory_id], checked_at=func.now())
        db.execute(statement.on_conflict_do_update(
            index_elements=["persona_id", "memory_id"],
            set_={"fingerprint": current[memory_id], "checked_at": func.now()}))
        count += 1
    return count
