"""Persist candidate components, plan without write locks, and retry independently."""
import copy
import json
import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import or_, and_
from sqlalchemy.exc import IntegrityError
from core.config import settings
from core.models import MemoryExtractionJob, SessionPersona, MemoryType
from services.memory.graph_evidence import sources_are_current, memory_evidence_is_current, content_fingerprint
from services.memory.memory_event_buffer import (
    load_event_snapshot, plan_events, apply_event_plan, bind_buffered_graph_dependencies,
    resolve_graph_dependencies,
)
from services.memory.memory_facts import temporal_is_compatible, merge_temporal

logger = logging.getLogger("uvicorn.error.memory_extraction")
ACTIVE = ("pending", "processing", "retrying")


def _dump(value):
    return json.dumps(value, ensure_ascii=False)


def enqueue_candidates(persona_id, cards, entities, relations, sources, baseline, db, *, force=False):
    indices = {card["_extraction_index"] for card in cards}
    parent = {index: index for index in indices}

    def root(index):
        while parent[index] != index:
            index = parent[index]
        return index

    def join(items):
        valid = [index for index in items if type(index) is int and index in indices]
        for index in valid[1:]:
            parent[root(index)] = root(valid[0])

    # Events share a bounded working set, so their capacity decisions must commit together.
    join([card["_extraction_index"] for card in cards if card["memory_type"] == MemoryType.event])
    graph = {"entities": [], "relations": []}
    for key, items in (("entities", entities), ("relations", relations)):
        for item in items:
            if not isinstance(item, dict):
                continue
            refs = item.get("memory_indices", sorted(indices))
            if not isinstance(refs, list) or not refs or any(type(i) is not int or i not in indices for i in refs):
                continue
            join(refs)
            graph[key].append({**item, "memory_indices": sorted(set(refs))})
    groups = {}
    for card in cards:
        groups.setdefault(root(card["_extraction_index"]), []).append(card)
    if not groups:
        groups[None] = []
    jobs = []
    batch_id = None
    for component in groups.values():
        ids = {card["_extraction_index"] for card in component}
        component_sources = [source for source in sources if not component or any(
            card["source_start_message_id"] <= source["id"] <= card["source_message_id"] for card in component)]
        payload = {"cards": component, "sources": component_sources, "baseline": baseline,
                   "force": force, "advance": bool(sources), "batch_id": batch_id,
                   **{key: [item for item in items if set(item["memory_indices"]) <= ids]
                      for key, items in graph.items()}}
        job = MemoryExtractionJob(persona_id=persona_id, kind="candidates", payload_json=_dump(payload))
        db.add(job)
        db.flush()
        if batch_id is None:
            batch_id = job.id
        payload["batch_id"] = batch_id
        job.payload_json = _dump(payload)
        jobs.append(job.id)
    return jobs


def queue_capture_retry(persona_id, db, *, force=False, reason="extraction_failed"):
    db.rollback()
    key = f"capture:{persona_id}"
    job = db.query(MemoryExtractionJob).filter_by(dedupe_key=key).first()
    if job is None:
        job = MemoryExtractionJob(persona_id=persona_id, kind="capture", dedupe_key=key,
                                  payload_json=_dump({"force": force}), status="retrying" if reason else "pending")
        db.add(job)
    elif force:
        job.payload_json = _dump({"force": True})
    if reason:
        job.last_error_code = reason
    job.run_after = datetime.utcnow() + timedelta(seconds=30 if reason else 0)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(MemoryExtractionJob).filter_by(dedupe_key=key).first()
        if existing is None:
            raise
        if force:
            existing.payload_json = _dump({"force": True})
        if reason:
            existing.last_error_code = reason
        db.commit()


def request_capture(persona_id, db, *, force=False):
    """HTTP 和回合维护只可靠入队，所有模型调用交给记忆 Worker。"""
    queue_capture_retry(persona_id, db, force=force, reason=None)


def processing_status(persona_id, db):
    rows = db.query(MemoryExtractionJob.status, MemoryExtractionJob.last_error_code).filter(
        MemoryExtractionJob.persona_id == persona_id, MemoryExtractionJob.status.in_(ACTIVE)).all()
    latest = db.query(MemoryExtractionJob.status, MemoryExtractionJob.last_error_code).filter_by(persona_id=persona_id).order_by(MemoryExtractionJob.id.desc()).first()
    errors = {row.last_error_code for row in rows if row.last_error_code}
    if not rows and latest and latest.status == "cancelled" and latest.last_error_code:
        errors.add(latest.last_error_code)
    return {"status": "retrying" if any(row.status == "retrying" for row in rows) else "pending" if rows else
            "failed" if latest and latest.status == "cancelled" else "completed",
            "pending_count": len(rows), "error_codes": sorted(errors)}


def pending_context(persona_id, db, before_message_id):
    result = []
    rows = db.query(MemoryExtractionJob).filter(
        MemoryExtractionJob.persona_id == persona_id, MemoryExtractionJob.kind == "candidates",
        MemoryExtractionJob.status.in_(ACTIVE)).order_by(MemoryExtractionJob.id.desc()).limit(16).all()
    for row in rows:
        payload = json.loads(row.payload_json)
        sources = payload.get("sources", [])
        if sources and max(source["id"] for source in sources) >= before_message_id:
            continue
        for card in payload.get("cards", []):
            needed = [source for source in sources if card["source_start_message_id"] <= source["id"] <= card["source_message_id"]]
            baseline = next((item for item in payload.get("baseline", []) if item["id"] == card.get("_buffer_id")), None)
            if baseline:
                needed += baseline["payload"]["sources"]
            if needed and not sources_are_current(persona_id, needed, db):
                continue
            result.append({key: card.get(key) for key in ("content", "memory_type", "temporal_status", "temporal_note")})
            if len(result) >= 8:
                return result
    return result


def _claim(job_id, db):
    now = datetime.utcnow()
    row = db.get(MemoryExtractionJob, job_id)
    if row is None or row.status not in ACTIVE:
        db.rollback()
        return None
    if row.status == "processing" and row.lease_until and row.lease_until > now:
        db.rollback()
        return None
    busy = db.query(MemoryExtractionJob.id).filter(
        MemoryExtractionJob.persona_id == row.persona_id, MemoryExtractionJob.id != row.id,
        MemoryExtractionJob.status == "processing", MemoryExtractionJob.lease_until > now).first()
    if busy:
        db.rollback()
        return None
    token = uuid.uuid4().hex
    data = {"id": row.id, "persona_id": row.persona_id, "kind": row.kind,
            "raw": row.payload_json, "payload": json.loads(row.payload_json)}
    try:
        updated = db.query(MemoryExtractionJob).filter(
            MemoryExtractionJob.id == job_id,
            or_(MemoryExtractionJob.status.in_(("pending", "retrying")),
                and_(MemoryExtractionJob.status == "processing", MemoryExtractionJob.lease_until <= now)),
        ).update({"status": "processing", "lease_token": token,
                  "lease_until": now + timedelta(seconds=max(300, 12 * (settings.LLM_TIMEOUT * 3 + 60)))}, synchronize_session=False)
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    return {**data, "token": token} if updated else None


def _plan(data, db):
    from services.memory import memory_extraction_service as extraction
    payload = copy.deepcopy(data["payload"])
    persona_id = data["persona_id"]
    persona = db.get(SessionPersona, persona_id)
    if persona is None:
        raise ValueError("persona_deleted")
    character_id = persona.character_id
    snapshot = load_event_snapshot(persona_id, db)
    current_ids = {item["id"] for item in snapshot if item["valid"]}
    baseline = {item["id"]: item for item in payload.get("baseline", []) if item["valid"]}
    sources = list(payload.get("sources", []))
    current = {item["id"]: item for item in snapshot if item["valid"]}
    valid_cards = []
    required = []
    for card in payload["cards"]:
        card["memory_type"] = MemoryType(card["memory_type"])
        buffer_id = card.get("_buffer_id")
        if buffer_id in baseline:
            sources += baseline[buffer_id]["payload"]["sources"]
            later = current.get(buffer_id, {}).get("payload", {}).get("card", {}).get("source_message_id", 0)
            if buffer_id not in current_ids or later > card["source_message_id"]:
                card["_buffer_id"] = None
                card["_prior_sources"] = baseline[buffer_id]["payload"]["sources"]
        needed = [source for source in payload.get("sources", [])
                  if card["source_start_message_id"] <= source["id"] <= card["source_message_id"]]
        if buffer_id in baseline:
            needed += baseline[buffer_id]["payload"]["sources"]
        if needed and not sources_are_current(persona_id, needed, db):
            continue
        valid_cards.append(card)
        required += needed
    if payload["cards"] and not valid_cards:
        raise ValueError("sources_changed")
    sources = list({source["id"]: source for source in required}.values())
    plan = plan_events(valid_cards, payload["entities"], payload["relations"], sources, snapshot,
                       force=payload["force"], advance=payload["advance"], batch_id=payload["batch_id"])
    plan["required_sources"] = list(sources)
    for item in snapshot:
        if item["valid"]:
            sources += item["payload"]["sources"] + item["payload"].get("graph_sources", [])
    sources = list({source["id"]: source for source in sources}.values())
    db.rollback()
    actions, virtual, superseded = [], [], set()
    for position, card in enumerate(plan["ready"]):
        # Event checkpoints are append-only stages of a known event, never model replacements.
        if "_event_id" in card:
            actions.append({"card": card, "decision": None, "matched": None, "virtual_id": -1-position})
            continue
        candidates = extraction.retrieve_write_candidates(
            persona_id=persona_id, character_id=character_id, query=card["content"], db=db,
            memory_type=card["memory_type"], temporal_status=card["temporal_status"], temporal_note=card["temporal_note"],
            release_read=db.rollback)
        candidates = [candidate for candidate in candidates
                      if candidate["id"] not in superseded and temporal_is_compatible(candidate.get("temporal_status", "unknown"), candidate.get("temporal_note"),
                                                card["temporal_status"], card["temporal_note"],
                                                allow_missing_note=card["temporal_note"] is not None)
                      and memory_evidence_is_current(persona_id, candidate["id"], content_fingerprint(candidate["content"]), db)]
        candidates += [item for item in virtual if item["memory_type"] == card["memory_type"]
                       and temporal_is_compatible(item["temporal_status"], item["temporal_note"], card["temporal_status"], card["temporal_note"])]
        db.rollback()
        decision, matched = None, None
        if candidates:
            decision = extraction.resolve_memory_relationship_via_llm(candidates, card)
            if decision["relation"] != "coexist":
                matched = candidates[0] if len(candidates) == 1 else next(
                    item for item in candidates if item["id"] == decision["matched_memory_id"])
                merged = merge_temporal(matched.get("temporal_status", "unknown"), matched.get("temporal_note"),
                                        card["temporal_status"], card["temporal_note"])
                if decision["relation"] == "same" and merged != (matched.get("temporal_status", "unknown"), matched.get("temporal_note")):
                    decision = {"relation": "replace", "resolved_content": matched["content"]}
                old_bound, new_bound = matched.get("source_message_id"), card["source_message_id"]
                if decision["relation"] == "replace" and matched.get("event_id") is not None:
                    decision, matched = {"relation": "coexist"}, None
                elif decision["relation"] == "replace" and old_bound and new_bound and old_bound > new_bound:
                    decision = {"relation": "coexist"}
                    matched = None
                    if card["temporal_status"] == "current":
                        card["temporal_status"] = "historical"
                elif decision["relation"] == "replace":
                    card["temporal_status"], card["temporal_note"] = merged
                    score = max(card["importance_score"], matched.get("importance_score", .5))
                    card["importance_score"] = min(1., score + (1.-score)*.1)
                    superseded.add(matched["id"])
                    virtual = [item for item in virtual if item["id"] != matched["id"]]
        action = {"card": card, "decision": decision, "matched": matched, "virtual_id": -1-position}
        actions.append(action)
        if not decision or decision["relation"] != "same":
            content = decision["resolved_content"] if decision and decision["relation"] == "replace" else card["content"]
            virtual.append({**card, "id": action["virtual_id"], "content": content})
    return plan, actions, sources, character_id


def _commit(data, planned, db):
    from services.memory import memory_extraction_service as extraction
    plan, actions, sources, character_id = planned
    row = db.query(MemoryExtractionJob).populate_existing().filter_by(id=data["id"]).first()
    if row is None or row.lease_token != data["token"] or row.payload_json != data["raw"]:
        raise RuntimeError("job_changed")
    # Auxiliary graph provenance is validated per graph item; only narrative sources gate memory commits.
    required = list(plan["required_sources"])
    for action in actions:
        required += action["card"].get("_source_evidence", [])
    required = list({source["id"]: source for source in required}.values())
    if required and not sources_are_current(data["persona_id"], required, db):
        raise ValueError("sources_changed")
    for action in actions:
        matched = action["matched"]
        if matched and matched["id"] > 0 and not memory_evidence_is_current(
                data["persona_id"], matched["id"], content_fingerprint(matched["content"]), db):
            raise RuntimeError("candidate_changed")
    event_ids = apply_event_plan(data["persona_id"], plan, db)
    bindings, virtual_ids = {}, {}
    stats = {"new": 0, "replaced": 0, "reused": 0}
    for action in actions:
        card, decision, matched = action["card"], action["decision"], action["matched"]
        relation = decision["relation"] if decision else "coexist"
        matched_id = virtual_ids.get(matched["id"], matched["id"]) if matched else None
        if relation == "same":
            memory_id, content = matched_id, matched["content"]
            stats["reused"] += 1
        else:
            content = decision["resolved_content"] if relation == "replace" else card["content"]
            chunk = extraction.add_memory_chunk(
                persona_id=data["persona_id"], character_id=character_id, origin_session_id=db.get(SessionPersona, data["persona_id"]).session_id,
                content=content, memory_type=card["memory_type"], importance_score=card["importance_score"],
                source_start_message_id=card["source_start_message_id"], source_message_id=card["source_message_id"],
                supersedes_id=matched_id if relation == "replace" else None, auto_commit=False, db=db,
                temporal_status=card["temporal_status"], temporal_note=card["temporal_note"],
                event_id=event_ids.get(card.get("_event_id")),
                source_evidence=card.get("_source_evidence", [source for source in data["payload"]["sources"]
                    if card["source_start_message_id"] <= source["id"] <= card["source_message_id"]]))
            memory_id = getattr(chunk, "id", None)
            stats["replaced" if relation == "replace" else "new"] += 1
        if type(memory_id) is int:
            virtual_ids[action["virtual_id"]] = memory_id
            bindings[card["_extraction_index"]] = {"memory_id": memory_id, "hash": content_fingerprint(content),
                "source_start": card["source_start_message_id"], "source_end": card["source_message_id"]}
    bind_buffered_graph_dependencies(data["persona_id"], bindings, db)
    event_indices = {card["_extraction_index"] for card in data["payload"]["cards"]
                     if card["memory_type"] == MemoryType.event and (
                         card.get("_buffer_id") is not None or card.get("_event_status") == "ongoing")}
    def direct_graph(key):
        return [item for item in data["payload"][key] if not event_indices.intersection(item["memory_indices"])]
    entities = resolve_graph_dependencies(direct_graph("entities") + plan["entities"], bindings)
    relations = resolve_graph_dependencies(direct_graph("relations") + plan["relations"], bindings)
    if entities or relations:
        extraction.upsert_graph_data(persona_id=data["persona_id"], entities=entities, relations=relations,
                                     db=db, source_messages=sources, memory_bindings=bindings)
    row.status = "completed"
    row.payload_json = "{}"
    row.lease_token = row.lease_until = row.last_error_code = None
    row.written_count = stats["new"] + stats["replaced"]
    written = row.written_count
    db.commit()
    logger.info("[MEMORY EXTRACTION] committed job_id=%s new=%s replaced=%s reused=%s written=%s",
                data["id"], stats["new"], stats["replaced"], stats["reused"], written)
    if written and any(action["card"]["importance_score"] >= settings.APP_COGNITION_IMPORTANCE_THRESHOLD for action in actions):
        try:
            extraction.cognition_service.update_cognition_state(data["persona_id"], db)
        except Exception as exc:
            db.rollback()
            logger.warning("[MEMORY EXTRACTION] cognition_deferred error_type=%s", type(exc).__name__)
    return written


def process_job(job_id, db):
    data = _claim(job_id, db)
    if data is None:
        return 0
    try:
        if data["kind"] == "capture":
            from services.memory.memory_extraction_service import summarize_and_store_memory
            persona = db.get(SessionPersona, data["persona_id"])
            if persona is None:
                return 0
            session_id = persona.session_id
            db.rollback()
            summarize_and_store_memory(session_id, db, flush_events=data["payload"].get("force", False),
                                       _process=False, _queue_failure=False)
            from services.memory.memory_extraction_service import get_unsummarized_count
            remaining = get_unsummarized_count(session_id, db)
            row = db.get(MemoryExtractionJob, data["id"])
            if row is None or row.lease_token != data["token"]:
                db.rollback()
                return 0
            if remaining or row.payload_json != data["raw"]:
                row.status = "retrying"
                row.run_after = datetime.utcnow() + timedelta(seconds=5)
            else:
                row.status, row.dedupe_key, row.payload_json = "completed", None, "{}"
            row.last_error_code = None
            row.lease_token = row.lease_until = None
            db.commit()
            return 0
        return _commit(data, _plan(data, db), db)
    except Exception as exc:
        db.rollback()
        row = db.get(MemoryExtractionJob, data["id"])
        if row is None or row.lease_token != data["token"]:
            return 0
        row.attempts += 1
        row.status = "cancelled" if str(exc) in {"sources_changed", "persona_deleted"} else "retrying"
        row.last_error_code = str(exc) if str(exc) in {"sources_changed", "candidate_changed", "job_changed",
            "invalid_extraction_output", "extraction_failed", "capture_commit_failed"} else type(exc).__name__
        row.run_after = datetime.utcnow() + timedelta(seconds=min(3600, 15 * 2 ** min(row.attempts, 8)))
        row.lease_token = row.lease_until = None
        if row.status == "cancelled":
            row.payload_json = "{}"
            row.dedupe_key = None
        code = row.last_error_code
        db.commit()
        logger.warning("[MEMORY EXTRACTION] job_deferred job_id=%s reason=%s", data["id"], code)
        return 0


def force_pending_events(persona_id, db):
    for row in db.query(MemoryExtractionJob).filter(
            MemoryExtractionJob.persona_id == persona_id, MemoryExtractionJob.status.in_(ACTIVE)).all():
        payload = json.loads(row.payload_json)
        payload["force"] = True
        row.payload_json = _dump(payload)
        if row.status != "processing":
            row.run_after = datetime.utcnow()
    db.commit()


def process_due_jobs(db, persona_id=None, *, force=False, limit=16):
    now = datetime.utcnow()
    query = db.query(MemoryExtractionJob).filter(MemoryExtractionJob.status.in_(ACTIVE))
    if persona_id is not None:
        query = query.filter_by(persona_id=persona_id)
    if not force:
        query = query.filter(or_(
            and_(MemoryExtractionJob.status.in_(("pending", "retrying")), MemoryExtractionJob.run_after <= now),
            and_(MemoryExtractionJob.status == "processing", MemoryExtractionJob.lease_until <= now)))
    rows = query.order_by(MemoryExtractionJob.id).limit(limit).all()
    ids = [row.id for row in rows]
    if force:
        for row in rows:
            payload = json.loads(row.payload_json)
            payload["force"] = True
            row.payload_json = _dump(payload)
        db.commit()
    else:
        db.rollback()
    return sum(process_job(job_id, db) for job_id in ids)
