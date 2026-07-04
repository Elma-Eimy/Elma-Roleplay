"""
记忆管理器 — 负责记忆的提纯、存储、检索与清理

核心职责：
  1. 从对话中提取结构化记忆（LLM 提纯） [已移至 cognition_service]
  2. 双写入 SQLite（MemoryChunk）和 ChromaDB（向量 embedding）
  3. 跨继承链的单次 RAG 检索
  4. Session 删除时的 ChromaDB 数据一致性清理
  5. 代理并重新导出子模块服务以实现向后兼容 (Facade 模式)

ChromaDB 架构：
  每个 Character 共享一个 collection（collection_name = f"character_{character_id}"）
  通过 metadata 中的 persona_id 字段 + $in 操作符实现单次查询跨继承链检索
"""

import json
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Optional
from sqlalchemy.orm import Session as DBSession
from core import models
from core.models import MemoryChunk, SessionPersona, ChatMessage, MemoryType, Session
from services.clients import LLM_MODEL, chroma_client, openai_ef
from core.config import settings


# ──────────────────────────────────────────────
# 1. ChromaDB Collection 管理
# ──────────────────────────────────────────────

def get_character_collection(character_id: int):
    """
    获取或创建某个角色的 ChromaDB collection。

    命名规则：character_{character_id}
    所有属于该角色的 SessionPersona 的记忆都存放在同一个 collection 中，
    通过 metadata.persona_id 区分不同 Persona。
    """
    collection_name = f"character_{character_id}"
    collection = chroma_client.get_or_create_collection(
        name=collection_name,
        embedding_function=openai_ef
    )

    # 动态探测 collection 已有的向量维度，并同步给 embedding_function 的缓存，以防 API 失败时 fallback 维度不匹配
    try:
        if collection.count() > 0:
            existing = collection.get(limit=1, include=["embeddings"])
            if existing and existing.get("embeddings") is not None and len(existing["embeddings"]) > 0:
                openai_ef.__class__._cached_dim = len(existing["embeddings"][0])
    except Exception as e:
        print(f"[WARN] 动态探测 collection {collection_name} 向量维度失败: {e}")

    return collection


# ──────────────────────────────────────────────
# 2. 继承链工具
# ──────────────────────────────────────────────

def get_ancestor_persona_ids(persona_id: int, db: DBSession) -> list[int]:
    """
    沿 SessionPersona.parent_persona_id 向上遍历，返回完整的祖先链。

    使用递归公共表表达式 (CTE) 进行单次数据库查询优化，规避 N+1 数据库阻塞。
    返回值示例：[3, 2, 1]（当前 Persona → 父 → 祖父）
    如果没有继承，返回 [persona_id] 仅包含自身。
    """
    from sqlalchemy import text
    sql = """
    WITH RECURSIVE ancestor(id, parent_id) AS (
        SELECT id, parent_persona_id FROM session_personas WHERE id = :persona_id
        UNION ALL
        SELECT sp.id, sp.parent_persona_id 
        FROM session_personas sp
        JOIN ancestor a ON sp.id = a.parent_id
    )
    SELECT id FROM ancestor;
    """
    try:
        # SQLite 递归 CTE 一次性获取所有祖先 ID
        result = db.execute(text(sql), {"persona_id": persona_id}).fetchall()
        ids = [row[0] for row in result]
        if ids:
            return ids
    except Exception as e:
        print(f"[WARN] get_ancestor_persona_ids: SQL CTE 递归查询失败: {e}. 已自动回退到循环同步遍历。")

    # 容错降级回退机制
    ids = []
    cur = persona_id
    visited = set()  # 防御性：防止循环引用导致死循环

    while cur is not None:
        if cur in visited:
            break
        visited.add(cur)
        ids.append(cur)

        persona = db.get(SessionPersona, cur)
        if persona is None:
            break
        cur = persona.parent_persona_id

    return ids


# ──────────────────────────────────────────────
# 3. 记忆写入（SQLite + ChromaDB 双写）
# ──────────────────────────────────────────────

def _build_chroma_metadata(
    persona_id: int,
    memory_type: MemoryType,
    importance_score: float,
    origin_session_id: Optional[int],
    created_at: datetime,
    source_message_id: Optional[int]
) -> dict:
    """
    构建 ChromaDB metadata 字典，严格对齐 SQLite MemoryChunk 字段类型。

    类型映射：
      persona_id        → int    (直接存)
      memory_type       → str    (.value，如 "fact")
      importance_score  → float  (直接存)
      origin_session_id → int    (None 时不写入，ChromaDB 不支持 None)
      created_at        → str    (.isoformat())
    """
    metadata = {
        "persona_id": persona_id,
        "memory_type": memory_type.value,
        "importance_score": importance_score,
        "created_at": created_at.isoformat(),
    }
    # ChromaDB metadata 不支持 None 值，nullable 字段为空时跳过
    if origin_session_id is not None:
        metadata["origin_session_id"] = origin_session_id
    if source_message_id is not None:
        metadata["source_message_id"] = source_message_id

    return metadata


def add_memory_chunk(
    persona_id: int,
    character_id: int,
    content: str,
    memory_type: MemoryType,
    importance_score: float,
    origin_session_id: Optional[int],
    source_message_id: Optional[int],
    db: DBSession,
    auto_commit: bool = True
) -> MemoryChunk:
    """
    创建一条记忆并双写入 SQLite 和 ChromaDB。

    参数：
      auto_commit — True（默认）：每条记忆独立 commit，适合单条写入场景。
                    False：只 flush + 写 ChromaDB，不 commit。
                    适合批量写入场景（由调用方做单次原子 commit）。

    流程：
      1. 创建 MemoryChunk ORM 对象 → db.flush() 获取自增 ID
      2. 生成 chroma_doc_id = f"mem_{chunk.id}"
      3. 写入 ChromaDB collection（character_{character_id}）
      4. 若 auto_commit=True → db.commit()
    """
    # Step 1: SQLite 写入（flush 获取 ID，但不 commit）
    chunk = MemoryChunk(
        persona_id=persona_id,
        content=content,
        memory_type=memory_type,
        importance_score=importance_score,
        origin_session_id=origin_session_id,
        source_message_id=source_message_id,
    )
    db.add(chunk)
    db.flush()  # 获取自增 ID

    # Step 2: 生成 ChromaDB document ID
    chroma_doc_id = f"mem_{chunk.id}"
    chunk.chroma_doc_id = chroma_doc_id

    # Step 3: 写入 ChromaDB
    now = chunk.created_at or datetime.now(timezone.utc)
    metadata = _build_chroma_metadata(
        persona_id=persona_id,
        memory_type=memory_type,
        importance_score=importance_score,
        origin_session_id=origin_session_id,
        created_at=now,
        source_message_id=source_message_id,
    )

    collection = get_character_collection(character_id)
    try:
        collection.add(
            ids=[chroma_doc_id],
            documents=[content],
            metadatas=[metadata],
        )
    except Exception as e:
        # ChromaDB 写入失败时回滚 SQLite，保持一致性
        db.rollback()
        print(f"==========================================")
        print(f"[ERROR] add_memory_chunk: ChromaDB 写入失败，已回滚 SQLite")
        print(f"[ERROR] 错误类型: {type(e).__name__}")
        print(f"[ERROR] 错误详情: {e}")
        print(f"==========================================")
        raise

    # Step 4: 提交事务（仅在 auto_commit 模式下）
    if auto_commit:
        try:
            db.commit()
            db.refresh(chunk)
        except Exception as e:
            # SQLite commit 失败 → 回滚 ChromaDB 中刚写入的文档
            try:
                collection.delete(ids=[chroma_doc_id])
            except Exception:
                print(f"[CRITICAL] ChromaDB 回滚也失败，可能存在孤儿文档: {chroma_doc_id}")
            db.rollback()
            print(f"==========================================")
            print(f"[ERROR] add_memory_chunk: db.commit() 失败，已回滚 ChromaDB")
            print(f"[ERROR] 错误类型: {type(e).__name__}")
            print(f"[ERROR] 错误详情: {e}")
            print(f"==========================================")
            raise

    return chunk


# ──────────────────────────────────────────────
# 4. 跨继承链 RAG 检索
# ──────────────────────────────────────────────

def retrieve_memories(
    persona_id: int,
    character_id: int,
    query: str,
    db: DBSession,
    top_k: Optional[int] = None,
    min_importance: Optional[float] = None
) -> list:
    """
    跨继承链检索相关记忆。始终只需 1 次 ChromaDB 查询。

    参数:
      persona_id     — 当前 SessionPersona 的 ID
      character_id   — 角色 ID（用于定位 collection）
      query          — 用户输入文本
      db             — SQLAlchemy 数据库会话
      top_k          — 返回的最大记忆条数（默认取 config 配置）
      min_importance — 最低重要性阈值（0.0~1.0）

    返回:
      [{"content": str, "memory_type": str, "importance_score": float, "distance": float}, ...]
    """
    if top_k is None:
        top_k = settings.APP_RETRIEVAL_TOP_K
    if min_importance is None:
        min_importance = settings.APP_RETRIEVAL_MIN_IMPORTANCE

    collection = get_character_collection(character_id)
    try:
        if collection.count() == 0:
            return []
    except Exception as e:
        print(f"[WARN] retrieve_memories: ChromaDB count 失败 (可能库未就绪): {e}. 跳过 RAG 检索。")
        return []

    # Step 1: 获取祖先链
    ancestor_ids = get_ancestor_persona_ids(persona_id, db)

    # Step 2: 构建 where 过滤条件
    where_filter = {"persona_id": {"$in": ancestor_ids}}

    # 叠加重要性阈值过滤
    if min_importance > 0.0:
        where_filter = {
            "$and": [
                {"persona_id": {"$in": ancestor_ids}},
                {"importance_score": {"$gte": min_importance}},
            ]
        }

    # Bug8修复：加 max(1, ...) 防止配置异常时 n_results=0 导致 ChromaDB 报错
    fetch_k = max(1, top_k * settings.APP_RETRIEVAL_CANDIDATE_MULTIPLIER)

    # Step 3: 单次查询 (粗排)
    try:
        results = collection.query(
            query_texts=[query],
            n_results=fetch_k,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as e:
        print(f"==========================================")
        print(f"[ERROR] retrieve_memories: ChromaDB 查询失败")
        print(f"[ERROR] 错误类型: {type(e).__name__}")
        print(f"[ERROR] 错误详情: {e}")
        print(f"==========================================")
        return []

    # Step 4: 组装结果与精排 (混合打分)
    if not results or not results.get("documents") or not results["documents"][0]:
        return []

    # 获取当前最新的消息 ID，作为逻辑时间的基准
    current_msg_id = 0
    persona = db.get(SessionPersona, persona_id)
    if persona:
        current_msg = db.query(ChatMessage).filter(
            ChatMessage.session_id == persona.session_id,
            ChatMessage.is_active == True
        ).order_by(ChatMessage.id.desc()).first()
        if current_msg:
            current_msg_id = current_msg.id

    raw_memories = []
    docs = results["documents"][0]
    metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
    dists = results["distances"][0] if results.get("distances") else [0.0] * len(docs)
    ids = results["ids"][0] if results.get("ids") else [""] * len(docs)

    for doc, meta, dist, cid in zip(docs, metas, dists, ids):
        # 叠加向量相似度距离阈值过滤，防止召回无关的多余内容
        if dist > settings.APP_RETRIEVAL_MAX_DISTANCE:
            continue
            
        chunk_id = None
        if cid.startswith("mem_"):
            try:
                chunk_id = int(cid[4:])
            except ValueError:
                pass

        sim_score = max(0.0, 1.0 - (dist / settings.APP_RETRIEVAL_MAX_DISTANCE))
        imp_score = float(meta.get("importance_score", 0.5))
        
        # 计算逻辑时间衰减（类型感知：客观事实在单会话内不应用逻辑时间衰减，时间得分保持满分）
        mem_type = meta.get("memory_type", "fact")
        if mem_type == "fact":
            time_score = 1.0
            turns_passed = 0
        else:
            source_msg_id = int(meta.get("source_message_id", current_msg_id))
            turns_passed = max(0, current_msg_id - source_msg_id)
            half_life = max(1, settings.APP_RETRIEVAL_HALF_LIFE_TURNS)
            time_score = 0.5 ** (turns_passed / half_life)
        
        # 混合打分
        final_score = (
            settings.APP_RETRIEVAL_WEIGHT_SIMILARITY * sim_score +
            settings.APP_RETRIEVAL_WEIGHT_IMPORTANCE * imp_score +
            settings.APP_RETRIEVAL_WEIGHT_TIME * time_score
        )
        
        # 跨会话继承链的权重惩罚 (根据代数累乘)
        mem_persona_id = meta.get("persona_id")
        try:
            # 0=当前会话，1=父会话，2=祖父会话...
            generation_distance = ancestor_ids.index(mem_persona_id)
        except ValueError:
            generation_distance = 1 # 降级处理
            
        if generation_distance > 0:
            # 针对事实 (fact) 类型的长期客观记忆，采用更轻微的衰减率以防在深代分叉中遗忘
            # 针对事件 (event)、情绪 (emotion) 或关系 (relationship)，采用标准的衰减权重
            mem_type = meta.get("memory_type", "fact")
            decay_base = 0.95 if mem_type == "fact" else settings.APP_RETRIEVAL_ANCESTOR_WEIGHT
            final_score *= (decay_base ** generation_distance)

        raw_memories.append({
            "id": chunk_id,
            "chroma_doc_id": cid,
            "content": doc,
            "memory_type": meta.get("memory_type", ""),
            "importance_score": imp_score,
            "persona_id": meta.get("persona_id"),
            "origin_session_id": meta.get("origin_session_id"),
            "distance": dist,
            "sim_score": sim_score,
            "time_score": time_score,
            "turns_passed": turns_passed,
            "final_score": final_score,
        })

    # 按 final_score 降序排序
    raw_memories.sort(key=lambda x: x["final_score"], reverse=True)

    # 语义去重 (Deduplication) - 采用基于 SequenceMatcher 的轻量级文本去重以消除继承链 COW 重复记录
    deduped_memories = []
    for rm in raw_memories:
        is_duplicate = False
        for dm in deduped_memories:
            ratio = SequenceMatcher(None, rm["content"], dm["content"]).ratio()
            if ratio >= settings.APP_DEDUP_RETRIEVE_TEXT_THRESHOLD:
                is_duplicate = True
                break
        if not is_duplicate:
            deduped_memories.append(rm)

    memories = deduped_memories[:top_k]
    return memories


# ──────────────────────────────────────────────
# 5. 删除一致性（ChromaDB 清理）
# ──────────────────────────────────────────────

def delete_persona_memories(
    persona_id: int,
    character_id: int,
    db: DBSession
) -> int:
    """
    删除某个 Persona 的全部记忆（ChromaDB + SQLite），使用最终一致性异步发件箱任务。

    ⚠️ 此函数应在删除 Session 之前调用，确保 ChromaDB 数据一致性。

    调用顺序：
      1. delete_persona_memories(persona.id, persona.character_id, db)  ← 清理并入库异步任务
      2. db.delete(session)                                             ← CASCADE
      3. db.commit()                                                    ← 原子提交（包括发件箱任务）

    返回入库待删除的记忆条数。
    """
    # 查询 SQLite 获取所有要删除的 chroma_doc_id
    chunks = db.query(MemoryChunk).filter(
        MemoryChunk.persona_id == persona_id
    ).all()
    doc_ids = [c.chroma_doc_id for c in chunks if c.chroma_doc_id]
    deleted_count = len(doc_ids)

    # 写入发件箱任务
    if doc_ids:
        try:
            payload = {
                "character_id": character_id,
                "doc_ids": doc_ids
            }
            job = models.OutboxJob(
                task_type="delete_vector",
                payload=json.dumps(payload)
            )
            db.add(job)
            print(f"[INFO] Outbox: 已入库 persona_id={persona_id} 的 {deleted_count} 条记忆删除任务")
        except Exception as e:
            print(f"[ERROR] delete_persona_memories 写入发件箱任务失败: {e}")

    # 清理 SQLite（补充保障，即使 CASCADE 会处理）
    try:
        db.query(MemoryChunk).filter(
            MemoryChunk.persona_id == persona_id
        ).delete(synchronize_session="fetch")
    except Exception as e:
        print(f"[WARN] delete_persona_memories: SQLite 清理异常（CASCADE 可能已处理）: {e}")

    return deleted_count



def update_memory_chunk(
    chunk_id: int,
    content: str,
    importance_score: float,
    db: DBSession,
    auto_commit: bool = True
) -> MemoryChunk:
    """
    修改单条记忆（SQLite + ChromaDB 同步更新）。

    auto_commit=True（默认，单条写入场景）：
      SQLite flush → ChromaDB update → db.commit()，全部在本函数内完成。
      任何一步失败均 rollback，保持两侧一致。

    auto_commit=False（批量事务场景）：
      只做 SQLite flush，不立即写 ChromaDB，消除"ChromaDB 已落盘但
      SQLite commit 尚未成功"的不一致窗口。
      函数在 chunk 上挂载 _pending_chroma_update 闭包属性，调用方必须在
      db.commit() 成功后立即调用该闭包以完成 ChromaDB 侧的更新；若
      db.commit() 失败则丢弃该闭包即可，ChromaDB 无任何修改，天然一致。
    """
    chunk = db.get(MemoryChunk, chunk_id)
    if not chunk:
        raise ValueError("MemoryChunk not found")

    chunk.content = content
    chunk.importance_score = importance_score
    db.flush()

    if auto_commit:
        # ── 即时模式：SQLite flush 成功后立刻写 ChromaDB，再 commit ──
        if chunk.chroma_doc_id:
            try:
                character_id = chunk.persona.character_id
                collection = get_character_collection(character_id)
                now = chunk.created_at or datetime.now(timezone.utc)
                metadata = _build_chroma_metadata(
                    persona_id=chunk.persona_id,
                    memory_type=chunk.memory_type,
                    importance_score=importance_score,
                    origin_session_id=chunk.origin_session_id,
                    created_at=now,
                    source_message_id=chunk.source_message_id
                )
                collection.update(
                    ids=[chunk.chroma_doc_id],
                    documents=[content],
                    metadatas=[metadata]
                )
            except Exception as e:
                db.rollback()
                print(f"[ERROR] update_memory_chunk ChromaDB 更新失败: {e}")
                raise

        try:
            db.commit()
            db.refresh(chunk)
        except Exception as e:
            db.rollback()
            print(f"[ERROR] update_memory_chunk db.commit() 失败: {e}")
            raise

        return chunk

    else:
        # ── 延迟模式：只改 SQLite ORM，ChromaDB 写入交由调用方在 commit 后执行 ──
        # 提前快照所有需要的字段值（flush 后属性仍可读；commit 后会 expire，
        # 所以必须在此处捕获，不能在 commit 后依赖 ORM 对象属性）
        chroma_doc_id = chunk.chroma_doc_id
        character_id = chunk.persona.character_id
        now = chunk.created_at or datetime.now(timezone.utc)
        snap_persona_id = chunk.persona_id
        snap_memory_type = chunk.memory_type
        snap_origin_session_id = chunk.origin_session_id
        snap_source_message_id = chunk.source_message_id

        def _flush_to_chroma():
            """在 db.commit() 成功后由调用方调用，将变更同步写入 ChromaDB。"""
            if not chroma_doc_id:
                return
            collection = get_character_collection(character_id)
            metadata = _build_chroma_metadata(
                persona_id=snap_persona_id,
                memory_type=snap_memory_type,
                importance_score=importance_score,
                origin_session_id=snap_origin_session_id,
                created_at=now,
                source_message_id=snap_source_message_id
            )
            collection.update(
                ids=[chroma_doc_id],
                documents=[content],
                metadatas=[metadata]
            )

        # 将闭包挂载到 chunk，方便调用方通过对象引用统一追踪
        chunk._pending_chroma_update = _flush_to_chroma
        return chunk


def delete_memory_chunk(
    chunk_id: int,
    db: DBSession
):
    """
    删除单条记忆（SQLite + ChromaDB 最终一致性异步删除）。
    """
    chunk = db.get(MemoryChunk, chunk_id)
    if not chunk:
        raise ValueError("MemoryChunk not found")

    # 异步删除 ChromaDB
    if chunk.chroma_doc_id:
        try:
            character_id = chunk.persona.character_id
            payload = {
                "character_id": character_id,
                "doc_ids": [chunk.chroma_doc_id]
            }
            job = models.OutboxJob(
                task_type="delete_vector",
                payload=json.dumps(payload)
            )
            db.add(job)
            print(f"[INFO] Outbox: 已入库 chunk_id={chunk_id} 的 1 条记忆删除任务")
        except Exception as e:
            print(f"[WARN] delete_memory_chunk 写入发件箱任务失败: {e}")

    db.delete(chunk)
    db.commit()



# ──────────────────────────────────────────────
# 6. 外观接口 (Facade Pattern) 重新导出子服务函数以维持 100% 向后兼容性
# ──────────────────────────────────────────────

from services.cognition_service import (
    get_unsummarized_count,
    summarize_and_store_memory,
    get_cognition_unseen_count,
    update_cognition_state,
)
from services.session_service import safe_delete_session
