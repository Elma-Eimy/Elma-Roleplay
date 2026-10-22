"""Semantic seeds -> graph expansion -> authoritative, deduplicated fact cards."""
from core.config import settings
from core.models import MemoryChunk, MemoryConsolidationSource
from services.memory import memory_manager
from services.memory.graph_service import retrieve_graph_recall
from services.memory.memory_facts import fact_payload, fact_sources_current
from services.memory.memory_visibility import memory_view
from services.memory.persona_lineage import build_branch_turn_segments

# One shared budget for both channels; skip oversize cards rather than cut facts.
MAX_FACTS = 16
MAX_FACT_CHARS = 6000


def retrieve_joint_memories(persona_id, character_id, query, db, *, before_message_id=None):
    semantic = memory_manager.retrieve_memories(
        persona_id=persona_id, character_id=character_id, query=query, db=db,
        before_message_id=before_message_id,
    )
    visible, hidden = memory_view(persona_id, db, before_message_id)
    semantic_ids = list(dict.fromkeys(item["id"] for item in semantic
                                     if type(item.get("id")) is int))
    semantic_ages = {item["id"]: item["turns_passed"] for item in semantic
                     if type(item.get("id")) is int and "turns_passed" in item}
    # SQLite is the authority even when vector metadata or text is stale.
    semantic_rows = {row.id: row for row in db.query(MemoryChunk).filter(
        visible, MemoryChunk.id.not_in(hidden), MemoryChunk.id.in_(semantic_ids)).all()}
    seeds = tuple(mid for mid in semantic_ids if mid in semantic_rows)
    # Semantic hits may be summaries while graph evidence still names originals.
    original_ids = [row[0] for row in db.query(MemoryConsolidationSource.source_id).filter(
        MemoryConsolidationSource.summary_id.in_(seeds)).all()]
    graph_seeds = tuple(dict.fromkeys([*seeds, *original_ids]))
    graph = retrieve_graph_recall(persona_id, query, db,
                                  before_message_id=before_message_id, seed_memory_ids=graph_seeds)
    # Use the active summary for compacted sources; never inject hidden originals.
    summaries = db.query(MemoryConsolidationSource.source_id, MemoryChunk.id).join(
        MemoryChunk, MemoryChunk.id == MemoryConsolidationSource.summary_id).filter(
        MemoryConsolidationSource.source_id.in_(set(graph.memory_ids) & hidden),
        visible, MemoryChunk.id.not_in(hidden)).order_by(MemoryChunk.id).all()
    summary_by_source = {}
    for source_id, summary_id in summaries:
        summary_by_source.setdefault(source_id, []).append(summary_id)
    graph_ids = list(dict.fromkeys(mid for source_id in graph.memory_ids
                                   for mid in summary_by_source.get(source_id, [source_id])))
    graph_rows = {row.id: row for row in db.query(MemoryChunk).filter(
        visible, MemoryChunk.id.not_in(hidden), MemoryChunk.id.in_(graph_ids),
        MemoryChunk.importance_score >= settings.APP_RETRIEVAL_MIN_IMPORTANCE).all()}
    candidates = [(semantic_rows[mid], "semantic") for mid in seeds]
    candidates.extend((graph_rows[mid], "graph") for mid in graph_ids if mid in graph_rows)
    result, seen_ids, seen_content, used_chars = [], set(), set(), 0
    branch_segments, turn_count_cache = None, {}
    for row, channel in candidates:
        identity = ("".join(c.casefold() for c in row.content if c.isalnum()),
                    row.temporal_status, row.temporal_note)
        if row.id in seen_ids or identity in seen_content or not fact_sources_current(row, db):
            continue
        # Includes a reserve for type, story-time labels and line punctuation.
        cost = len(row.content) + len(row.temporal_note or "") + 80
        if used_chars + cost > MAX_FACT_CHARS:
            continue
        if len(result) >= MAX_FACTS:
            break
        payload = fact_payload(row)
        payload["retrieval_channel"] = channel
        if row.id in semantic_ages:
            payload["turns_passed"] = semantic_ages[row.id]
        elif payload["memory_type"] == "fact":
            payload["turns_passed"] = 0
        else:
            if branch_segments is None:
                branch_segments = build_branch_turn_segments(persona_id, db)
            payload["turns_passed"] = memory_manager.calculate_memory_age_turns(
                memory_persona_id=row.persona_id, source_message_id=row.source_message_id,
                current_persona_id=persona_id, db=db,
                branch_segments=branch_segments, count_cache=turn_count_cache,
            )
        result.append(payload)
        used_chars += cost
        seen_ids.add(row.id)
        seen_content.add(identity)
    return result
