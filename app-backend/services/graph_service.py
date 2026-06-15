"""
知识图谱 RAG 服务 — 负责 SQLite 知识图谱实体的提取写入、匹配与检索
"""

from sqlalchemy.orm import Session
from core.models import GraphEntity, GraphRelation
from services.memory_manager import get_ancestor_persona_ids

def upsert_graph_data(
    persona_id: int,
    entities: list[dict],
    relations: list[dict],
    db: Session
):
    """
    增量 Upsert 实体和关系到 SQLite。
    
    参数：
      entities: [{"name": "小红", "entity_type": "person", "description": "用户的妹妹"}]
      relations: [{"source": "用户", "relation_type": "sibling", "target": "小红", "description": "用户和小红是亲兄妹", "importance": 0.8}]
    """
    entity_name_to_id = {}
    
    # 1. Upsert 实体列表
    for ent in entities:
        name = ent.get("name", "").strip()
        if not name:
            continue
        ent_type = ent.get("entity_type", "concept").strip()
        desc = ent.get("description", "").strip()
        
        # 检索当前 Persona 下是否已存在同名实体
        db_ent = db.query(GraphEntity).filter(
            GraphEntity.persona_id == persona_id,
            GraphEntity.name == name
        ).first()
        
        if db_ent:
            # 存在则合并更新描述和类型
            if desc:
                db_ent.description = desc
            db_ent.entity_type = ent_type
        else:
            # 不存在则新建
            db_ent = GraphEntity(
                persona_id=persona_id,
                name=name,
                entity_type=ent_type,
                description=desc
            )
            db.add(db_ent)
            db.flush()  # 刷入内存以获取自增主键 ID
            
        entity_name_to_id[name] = db_ent.id

    # 2. 补齐关系中提到但未在 entities 列表中声明的实体
    for rel in relations:
        src = rel.get("source", "").strip()
        tgt = rel.get("target", "").strip()
        for name in (src, tgt):
            if name and name not in entity_name_to_id:
                # 检查数据库中是否存在
                db_ent = db.query(GraphEntity).filter(
                    GraphEntity.persona_id == persona_id,
                    GraphEntity.name == name
                ).first()
                if db_ent:
                    entity_name_to_id[name] = db_ent.id
                else:
                    # 创建兜底默认实体
                    db_ent = GraphEntity(
                        persona_id=persona_id,
                        name=name,
                        entity_type="concept",
                        description=f"关于 {name} 的概念或事物。"
                    )
                    db.add(db_ent)
                    db.flush()
                    entity_name_to_id[name] = db_ent.id

    # 3. Upsert 关系列表
    for rel in relations:
        src = rel.get("source", "").strip()
        tgt = rel.get("target", "").strip()
        if not src or not tgt:
            continue
            
        rel_type = rel.get("relation_type", "related").strip()
        desc = rel.get("description", "").strip()
        importance = rel.get("importance", 0.5)
        try:
            importance = float(importance)
            importance = max(0.0, min(1.0, importance))
        except (ValueError, TypeError):
            importance = 0.5
            
        src_id = entity_name_to_id.get(src)
        tgt_id = entity_name_to_id.get(tgt)
        if not src_id or not tgt_id:
            continue
            
        # 查重当前 Persona 下这两个实体间是否存在同种类型的关系
        db_rel = db.query(GraphRelation).filter(
            GraphRelation.persona_id == persona_id,
            GraphRelation.source_id == src_id,
            GraphRelation.target_id == tgt_id,
            GraphRelation.relation_type == rel_type
        ).first()
        
        if db_rel:
            if desc:
                db_rel.description = desc
            db_rel.importance = importance
        else:
            db_rel = GraphRelation(
                persona_id=persona_id,
                source_id=src_id,
                target_id=tgt_id,
                relation_type=rel_type,
                description=desc,
                importance=importance
            )
            db.add(db_rel)

    # 提示：不在此处调用 db.commit()，由上游调用方事务统一提交，保证数据库原子性。


def retrieve_graph_context(
    persona_id: int,
    query_text: str,
    db: Session
) -> str:
    """
    匹配当前消息中的实体，并从图谱（包含继承祖先链）中拉取 1-hop 和 2-hop 的关联关系。
    """
    if not query_text:
        return ""
        
    # 1. 递归获取继承的祖先 Persona IDs
    ancestor_ids = get_ancestor_persona_ids(persona_id, db)
    if not ancestor_ids:
        ancestor_ids = [persona_id]
        
    # 2. 读取这些 Persona 的所有实体
    entities = db.query(GraphEntity).filter(
        GraphEntity.persona_id.in_(ancestor_ids)
    ).all()
    
    if not entities:
        return ""
        
    # 3. 匹配消息中的实体（忽略大小写子串匹配）
    matched_entity_ids = set()
    query_lower = query_text.lower()
    
    for ent in entities:
        if ent.name.lower() in query_lower:
            matched_entity_ids.add(ent.id)
            
    if not matched_entity_ids:
        return ""
        
    # 4. 读出所有的图谱关系
    all_relations = db.query(GraphRelation).filter(
        GraphRelation.persona_id.in_(ancestor_ids)
    ).all()
    
    # 5. 组装 1-hop 关系与 1-hop 邻居实体 IDs
    matched_relations = []
    first_hop_entity_ids = set(matched_entity_ids)
    
    for rel in all_relations:
        if rel.source_id in matched_entity_ids or rel.target_id in matched_entity_ids:
            matched_relations.append(rel)
            first_hop_entity_ids.add(rel.source_id)
            first_hop_entity_ids.add(rel.target_id)
            
    # 6. 二度遍历 (2-hop)：拉取这组邻居实体内部存在的其它关系
    added_relation_ids = {r.id for r in matched_relations}
    for rel in all_relations:
        if rel.id not in added_relation_ids:
            if rel.source_id in first_hop_entity_ids and rel.target_id in first_hop_entity_ids:
                matched_relations.append(rel)
                added_relation_ids.add(rel.id)
                
    if not matched_relations:
        return ""
        
    # 7. 格式化构建提示词背景
    entity_map = {ent.id: ent.name for ent in entities}
    
    # 7.1 格式化实体定义描述（优先保留祖先链越新/越顶层的描述）
    entity_desc_lines = []
    matched_entities_to_describe = [ent for ent in entities if ent.id in first_hop_entity_ids]
    seen_names = set()
    
    # 按祖先链出现的倒序排序，即子 Session 优先于父 Session
    for ent in sorted(matched_entities_to_describe, key=lambda e: ancestor_ids.index(e.persona_id)):
        if ent.name not in seen_names:
            seen_names.add(ent.name)
            if ent.description:
                entity_desc_lines.append(f"- {ent.name}: {ent.description}")
                
    # 7.2 格式化关系描述列表（按权重由高到低排序）
    relation_lines = []
    seen_relation_triples = set()
    matched_relations.sort(key=lambda r: (r.importance or 0.5), reverse=True)
    
    for rel in matched_relations:
        src_name = entity_map.get(rel.source_id)
        tgt_name = entity_map.get(rel.target_id)
        if not src_name or not tgt_name:
            continue
            
        triple_key = (src_name, rel.relation_type, tgt_name)
        if triple_key not in seen_relation_triples:
            seen_relation_triples.add(triple_key)
            if rel.description:
                relation_lines.append(f"- {rel.description}")
            else:
                relation_lines.append(f"- {src_name}与{tgt_name}的关系是: {rel.relation_type}")
                
    # 组装输出
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
