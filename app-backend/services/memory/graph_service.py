"""Lightweight branch-aware Graph RAG storage and retrieval."""

from __future__ import annotations

import json
import unicodedata
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.orm import Session

from core.config import settings
from core.models import GraphEntity, GraphRelation, SessionPersona, MemoryChunk
from services.memory.persona_lineage import get_ancestor_persona_ids
from services.memory.graph_evidence import GraphEvidenceWriter, load_graph_view


GENERIC_ALIAS_KEYS = {
    "他", "她", "它", "他们", "她们", "它们", "这里", "那里", "这儿", "那儿",
    "这个", "那个", "这件事", "那件事", "对方", "某人", "someone", "somebody",
    "he", "she", "it", "they", "here", "there", "this", "that",
}
MAX_ALIASES_PER_ENTITY = 8
MAX_ALIAS_CHARS = 50


@dataclass(frozen=True)
class EntityView:
    id: int
    persona_id: int
    name: str
    aliases: str | None
    entity_type: str
    description: str | None
    memory_ids: tuple[int, ...]


@dataclass(frozen=True)
class GraphRecall:
    context: str = ""
    memory_ids: tuple[int, ...] = ()
    relation_count: int = 0


def _memory_ids(row):
    # Only called on rows already validated by load_graph_view.
    return tuple(item["id"] for item in json.loads(row.evidence_json)["memories"])


def normalize_entity_name(value: object) -> str:
    """Normalize a display name for matching, without changing stored text."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return "".join(char for char in text if char.isalnum())


def _load_aliases(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        values = raw
    elif isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            values = parsed if isinstance(parsed, list) else []
        except (TypeError, ValueError, json.JSONDecodeError):
            values = []
    else:
        values = []
    return [str(value).strip() for value in values if str(value).strip()]


def sanitize_entity_aliases(raw: object, canonical_name: str) -> list[str]:
    canonical_key = normalize_entity_name(canonical_name)
    generic_keys = {normalize_entity_name(value) for value in GENERIC_ALIAS_KEYS}
    aliases = []
    seen = {canonical_key}
    for alias in _load_aliases(raw):
        if len(alias) > MAX_ALIAS_CHARS:
            continue
        key = normalize_entity_name(alias)
        if not key or key in seen or key in generic_keys:
            continue
        aliases.append(alias)
        seen.add(key)
        if len(aliases) >= MAX_ALIASES_PER_ENTITY:
            break
    return aliases


def _dump_aliases(aliases: list[str]) -> str | None:
    return json.dumps(aliases, ensure_ascii=False) if aliases else None


def _entity_match_keys(entity: GraphEntity | EntityView) -> set[str]:
    keys = {normalize_entity_name(entity.name)}
    keys.update(normalize_entity_name(alias) for alias in _load_aliases(entity.aliases))
    return {key for key in keys if key}


def _relation_type_key(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "related")).casefold().strip()


def upsert_graph_data(
    persona_id: int,
    entities: list[dict],
    relations: list[dict],
    db: Session,
    *,
    source_messages: list[dict] | None = None,
    memory_bindings: dict | None = None,
):
    """Append evidence-backed versions; the caller owns the transaction."""
    writer = GraphEvidenceWriter(persona_id, source_messages, memory_bindings, db)
    if not writer.valid or not memory_bindings:
        return
    ancestor_ids = get_ancestor_persona_ids(persona_id, db) or [persona_id]
    priority = {pid: index for index, pid in enumerate(ancestor_ids)}
    old_entities, _ = load_graph_view(persona_id, db)
    effective = list(_effective_entities(old_entities, priority).values())

    def identity(raw_name):
        name = str(raw_name or "").strip()
        if not normalize_entity_name(name):
            return None, None
        # 别名用于召回，不能把旧别名推断复制为不带其原始依据的新身份事实。
        known = next((entity for entity in effective
                      if normalize_entity_name(entity.name) == normalize_entity_name(name)), None)
        return (known.name if known else name), known

    for raw in entities or []:
        if not isinstance(raw, dict):
            continue
        evidence = writer.evidence_for(raw)
        name, known = identity(raw.get("name"))
        if evidence is None or name is None:
            continue
        # 别名只存本次明确提供的值；历史别名在有效视图中按各自证据合并。
        aliases = sanitize_entity_aliases(raw.get("aliases"), name)
        entity = GraphEntity(
            persona_id=persona_id, name=name,
            aliases=_dump_aliases(aliases),
            entity_type=str(raw.get("entity_type") or (known.entity_type if known else "concept")),
            description=str(raw.get("description") or "").strip(),
            is_stub=False, **evidence,
        )
        db.add(entity)
        db.flush()
        old_entities.append(entity)
        effective = list(_effective_entities(old_entities, priority).values())

    # 每条边使用相同证据下的身份桩，不把其他事实的描述复制成新的证据。
    stubs = {}
    for raw in relations or []:
        if not isinstance(raw, dict):
            continue
        evidence = writer.evidence_for(raw)
        if evidence is None:
            continue
        source_name, source_known = identity(raw.get("source"))
        target_name, target_known = identity(raw.get("target"))
        if source_name is None or target_name is None:
            continue
        endpoints = []
        for name, known in ((source_name, source_known), (target_name, target_known)):
            key = (name, evidence["evidence_json"])
            if key not in stubs:
                entity = GraphEntity(
                    persona_id=persona_id, name=name,
                    entity_type="concept",
                    description="", is_stub=True, **evidence,
                )
                db.add(entity)
                db.flush()
                stubs[key] = entity
            endpoints.append(stubs[key])
        try:
            importance = max(0.0, min(1.0, float(raw.get("importance", 0.5))))
        except (TypeError, ValueError):
            importance = 0.5
        db.add(GraphRelation(
            persona_id=persona_id, source_id=endpoints[0].id, target_id=endpoints[1].id,
            relation_type=str(raw.get("relation_type") or "related").strip(),
            description=str(raw.get("description") or "").strip(),
            importance=importance, **evidence,
        ))
    db.flush()


def _effective_entities(
    entities: list[GraphEntity],
    persona_priority: dict[int, int],
) -> dict[str, EntityView]:
    effective: dict[str, GraphEntity] = {}
    for entity in sorted(
        entities,
        key=lambda item: (bool(item.is_stub), persona_priority.get(item.persona_id, 999),
                          -(item.source_message_id_bound or 0), -item.id),
    ):
        key = normalize_entity_name(entity.name)
        if key and key not in effective:
            effective[key] = entity
    aliases = defaultdict(list)
    for entity in sorted(entities, key=lambda item: (
        persona_priority.get(item.persona_id, 999), -(item.source_message_id_bound or 0), -item.id,
    )):
        aliases[normalize_entity_name(entity.name)].extend(_load_aliases(entity.aliases))
    return {key: EntityView(entity.id, entity.persona_id, entity.name,
                           _dump_aliases(sanitize_entity_aliases(aliases[key], entity.name)),
                           entity.entity_type, entity.description, _memory_ids(entity))
            for key, entity in effective.items()}


def retrieve_graph_recall(
    persona_id: int, query_text: str, db: Session, *, before_message_id: int | None = None,
    seed_memory_ids: tuple[int, ...] = (),
) -> GraphRecall:
    """Match canonical names/aliases and return deterministic true 1/2-hop context."""
    if not query_text:
        return GraphRecall()

    ancestor_ids = get_ancestor_persona_ids(persona_id, db) or [persona_id]
    persona_priority = {pid: index for index, pid in enumerate(ancestor_ids)}
    entities, relations = load_graph_view(persona_id, db, before_message_id)
    if not entities:
        return GraphRecall()

    effective_entities = _effective_entities(entities, persona_priority)
    query_key = normalize_entity_name(query_text)
    matched_keys = set()
    seeds = set(seed_memory_ids)
    # 语义命中卡关联的实体也可以成为种子；不要求用户问题写出实体名。
    seeded_keys = {normalize_entity_name(entity.name) for entity in entities
                   if seeds.intersection(_memory_ids(entity))}
    for canonical_key, entity in effective_entities.items():
        match_keys = _entity_match_keys(entity)
        if canonical_key in seeded_keys or any(key and key in query_key for key in match_keys):
            matched_keys.add(canonical_key)
    if not matched_keys:
        return GraphRecall()

    entity_by_id = {entity.id: entity for entity in entities}
    support_ids = {mid for relation in relations for mid in _memory_ids(relation)}
    temporal = {row.id: (row.temporal_status, row.temporal_note or "")
                for row in db.query(MemoryChunk).filter(MemoryChunk.id.in_(support_ids)).all()}
    # 将继承的写时复制（COW）ID 合并为名称级别的有效三元组（triples）。
    effective_relations: dict[tuple[str, str, str], GraphRelation] = {}
    for relation in sorted(
        relations,
        key=lambda item: (persona_priority.get(item.persona_id, 999),
                          -(item.source_message_id_bound or 0), -item.id),
    ):
        source = entity_by_id.get(relation.source_id)
        target = entity_by_id.get(relation.target_id)
        if source is None or target is None:
            continue
        source_key = normalize_entity_name(source.name)
        target_key = normalize_entity_name(target.name)
        if source_key not in effective_entities or target_key not in effective_entities:
            continue
        # 相同边的计划、历史与当前版本并存，不能按较新的写入时间互相覆盖。
        temporal_key = sorted({temporal[mid] for mid in _memory_ids(relation) if mid in temporal})
        relation_key = json.dumps([_relation_type_key(relation.relation_type), temporal_key], ensure_ascii=False)
        triple = (source_key, relation_key, target_key)
        if triple not in effective_relations:
            effective_relations[triple] = relation

    adjacency: dict[str, list[tuple[tuple[str, str, str], GraphRelation, str]]] = defaultdict(list)
    for triple, relation in effective_relations.items():
        if (relation.importance or 0.0) < settings.APP_GRAPH_MIN_IMPORTANCE:
            continue
        source_key, _, target_key = triple
        adjacency[source_key].append((triple, relation, target_key))
        adjacency[target_key].append((triple, relation, source_key))

    persona = db.get(SessionPersona, persona_id)
    character_name = persona.character.name if persona and persona.character else ""
    hub_keys = {normalize_entity_name("用户"), normalize_entity_name("user")}
    if character_name:
        hub_keys.add(normalize_entity_name(character_name))

    selected: dict[tuple[str, str, str], tuple[GraphRelation, int]] = {}
    first_hop_neighbors = set()
    for seed in sorted(matched_keys):
        for triple, relation, neighbor in adjacency.get(seed, []):
            selected.setdefault(triple, (relation, 1))
            if seed not in hub_keys and neighbor not in hub_keys:
                first_hop_neighbors.add(neighbor)

    for node in sorted(first_hop_neighbors):
        for triple, relation, _neighbor in adjacency.get(node, []):
            if triple not in selected:
                selected[triple] = (relation, 2)

    ranked = sorted(
        selected.items(),
        key=lambda item: (
            item[1][1],
            persona_priority.get(item[1][0].persona_id, 999),
            -(item[1][0].importance or 0.5),
            item[0][0],
            item[0][1],
            item[0][2],
            item[1][0].id,
        ),
    )[:max(0, settings.APP_GRAPH_MAX_RELATIONS)]
    described_keys = set(matched_keys)
    relation_lines = []
    memory_ids = []
    for (source_key, _relation_key, target_key), (relation, _hop) in ranked:
        described_keys.update((source_key, target_key))
        memory_ids.extend(_memory_ids(relation))
        source_name = effective_entities[source_key].name
        target_name = effective_entities[target_key].name
        if relation.description:
            relation_lines.append(f"- {relation.description}")
        else:
            relation_lines.append(
                f"- {source_name}与{target_name}的关系是: {relation.relation_type}"
            )

    entity_desc_lines = []
    for key in sorted(
        described_keys,
        key=lambda value: (
            persona_priority.get(effective_entities[value].persona_id, 999),
            effective_entities[value].name.casefold(),
            effective_entities[value].id,
        ),
    ):
        entity = effective_entities[key]
        if entity.description:
            entity_desc_lines.append(f"- {entity.name}: {entity.description}")
            memory_ids.extend(entity.memory_ids)

    output_parts = []
    if entity_desc_lines:
        output_parts.append("实体定义:")
        output_parts.extend(entity_desc_lines)
    if relation_lines:
        if output_parts:
            output_parts.append("")
        output_parts.append("关系网:")
        output_parts.extend(relation_lines)
    return GraphRecall("\n".join(output_parts), tuple(dict.fromkeys(memory_ids)), len(ranked))


def retrieve_graph_context(
    persona_id: int, query_text: str, db: Session, *, before_message_id: int | None = None,
) -> str:
    """Compatibility formatter; chat uses the shared fact records instead."""
    recalled = retrieve_graph_recall(persona_id, query_text, db, before_message_id=before_message_id)
    return recalled.context if recalled.relation_count else ""
