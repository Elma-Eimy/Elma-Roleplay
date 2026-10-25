"""进行中事件的持久缓冲、来源校验和有界收尾。"""

import json
import logging

from core.models import MemoryEventBuffer, MemoryType
from services.memory.graph_evidence import sources_are_current
from services.memory.memory_facts import merge_temporal, temporal_is_compatible


logger = logging.getLogger("uvicorn.error.memory_extraction")
MAX_OPEN_EVENTS = 3
MAX_EVENT_BATCHES = 3
MAX_EVENT_MESSAGES = 60


class EventBufferConflict(RuntimeError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def prune_graph_payload(payload, persona_id, db):
    """图谱辅助来源失效只移除对应图谱候选，不使事件正文失效。"""
    available = {source["id"]: source for source in payload.get("graph_sources", [])}
    kept_sources = {}
    result = dict(payload)
    for key in ("entities", "relations"):
        kept = []
        for item in payload.get(key, []):
            needed = {}
            for binding in item.get("_extra_bindings", []):
                start, end = binding.get("source_start"), binding.get("source_end")
                if start not in available or end not in available:
                    needed = None
                    break
                needed.update({mid: source for mid, source in available.items() if start <= mid <= end})
            if needed is None or (needed and not sources_are_current(persona_id, list(needed.values()), db)):
                continue
            kept.append(item)
            kept_sources.update(needed)
        result[key] = kept
    result["graph_sources"] = list(kept_sources.values())
    return result


def load_event_snapshot(persona_id, db, before_message_id=None):
    """返回脱离 ORM 的快照，不将父故事的未来缓冲注入当前故事。"""
    snapshot = []
    for row in db.query(MemoryEventBuffer).filter_by(persona_id=persona_id).order_by(MemoryEventBuffer.id).all():
        try:
            payload = json.loads(row.payload_json)
            sources = payload["sources"]
            valid = bool(sources) and sources_are_current(persona_id, sources, db)
            if before_message_id is not None:
                valid = valid and max(source["id"] for source in sources) < before_message_id
            if valid:
                payload = prune_graph_payload(payload, persona_id, db)
        except (TypeError, ValueError, KeyError):
            payload, valid = None, False
        snapshot.append({"id": row.id, "revision": row.revision, "payload": payload,
                         "age": row.age_batches, "valid": valid})
    return snapshot


def event_context(snapshot):
    return [{"buffer_id": item["id"], "content": item["payload"]["card"]["content"],
             "temporal_status": item["payload"]["card"]["temporal_status"],
             "temporal_note": item["payload"]["card"]["temporal_note"]}
            for item in snapshot if item["valid"]]


def assert_event_snapshot(persona_id, snapshot, db):
    actual = db.query(MemoryEventBuffer).populate_existing().filter_by(persona_id=persona_id).all()
    if {row.id: row.revision for row in actual} != {item["id"]: item["revision"] for item in snapshot}:
        raise EventBufferConflict("event_snapshot_changed")
    for item in snapshot:
        if item["valid"]:
            if not sources_are_current(persona_id, item["payload"]["sources"], db):
                raise EventBufferConflict("event_sources_changed")


def _buffered_card_graph(items, index, total):
    """提取与当前缓冲事件相关的图谱项。

    单卡支持项直接绑定 [0]；同时引用本批其他卡片的多卡支持项记录 _pending_indices，
    在本批已落库卡片完成绑定后补齐 _extra_bindings，绝不把多卡依据降级为单卡。
    """
    staged = []
    for item in items:
        if not isinstance(item, dict):
            continue
        indices = item.get("memory_indices", list(range(total)))
        if not isinstance(indices, list) or not indices or any(type(i) is not int for i in indices):
            continue
        unique = sorted(set(indices))
        if index not in unique:
            continue
        other = [i for i in unique if i != index]
        entry = {**item, "memory_indices": [0]}
        if other:
            entry["_pending_indices"] = other
        staged.append(entry)
    return staged


def resolve_graph_dependencies(items, memory_bindings):
    """缓冲项和本批收尾项共用绑定规则；依据不足的多卡图谱不发布。"""
    resolved = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if "_pending_indices" not in item:
            resolved.append(item)
            continue
        pending = item["_pending_indices"]
        if (not isinstance(pending, list) or any(type(index) is not int for index in pending)
                or any(index not in memory_bindings for index in pending)):
            continue
        extra = item.get("_extra_bindings", [])
        if not isinstance(extra, list):
            continue
        clean = {key: value for key, value in item.items() if key != "_pending_indices"}
        clean["_extra_bindings"] = extra + [memory_bindings[index] for index in sorted(set(pending))]
        resolved.append(clean)
    return resolved


def bind_buffered_graph_dependencies(persona_id, memory_bindings, db):
    """将本批已落库卡片的证据绑定写入进行中事件的跨卡图谱候选中。"""
    for row in db.query(MemoryEventBuffer).filter_by(persona_id=persona_id).all():
        payload = json.loads(row.payload_json)
        changed = False
        for key in ("entities", "relations"):
            original = payload.get(key, [])
            payload[key] = resolve_graph_dependencies(original, memory_bindings)
            changed = changed or payload[key] != original
        if changed:
            row.payload_json = json.dumps(payload, ensure_ascii=False)
    db.flush()


def plan_events(parsed, entities, relations, sources, snapshot, *, force=False, advance=True, batch_id=0):
    """纯内存规划；模型和向量检索前不写入数据库。"""
    pending = {item["id"]: dict(item) for item in snapshot if item["valid"]}
    original_ids = set(pending)
    ready = []
    extra_entities, extra_relations = [], []
    touched = set()
    buffered = 0
    flushed = 0

    def release(item, index=None):
        nonlocal flushed
        payload = item["payload"]
        index = -1 - flushed if index is None else index
        card = {**payload["card"], "_extraction_index": index, "_source_evidence": payload["sources"]}
        ready.append(card)
        extra_entities.extend({**entry, "memory_indices": [index]} for entry in payload["entities"])
        extra_relations.extend({**entry, "memory_indices": [index]} for entry in payload["relations"])
        flushed += 1

    for card in parsed:
        buffer_id = card.get("_buffer_id")
        state = card.get("_event_status", "complete")
        if buffer_id is not None and (type(buffer_id) is not int or buffer_id not in original_ids or buffer_id in touched):
            raise EventBufferConflict("invalid_or_repeated_buffer_id")
        if card["memory_type"] != MemoryType.event:
            if buffer_id is not None or state != "complete":
                raise EventBufferConflict("non_event_buffer")
            ready.append(card)
            continue
        if state not in {"ongoing", "complete"}:
            raise EventBufferConflict("invalid_event_status")
        old = pending.pop(buffer_id, None)
        resolved_status = card["temporal_status"]
        resolved_note = card["temporal_note"]
        if old:
            touched.add(buffer_id)
            old_card = old["payload"]["card"]
            if not temporal_is_compatible(
                old_card["temporal_status"], old_card["temporal_note"],
                card["temporal_status"], card["temporal_note"],
            ):
                raise EventBufferConflict("event_temporal_mismatch")
            resolved_status, resolved_note = merge_temporal(
                old_card["temporal_status"], old_card["temporal_note"],
                card["temporal_status"], card["temporal_note"],
            )
        current_sources = [source for source in sources
                           if card["source_start_message_id"] <= source["id"] <= card["source_message_id"]]
        evidence = {source["id"]: source for source in
                    (old["payload"]["sources"] if old else card.get("_prior_sources", [])) + current_sources}
        evidence = [evidence[mid] for mid in sorted(evidence)]
        stored_card = {key: value for key, value in card.items() if not key.startswith("_")}
        stored_card["memory_type"] = "event"
        stored_card["temporal_status"] = resolved_status
        stored_card["temporal_note"] = resolved_note
        stored_card["source_start_message_id"] = evidence[0]["id"]
        stored_card["source_message_id"] = evidence[-1]["id"]
        stored_card["importance_score"] = max(stored_card["importance_score"],
                                               old["payload"]["card"]["importance_score"] if old else 0)
        staged_entities = _buffered_card_graph(entities, card["_extraction_index"], len(parsed))
        staged_relations = _buffered_card_graph(relations, card["_extraction_index"], len(parsed))
        has_cross_card_graph = any(
            "_pending_indices" in entry for entry in staged_entities + staged_relations
        )
        graph_sources = list({
            s["id"]: s
            for s in ((old["payload"].get("graph_sources", []) if old else []) + (sources if has_cross_card_graph else []))
        }.values())
        payload = {"card": stored_card, "sources": evidence,
                   "graph_sources": graph_sources,
                   "entities": staged_entities,
                   "relations": staged_relations}
        previous_batch = old["payload"].get("last_batch_id", 0) if old else 0
        payload["last_batch_id"] = max(batch_id, previous_batch)
        age = old["age"] + int(advance and batch_id > previous_batch) if old else 1
        should_close = force or state == "complete" or age >= MAX_EVENT_BATCHES or len(evidence) >= MAX_EVENT_MESSAGES
        if should_close:
            ready.append({**stored_card, "memory_type": MemoryType.event,
                          "_extraction_index": card["_extraction_index"], "_source_evidence": evidence})
            if old:
                flushed += 1
        else:
            if old:
                item = {**old, "age": age, "payload": payload}
            else:
                item = {"id": -1 - card["_extraction_index"], "age": age, "payload": payload, "valid": True}
            pending[item["id"]] = item
            touched.add(item["id"])
            buffered += 1

    for buffer_id, item in list(pending.items()):
        if buffer_id not in touched and advance and batch_id > item["payload"].get("last_batch_id", 0):
            item["age"] += 1
            item["payload"] = {**item["payload"], "last_batch_id": batch_id}
        if force or item["age"] >= MAX_EVENT_BATCHES or len(item["payload"]["sources"]) >= MAX_EVENT_MESSAGES:
            release(item)
            del pending[buffer_id]
    while len(pending) > MAX_OPEN_EVENTS:
        buffer_id = min(pending, key=lambda key: (key < 0, abs(key)))
        release(pending.pop(buffer_id))
    for card in ready:
        if isinstance(card["memory_type"], str):
            card["memory_type"] = MemoryType(card["memory_type"])
    return {"ready": ready, "entities": extra_entities, "relations": extra_relations,
            "pending": list(pending.values()), "snapshot": snapshot,
            "stats": {"buffered": buffered, "flushed": flushed, "open": len(pending)}}


def apply_event_plan(persona_id, plan, db):
    assert_event_snapshot(persona_id, plan["snapshot"], db)
    retained = {item["id"] for item in plan["pending"] if item["id"] > 0}
    for item in plan["snapshot"]:
        if item["id"] not in retained:
            db.delete(db.get(MemoryEventBuffer, item["id"]))
    for item in plan["pending"]:
        if item["id"] > 0:
            row = db.get(MemoryEventBuffer, item["id"])
            row.revision += 1
        else:
            row = MemoryEventBuffer(persona_id=persona_id)
            db.add(row)
        row.payload_json = json.dumps(item["payload"], ensure_ascii=False)
        row.age_batches = item["age"]
    db.flush()


def flush_before_fork(persona, fork_message_id, db):
    """分叉作为事件边界；仅收尾完整落在分叉点之前的有效父故事缓冲。"""
    from services.memory.memory_manager import add_memory_chunk
    from services.memory.graph_service import upsert_graph_data
    from services.memory.graph_evidence import content_fingerprint

    for item in load_event_snapshot(persona.id, db):
        all_sources = list({
            s["id"]: s
            for s in (item["payload"]["sources"] + item["payload"].get("graph_sources", []))
        }.values()) if item["payload"] else []
        if not item["valid"] or max(source["id"] for source in all_sources) > fork_message_id:
            continue
        payload = item["payload"]
        card = payload["card"]
        chunk = add_memory_chunk(persona_id=persona.id, character_id=persona.character_id,
                                 origin_session_id=persona.session_id, db=db, auto_commit=False,
                                 source_evidence=payload["sources"], **card)
        upsert_graph_data(persona_id=persona.id, entities=payload["entities"], relations=payload["relations"],
                          db=db, source_messages=all_sources, memory_bindings={0: {
                              "memory_id": chunk.id, "hash": content_fingerprint(chunk.content),
                              "source_start": card["source_start_message_id"], "source_end": card["source_message_id"]}})
        db.delete(db.get(MemoryEventBuffer, item["id"]))
        logger.info("[MEMORY EXTRACTION] event_flushed_for_fork persona_id=%s buffer_id=%s memory_id=%s",
                    persona.id, item["id"], chunk.id)
