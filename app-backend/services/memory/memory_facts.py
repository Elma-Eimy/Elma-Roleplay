"""Shared fact representation for semantic and graph recall (SQLite-owned)."""
import json

TEMPORAL_STATUSES = {"unknown", "current", "historical", "planned"}
TEMPORAL_LABELS = {"current": "当前事实", "historical": "历史", "planned": "计划，尚未确认发生"}


def normalize_temporal(status, note=None):
    status = status if isinstance(status, str) and status in TEMPORAL_STATUSES else "unknown"
    note = " ".join(note.split())[:120] if isinstance(note, str) else ""
    return status, note or None


def fact_payload(chunk):
    """Both retrieval channels render this record, never independent graph prose."""
    return {
        "id": chunk.id, "content": chunk.content,
        "memory_type": getattr(chunk.memory_type, "value", chunk.memory_type),
        "importance_score": chunk.importance_score,
        "persona_id": chunk.persona_id, "origin_session_id": chunk.origin_session_id,
        "source_start_message_id": chunk.source_start_message_id,
        "source_message_id": chunk.source_message_id,
        "temporal_status": chunk.temporal_status, "temporal_note": chunk.temporal_note,
    }


def fact_sources_current(chunk, db, _visited=None):
    """Legacy/manual cards retain compatibility; new automatic cards are checked."""
    visited = set() if _visited is None else _visited
    if chunk.id in visited:
        return False
    visited = visited | {chunk.id}
    if chunk.consolidation_id is not None:
        from core.models import MemoryChunk, MemoryConsolidationSource
        originals = db.query(MemoryChunk).join(MemoryConsolidationSource,
            MemoryConsolidationSource.source_id == MemoryChunk.id).filter(
            MemoryConsolidationSource.summary_id == chunk.id).all()
        return len(originals) >= 2 and all(fact_sources_current(row, db, visited) for row in originals)
    if chunk.source_evidence_json is None:
        return True
    from services.memory.graph_evidence import sources_are_current
    try:
        sources = json.loads(chunk.source_evidence_json)
        if not isinstance(sources, list) or not sources or any(
            not isinstance(item, dict) or type(item.get("id")) is not int
            or not isinstance(item.get("hash"), str) or len(item["hash"]) != 64 for item in sources
        ):
            return False
        ids = [item["id"] for item in sources]
        bound = chunk.source_message_id_bound or chunk.source_message_id
        if min(ids) != chunk.source_start_message_id or max(ids) != bound:
            return False
        return sources_are_current(chunk.persona_id, sources, db)
    except (TypeError, ValueError):
        return False
