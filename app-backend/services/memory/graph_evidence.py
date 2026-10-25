"""Validate graph evidence against the branch's authoritative SQLite history."""
from __future__ import annotations

import hashlib
import json
from sqlalchemy import and_, or_, func
from core.models import ChatMessage, GraphEntity, GraphRelation, MemoryChunk, MessageRole, SessionPersona
from services.memory.memory_visibility import memory_view
from services.memory.persona_lineage import build_branch_turn_segments


def content_fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def message_fingerprint(message) -> str:
    role = getattr(message.role, "value", message.role)
    return content_fingerprint(str(role) + "\n" + message.content)


def snapshot_sources(messages) -> list[dict]:
    return [{"id": message.id, "hash": message_fingerprint(message)} for message in messages]


def sources_are_current(persona_id, sources, db):
    expected = {item["id"]: item for item in sources or []}
    persona = db.get(SessionPersona, persona_id)
    session_id = persona.session_id if persona else -1
    actual = db.query(ChatMessage).populate_existing().filter(
        ChatMessage.id.in_(expected), ChatMessage.session_id == session_id,
        ChatMessage.is_active.is_(True),
        ChatMessage.role.in_((MessageRole.user, MessageRole.assistant))).all()
    latest_user = db.query(ChatMessage.id).filter(
        ChatMessage.session_id == session_id, ChatMessage.is_active.is_(True),
        ChatMessage.role == MessageRole.user).order_by(ChatMessage.id.desc()).first()
    return (bool(expected) and len(actual) == len(expected) and latest_user is not None
            and all(message.id < latest_user.id and
                    message_fingerprint(message) == expected[message.id]["hash"] for message in actual))


def _parse_evidence(raw):
    try:
        data = json.loads(raw or "null")
        if not isinstance(data, dict) or data.get("version") != 1:
            return None
        for key in ("messages", "memories"):
            items = data.get(key)
            if not isinstance(items, list) or not items:
                return None
            if any(not isinstance(item, dict) or type(item.get("id")) is not int
                   or not isinstance(item.get("hash"), str) or len(item["hash"]) != 64
                   for item in items):
                return None
        return data
    except (TypeError, ValueError):
        return None


def _supporting_memories(persona_id, ids, db, before_message_id=None):
    visible, _ = memory_view(persona_id, db, before_message_id)
    # 整理仅压缩召回表示，原卡仍是有效证据；真正的版本替代会使旧证据失效。
    replaced = {row[0] for row in db.query(MemoryChunk.supersedes_id).filter(
        visible, MemoryChunk.supersedes_id.isnot(None)).all()}
    return {row.id: row for row in db.query(MemoryChunk).populate_existing().filter(
        visible, MemoryChunk.id.in_(ids), MemoryChunk.id.not_in(replaced)).all()}


def memory_evidence_is_current(persona_id, memory_id, fingerprint, db):
    from services.memory.memory_facts import fact_sources_current

    memory = _supporting_memories(persona_id, [memory_id], db).get(memory_id)
    return (memory is not None and content_fingerprint(memory.content) == fingerprint
            and fact_sources_current(memory, db))


def load_graph_view(persona_id, db, before_message_id=None):
    segments = build_branch_turn_segments(persona_id, db)
    sessions = {segment["persona_id"]: segment["session_id"] for segment in segments}

    def scope(model):
        conditions = []
        for index, segment in enumerate(segments):
            condition = model.persona_id == segment["persona_id"]
            if index:
                boundary = segment["through_message_id"]
                if boundary is None:
                    continue
                condition = and_(condition, model.source_message_id_bound <= boundary)
            elif before_message_id is not None:
                condition = and_(condition, model.source_message_id_bound < before_message_id)
            conditions.append(condition)
        return and_(model.evidence_json.isnot(None), model.source_message_id_bound.isnot(None),
                    or_(*conditions) if conditions else model.id == -1)

    entities = db.query(GraphEntity).filter(scope(GraphEntity)).all()
    relations = db.query(GraphRelation).filter(scope(GraphRelation)).all()
    parsed = {id(row): _parse_evidence(row.evidence_json) for row in entities + relations}
    evidence = [data for data in parsed.values() if data]
    memory_ids = {item["id"] for data in evidence for item in data["memories"]}
    message_ids = {item["id"] for data in evidence for item in data["messages"]}
    memories = _supporting_memories(persona_id, memory_ids, db, before_message_id) if memory_ids else {}
    messages = {row.id: row for row in db.query(ChatMessage).populate_existing().filter(
        ChatMessage.id.in_(message_ids), ChatMessage.is_active.is_(True),
        ChatMessage.role.in_((MessageRole.user, MessageRole.assistant))).all()} if message_ids else {}
    confirmed_bounds = dict(db.query(ChatMessage.session_id, func.max(ChatMessage.id)).filter(
        ChatMessage.session_id.in_(sessions.values()), ChatMessage.is_active.is_(True),
        ChatMessage.role == MessageRole.user).group_by(ChatMessage.session_id).all())

    def valid(row):
        data = parsed[id(row)]
        if not data:
            return False
        confirmed = confirmed_bounds.get(sessions.get(row.persona_id))
        if confirmed is None or row.source_message_id_bound >= confirmed:
            return False
        ids = [item["id"] for item in data["messages"]]
        if min(ids) != row.source_start_message_id or max(ids) != row.source_message_id_bound:
            return False
        for item in data["messages"]:
            message = messages.get(item["id"])
            if (message is None or message.session_id != sessions.get(row.persona_id)
                    or message_fingerprint(message) != item["hash"]):
                return False
        return all(item["id"] in memories and
                   content_fingerprint(memories[item["id"]].content) == item["hash"]
                   for item in data["memories"])

    return [row for row in entities if valid(row)], [row for row in relations if valid(row)]


class GraphEvidenceWriter:
    def __init__(self, persona_id, sources, bindings, db):
        self.persona_id = persona_id
        self.db = db
        self.sources = {item["id"]: item for item in sources or []}
        self.bindings = bindings or {}
        self.memories = _supporting_memories(persona_id, {
            item["memory_id"] for item in self.bindings.values()}, db) if self.bindings else {}
        self.valid = bool(self.sources)

    def evidence_for(self, item):
        if not self.valid or not self.bindings:
            return None
        if item.get("_pending_indices"):
            return None
        indices = item.get("memory_indices", sorted(self.bindings))
        if (not isinstance(indices, list) or not indices or
                any(type(index) is not int or index not in self.bindings for index in indices)):
            return None
        extra_bindings = item.get("_extra_bindings") or []
        if not isinstance(extra_bindings, list):
            return None
        missing_ids = {
            b["memory_id"] for b in extra_bindings
            if isinstance(b, dict) and type(b.get("memory_id")) is int and b["memory_id"] not in self.memories
        }
        if missing_ids:
            self.memories.update(_supporting_memories(self.persona_id, missing_ids, self.db))
        selected = [self.bindings[index] for index in sorted(set(indices))] + list(extra_bindings)
        messages, memories = {}, {}
        for binding in selected:
            if not isinstance(binding, dict) or type(binding.get("memory_id")) is not int:
                return None
            memory = self.memories.get(binding["memory_id"])
            if memory is None or content_fingerprint(memory.content) != binding.get("hash"):
                return None
            start, end = binding.get("source_start"), binding.get("source_end")
            if start not in self.sources or end not in self.sources or start > end:
                return None
            messages.update({mid: source for mid, source in self.sources.items() if start <= mid <= end})
            memories[memory.id] = {"id": memory.id, "hash": binding["hash"]}
        ids = sorted(messages)
        if not sources_are_current(self.persona_id, list(messages.values()), self.db):
            return None
        data = {"version": 1, "messages": [messages[mid] for mid in ids],
                "memories": [memories[mid] for mid in sorted(memories)]}
        return {"source_start_message_id": ids[0], "source_message_id_bound": ids[-1],
                "evidence_json": json.dumps(data, ensure_ascii=False, sort_keys=True)}
