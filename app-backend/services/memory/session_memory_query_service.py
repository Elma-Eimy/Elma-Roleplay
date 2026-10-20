"""Read models for session-scoped memory management and character navigation."""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from sqlalchemy import and_, case, func
from sqlalchemy.orm import Session as DBSession

from core.models import (Character, MemoryChunk, Session, SessionPersona,
                         MemoryConsolidationScope, MemoryConsolidationSource)
from services.conversation import session_service
from services.memory.persona_lineage import get_ancestor_persona_ids
from services.memory.memory_visibility import memory_view, memory_source_bound


MemoryScope = Literal["all", "local", "inherited"]
MemoryStatus = Literal["active", "superseded", "all"]


class MemoryQueryNotFoundError(ValueError):
    pass


def serialize_memory_item(
    chunk: MemoryChunk,
    *,
    current_persona_id: int,
    is_superseded: bool,
) -> dict:
    return {
        "id": chunk.id,
        "content": chunk.content,
        "memory_type": chunk.memory_type.value if chunk.memory_type else "fact",
        "importance_score": chunk.importance_score,
        "is_local": chunk.persona_id == current_persona_id,
        "created_at": chunk.created_at.isoformat() if chunk.created_at else None,
        "origin_session_id": chunk.origin_session_id,
        "source_start_message_id": chunk.source_start_message_id,
        "source_message_id": chunk.source_message_id,
        "supersedes_id": chunk.supersedes_id,
        "is_superseded": bool(is_superseded),
        "consolidation_id": chunk.consolidation_id,
    }


def query_session_memories(
    *,
    session_id: int,
    q: str | None,
    scope: MemoryScope,
    status: MemoryStatus,
    limit: int,
    offset: int,
    db: DBSession,
) -> dict:
    """Filter and count visible SQLite memories before applying pagination."""
    session = db.get(Session, session_id)
    if session is None or session.persona is None:
        raise MemoryQueryNotFoundError("Session or Persona not found")

    current_persona_id = session.persona.id
    ancestor_ids = get_ancestor_persona_ids(current_persona_id, db)
    inherited_ids = [persona_id for persona_id in ancestor_ids if persona_id != current_persona_id]
    visible_filter, superseded_ids = memory_view(current_persona_id, db)

    search_text = q.strip() if q else ""
    visible_filters = [visible_filter]
    if search_text:
        visible_filters.append(MemoryChunk.content.contains(search_text))

    active_condition = MemoryChunk.id.not_in(superseded_ids)
    superseded_condition = MemoryChunk.id.in_(superseded_ids)

    facet_row = (
        db.query(
            func.coalesce(
                func.sum(
                    case(
                        (
                            and_(
                                MemoryChunk.persona_id == current_persona_id,
                                active_condition,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("local_active"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            and_(
                                MemoryChunk.persona_id.in_(inherited_ids),
                                active_condition,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("inherited_active"),
            func.coalesce(
                func.sum(case((superseded_condition, 1), else_=0)),
                0,
            ).label("superseded"),
        )
        .filter(*visible_filters)
        .one()
    )
    local_active = int(facet_row.local_active or 0)
    inherited_active = int(facet_row.inherited_active or 0)
    facets = {
        "effective_total": local_active + inherited_active,
        "local_active": local_active,
        "inherited_active": inherited_active,
        "superseded": int(facet_row.superseded or 0),
    }

    filtered = db.query(MemoryChunk).filter(*visible_filters)
    if scope == "local":
        filtered = filtered.filter(MemoryChunk.persona_id == current_persona_id)
    elif scope == "inherited":
        filtered = filtered.filter(MemoryChunk.persona_id.in_(inherited_ids))

    if status == "active":
        filtered = filtered.filter(active_condition)
    elif status == "superseded":
        filtered = filtered.filter(superseded_condition)

    total = filtered.order_by(None).count()
    rows = (
        filtered.add_columns(
            case((superseded_condition, True), else_=False).label("is_superseded")
        )
        .order_by(MemoryChunk.created_at.desc(), MemoryChunk.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    items = [
        serialize_memory_item(
            chunk,
            current_persona_id=current_persona_id,
            is_superseded=is_superseded,
        )
        for chunk, is_superseded in rows
    ]
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
        "facets": facets,
    }


def _memory_stats_from_loaded_rows(
    *,
    current_persona_id: int,
    personas_by_id: dict[int, SessionPersona],
    memories_by_persona: dict[int, list[MemoryChunk]],
    sessions_by_id: dict[int, Session],
    scopes_by_persona: dict[int, set[int]],
    sources_by_summary: dict[int, set[int]],
) -> dict:
    lineage_ids = []
    visited = set()
    persona_id = current_persona_id
    while persona_id is not None and persona_id not in visited:
        visited.add(persona_id)
        lineage_ids.append(persona_id)
        persona = personas_by_id.get(persona_id)
        if persona is None:
            break
        persona_id = persona.parent_persona_id

    visible_memories = []
    for index, lineage_id in enumerate(lineage_ids):
        child = sessions_by_id.get(personas_by_id[lineage_ids[index - 1]].session_id) if index else None
        boundary = child.fork_message_id if child else None
        for memory in memories_by_persona.get(lineage_id, ()):
            source_bound = memory_source_bound(memory)
            if index and source_bound is not None and (boundary is None or source_bound > boundary):
                continue
            visible_memories.append(memory)
    visible_ids = {memory.id for memory in visible_memories}
    scoped_batches = scopes_by_persona.get(current_persona_id, set())
    visible_memories = [memory for memory in visible_memories if memory.consolidation_id is None or (
        memory.consolidation_id in scoped_batches
        and len(sources_by_summary.get(memory.id, set())) >= 2
        and sources_by_summary[memory.id] <= visible_ids
    )]
    superseded_ids = {
        memory.supersedes_id
        for memory in visible_memories
        if memory.supersedes_id is not None
    }
    superseded_ids.update(source_id for memory in visible_memories
                          if memory.consolidation_id is not None
                          for source_id in sources_by_summary.get(memory.id, set()))
    local_active = sum(
        memory.persona_id == current_persona_id and memory.id not in superseded_ids
        for memory in visible_memories
    )
    inherited_active = sum(
        memory.persona_id != current_persona_id and memory.id not in superseded_ids
        for memory in visible_memories
    )
    return {
        "effective_total": local_active + inherited_active,
        "local_active": local_active,
        "inherited_active": inherited_active,
        "superseded": sum(memory.id in superseded_ids for memory in visible_memories),
    }


def get_character_memory_overview(
    *,
    character_id: int,
    limit: int,
    offset: int,
    db: DBSession,
) -> dict:
    """Return a paginated story navigator with branch-correct memory statistics."""
    if db.get(Character, character_id) is None:
        raise MemoryQueryNotFoundError("Character not found")

    page = session_service.get_character_sessions(
        character_id=character_id,
        include_last_message=True,
        limit=limit,
        offset=offset,
        db=db,
    )
    all_personas = (
        db.query(SessionPersona)
        .filter(SessionPersona.character_id == character_id)
        .all()
    )
    personas_by_id = {persona.id: persona for persona in all_personas}
    relevant_persona_ids = set()
    for item in page["sessions"]:
        persona_id = item["persona"]["id"]
        visited = set()
        while persona_id is not None and persona_id not in visited:
            visited.add(persona_id)
            relevant_persona_ids.add(persona_id)
            persona = personas_by_id.get(persona_id)
            if persona is None:
                break
            persona_id = persona.parent_persona_id
    memories = (
        db.query(MemoryChunk)
        .filter(MemoryChunk.persona_id.in_(relevant_persona_ids))
        .all()
        if relevant_persona_ids
        else []
    )
    memories_by_persona: dict[int, list[MemoryChunk]] = defaultdict(list)
    for memory in memories:
        memories_by_persona[memory.persona_id].append(memory)

    # 固定次数批量加载，避免角色故事数量增长时产生逐故事查询。
    sessions_by_id = {row.id: row for row in db.query(Session).filter(
        Session.id.in_([persona.session_id for persona in all_personas])).all()}
    scopes_by_persona: dict[int, set[int]] = defaultdict(set)
    for row in db.query(MemoryConsolidationScope).filter(
        MemoryConsolidationScope.persona_id.in_(relevant_persona_ids)).all():
        scopes_by_persona[row.persona_id].add(row.consolidation_id)
    sources_by_summary: dict[int, set[int]] = defaultdict(set)
    for row in db.query(MemoryConsolidationSource).filter(
        MemoryConsolidationSource.summary_id.in_([m.id for m in memories if m.consolidation_id is not None])).all():
        sources_by_summary[row.summary_id].add(row.source_id)

    recent_session_id = (
        db.query(Session.id)
        .join(SessionPersona, SessionPersona.session_id == Session.id)
        .filter(SessionPersona.character_id == character_id)
        .order_by(Session.updated_at.desc(), Session.id.desc())
        .limit(1)
        .scalar()
    )
    sessions = []
    for item in page["sessions"]:
        sessions.append(
            {
                "session_id": item["id"],
                "title": item["title"],
                "parent_session_id": item["parent_session_id"],
                "created_at": item["created_at"],
                "updated_at": item["updated_at"],
                "last_message": item["last_message"],
                "memory_stats": _memory_stats_from_loaded_rows(
                    current_persona_id=item["persona"]["id"],
                    personas_by_id=personas_by_id,
                    memories_by_persona=memories_by_persona,
                    sessions_by_id=sessions_by_id,
                    scopes_by_persona=scopes_by_persona,
                    sources_by_summary=sources_by_summary,
                ),
            }
        )

    return {
        "character_id": character_id,
        "story_count": page["total"],
        "recent_session_id": recent_session_id,
        "sessions": sessions,
        "total": page["total"],
        "limit": limit,
        "offset": offset,
        "has_more": page["has_more"],
    }
