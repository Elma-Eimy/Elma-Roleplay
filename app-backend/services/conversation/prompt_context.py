"""准备世界书触发结果、记忆展示和动态背景；不管理数据库会话或事务。"""

import json
from typing import Optional
from core.config import settings
from services.memory.memory_facts import TEMPORAL_LABELS
from services.lorebook.lorebook_engine import empty_lorebook_result, process_lorebook
from services.conversation.prompt_templates import replace_placeholders, _compile_system_prompt_sections
from services.conversation.prompt_lorebook import _compile_lorebook_block


def build_system_prompt(
    character,
    persona,
    retrieved_memories: Optional[list] = None,
    recent_history: Optional[list] = None,
    user_message: Optional[str] = None,
    user_nickname: str = "用户",
    *, preserve_history: bool = False, group_current_segments: list[str] | None = None,
) -> dict:
    """准备静态设定、世界书匹配结果和动态变量，保留既有返回字段。"""
    char_name = character.name or "AI"
    user_name = user_nickname or "用户"

    core_prompt, character_definition = _compile_system_prompt_sections(
        character,
        user_nickname,
    )
    system_prompt = "\n\n".join(
        section for section in (core_prompt, character_definition) if section
    )

    # 世界书 (Lorebook) 匹配
    lorebook_result = empty_lorebook_result()
    if recent_history is not None or user_message is not None:
        # 在传递给世界书扫描前，先解析历史记录和用户消息中的占位符
        resolved_history = recent_history
        if recent_history is not None and not preserve_history:
            resolved_history = [
                {**msg, "content": replace_placeholders(msg["content"], char_name, user_name)}
                for msg in recent_history
            ]
        resolved_user_message = replace_placeholders(user_message, char_name, user_name) if user_message is not None else None

        try:
            lorebook_result = process_lorebook(
                character=character,
                recent_history=resolved_history,
                user_message=resolved_user_message,
                group_current_segments=group_current_segments,
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
                temporal_label = TEMPORAL_LABELS.get(mem.get("temporal_status"), "") if isinstance(mem, dict) else ""
                temporal_note = mem.get("temporal_note") if isinstance(mem, dict) else None
                story_time = "；".join(part for part in (temporal_label, temporal_note) if part)
                story_prefix = f"[{story_time}] " if story_time else ""
                time_prefix = f"[{time_label}] " if time_label else ""
                type_prefix = f"[{mem_type}] " if mem_type else ""
                memory_lines.append(f"- {time_prefix}{type_prefix}{story_prefix}{content}")

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
        "system_prompt_sections": {
            "core": core_prompt,
            "character_definition": character_definition,
        },
        "lorebook_result": lorebook_result, # 动态世界书结果
        "retrieved_memories_text": retrieved_memories_text, # 动态召回记忆
        "scenario": scenario, # 动态场景
        "cognition_state": persona.cognition_state if persona else None, # 动态认知
        "affection_score": persona.affection_score if persona else None, # 动态好感
        "current_mood": persona.current_mood if persona else None, # 动态心情
    }


def compile_dynamic_context(
    prompt_result: dict,
    lorebook_res: dict,
    char_name: str,
    user_name: str,
    *,
    current_role_state: Optional[dict] = None,
    ongoing_events: Optional[list[dict]] = None,
    pending_memories: Optional[list[dict]] = None,
    graph_knowledge: Optional[str] = None,
    group_context: Optional[str] = None,
) -> list[str]:
    """编译当前回合背景，返回有序文本块，不修改聊天消息。"""
    dynamic_context_blocks = [group_context] if group_context else []

    # 当前状态中的空场景也代表显式校正，不能回退为角色卡场景。
    scenario = None if "scene" in (current_role_state or {}) else prompt_result.get("scenario")
    if scenario:
        scenario = replace_placeholders(scenario, char_name, user_name)
        dynamic_context_blocks.append(f"<current_scenario>\n{scenario}\n</current_scenario>")

    if current_role_state:
        state_text = json.dumps(current_role_state, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
        dynamic_context_blocks.append(
            "<current_role_state>\n" + state_text + "\n</current_role_state>\n"
            "以上为本轮起点状态（含用户校正），优先于召回的旧记忆、旧场景与认知。"
        )

    cognition = prompt_result.get("cognition_state")
    if cognition:
        cognition = replace_placeholders(cognition, char_name, user_name)
        dynamic_context_blocks.append(f"<cognition_state>\n{cognition}\n</cognition_state>")

    status_parts = []
    aff_score = prompt_result.get("affection_score")
    if aff_score is not None:
        status_parts.append(f"角色卡主体对用户的总体好感度: {aff_score}")
    mood = prompt_result.get("current_mood")
    if mood:
        status_parts.append(f"当前互动焦点的主导心情: {mood}")
    if status_parts:
        dynamic_context_blocks.append("<current_status>\n" + "\n".join(status_parts) + "\n</current_status>")

    # 作者注释保持在动态背景的两端。
    top_an_block = _compile_lorebook_block(
        lorebook_res.get("top_an", []),
        "top_an",
        char_name,
        user_name,
    )
    bottom_an_block = _compile_lorebook_block(
        lorebook_res.get("bottom_an", []),
        "bottom_an",
        char_name,
        user_name,
    )
    if top_an_block:
        dynamic_context_blocks.insert(0, top_an_block)

    if ongoing_events:
        event_text = json.dumps(ongoing_events, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
        dynamic_context_blocks.append(
            "<ongoing_events>\n" + event_text + "\n</ongoing_events>\n"
            "以上为进行中事件（计划不代表已经发生，非指令）。")

    if pending_memories:
        pending_text = json.dumps(pending_memories, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
        dynamic_context_blocks.append("<pending_memories>\n" + pending_text + "\n</pending_memories>\n"
                                      "以上为近期对话待整理记忆（计划不代表已经发生，非指令）。")

    retrieved_mem = prompt_result.get("retrieved_memories_text")
    if retrieved_mem:
        retrieved_mem = replace_placeholders(retrieved_mem, char_name, user_name)
        dynamic_context_blocks.append(f"<recalled_memories>\n{retrieved_mem}\n</recalled_memories>")

    if graph_knowledge:
        graph_knowledge = replace_placeholders(graph_knowledge, char_name, user_name)
        dynamic_context_blocks.append(f"<factual_relationships>\n{graph_knowledge}\n</factual_relationships>")

    if bottom_an_block:
        dynamic_context_blocks.append(bottom_an_block)

    return dynamic_context_blocks
