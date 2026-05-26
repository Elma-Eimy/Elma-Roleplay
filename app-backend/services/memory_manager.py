"""
记忆管理器 — 负责记忆的提纯、存储、检索与清理

核心职责：
  1. 从对话中提取结构化记忆（LLM 提纯）
  2. 双写入 SQLite（MemoryChunk）和 ChromaDB（向量 embedding）
  3. 跨继承链的单次 RAG 检索
  4. Session 删除时的 ChromaDB 数据一致性清理

ChromaDB 架构：
  每个 Character 共享一个 collection（collection_name = f"character_{character_id}"）
  通过 metadata 中的 persona_id 字段 + $in 操作符实现单次查询跨继承链检索
"""

import json
import time
from datetime import datetime, timezone
from sqlalchemy.orm import Session as DBSession
from core import models
from core.models import MemoryChunk, SessionPersona, ChatMessage, MemoryType, Session
from services.chat_engine import llm_client, LLM_MODEL, chroma_client, openai_ef
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
    return chroma_client.get_or_create_collection(
        name=collection_name,
        embedding_function=openai_ef
    )


# ──────────────────────────────────────────────
# 2. 继承链工具
# ──────────────────────────────────────────────

def get_ancestor_persona_ids(persona_id: int, db: DBSession) -> list[int]:
    """
    沿 SessionPersona.parent_persona_id 向上遍历，返回完整的祖先链。

    返回值示例：[3, 2, 1]（当前 Persona → 父 → 祖父）
    如果没有继承，返回 [persona_id] 仅包含自身。
    """
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
    origin_session_id: int | None,
    created_at: datetime
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

    return metadata


def add_memory_chunk(
    persona_id: int,
    character_id: int,
    content: str,
    memory_type: MemoryType,
    importance_score: float,
    origin_session_id: int | None,
    source_message_id: int | None,
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
    top_k: int | None = None,
    min_importance: float | None = None
) -> list[dict]:
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

    # Step 3: 单次查询
    try:
        results = collection.query(
            query_texts=[query],
            n_results=top_k,
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

    # Step 4: 组装结果
    if not results or not results.get("documents") or not results["documents"][0]:
        return []

    memories = []
    docs = results["documents"][0]
    metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
    dists = results["distances"][0] if results.get("distances") else [0.0] * len(docs)

    for doc, meta, dist in zip(docs, metas, dists):
        # 叠加向量相似度距离阈值过滤，防止召回无关的多余内容
        if dist > settings.APP_RETRIEVAL_MAX_DISTANCE:
            continue
        memories.append({
            "content": doc,
            "memory_type": meta.get("memory_type", ""),
            "importance_score": meta.get("importance_score", 0.0),
            "persona_id": meta.get("persona_id"),
            "origin_session_id": meta.get("origin_session_id"),
            "distance": dist,
        })

    return memories


# ──────────────────────────────────────────────
# 5. 记忆提纯（LLM 从对话中提取结构化记忆）
# ──────────────────────────────────────────────

def get_unsummarized_count(session_id: int, db: DBSession) -> int:
    """
    返回指定 Session 中尚未被记忆提纯处理的消息数量。

    供调用方（如 main.py 的 chat 端点）判断是否需要触发 summarize_and_store_memory。
    """
    persona = db.query(SessionPersona).filter(
        SessionPersona.session_id == session_id
    ).first()

    if not persona:
        return 0

    query = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    )
    if persona.last_summarized_msg_id is not None:
        query = query.filter(ChatMessage.id > persona.last_summarized_msg_id)

    return query.count()


def summarize_and_store_memory(session_id: int, db: DBSession) -> int:
    """
    核心提纯函数：从指定 Session 的未总结对话中提取结构化记忆，双写入库。

    增量机制：
      - 仅处理 last_summarized_msg_id 之后的消息（避免重复提纯）
      - 成功后更新 last_summarized_msg_id 为最后处理的消息 ID
      - 服务中断重启后，未总结的消息不会丢失

    返回成功入库的记忆条数。
    """
    # Step 1: 获取 Session 对应的 Persona
    persona = db.query(SessionPersona).filter(
        SessionPersona.session_id == session_id
    ).first()

    if not persona:
        print(f"[WARN] summarize_and_store_memory: Session {session_id} 没有关联的 Persona")
        return 0

    persona_id = persona.id
    character_id = persona.character_id

    # Step 2: 只查询尚未总结的消息（增量查询）
    query = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    )
    if persona.last_summarized_msg_id is not None:
        query = query.filter(ChatMessage.id > persona.last_summarized_msg_id)

    unsummarized = query.order_by(ChatMessage.id).all()  # 修改为 id 排序保证确定性

    if not unsummarized:
        return 0

    # 记录待更新的指针 ID
    last_msg_id = unsummarized[-1].id

    # 组合对话文本
    chat_text = ""
    for msg in unsummarized:
        role_label = "User" if msg.role.value == "user" else "Assistant"
        chat_text += f"{role_label}: {msg.content}\n"

    # 【优化关键点】在大模型调用前，主动提交并结束当前事务，释放 SQLite 文件锁
    db.commit()

    # Step 3: 调用 LLM 提纯（升级版 Prompt，要求返回结构化数据）
    system_prompt = """你是一个专业的"记忆整理员"。你的任务是从下面这段用户与AI角色的对话中，提取出值得长期记住的信息。

请过滤掉无意义的闲聊（如"早安"、"哈哈哈"等），只保留有价值的记忆。

对于每条提取出的记忆，你需要判断：
1. memory_type：记忆类型，必须是以下四种之一：
   - "event"：发生了什么事件
   - "emotion"：角色的情绪体验
   - "relationship"：与用户关系的变化
   - "fact"：世界观或客观事实
2. importance_score：重要性评分，0.0 到 1.0 之间的浮点数
   - 0.0~0.3：琐碎信息
   - 0.4~0.6：一般重要
   - 0.7~1.0：非常重要（关键承诺、重大事件、核心设定）

你必须以 JSON 数组格式返回，每个元素包含 content、memory_type、importance_score 三个字段。
例如：
[
  {"content": "用户最喜欢的食物是草莓蛋糕", "memory_type": "fact", "importance_score": 0.7},
  {"content": "角色因为用户的夸奖感到非常开心", "memory_type": "emotion", "importance_score": 0.5},
  {"content": "用户答应明天带角色去游乐园", "memory_type": "event", "importance_score": 0.8}
]

如果没有找到任何重要信息，请返回空数组 []。
不要输出任何 markdown 格式（如 ```json），直接返回纯 JSON 数组。"""

    try:
        response = llm_client.chat.completions.create(
            model=settings.LLM_MEMORY_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请提取以下对话中的重要记忆：\n{chat_text}"},
            ],
            temperature=settings.LLM_MEMORY_TEMPERATURE,
        )

        content = response.choices[0].message.content.strip()
        # 暴力清洗可能存在的 markdown 标记
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        try:
            extracted_memories = json.loads(content)
        except json.JSONDecodeError as e:
            print(f"[ERROR] LLM 返回的 JSON 格式非法: {content}")
            return 0

        if isinstance(extracted_memories, dict) and "memories" in extracted_memories:
            extracted_memories = extracted_memories["memories"]

        if not isinstance(extracted_memories, list):
            print("[WARN] LLM 未返回列表结构，提纯中止，等待下次重试。")
            return 0 # 不更新 last_summarized_msg_id

        if len(extracted_memories) == 0:
            # 重新获取 Persona，开启新事务更新进度指针
            persona = db.get(SessionPersona, persona_id)
            if persona:
                persona.last_summarized_msg_id = last_msg_id
                db.commit()
            return 0

    except Exception as e:
        print(f"==========================================")
        print(f"[ERROR] summarize_and_store_memory: LLM 提纯失败")
        print(f"[ERROR] 错误类型: {type(e).__name__}")
        print(f"[ERROR] 错误详情: {e}")
        print(f"==========================================")
        return 0

    # Step 4: 解析并过滤有效记忆
    parsed_memories = []
    for mem in extracted_memories:
        if not isinstance(mem, dict):
            continue

        mem_content = mem.get("content", "")
        if not mem_content or not isinstance(mem_content, str):
            continue

        # 解析 memory_type（容错：无效类型默认为 fact）
        raw_type = mem.get("memory_type", "fact")
        try:
            mem_type = MemoryType(raw_type)
        except ValueError:
            mem_type = MemoryType.fact

        # 解析 importance_score（容错：无效值默认为 0.5）
        raw_score = mem.get("importance_score", 0.5)
        try:
            mem_score = float(raw_score)
            mem_score = max(0.0, min(1.0, mem_score))  # 钳位到 [0, 1]
        except (ValueError, TypeError):
            mem_score = 0.5

        parsed_memories.append({
            "content": mem_content,
            "memory_type": mem_type,
            "importance_score": mem_score,
        })

    if not parsed_memories:
        # 所有条目都被过滤掉了，更新指针（不需要重试）
        persona = db.get(SessionPersona, persona_id)
        if persona:
            persona.last_summarized_msg_id = last_msg_id
            db.commit()
        return 0

    # Step 5: 原子批量写入（全部成功或全部回滚）
    chroma_ids_written = []
    max_importance = 0.0

    # 重新绑定 persona 到当前新事务中
    persona = db.get(SessionPersona, persona_id)
    if not persona:
        print(f"[ERROR] Persona {persona_id} 在大模型调用期间已被删除")
        return 0

    try:
        for pm in parsed_memories:
            chunk = add_memory_chunk(
                persona_id=persona_id,
                character_id=character_id,
                content=pm["content"],
                memory_type=pm["memory_type"],
                importance_score=pm["importance_score"],
                origin_session_id=session_id,
                source_message_id=None,
                db=db,
                auto_commit=False,  # 不逐条 commit，最后统一提交
            )
            chroma_ids_written.append(chunk.chroma_doc_id)
            if pm["importance_score"] > max_importance:
                max_importance = pm["importance_score"]

        # 所有记忆写入成功，更新进度指针
        persona.last_summarized_msg_id = last_msg_id

        # 单次原子提交（SQLite 侧）
        db.commit()

    except Exception as e:
        # 任何一条写入失败 → 全部回滚
        db.rollback()

        # 清理已写入 ChromaDB 的文档（恢复到本次操作前的状态）
        if chroma_ids_written:
            try:
                collection = get_character_collection(character_id)
                collection.delete(ids=chroma_ids_written)
                print(f"[INFO] 批量回滚: 已从 ChromaDB 清理 {len(chroma_ids_written)} 条文档")
            except Exception as cleanup_err:
                print(f"==========================================")
                print(f"[CRITICAL] ChromaDB 批量回滚失败，可能存在孤儿文档")
                print(f"[CRITICAL] 残留文档 IDs: {chroma_ids_written}")
                print(f"[CRITICAL] 错误详情: {cleanup_err}")
                print(f"==========================================")

        print(f"==========================================")
        print(f"[ERROR] summarize_and_store_memory: 批量写入失败，全部回滚")
        print(f"[ERROR] 进度指针未更新，等待下次重试")
        print(f"[ERROR] 错误类型: {type(e).__name__}")
        print(f"[ERROR] 错误详情: {e}")
        print(f"==========================================")
        return 0

    success_count = len(parsed_memories)

    # Step 6: 检查是否需要触发 cognition_state 高重要性更新
    if max_importance >= settings.APP_COGNITION_IMPORTANCE_THRESHOLD:
        try:
            update_cognition_state(persona_id, db)
            print(f"[INFO] 高重要性记忆 ({max_importance:.2f}) 触发了 cognition_state 即时更新")
        except Exception as e:
            print(f"[WARN] cognition_state 即时更新失败: {e}")

    return success_count


# ──────────────────────────────────────────────
# 6. 删除一致性（ChromaDB 清理）
# ──────────────────────────────────────────────

def delete_persona_memories(
    persona_id: int,
    character_id: int,
    db: DBSession
) -> int:
    """
    删除某个 Persona 的全部记忆（ChromaDB + SQLite）。

    ⚠️ 此函数应在删除 Session 之前调用，确保 ChromaDB 数据一致性。

    调用顺序：
      1. delete_persona_memories(persona.id, persona.character_id, db)  ← 清理
      2. db.delete(session)                                             ← CASCADE
      3. db.commit()

    返回被删除的记忆条数。
    """
    deleted_count = 0

    # Step 1: 清理 ChromaDB
    try:
        collection = get_character_collection(character_id)
        # 先统计要删除的数量
        existing = collection.get(
            where={"persona_id": persona_id},
            include=[],
        )
        deleted_count = len(existing["ids"]) if existing and existing.get("ids") else 0

        if deleted_count > 0:
            collection.delete(
                where={"persona_id": persona_id}
            )
            print(f"[INFO] ChromaDB: 已删除 persona_id={persona_id} 的 {deleted_count} 条记忆")
    except Exception as e:
        print(f"==========================================")
        print(f"[ERROR] delete_persona_memories: ChromaDB 清理失败")
        print(f"[ERROR] persona_id={persona_id}, character_id={character_id}")
        print(f"[ERROR] 错误类型: {type(e).__name__}")
        print(f"[ERROR] 错误详情: {e}")
        print(f"==========================================")
        # 不抛出异常，允许后续 SQLite CASCADE 继续执行

    # Step 2: 清理 SQLite（补充保障，即使 CASCADE 会处理）
    try:
        db.query(MemoryChunk).filter(
            MemoryChunk.persona_id == persona_id
        ).delete(synchronize_session="fetch")
    except Exception as e:
        print(f"[WARN] delete_persona_memories: SQLite 清理异常（CASCADE 可能已处理）: {e}")

    return deleted_count


# ──────────────────────────────────────────────
# 7. 认知状态更新（cognition_state）
# ──────────────────────────────────────────────

def get_cognition_unseen_count(persona_id: int, session_id: int, db: DBSession) -> int:
    """
    返回自上次认知更新以来的新消息数量。

    供调用方判断是否需要触发定期认知更新
    （与 settings.APP_COGNITION_UPDATE_INTERVAL 比较）。
    """
    persona = db.get(SessionPersona, persona_id)
    if not persona:
        return 0

    query = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    )
    if persona.last_cognition_update_msg_id is not None:
        query = query.filter(ChatMessage.id > persona.last_cognition_update_msg_id)

    return query.count()


def update_cognition_state(persona_id: int, db: DBSession) -> str | None:
    """
    调用 LLM 更新 SessionPersona.cognition_state（角色宏观认知摘要）。

    输入：旧 cognition_state + 自上次认知更新以来的消息
    输出：新的认知摘要文本，同时写入 SessionPersona.cognition_state

    触发方式：
      a. 日常积累：当 get_cognition_unseen_count() >= cognition_update_interval 时
      b. 高重要性：当记忆提纯产生 importance >= cognition_importance_threshold 的记忆时
    """
    persona = db.get(SessionPersona, persona_id)
    if not persona:
        print(f"[WARN] update_cognition_state: Persona {persona_id} 不存在")
        return None

    session_id = persona.session_id
    old_cognition = persona.cognition_state or "（尚未建立认知）"

    # 查询自上次认知更新以来的消息
    query = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    )
    if persona.last_cognition_update_msg_id is not None:
        query = query.filter(ChatMessage.id > persona.last_cognition_update_msg_id)

    recent_messages = query.order_by(ChatMessage.id).all()

    if not recent_messages:
        return persona.cognition_state

    # 提取所需数据，防止之后事务释放后访问属性报错
    last_msg_id = recent_messages[-1].id

    # 组合对话文本
    chat_text = ""
    for msg in recent_messages:
        role_label = "User" if msg.role.value == "user" else "Assistant"
        chat_text += f"{role_label}: {msg.content}\n"

    # LLM Prompt
    system_prompt = f"""你是一个角色认知更新专家。你需要基于角色当前的认知状态 and 最近的对话，生成更新后的认知摘要。

认知摘要应当描述"角色此刻对自己、世界和用户的整体认知"，它将直接组装进角色的 System Prompt。

要求：
1. 保留旧认知中仍然有效的部分
2. 融入新对话中产生的重要认知变化
3. 用简洁的第三人称描述（如"她认为..."、"他知道..."）
4. 控制在 {settings.APP_COGNITION_MAX_WORDS} 字以内
5. 直接返回纯文本，不要使用 JSON 或 markdown 格式"""

    user_content = f"""当前认知状态：
{old_cognition}

最近的对话：
{chat_text}

请生成更新后的认知摘要："""

    # 【优化关键点】在大模型调用前，主动提交并结束当前事务，释放 SQLite 文件锁
    db.commit()

    try:
        response = llm_client.chat.completions.create(
            model=settings.LLM_MEMORY_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=settings.LLM_MEMORY_TEMPERATURE,
        )

        new_cognition = response.choices[0].message.content.strip()

        # 重新获取 Persona，在一个独立的小事务中更新认知数据
        persona = db.get(SessionPersona, persona_id)
        if persona:
            persona.cognition_state = new_cognition
            persona.last_cognition_update_msg_id = last_msg_id
            db.commit()

        print(f"[INFO] cognition_state 已更新 (persona_id={persona_id})")
        return new_cognition

    except Exception as e:
        print(f"==========================================")
        print(f"[ERROR] update_cognition_state: LLM 调用失败")
        print(f"[ERROR] 错误类型: {type(e).__name__}")
        print(f"[ERROR] 错误详情: {e}")
        print(f"==========================================")
        return None


# ──────────────────────────────────────────────
# 8. 安全删除（继承链重连）
# ──────────────────────────────────────────────

def safe_delete_session(session_id: int, db: DBSession) -> dict:
    """
    安全删除 Session：重连继承链 -> 验证 SQLite -> 清理 ChromaDB -> 提交。

    当删除继承链中间的节点时（如 s1 -> s2 -> s3 中删除 s2），
    自动将子节点重连到父节点，避免继承链断裂。

    安全顺序：
      1. 重连子 Session / Persona 的继承关系
      2. db.delete(session) + db.flush() → 验证所有 FK 约束
      3. 约束验证通过后，才清理 ChromaDB 数据
      4. db.commit() 最终提交

    如果 Step 2 的 flush 失败（FK 约束冲突等），ChromaDB 完全不受影响。

    返回：{"deleted_session_id": int, "relinked_children": int, "memories_deleted": int}
    """
    session = db.get(Session, session_id)
    if not session:
        raise ValueError(f"Session {session_id} 不存在")

    parent_session_id = session.parent_session_id
    result = {
        "deleted_session_id": session_id,
        "relinked_children": 0,
        "memories_deleted": 0,
    }

    # Step 1: 重连子 Session
    children_sessions = db.query(Session).filter(
        Session.parent_session_id == session_id
    ).all()

    for child in children_sessions:
        child.parent_session_id = parent_session_id
        result["relinked_children"] += 1

    # Step 2: 重连子 Persona + 收集 ChromaDB 清理所需信息
    persona = session.persona
    persona_id = None
    character_id = None

    if persona:
        persona_id = persona.id
        character_id = persona.character_id
        parent_persona_id = persona.parent_persona_id

        children_personas = db.query(SessionPersona).filter(
            SessionPersona.parent_persona_id == persona.id
        ).all()

        for child_p in children_personas:
            child_p.parent_persona_id = parent_persona_id

    # Step 3: 先验证 SQLite 操作（flush 但不 commit，检查所有 FK 约束）
    db.delete(session)
    try:
        db.flush()
    except Exception as e:
        db.rollback()
        print(f"==========================================")
        print(f"[ERROR] safe_delete_session: SQLite 约束验证失败，已回滚")
        print(f"[ERROR] 错误类型: {type(e).__name__}")
        print(f"[ERROR] 错误详情: {e}")
        print(f"==========================================")
        raise ValueError(f"Session {session_id} 删除失败（SQLite 约束冲突）: {e}")

    # Step 4: SQLite 验证通过，安全清理 ChromaDB
    if persona_id is not None and character_id is not None:
        try:
            collection = get_character_collection(character_id)
            existing = collection.get(
                where={"persona_id": persona_id},
                include=[],
            )
            chroma_count = len(existing["ids"]) if existing and existing.get("ids") else 0

            if chroma_count > 0:
                collection.delete(where={"persona_id": persona_id})
                result["memories_deleted"] = chroma_count
                print(f"[INFO] ChromaDB: 已删除 persona_id={persona_id} 的 {chroma_count} 条记忆")
        except Exception as e:
            # ChromaDB 清理失败不阻塞 SQLite 提交
            # 孤儿向量数据可接受（persona 已不存在，不会被检索到）
            print(f"[WARN] ChromaDB 清理失败（SQLite 将继续提交，孤儿数据不影响检索）: {e}")

    # Step 5: 最终提交
    db.commit()

    print(f"[INFO] safe_delete_session: 已安全删除 Session {session_id}，"
          f"重连了 {result['relinked_children']} 个子节点，"
          f"清理了 {result['memories_deleted']} 条记忆")

    return result
