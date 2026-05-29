"""
认知状态更新与记忆提纯服务
"""

import json
from sqlalchemy.orm import Session as DBSession
from core.models import SessionPersona, ChatMessage, MemoryType
from services.chat_engine import llm_client
from core.config import settings


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
    # 动态导入以防循环依赖
    from services.memory_manager import add_memory_chunk

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

    # 限制单次提纯的最大消息数，防止大模型 Token 爆仓（默认设置为 30 条）
    MAX_BATCH_SIZE = max(30, settings.APP_MEMORY_EXTRACT_LIMIT)
    unsummarized = query.order_by(ChatMessage.id).limit(MAX_BATCH_SIZE).all()

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

    # Step 5: 原子批量写入（全部成功 or 全部回滚）
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
                source_message_id=last_msg_id,
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

认知摘要应当描述"角色（名字为：{persona.character.name}）此刻对自己、世界和用户的整体认知"，它将直接组装进角色的 System Prompt。

要求：
1. 保留旧认知中仍然有效的部分
2. 融入新对话中产生的重要认知变化
3. 必须使用角色（名字为：{persona.character.name}）自己的第一人称视角描述（如"作为 {persona.character.name}，我认为..."、"我知道..."、"我感觉..."），禁止使用第三人称（如"他"、"她"、"{persona.character.name}认为..."），以使生成的内容能够作为 {persona.character.name} 的第一人称心声无缝融入扮演设定。
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
