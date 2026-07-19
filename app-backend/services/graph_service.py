"""Lightweight branch-aware Graph RAG storage and retrieval."""

from __future__ import annotations

import json
import unicodedata
from collections import defaultdict
from typing import Iterable

from sqlalchemy.orm import Session

from core.config import settings
from core.models import GraphEntity, GraphRelation, SessionPersona
from services.memory_manager import get_ancestor_persona_ids


GENERIC_ALIAS_KEYS = {
    "他", "她", "它", "他们", "她们", "它们", "这里", "那里", "这儿", "那儿",
    "这个", "那个", "这件事", "那件事", "对方", "某人", "someone", "somebody",
    "he", "she", "it", "they", "here", "there", "this", "that",
}
MAX_ALIASES_PER_ENTITY = 8
MAX_ALIAS_CHARS = 50


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


def _entity_match_keys(entity: GraphEntity) -> set[str]:
    keys = {normalize_entity_name(entity.name)}
    keys.update(normalize_entity_name(alias) for alias in _load_aliases(entity.aliases))
    return {key for key in keys if key}


def _find_matching_entity(
    entities: Iterable[GraphEntity],
    name: str,
    persona_priority: dict[int, int] | None = None,
) -> GraphEntity | None:
    key = normalize_entity_name(name)
    if not key:
        return None
    matches = [entity for entity in entities if key in _entity_match_keys(entity)]
    if not matches:
        return None
    if persona_priority is None:
        return min(matches, key=lambda entity: entity.id)
    return min(
        matches,
        key=lambda entity: (persona_priority.get(entity.persona_id, 999), entity.id),
    )


def _merge_aliases(existing: object, incoming: object, canonical_name: str) -> list[str]:
    return sanitize_entity_aliases(
        _load_aliases(existing) + _load_aliases(incoming),
        canonical_name,
    )


def _relation_type_key(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "related")).casefold().strip()


def upsert_graph_data(
    persona_id: int,
    entities: list[dict],
    relations: list[dict],
    db: Session,
):
    """Write current-branch entities and relations without semantic adjudication."""
    ancestor_ids = get_ancestor_persona_ids(persona_id, db) or [persona_id]
    persona_priority = {pid: index for index, pid in enumerate(ancestor_ids)}
    chain_entities = db.query(GraphEntity).filter(
        GraphEntity.persona_id.in_(ancestor_ids)
    ).all()
    current_entities = [entity for entity in chain_entities if entity.persona_id == persona_id]
    entity_lookup: dict[str, GraphEntity] = {}

    def register(entity: GraphEntity) -> None:
        for key in _entity_match_keys(entity):
            entity_lookup[key] = entity

    for entity in current_entities:
        register(entity)

    def ensure_local_entity(
        name: str,
        entity_type: str = "",
        description: str = "",
        aliases: object = None,
        extracted: bool = False,
    ) -> GraphEntity | None:
        display_name = str(name or "").strip()
        key = normalize_entity_name(display_name)
        if not key:
            return None

        existing = entity_lookup.get(key) or _find_matching_entity(current_entities, display_name)
        if existing is not None:
            if description:
                existing.description = description
            if entity_type:
                existing.entity_type = entity_type
            merged_aliases = _merge_aliases(existing.aliases, aliases, existing.name)
            existing.aliases = _dump_aliases(merged_aliases)
            register(existing)
            return existing

        ancestor = _find_matching_entity(
            (entity for entity in chain_entities if entity.persona_id != persona_id),
            display_name,
            persona_priority,
        )
        effective_name = ancestor.name if ancestor is not None else display_name
        effective_type = entity_type or (
            ancestor.entity_type if ancestor is not None else "concept"
        )
        effective_description = (
            description
            or (ancestor.description if ancestor is not None else "")
            or ("" if extracted else f"关于 {display_name} 的概念或事物。")
        )
        merged_aliases = _merge_aliases(
            ancestor.aliases if ancestor is not None else None,
            aliases,
            effective_name,
        )
        entity = GraphEntity(
            persona_id=persona_id,
            name=effective_name,
            aliases=_dump_aliases(merged_aliases),
            entity_type=effective_type,
            description=effective_description,
        )
        db.add(entity)
        db.flush()
        current_entities.append(entity)
        chain_entities.append(entity)
        register(entity)
        # Also resolve the exact relation spelling used in this batch.
        entity_lookup[key] = entity
        return entity

    for raw_entity in entities or []:
        if not isinstance(raw_entity, dict):
            continue
        ensure_local_entity(
            name=raw_entity.get("name", ""),
            entity_type=str(raw_entity.get("entity_type", "concept") or "concept").strip(),
            description=str(raw_entity.get("description", "") or "").strip(),
            aliases=raw_entity.get("aliases"),
            extracted=True,
        )

    # Snapshot ancestor relations once; current relations are updated as we go.
    chain_entity_by_id = {entity.id: entity for entity in chain_entities}
    ancestor_relations = db.query(GraphRelation).filter(
        GraphRelation.persona_id.in_(ancestor_ids[1:])
    ).all() if len(ancestor_ids) > 1 else []

    for raw_relation in relations or []:
        if not isinstance(raw_relation, dict):
            continue
        source_name = str(raw_relation.get("source", "") or "").strip()
        target_name = str(raw_relation.get("target", "") or "").strip()
        if not source_name or not target_name:
            continue

        source = ensure_local_entity(source_name)
        target = ensure_local_entity(target_name)
        if source is None or target is None:
            continue
        chain_entity_by_id[source.id] = source
        chain_entity_by_id[target.id] = target

        relation_type = str(raw_relation.get("relation_type", "related") or "related").strip()
        relation_key = _relation_type_key(relation_type)
        description = str(raw_relation.get("description", "") or "").strip()
        try:
            importance = max(0.0, min(1.0, float(raw_relation.get("importance", 0.5))))
        except (TypeError, ValueError):
            importance = 0.5

        current_relation = db.query(GraphRelation).filter(
            GraphRelation.persona_id == persona_id,
            GraphRelation.source_id == source.id,
            GraphRelation.target_id == target.id,
        ).all()
        current_relation = next(
            (
                relation for relation in current_relation
                if _relation_type_key(relation.relation_type) == relation_key
            ),
            None,
        )
        if current_relation is not None:
            if description:
                current_relation.description = description
            current_relation.relation_type = relation_type
            current_relation.importance = min(
                1.0,
                max(current_relation.importance or 0.5, importance)
                + (1.0 - max(current_relation.importance or 0.5, importance)) * 0.1,
            )
            continue

        source_key = normalize_entity_name(source.name)
        target_key = normalize_entity_name(target.name)
        ancestor_matches = []
        for relation in ancestor_relations:
            ancestor_source = chain_entity_by_id.get(relation.source_id)
            ancestor_target = chain_entity_by_id.get(relation.target_id)
            if not ancestor_source or not ancestor_target:
                continue
            if (
                normalize_entity_name(ancestor_source.name) == source_key
                and normalize_entity_name(ancestor_target.name) == target_key
                and _relation_type_key(relation.relation_type) == relation_key
            ):
                ancestor_matches.append(relation)
        ancestor_relation = min(
            ancestor_matches,
            key=lambda relation: (
                persona_priority.get(relation.persona_id, 999),
                relation.id,
            ),
            default=None,
        )

        inherited_importance = ancestor_relation.importance if ancestor_relation else 0.5
        effective_importance = (
            min(
                1.0,
                max(inherited_importance or 0.5, importance)
                + (1.0 - max(inherited_importance or 0.5, importance)) * 0.1,
            )
            if ancestor_relation is not None
            else importance
        )
        db.add(GraphRelation(
            persona_id=persona_id,
            source_id=source.id,
            target_id=target.id,
            relation_type=relation_type,
            description=description or (
                ancestor_relation.description if ancestor_relation is not None else ""
            ),
            importance=effective_importance,
        ))

    # Commit remains owned by the caller's memory-extraction transaction.


def _effective_entities(
    entities: list[GraphEntity],
    persona_priority: dict[int, int],
) -> dict[str, GraphEntity]:
    effective: dict[str, GraphEntity] = {}
    for entity in sorted(
        entities,
        key=lambda item: (persona_priority.get(item.persona_id, 999), item.id),
    ):
        key = normalize_entity_name(entity.name)
        if key and key not in effective:
            effective[key] = entity
    return effective


def retrieve_graph_context(persona_id: int, query_text: str, db: Session) -> str:
    """Match canonical names/aliases and return deterministic true 1/2-hop context."""
    if not query_text:
        return ""

    ancestor_ids = get_ancestor_persona_ids(persona_id, db) or [persona_id]
    persona_priority = {pid: index for index, pid in enumerate(ancestor_ids)}
    entities = db.query(GraphEntity).filter(GraphEntity.persona_id.in_(ancestor_ids)).all()
    if not entities:
        return ""

    effective_entities = _effective_entities(entities, persona_priority)
    query_key = normalize_entity_name(query_text)
    matched_keys = set()
    for canonical_key, entity in effective_entities.items():
        match_keys = _entity_match_keys(entity)
        if any(key and key in query_key for key in match_keys):
            matched_keys.add(canonical_key)
    if not matched_keys:
        return ""

    entity_by_id = {entity.id: entity for entity in entities}
    relations = db.query(GraphRelation).filter(
        GraphRelation.persona_id.in_(ancestor_ids),
        GraphRelation.importance >= settings.APP_GRAPH_MIN_IMPORTANCE,
    ).all()

    # Collapse inherited COW IDs into name-level effective triples.
    effective_relations: dict[tuple[str, str, str], GraphRelation] = {}
    for relation in sorted(
        relations,
        key=lambda item: (persona_priority.get(item.persona_id, 999), item.id),
    ):
        source = entity_by_id.get(relation.source_id)
        target = entity_by_id.get(relation.target_id)
        if source is None or target is None:
            continue
        source_key = normalize_entity_name(source.name)
        target_key = normalize_entity_name(target.name)
        if source_key not in effective_entities or target_key not in effective_entities:
            continue
        triple = (source_key, _relation_type_key(relation.relation_type), target_key)
        if triple not in effective_relations:
            effective_relations[triple] = relation

    if not effective_relations:
        return ""

    adjacency: dict[str, list[tuple[tuple[str, str, str], GraphRelation, str]]] = defaultdict(list)
    for triple, relation in effective_relations.items():
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

    if not selected:
        return ""

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
    if not ranked:
        return ""

    described_keys = set(matched_keys)
    relation_lines = []
    for (source_key, _relation_key, target_key), (relation, _hop) in ranked:
        described_keys.update((source_key, target_key))
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

    output_parts = []
    if entity_desc_lines:
        output_parts.append("实体定义:")
        output_parts.extend(entity_desc_lines)
    if relation_lines:
        if output_parts:
            output_parts.append("")
        output_parts.append("关系网:")
        output_parts.extend(relation_lines)
    return "\n".join(output_parts)
