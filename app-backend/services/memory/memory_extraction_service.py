"""从对话中提取、规范化并持久化长期记忆。"""

import json
import re
from sqlalchemy.orm import Session as DBSession
from core.models import SessionPersona, ChatMessage, MemoryType
from services.infrastructure.llm_provider import get_llm_provider
from services.memory.memory_manager import add_memory_chunk, retrieve_memories
from services.memory.graph_service import upsert_graph_data
import services.memory.cognition_service as cognition_service
from core.config import settings


_MEMORY_MAX_CARDS_PER_BATCH = 8
_MEMORY_MAX_CONTENT_CHARS = 500
_LEADING_REFERENCE_RE = re.compile(
    r"^(?:他|她|它|他们|她们|它们|这|那|这个|那个|这里|那里|"
    r"he\b|she\b|it\b|they\b|this\b|that\b)",
    re.IGNORECASE,
)
_VAGUE_LOCATION_RE = re.compile(
    r"(?:这里|那里|这边|那边|此处|彼处|\bhere\b|\bthere\b)",
    re.IGNORECASE,
)
_TRIVIAL_MEMORY_TEXTS = {
    "你好", "您好", "谢谢", "感谢", "再见", "晚安", "哈哈", "呵呵",
    "ok", "okay", "thanks", "thankyou", "hello", "hi", "bye",
}


def _clean_memory_content(value: str) -> str:
    content = re.sub(r"\s+", " ", value).strip().strip('"\'`-*# ')
    if len(content) > _MEMORY_MAX_CONTENT_CHARS:
        content = content[:_MEMORY_MAX_CONTENT_CHARS].rstrip(" ,，。;；") + "…"
    return content


def normalize_extracted_memories(
    extracted_memories: list,
    source_message_ids: list[int],
) -> list[dict]:
    """Validate model output and return bounded, self-contained memory cards."""
    if not source_message_ids:
        return []

    valid_ids = set(source_message_ids)
    default_start = source_message_ids[0]
    default_end = source_message_ids[-1]
    parsed: list[dict] = []

    for memory in extracted_memories:
        if len(parsed) >= _MEMORY_MAX_CARDS_PER_BATCH:
            break
        if not isinstance(memory, dict):
            continue

        raw_content = memory.get("content")
        if not isinstance(raw_content, str):
            continue
        content = _clean_memory_content(raw_content)
        compact = re.sub(r"[\W_]+", "", content, flags=re.UNICODE).casefold()
        if len(compact) < 4 or compact in _TRIVIAL_MEMORY_TEXTS:
            continue
        # 不要仅仅因为实质性角色扮演记忆以代词开头就将其丢弃。只拒绝那些其含义几乎完全依赖于未解析指代的极短片段。
        if _LEADING_REFERENCE_RE.match(content) and (
            len(compact) < 8 or _VAGUE_LOCATION_RE.search(content)
        ):
            continue

        # 仅删除确定相同的记忆卡。对于否定对（例如“喜欢”/“不喜欢”），模糊文本相似度是不安全的；语义候选将在稍后通过受限的 LLM 关系检查进行解析。
        duplicate = False
        for existing in parsed:
            existing_compact = re.sub(
                r"[\W_]+", "", existing["content"], flags=re.UNICODE
            ).casefold()
            if compact == existing_compact:
                duplicate = True
                break
        if duplicate:
            continue

        raw_type = memory.get("memory_type", "fact")
        try:
            memory_type = MemoryType(raw_type)
        except (ValueError, TypeError):
            memory_type = MemoryType.fact

        try:
            importance = max(
                0.0, min(1.0, float(memory.get("importance_score", 0.5)))
            )
        except (ValueError, TypeError):
            importance = 0.5

        try:
            source_start = int(memory.get("source_start_message_id"))
            source_end = int(memory.get("source_end_message_id"))
        except (ValueError, TypeError):
            source_start, source_end = default_start, default_end
        if (
            source_start not in valid_ids
            or source_end not in valid_ids
            or source_start > source_end
        ):
            source_start, source_end = default_start, default_end

        parsed.append({
            "content": content,
            "memory_type": memory_type,
            "importance_score": importance,
            "source_start_message_id": source_start,
            "source_message_id": source_end,
        })

    return parsed


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


def get_memory_extract_batch_size() -> int:
    """返回单次记忆提纯允许处理的最大消息数。"""
    return max(30, max(1, int(settings.APP_MEMORY_EXTRACT_LIMIT)))


def get_effective_memory_extract_limit() -> int:
    """计算不会晚于短期历史淘汰点的实际提纯触发阈值。

    配置中的 memory_extract_history_limit 仍表示期望阈值；当它大于短期
    history 窗口时，自动收紧到 ``history_limit - handoff_margin``，为后台
    提纯任务留出少量缓冲消息。
    """
    configured_limit = max(1, int(settings.APP_MEMORY_EXTRACT_LIMIT))
    history_limit = max(1, int(settings.APP_CONTEXT_HISTORY_LIMIT))
    configured_margin = max(0, int(settings.APP_MEMORY_HANDOFF_MARGIN))
    margin = min(configured_margin, max(0, history_limit - 1))
    safe_limit = max(1, history_limit - margin)
    return min(configured_limit, safe_limit)


def get_memory_handoff_history_limit(session_id: int, db: DBSession) -> int:
    """返回本轮 Prompt 应保留的短期历史条数。

    后台提纯完成前，尚未总结的活跃消息不能先被短期窗口淘汰，因此窗口会
    临时扩展到未总结消息数；为防止外部服务长期失败导致 Prompt 无界增长，
    扩展上限与单次提纯批次大小保持一致。指针推进后会自动恢复常规窗口。
    """
    base_limit = max(1, int(settings.APP_CONTEXT_HISTORY_LIMIT))
    unsummarized_count = get_unsummarized_count(session_id, db)
    retained_unsummarized = min(
        unsummarized_count,
        get_memory_extract_batch_size(),
    )
    return max(base_limit, retained_unsummarized)


def resolve_memory_relationship_via_llm(
    old_content: str,
    new_content: str,
) -> dict[str, str]:
    """Classify one high-similarity candidate conservatively.

    Vector distance only selects a candidate; it must never delete or merge text
    by itself. On malformed output or provider failure, coexist is the safe and
    reversible fallback.
    """
    system_prompt = """你是一个长期记忆整理助手。比较一条已有记忆和一条新提取记忆，只能判断为以下三类之一：
- same：两条表达实质相同，且新记忆没有值得保留的新细节。
- replace：两条不能继续同时作为当前信息成立，或新记忆补充了应当成为默认表达的重要细节。
- coexist：两条可以同时成立，或无法确定它们是否描述同一件事。

特别注意否定词、程度变化、时间变化和关系变化。“喜欢”与“不喜欢”、“已经”与“尚未”绝不是 same。
判断不确定时必须选择 coexist。不要编造输入中没有的信息。

只返回 JSON：
{"relation":"same|replace|coexist","resolved_content":"..."}

same 时 resolved_content 使用已有记忆；replace 时输出一条可独立理解、以新信息为准且保留仍有效细节的记忆；coexist 时使用新记忆。"""
    user_content = (
        f"【已有记忆】：{old_content}\n"
        f"【新提取记忆】：{new_content}"
    )

    try:
        provider = get_llm_provider()
        response = provider.generate(
            model=settings.LLM_MEMORY_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        payload = json.loads(content.strip())
        relation = payload.get("relation") if isinstance(payload, dict) else None
        if relation not in {"same", "replace", "coexist"}:
            raise ValueError(f"unsupported relation: {relation!r}")

        default_content = old_content if relation == "same" else new_content
        resolved = payload.get("resolved_content", default_content)
        if not isinstance(resolved, str):
            resolved = default_content
        resolved = _clean_memory_content(resolved)
        if not resolved:
            resolved = default_content
        return {"relation": relation, "resolved_content": resolved}
    except Exception as exc:
        print(f"[WARN] resolve_memory_relationship_via_llm 失败，保守按 coexist 处理: {exc}")
        return {"relation": "coexist", "resolved_content": new_content}


def summarize_and_store_memory(session_id: int, db: DBSession) -> int:
    """
    核心提纯函数：从指定 Session 的未总结对话中提取结构化记忆，
    原子写入 SQLite 主数据与向量同步 Outbox 任务。

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
        ChatMessage.session_id == session_id,
        ChatMessage.is_active == True
    )
    if persona.last_summarized_msg_id is not None:
        query = query.filter(ChatMessage.id > persona.last_summarized_msg_id)

    # 限制单次提纯的最大消息数，防止大模型 Token 爆仓（默认设置为 30 条）
    MAX_BATCH_SIZE = get_memory_extract_batch_size()
    unsummarized = query.order_by(ChatMessage.id).limit(MAX_BATCH_SIZE).all()

    if not unsummarized:
        return 0

    # 记录待更新的指针 ID
    last_msg_id = unsummarized[-1].id

    # 组合对话文本
    chat_text = ""
    for msg in unsummarized:
        role_label = "User" if msg.role.value == "user" else "Assistant"
        chat_text += f"[消息ID={msg.id}] {role_label}: {msg.content}\n"

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

【记忆卡颗粒度规则】
1. 一张记忆卡必须是脱离原对话后仍能独立理解的完整事实、偏好、关系变化或事件。
2. 必须消解“他、她、它、那里、那个、这件事”等指代，写出明确的人名、角色名、地点或事件。
3. 同一事件中紧密关联的时间、地点、原因和结果应合并在一张卡中；不要按原始消息逐句切碎。
4. 两个可以独立成立、独立更新的事实应拆成两张卡，不要写成笼统的大段对话摘要。
5. 保留时间状态，如“过去”“目前”“计划于下个月”；不要把计划写成已经发生的事实。
6. 不要记录寒暄、复述、推测、模型自己的措辞或角色基础人设中已有内容。
7. 每张卡建议为 1 到 3 句，最多 300 个字符；本批最多输出 8 张记忆卡。
8. source_start_message_id 和 source_end_message_id 必须引用输入中真实存在的消息ID，并覆盖支持该记忆的最小连续消息范围。

【身份与指代规则】
1. 输入中的 User 始终代表“用户”；User 的第一人称应改写为“用户”。
2. 输入中的 Assistant 始终代表上方角色名称所指的角色；Assistant 的第一人称，以及明确指向 Assistant 的“你/他/她”，应改写为角色名称或“角色本人”。
3. 第三方代词只有在本批对话中能确定身份时才展开；无法确定时不得编造姓名，可以使用“用户提到的妹妹”等有依据的描述性身份。
4. 如果第三方身份和关系都无法确定，不要为了凑记忆而猜测。

你需要提取出三部分内容：
1. memories：长期记忆片段列表。每个记忆包含：
   - content：记忆的自然语言描述（例如："用户最喜欢的食物是草莓蛋糕"）
   - memory_type：必须是 "event" (事件), "emotion" (角色情绪), "relationship" (关系变化), "fact" (客观事实/设定) 之一
   - importance_score：0.0 到 1.0 之间的重要性评分
   - source_start_message_id：支持该记忆的第一条消息ID
   - source_end_message_id：支持该记忆的最后一条消息ID
2. entities：对话中出现的重要实体/概念列表。每个实体包含：
   - name：实体或人名（例如："小红"、"草莓蛋糕"、"东京"）
   - aliases：可选的明确昵称、简称或同一名称写法列表（例如：["阿墨", "墨哥"]）；不得把“他/她/它/这里/那个”等通用代词作为别名
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
    {"content": "用户最喜欢的食物是草莓蛋糕", "memory_type": "fact", "importance_score": 0.7, "source_start_message_id": 101, "source_end_message_id": 103}
  ],
  "entities": [
    {"name": "小红", "aliases": ["红红"], "entity_type": "person", "description": "用户的妹妹，非常喜欢吃草莓蛋糕"}
  ],
  "relations": [
    {"source": "用户", "relation_type": "sibling", "target": "小红", "description": "用户和小红是亲兄妹", "importance": 0.8},
    {"source": "小红", "relation_type": "likes", "target": "草莓蛋糕", "description": "小红非常喜欢草莓蛋糕", "importance": 0.7}
  ]
}

如果没有提取到任何内容，对应字段返回空数组 []。
不要输出任何 markdown 格式（如 ```json），直接返回纯 JSON 对象。"""

    try:
        provider = get_llm_provider()
        response = provider.generate(
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

    # Step 4: 解析、规范化并过滤碎片/寒暄/同批重复记忆
    parsed_memories = normalize_extracted_memories(
        extracted_memories,
        [message.id for message in unsummarized],
    )

    # Step 5: 原子批量写入（全部成功 or 全部回滚）
    #
    # 所有语义变化都创建新卡片，不原地覆盖旧内容和旧来源。记忆及其向量同步
    # Outbox 任务由同一个 SQLite 事务原子提交。
    max_importance = 0.0

    # 重新绑定 persona 到当前新事务中
    persona = db.get(SessionPersona, persona_id)
    if not persona:
        print(f"[ERROR] Persona {persona_id} 在大模型调用期间已被删除")
        return 0

    try:
        # 批量写入传统向量记忆片段，引入增量融合与去重
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

            # Distance only selects comparison candidates. It never directly
            # deletes or merges text. Compare closest candidates first and stop
            # at the first definite same/replace decision.
            candidates = sorted(
                (
                    memory for memory in existing_similar
                    if memory.get("id") is not None
                    and memory.get("distance", 1.0) < settings.APP_DEDUP_WRITE_THRESHOLD
                ),
                key=lambda memory: memory.get("distance", 1.0),
            )
            decision = None
            matched_candidate = None
            for candidate in candidates:
                candidate_decision = resolve_memory_relationship_via_llm(
                    candidate["content"], pm["content"]
                )
                if candidate_decision["relation"] != "coexist":
                    decision = candidate_decision
                    matched_candidate = candidate
                    break

            if decision and decision["relation"] == "same":
                print(
                    f"[INFO] 记忆判定 same: 保留 chunk_id={matched_candidate['id']}，"
                    "跳过重复写入"
                )
            else:
                supersedes_id = None
                content_to_store = pm["content"]
                importance_to_store = float(pm["importance_score"])
                if decision and decision["relation"] == "replace":
                    supersedes_id = matched_candidate["id"]
                    content_to_store = decision["resolved_content"]
                    old_importance = float(
                        matched_candidate.get("importance_score", 0.5)
                    )
                    importance_to_store = min(
                        1.0,
                        max(old_importance, importance_to_store)
                        + (1.0 - max(old_importance, importance_to_store)) * 0.1,
                    )

                chunk = add_memory_chunk(
                    persona_id=persona_id,
                    character_id=character_id,
                    content=content_to_store,
                    memory_type=pm["memory_type"],
                    importance_score=importance_to_store,
                    origin_session_id=session_id,
                    source_message_id=pm["source_message_id"],
                    db=db,
                    source_start_message_id=pm["source_start_message_id"],
                    supersedes_id=supersedes_id,
                    auto_commit=False,
                )
                if supersedes_id is not None:
                    print(
                        f"[INFO] 记忆判定 replace: 新建 chunk_id={chunk.id} "
                        f"替代 chunk_id={supersedes_id}"
                    )

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

        # 单次原子提交（SQLite 侧）
        db.commit()

    except Exception as e:
        # 任何一步 SQLite 操作失败 → 全部回滚
        db.rollback()

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
            cognition_service.update_cognition_state(persona_id, db)
            print(f"[INFO] 高重要性记忆 ({max_importance:.2f}) 触发了 cognition_state 即时更新")
        except Exception as e:
            print(f"[WARN] cognition_state 即时更新失败: {e}")

    return success_count
