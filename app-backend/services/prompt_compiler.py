import re
import json
from typing import Optional
from core.config import settings
import core.models as models
from services.lorebook_engine import process_lorebook

def replace_placeholders(text: str, char_name: str, user_name: str) -> str:
    """
    替换文本中的 char/user 占位符。
    支持变体：
      - {{char}} / {{user}}
      - <char> / <character> / <user>
      - {$char} / {$character} / {$user}
    支持不区分大小写，且容忍大括号/尖括号内的空格。
    使用 lambda 函数避免用户昵称/角色名中的特殊字符（如反斜杠、$）造成正则转义或捕获组错误。
    """
    if not text:
        return text

    # 1. 替换 {{char}} / {{user}}
    pattern_curly = re.compile(r'\{\{\s*(char|user)\s*\}\}', re.IGNORECASE)
    def _repl_curly(match):
        var = match.group(1).lower()
        if var == 'char':
            return char_name
        elif var == 'user':
            return user_name
        return match.group(0)
    text = pattern_curly.sub(_repl_curly, text)

    # 2. 替换 <char> / <character> / <user>
    pattern_angle = re.compile(r'<\s*(char|character|user)\s*>', re.IGNORECASE)
    def _repl_angle(match):
        var = match.group(1).lower()
        if var in ('char', 'character'):
            return char_name
        elif var == 'user':
            return user_name
        return match.group(0)
    text = pattern_angle.sub(_repl_angle, text)

    # 3. 替换 {$char} / {$character} / {$user}
    pattern_dollar = re.compile(r'\{\s*\$\s*(char|character|user)\s*\}', re.IGNORECASE)
    def _repl_dollar(match):
        var = match.group(1).lower()
        if var in ('char', 'character'):
            return char_name
        elif var == 'user':
            return user_name
        return match.group(0)
    text = pattern_dollar.sub(_repl_dollar, text)

    return text

def compile_prompt_templates(text: str, character, original_prompt: str) -> str:
    """
    编译系统提示词模板中的嵌套宏：
      - {{original}} -> 默认的介绍块 (description + personality)
      - {{personality}} / {{description}} / {{scenario}} / {{mesExamples}} -> 对应角色卡字段
    不区分大小写，且容忍空格。
    """
    if not text:
        return text

    # 1. 替换 {{original}}
    text = re.compile(r'\{\{\s*original\s*\}\}', re.IGNORECASE).sub(lambda m: original_prompt, text)

    # 2. 替换嵌套属性字段
    field_map = {
        "personality": character.personality or "",
        "description": character.description or "",
        "scenario": character.scenario or "",
        "mesexamples": character.mes_example or "",
        "mes_examples": character.mes_example or "",
        "mes_example": character.mes_example or "",
    }

    def _field_repl(match):
        field_name = match.group(1).lower().replace("_", "").replace(" ", "")
        return field_map.get(field_name, match.group(0))

    pattern_fields = re.compile(
        r'\{\{\s*(personality|description|scenario|mesexamples|mes_examples|mes_example)\s*\}\}',
        re.IGNORECASE
    )
    text = pattern_fields.sub(_field_repl, text)

    return text

def compile_system_prompt(character, persona, user_nickname: str = "用户") -> str:
    """
    静态 System Prompt 组装与编译。
    """
    char_name = character.name or "AI"
    user_name = user_nickname or "用户"

    # 1. 构造默认的 original prompt 模块
    default_prompt_parts = []
    if character.description:
        default_prompt_parts.append(f"【角色设定】\n{character.description}")
    if character.personality:
        default_prompt_parts.append(f"【性格特点】\n{character.personality}")
    original_prompt = "\n\n".join(default_prompt_parts)

    sections = []

    # 2. 核心人设编译
    if character.system_prompt_override:
        # 智能检测：如果自定义预设中没有显式包含任何设定相关的占位符，自动在最前面拼接上原设描述，防止设定丢失
        has_original = re.search(r'\{\{\s*original\s*\}\}', character.system_prompt_override, re.IGNORECASE) is not None
        has_description = re.search(r'\{\{\s*description\s*\}\}', character.system_prompt_override, re.IGNORECASE) is not None
        has_personality = re.search(r'\{\{\s*personality\s*\}\}', character.system_prompt_override, re.IGNORECASE) is not None
        
        if not (has_original or has_description or has_personality) and original_prompt:
            sections.append(original_prompt)

        compiled_override = compile_prompt_templates(
            character.system_prompt_override, character, original_prompt
        )
        sections.append(compiled_override)
    else:
        if original_prompt:
            sections.append(original_prompt)

    # 3. 结构化输出指令 (静态)
    xml_instructions = """【重要：输出格式要求】
你必须且只能按照以下 XML 标签结构进行回复，绝对不要包含任何 markdown 代码块标记（如 ```xml 或 ```html）：
<reply>你的第一人称角色扮演回复文本（支持动作星号包裹与台词双引号包裹）</reply>
<status emotion="当前心情标签（例如：开心、平静、害羞等单个词语）" affection_change="好感度整数变化量（必须是整数，范围在 -5 到 5 之间）"/>"""
    sections.append(xml_instructions)

    # 4. 后置扮演规则编译
    post_instructions = character.post_history_instructions or None
    if post_instructions:
        compiled_post = compile_prompt_templates(
            post_instructions, character, original_prompt
        )
        sections.append(f"【扮演补充规则】\n{compiled_post}")

    # 5. 对话示例编译 (非子会话附加)
    if not (persona and persona.parent_persona_id):
        if character.mes_example and character.mes_example.strip():
            sections.append(f"【对话示例】\n{character.mes_example.strip()}")

    system_prompt = "\n\n".join(sections)

    # 6. 对生成的 System Prompt 整体进行最终的 char/user 占位符替换
    system_prompt = replace_placeholders(system_prompt, char_name, user_name)

    return system_prompt


def build_system_prompt(
    character,
    persona,
    retrieved_memories: Optional[list] = None,
    recent_history: Optional[list] = None,
    user_message: Optional[str] = None,
    user_nickname: str = "用户"
) -> dict:
    """
    静态 System Prompt 组装与编译。返回已编译静态部分，并提取动态变量供 User Message 拼接。
    """
    char_name = character.name or "AI"
    user_name = user_nickname or "用户"

    system_prompt = compile_system_prompt(character, persona, user_nickname)

    # ── 动态变量处理 ──
    
    # 世界书 (Lorebook) 匹配
    lorebook_result = {"before_char": [], "after_char": []}
    if recent_history is not None or user_message is not None:
        # 在传递给世界书扫描前，先解析历史记录和用户消息中的占位符
        resolved_history = None
        if recent_history is not None:
            resolved_history = [
                {**msg, "content": replace_placeholders(msg["content"], char_name, user_name)}
                for msg in recent_history
            ]
        resolved_user_message = replace_placeholders(user_message, char_name, user_name) if user_message is not None else None

        try:
            lorebook_result = process_lorebook(
                character=character,
                recent_history=resolved_history,
                user_message=resolved_user_message
            )
        except Exception as e:
            print(f"[WARN] build_system_prompt: 处理世界书匹配失败: {e}")

    # 检索到的记忆 (RAG)
    retrieved_memories_text = None
    if retrieved_memories:
        memory_lines = []
        for mem in retrieved_memories:
            content = mem.get("content", "") if isinstance(mem, dict) else str(mem)
            mem_type = mem.get("memory_type", "") if isinstance(mem, dict) else ""
            
            # 解析时间标签
            time_label = ""
            if isinstance(mem, dict) and "turns_passed" in mem:
                turns_passed = mem["turns_passed"]
                for tier in settings.APP_RP_TIME_TIERS:
                    if turns_passed <= tier.get("max_turns", 9999999):
                        time_label = tier.get("label", "")
                        break
                if not time_label:
                    time_label = "很久以前"
            
            if content:
                time_prefix = f"[{time_label}] " if time_label else ""
                type_prefix = f"[{mem_type}] " if mem_type else ""
                memory_lines.append(f"- {time_prefix}{type_prefix}{content}")

        if memory_lines:
            retrieved_memories_text = "\n".join(memory_lines)

    # 场景定义
    scenario = None
    if persona and persona.current_scenario_override:
        scenario = persona.current_scenario_override
    elif character.scenario:
        scenario = character.scenario

    return {
        "system_prompt": system_prompt, # 纯静态部分，极度缓存友好
        "lorebook_result": lorebook_result, # 动态世界书结果
        "retrieved_memories_text": retrieved_memories_text, # 动态召回记忆
        "scenario": scenario, # 动态场景
        "cognition_state": persona.cognition_state if persona else None, # 动态认知
        "affection_score": persona.affection_score if persona else None, # 动态好感
        "current_mood": persona.current_mood if persona else None, # 动态心情
    }


async def _build_chat_messages(
    character,
    persona,
    recent_history: list,
    user_message: str,
    retrieved_memories: Optional[list] = None,
    graph_knowledge: Optional[str] = None,
    db=None,
    user_nickname: str = "用户",
) -> list:
    """
    组装 LLM 所需的完整 messages 列表（system + history + 动态上下文）。
    """
    char_name = character.name or "AI"
    user_name = user_nickname or "用户"

    # Step 1: 组装缓存友好型静态 System Prompt 并抽取动态要素
    prompt_result = build_system_prompt(
        character=character,
        persona=persona,
        retrieved_memories=retrieved_memories,
        recent_history=recent_history,
        user_message=user_message,
        user_nickname=user_nickname,
    )

    # Step 2: 动态示例继承（仅拉取父会话分叉点之前最后 4 条，杜绝未来泄漏）
    if persona and persona.parent_persona_id and db is not None:
        from fastapi.concurrency import run_in_threadpool

        def fetch_parent_history():
            parent_persona = db.get(models.SessionPersona, persona.parent_persona_id)
            child_session = db.get(models.Session, persona.session_id)
            fork_message_id = child_session.fork_message_id if child_session else None

            # 旧会话没有可靠的分叉点时，宁可不注入父示例，也不能读取父会话
            # 当前最新消息并造成未来剧情泄漏。
            if parent_persona and fork_message_id is not None:
                fork_message_exists = db.query(models.ChatMessage.id).filter(
                    models.ChatMessage.id == fork_message_id,
                    models.ChatMessage.session_id == parent_persona.session_id,
                ).first()
                if not fork_message_exists:
                    return []

                return db.query(models.ChatMessage).filter(
                    models.ChatMessage.session_id == parent_persona.session_id,
                    models.ChatMessage.id < fork_message_id,
                    models.ChatMessage.role.in_([models.MessageRole.user, models.MessageRole.assistant]),
                    models.ChatMessage.is_active == True
                ).order_by(models.ChatMessage.id.desc()).limit(4).all()
            return []

        parent_msgs = await run_in_threadpool(fetch_parent_history)
        if parent_msgs:
            parent_msgs.reverse()
            parent_history_formatted = [
                {
                    "role": msg.role.value,
                    "content": msg.content,
                    "emotion_tag": getattr(msg, "emotion_tag", "平静"),
                    "affection_change": getattr(msg, "affection_change", 0)
                }
                for msg in parent_msgs
            ]
            recent_history = parent_history_formatted + recent_history

    # Step 3: 构建 messages 列表（首位为单条静态 system prompt）
    messages = [{"role": "system", "content": prompt_result["system_prompt"]}]

    # 历史消息：assistant 消息统一包装为 XML 格式保持上下文一致性
    for msg in recent_history:
        if msg["role"] == "assistant":
            content_str = replace_placeholders(msg["content"], char_name, user_name)
            emo = msg.get("emotion_tag") or "平静"
            change = msg.get("affection_change") or 0
            fallback_xml = f"<reply>{content_str}</reply>\n<status emotion=\"{emo}\" affection_change=\"{int(change)}\"/>"
            messages.append({"role": "assistant", "content": fallback_xml})
        else:
            content_str = replace_placeholders(msg["content"], char_name, user_name)
            messages.append({"role": msg["role"], "content": content_str})

    # Step 4: 动态上下文包装，统一挂载到最后一轮 User 消息中
    dynamic_context_blocks = []

    # 4.1 场景与认知状态
    scenario = prompt_result.get("scenario")
    if scenario:
        scenario = replace_placeholders(scenario, char_name, user_name)
        dynamic_context_blocks.append(f"<current_scenario>\n{scenario}\n</current_scenario>")

    cognition = prompt_result.get("cognition_state")
    if cognition:
        cognition = replace_placeholders(cognition, char_name, user_name)
        dynamic_context_blocks.append(f"<cognition_state>\n{cognition}\n</cognition_state>")

    # 4.2 心情与好感度
    status_parts = []
    aff_score = prompt_result.get("affection_score")
    if aff_score is not None:
        status_parts.append(f"对用户好感度: {aff_score}")
    mood = prompt_result.get("current_mood")
    if mood:
        status_parts.append(f"当前心情: {mood}")
    if status_parts:
        dynamic_context_blocks.append("<current_status>\n" + "\n".join(status_parts) + "\n</current_status>")

    # 4.3 世界书 (Lorebook) 知识
    lorebook_res = prompt_result.get("lorebook_result", {"before_char": [], "after_char": []})
    lore_contents = []
    for e in (lorebook_res.get("before_char", []) + lorebook_res.get("after_char", [])):
        content = e.get("content", "").strip()
        if content:
            content = replace_placeholders(content, char_name, user_name)
            lore_contents.append(content)
    if lore_contents:
        dynamic_context_blocks.append("<lorebook_knowledge>\n" + "\n\n".join(lore_contents) + "\n</lorebook_knowledge>")

    # 4.4 召回长期记忆 (RAG)
    retrieved_mem = prompt_result.get("retrieved_memories_text")
    if retrieved_mem:
        retrieved_mem = replace_placeholders(retrieved_mem, char_name, user_name)
        dynamic_context_blocks.append(f"<recalled_memories>\n{retrieved_mem}\n</recalled_memories>")

    # 4.4.5 召回精确图谱关系 (Graph RAG)
    if graph_knowledge:
        graph_knowledge = replace_placeholders(graph_knowledge, char_name, user_name)
        dynamic_context_blocks.append(f"<factual_relationships>\n{graph_knowledge}\n</factual_relationships>")

    # 4.5 拼装增强的 User 消息内容
    enhanced_user_content = ""
    if dynamic_context_blocks:
        enhanced_user_content += "【系统提供的上下文背景信息（大模型请注意结合以下背景进行角色扮演回复）：】\n"
        enhanced_user_content += "\n\n".join(dynamic_context_blocks) + "\n\n"
    
    resolved_user_message = replace_placeholders(user_message, char_name, user_name)
    enhanced_user_content += f"【当前用户的最新消息：】\n{resolved_user_message}"

    messages.append({"role": "user", "content": enhanced_user_content})

    # Step 5: 调用 LLM 之前主动提交并结束当前事务，释放 SQLite 文件锁
    if db is not None:
        try:
            from fastapi.concurrency import run_in_threadpool
            await run_in_threadpool(db.commit)
        except Exception as e:
            print(f"[WARN] prompt_compiler._build_chat_messages: 释放 SQLite 锁失败: {e}")

    return messages
