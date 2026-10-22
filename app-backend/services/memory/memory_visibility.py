"""SQLite 权威记忆视图：分叉边界、整理快照和多来源屏蔽。"""

from collections import defaultdict
from sqlalchemy import and_, or_, select, func
from core.models import MemoryChunk, MemoryConsolidationScope, MemoryConsolidationSource
from services.memory.persona_lineage import build_branch_turn_segments


def memory_source_bound(chunk):
    return chunk.source_message_id_bound if chunk.source_message_id_bound is not None else chunk.source_message_id


def branch_memory_filter(persona_id, db, before_message_id=None):
    segments = build_branch_turn_segments(persona_id, db)
    conditions = []
    source_bound = func.coalesce(MemoryChunk.source_message_id_bound, MemoryChunk.source_message_id)
    for index, segment in enumerate(segments):
        condition = MemoryChunk.persona_id == segment["persona_id"]
        if index == 0 and before_message_id is not None:
            condition = and_(condition, or_(source_bound.is_(None), source_bound < before_message_id))
        if index:
            boundary = segment["through_message_id"]
            condition = and_(condition, or_(
                source_bound.is_(None),
                source_bound <= boundary if boundary is not None else False,
            ))
        conditions.append(condition)
    return or_(*conditions) if conditions else MemoryChunk.persona_id == persona_id


def consolidation_state(persona_id, db, branch_filter=None):
    """只认可本故事保存的整理快照；父故事后续的应用/撤销不改变它。"""
    if branch_filter is None:
        branch_filter = branch_memory_filter(persona_id, db)
    batch_ids = select(MemoryConsolidationScope.consolidation_id).where(
        MemoryConsolidationScope.persona_id == persona_id)
    summaries = db.query(MemoryChunk.id).filter(
        MemoryChunk.consolidation_id.in_(batch_ids),
        branch_filter,
    ).all()
    if not summaries:
        return set(), set()
    links = db.query(MemoryConsolidationSource).filter(
        MemoryConsolidationSource.summary_id.in_([row.id for row in summaries])).all()
    source_ids = {link.source_id for link in links}
    visible_sources = {row[0] for row in db.query(MemoryChunk.id).filter(
        MemoryChunk.id.in_(source_ids), branch_filter).all()}
    sources_by_summary = defaultdict(set)
    for link in links:
        sources_by_summary[link.summary_id].add(link.source_id)
    active_summaries, masked_sources = set(), set()
    for summary in summaries:
        sources = sources_by_summary[summary.id]
        if len(sources) >= 2 and sources <= visible_sources:
            active_summaries.add(summary.id)
            masked_sources.update(sources)
    return active_summaries, masked_sources


def memory_view(persona_id, db, before_message_id=None):
    """每次操作只解析一次整理和分支状态，返回可见 SQL 条件与收起的原卡 ID。"""
    branch_filter = branch_memory_filter(persona_id, db, before_message_id)
    summary_ids, masked_sources = consolidation_state(persona_id, db, branch_filter)
    visible_filter = and_(branch_filter, or_(
        MemoryChunk.consolidation_id.is_(None), MemoryChunk.id.in_(summary_ids)))
    replacements = db.query(MemoryChunk.supersedes_id).filter(
        visible_filter, MemoryChunk.supersedes_id.isnot(None)).all()
    return visible_filter, masked_sources | {row[0] for row in replacements}


def inherit_consolidation_scope(parent_id, child_id, db):
    for row in db.query(MemoryConsolidationScope).filter_by(persona_id=parent_id).all():
        db.add(MemoryConsolidationScope(persona_id=child_id, consolidation_id=row.consolidation_id))
    db.flush()
    # 旧分叉点不一定看得到父故事现有的整理，不能保留完全无效的关联。
    active_summaries, _ = consolidation_state(child_id, db)
    valid_batches = select(MemoryChunk.consolidation_id).where(MemoryChunk.id.in_(active_summaries))
    db.query(MemoryConsolidationScope).filter(
        MemoryConsolidationScope.persona_id == child_id,
        MemoryConsolidationScope.consolidation_id.not_in(valid_batches),
    ).delete(synchronize_session=False)


def is_consolidation_protected(memory_id, db):
    chunk = db.get(MemoryChunk, memory_id)
    if chunk is None:
        return False
    if chunk.consolidation_id is not None:
        return True
    references = db.query(MemoryConsolidationScope.persona_id, MemoryConsolidationSource.summary_id).select_from(MemoryConsolidationScope).join(
        MemoryChunk, MemoryChunk.consolidation_id == MemoryConsolidationScope.consolidation_id
    ).join(
        MemoryConsolidationSource, MemoryConsolidationSource.summary_id == MemoryChunk.id
    ).filter(MemoryConsolidationSource.source_id == memory_id).all()
    summaries_by_persona = defaultdict(set)
    for persona_id, summary_id in references:
        summaries_by_persona[persona_id].add(summary_id)
    for persona_id, summary_ids in summaries_by_persona.items():
        active_summaries, _ = consolidation_state(persona_id, db)
        if summary_ids & active_summaries:
            return True
    return False
