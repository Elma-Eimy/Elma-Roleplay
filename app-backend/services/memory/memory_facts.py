"""Shared fact representation for semantic and graph recall (SQLite-owned)."""
import json

TEMPORAL_STATUSES = {"unknown", "current", "historical", "planned"}
TEMPORAL_LABELS = {"current": "当前事实", "historical": "历史", "planned": "计划，尚未确认发生"}
_PRESENT_TEMPORAL_NOTES = {
    "目前", "现在", "当前", "如今", "眼下", "现阶段", "当下",
    "now", "currently", "presently",
}


def normalize_temporal(status, note=None):
    status = status if isinstance(status, str) and status in TEMPORAL_STATUSES else "unknown"
    note = " ".join(note.split())[:120] if isinstance(note, str) else ""
    if note and note.casefold() in _PRESENT_TEMPORAL_NOTES:
        if status in {"unknown", "current"}:
            status = "current"
            note = ""
    return status, note or None


def compatible_temporal_statuses(memory_type, temporal_status: str) -> tuple[str, ...]:
    """返回写入查重时可互相匹配的兼容时间状态集合。"""
    status = temporal_status if temporal_status in TEMPORAL_STATUSES else "unknown"
    if status == "planned":
        return ("planned",)
    kind = getattr(memory_type, "value", memory_type)
    if kind in {"fact", "emotion", "relationship"} and status in {"current", "unknown"}:
        return ("current", "unknown")
    if status in {"current", "historical"}:
        return (status, "unknown")
    return (status,)


def temporal_is_compatible(
    left_status: str | None,
    left_note: str | None,
    right_status: str | None,
    right_note: str | None,
    *,
    allow_missing_note: bool = True,
) -> bool:
    """判断两条记忆的故事内时间状态与时间附注是否相容（无明确冲突）。"""
    l_status, l_note = normalize_temporal(left_status, left_note)
    r_status, r_note = normalize_temporal(right_status, right_note)
    if "planned" in {l_status, r_status} and l_status != r_status:
        return False
    known_statuses = {l_status, r_status} - {"unknown"}
    if len(known_statuses) > 1:
        return False
    if l_note == r_note:
        return True
    if allow_missing_note and (l_note is None or r_note is None):
        return True
    return False


def merge_temporal(
    left_status: str | None,
    left_note: str | None,
    right_status: str | None,
    right_note: str | None,
) -> tuple[str, str | None]:
    """合并两条相容记忆的时间状态与附注，优先保留明确状态与非空附注（以右侧新信息优先）。"""
    l_status, l_note = normalize_temporal(left_status, left_note)
    r_status, r_note = normalize_temporal(right_status, right_note)
    resolved_status = r_status if r_status != "unknown" else l_status
    resolved_note = r_note if r_note is not None else l_note
    return resolved_status, resolved_note


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
