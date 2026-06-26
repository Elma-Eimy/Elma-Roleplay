"""
认知状态更新与记忆提纯服务
"""

import json
from typing import Optional
from sqlalchemy.orm import Session as DBSession
from core.models import SessionPersona, ChatMessage, MemoryType, MemoryChunk
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
        ChatMessage.session_id == session_id,
        ChatMessage.is_active == True
    )
    if persona.last_summarized_msg_id is not None:
        query = query.filter(ChatMessage.id > persona.last_summarized_msg_id)

    return query.count()


def merge_memories_via_llm(old_content: str, new_content: str) -> str:
    """
    使用快速 LLM 合并两个语义相似的记忆。

    将待合并内容通过 user 消息传入，而非嵌入 system prompt f-string，
    避免内容中含有 triple-quote 等特殊字符时破坏 prompt 结构。
    """
    system_prompt = (
        "你是一个记忆整理助手。你会收到两条相似的记忆片段，请将它们合并为"
        "一句最精简、无冗余、包含所有最新细节的自然语言陈述。\n"
        "如果新记忆是对旧记忆的纠正或状态更新，请以新记忆为准。\n"
        "不要输出任何解释或前缀，直接返回合并后的单句记忆陈述。"
    )
    user_content = (
        f"【记忆 A (旧)】: {old_content}\n"
        f"【记忆 B (新)】: {new_content}\n\n"
        "请合并以上两条记忆，直接返回合并后的单句陈述。"
    )

    try:
        response = llm_client.chat.completions.create(
            model=settings.LLM_MEMORY_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.1,  # 极低温度以防自由发挥
        )
        merged = response.choices[0].message.content.strip()
        # 剥离可能生成的引号
        if merged.startswith('"') and merged.endswith('"'):
            merged = merged[1:-1]
        if merged.startswith("'") and merged.endswith("'"):
            merged = merged[1:-1]
        if merged:
            return merged.strip()
    except Exception as e:
        print(f"[WARN] merge_memories_via_llm 失败: {e}")

    # 兜底返回新记忆
    return new_content


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
        ChatMessage.session_id == session_id,
        ChatMessage.is_active == True
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

    # 获取角色人设背景，用于过滤提取冗余
    char = persona.character
    char_name = char.name if char else ""
    char_description = char.description if char else ""
    char_personality = char.personality if char else ""
    char_scenario = char.scenario if char else ""

    char_info_block = f"""【角色基础人设】
角色名称：{char_name}
角色设定：{char_description}
性格特点：{char_personality or ''}
初始场景：{char_scenario or ''}

【防冗余提取规则】
你必须过滤掉任何已经明确存在于上述【角色基础人设】中的已知事实（例如 AI角色的本名、基础身份关系、人设中已明示的特征/设定）。只提取对话中产生的【新事实】、【新关系变动】或【人设之外的个性化互动细节】。

"""

    # Step 3: 调用 LLM 提纯（升级版 Prompt，要求返回结构化数据，包括知识图谱的实体与关系）
    system_prompt = char_info_block + """你是一个专业的"记忆与知识整理员"。你的任务是从下面这段用户与AI角色的对话中，提取出值得长期记住的信息以及相关的知识图谱（实体与关系）。

请过滤掉无意义的闲聊，只保留有价值的内容。

你需要提取出三部分内容：
1. memories：长期记忆片段列表。每个记忆包含：
   - content：记忆的自然语言描述（例如："用户最喜欢的食物是草莓蛋糕"）
   - memory_type：必须是 "event" (事件), "emotion" (角色情绪), "relationship" (关系变化), "fact" (客观事实/设定) 之一
   - importance_score：0.0 到 1.0 之间的重要性评分
2. entities：对话中出现的重要实体/概念列表。每个实体包含：
   - name：实体或人名（例如："小红"、"草莓蛋糕"、"东京"）
   - entity_type：必须是 "person" (人物), "place" (地点), "object" (物品), "event" (事件), "concept" (概念/其它) 之一
   - description：对该实体的简要描述、状态或喜好（第一人称视角，例如："用户的妹妹，非常喜欢吃草莓蛋糕。"）
3. relations：实体之间的关系列表。每个关系包含：
   - source：源实体名称（例如："用户" 或 "小红"）
   - target：目标实体名称（例如："小红" 或 "草莓蛋糕"）
   - relation_type：关系词/连接词（必须是简短英文单词或词组，例如："sibling", "likes", "visited", "friend" 等）
   - description：该关系的第一人称自然语言描述（例如："用户和小红是亲兄妹" 或 "小红非常喜欢草莓蛋糕"）
   - importance：0.0 到 1.0 之间的重要性评分

你必须以一个 JSON 对象格式返回，结构如下：
{
  "memories": [
    {"content": "用户最喜欢的食物是草莓蛋糕", "memory_type": "fact", "importance_score": 0.7}
  ],
  "entities": [
    {"name": "小红", "entity_type": "person", "description": "用户的妹妹，非常喜欢吃草莓蛋糕"}
  ],
  "relations": [
    {"source": "用户", "relation_type": "sibling", "target": "小红", "description": "用户和小红是亲兄妹", "importance": 0.8},
    {"source": "小红", "relation_type": "likes", "target": "草莓蛋糕", "description": "小红非常喜欢草莓蛋糕", "importance": 0.7}
  ]
}

如果没有提取到任何内容，对应字段返回空数组 []。
不要输出任何 markdown 格式（如 ```json），直接返回纯 JSON 对象。"""

    try:
        response = llm_client.chat.completions.create(
            model=settings.LLM_MEMORY_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请提取以下对话中的重要记忆与图谱三元组：\n{chat_text}"},
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
            raw_data = json.loads(content)
        except json.JSONDecodeError as e:
            print(f"[ERROR] LLM 返回的 JSON 格式非法: {content}")
            return 0

        # 初始化提取出来的图数据与记忆数据
        extracted_entities = []
        extracted_relations = []

        if isinstance(raw_data, dict):
            extracted_memories = raw_data.get("memories", [])
            extracted_entities = raw_data.get("entities", [])
            extracted_relations = raw_data.get("relations", [])
        else:
            # 兼容旧版本的纯 array 返回
            extracted_memories = raw_data

        if not isinstance(extracted_memories, list):
            print("[WARN] LLM 未返回列表结构，提纯中止，等待下次重试。")
            return 0 # 不更新 last_summarized_msg_id

        if len(extracted_memories) == 0 and len(extracted_entities) == 0:
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

    # Step 5: 原子批量写入（全部成功 or 全部回滚）
    #
    # 执行顺序（严格保证一致性）：
    #   ① 所有 SQLite ORM flush（add / update，均不 commit）
    #   ② 新建记忆写入 ChromaDB（add_memory_chunk 内部，auto_commit=False 时
    #      已在 flush 后立即写入，这是 add 路径的固有设计）
    #   ③ db.commit()  —— SQLite 侧原子落盘
    #   ④ 执行所有延迟 ChromaDB 更新闭包（update 路径，仅在 commit 成功后写入）
    #
    # 这样设计确保：
    #   • update 路径：ChromaDB 永远在 SQLite commit 之后才写，commit 失败则
    #     ChromaDB 无任何修改，无需还原，天然一致。
    #   • add 路径：ChromaDB 先写，commit 失败时通过 chroma_ids_written 回滚。
    chroma_ids_written = []          # add_memory_chunk 写入的 ChromaDB doc id 列表
    pending_chroma_updates = []      # update_memory_chunk 产生的延迟写入闭包列表
    max_importance = 0.0

    # 重新绑定 persona 到当前新事务中
    persona = db.get(SessionPersona, persona_id)
    if not persona:
        print(f"[ERROR] Persona {persona_id} 在大模型调用期间已被删除")
        return 0

    try:
        # 批量写入传统向量记忆片段，引入增量融合与去重
        # 注意：这两个 import 因循环依赖不能放在文件顶层，保留在函数体内
        from services.memory_manager import retrieve_memories, update_memory_chunk
        from services.graph_service import upsert_graph_data

        for pm in parsed_memories:
            # 1. 检索当前 Persona（含祖先链）下最多 3 条高相似度记忆（#5 fix：top_k=1 时
            #    若最佳候选被重要性/距离过滤掉会漏匹配，top_k=3 提供更充分的候选集）
            existing_similar = retrieve_memories(
                persona_id=persona_id,
                character_id=character_id,
                query=pm["content"],
                db=db,
                top_k=3,
                min_importance=0.0
            )

            # 按距离阈值筛选，再分为本地与祖先两类
            similar_in_threshold = [
                m for m in existing_similar if m.get("distance", 1.0) < settings.APP_DEDUP_WRITE_THRESHOLD
            ]
            local_candidates  = [m for m in similar_in_threshold if m.get("persona_id") == persona_id]
            ancestor_candidates = [m for m in similar_in_threshold if m.get("persona_id") != persona_id]

            if local_candidates:
                # 2a. 本地记忆：将所有候选链式合并（chain-merge）进新内容，
                #     只原地更新最佳匹配（得分最高/距离最近的第一条），其余靠检索侧去重自然消解
                merged_content = pm["content"]
                # 重要性融合公式：max(旧, 新) + 剩余空间 * 0.1
                # 效果：高分端趋于饱和（如 0.95 → 0.955），低分端有明显提升（如 0.3 → 0.37）
                merged_imp = float(pm["importance_score"])
                for candidate in local_candidates:
                    merged_content = merge_memories_via_llm(candidate["content"], merged_content)
                    old_imp = float(candidate.get("importance_score", 0.5))
                    merged_imp = min(1.0, max(old_imp, merged_imp) + (1.0 - max(old_imp, merged_imp)) * 0.1)

                # 仅更新第一条（最佳匹配），ChromaDB 写入延迟到 commit 后
                best_local = local_candidates[0]
                chunk_id = best_local["id"]
                updated_chunk = update_memory_chunk(
                    chunk_id=chunk_id,
                    content=merged_content,
                    importance_score=merged_imp,
                    db=db,
                    auto_commit=False
                )
                # 收集延迟写入闭包（字段快照已在 update_memory_chunk 内完成）
                if updated_chunk is not None:
                    pending_fn = getattr(updated_chunk, "_pending_chroma_update", None)
                    if pending_fn is not None:
                        pending_chroma_updates.append(pending_fn)
                print(f"[INFO] 语义去重: 链式合并 {len(local_candidates)} 条本地记忆 -> "
                      f"chunk_id={chunk_id} -> '{merged_content}'")

            elif ancestor_candidates:
                # 2b. 无本地匹配，但祖先有相似记忆 → 写时复制 (COW)
                best_ancestor = ancestor_candidates[0]
                merged_content = merge_memories_via_llm(best_ancestor["content"], pm["content"])
                old_imp = float(best_ancestor.get("importance_score", 0.5))
                new_imp = float(pm["importance_score"])
                merged_imp = min(1.0, max(old_imp, new_imp) + (1.0 - max(old_imp, new_imp)) * 0.1)
                chunk = add_memory_chunk(
                    persona_id=persona_id,
                    character_id=character_id,
                    content=merged_content,
                    memory_type=pm["memory_type"],
                    importance_score=merged_imp,
                    origin_session_id=session_id,
                    source_message_id=last_msg_id,
                    db=db,
                    auto_commit=False,
                )
                chroma_ids_written.append(chunk.chroma_doc_id)
                print(f"[INFO] 语义去重: 继承祖先记忆并进行写时复制 (COW) -> '{merged_content}'")

            else:
                # 3. 未找到相似记忆：正常插入新记录
                chunk = add_memory_chunk(
                    persona_id=persona_id,
                    character_id=character_id,
                    content=pm["content"],
                    memory_type=pm["memory_type"],
                    importance_score=pm["importance_score"],
                    origin_session_id=session_id,
                    source_message_id=last_msg_id,
                    db=db,
                    auto_commit=False,
                )
                chroma_ids_written.append(chunk.chroma_doc_id)

            if pm["importance_score"] > max_importance:
                max_importance = pm["importance_score"]

        # 批量写入图谱实体与关系
        if extracted_entities or extracted_relations:
            upsert_graph_data(
                persona_id=persona_id,
                entities=extracted_entities,
                relations=extracted_relations,
                db=db
            )

        # 所有记忆写入成功，更新进度指针
        persona.last_summarized_msg_id = last_msg_id

        # ③ 单次原子提交（SQLite 侧）
        db.commit()

        # ④ SQLite commit 成功后，执行所有延迟 ChromaDB 更新（update 路径）
        #    此时 commit 已完成，即使 ChromaDB 写入失败，SQLite 数据已持久化，
        #    最坏情况是向量侧短暂滞后，下次 update 会覆盖修正。
        if pending_chroma_updates:
            chroma_update_errors = []
            for fn in pending_chroma_updates:
                try:
                    fn()
                except Exception as chroma_err:
                    chroma_update_errors.append(chroma_err)
            if chroma_update_errors:
                print(f"[WARN] {len(chroma_update_errors)} 条延迟 ChromaDB 更新失败（SQLite 已成功提交）: "
                      f"{chroma_update_errors[0]}")

    except Exception as e:
        # 任何一步 SQLite 操作失败 → 全部回滚
        # 注意：update 路径的 pending_chroma_updates 尚未执行，ChromaDB 无任何修改，无需还原。
        db.rollback()

        # 清理 add 路径已写入 ChromaDB 的文档（恢复到本次操作前的状态）
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
        ChatMessage.session_id == session_id,
        ChatMessage.is_active == True
    )
    if persona.last_cognition_update_msg_id is not None:
        query = query.filter(ChatMessage.id > persona.last_cognition_update_msg_id)

    return query.count()


def update_cognition_state(persona_id: int, db: DBSession) -> Optional[str]:
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
        ChatMessage.session_id == session_id,
        ChatMessage.is_active == True
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
