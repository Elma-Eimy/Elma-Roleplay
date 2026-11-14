"""按成员浏览已确认的群聊记忆，复用索引正文与事实有效性规则。"""
from sqlalchemy import text
from services.conversation.session_access import group_session_operation, check_chat_arguments
from services.memory.group_memory_index import CARD_ROWS
from services.memory.group_memory_facts import effective_facts


@group_session_operation
def list_member_memories(persona_id, db, *, q='', scope='all', status='active', limit=20, offset=0):
    check_chat_arguments({'persona_id': persona_id}, db, kind='group')
    rows = [dict(row) for row in db.execute(text(CARD_ROWS + ' AND d.persona_id=:pid ORDER BY d.id'),
                                          {'pid': persona_id}).mappings()]
    # 全卡替换与分段更正都只来自该成员、已确认采用的来源。
    rows = [row for row in rows if row['content']]
    by_id = {row['id']: row for row in rows}
    retired = {}
    for link in db.execute(text(
        'SELECT id,replaces_id FROM group_recall_cards WHERE persona_id=:pid AND replaces_id IS NOT NULL'),
        {'pid': persona_id}):
        old, new = by_id.get(link.replaces_id), by_id.get(link.id)
        if old is None or new is None or (new['round_index'] or 0) <= (old['round_index'] or 0):
            continue
        key = (old['content'].strip(), old['memory_type'], old['temporal_status'], old['temporal_note'] or '')
        retired[key] = max(retired.get(key, 0), new['round_index'])
    visible = [row for row in rows if (row['round_index'] or 0) >= retired.get(
        (row['content'].strip(), row['memory_type'], row['temporal_status'], row['temporal_note'] or ''), 0)]
    active = {row['id']: row for row in effective_facts(visible)}
    items = []
    for row in rows:
        effective = active.get(row['id'])
        item = effective or row
        if not item.get('content'):
            continue
        items.append(dict(id=row['id'], content=item['content'], memory_type=row['memory_type'] or 'fact',
            importance_score=row['importance_score'] if row['importance_score'] is not None else 0.8,
            is_local=row['round_index'] is not None, is_superseded=effective is None,
            created_at=None, indexed=bool(row['indexed'])))
    query = q.strip().casefold()
    items = [row for row in items if not query or query in row['content'].casefold()]
    facets = dict(effective_total=sum(not row['is_superseded'] for row in items),
        local_active=sum(row['is_local'] and not row['is_superseded'] for row in items),
        inherited_active=sum(not row['is_local'] and not row['is_superseded'] for row in items),
        superseded=sum(row['is_superseded'] for row in items))
    selected = [row for row in reversed(items)
        if (scope == 'all' or row['is_local'] == (scope == 'local'))
        and (status == 'all' or row['is_superseded'] == (status == 'superseded'))]
    return dict(items=selected[offset:offset+limit], total=len(selected), limit=limit, offset=offset,
                has_more=offset+limit < len(selected), facets=facets)
