"""
对话引擎 — 负责调度模型、合并参数并调用大模型 API。
已重构解耦，各具体子职责分别划分至 clients.py, prompt_compiler.py, parse.py, llm_logger.py。
"""

import json
from typing import Optional

from core.config import settings

# ── 基础设施导入与重导出 ──
from services.clients import (
    chroma_client,
    openai_ef,
    llm_client,
    llm_client_async,
    LLM_MODEL,
    RobustOpenAIEmbeddingFunction
)

# ── Prompt 编译模块导入与重导出 ──
from services.prompt_compiler import (
    compile_system_prompt,
    replace_placeholders,
    build_system_prompt,
    _build_chat_messages
)

# ── 解析器导入与重导出 ──
from services.parse import extract_xml_block, _extract_xml_block

# ── 世界书引擎重导出 ──
from services.lorebook_engine import process_lorebook

# ── 日志记录器导入与重导出 ──
from services.llm_logger import (
    log_llm_non_stream,
    log_llm_stream_wrapper,
    log_llm_stream_wrapper_async,
    # 兼容性私有别名
    log_llm_non_stream as _log_llm_non_stream,
    log_llm_stream_wrapper as _log_llm_stream_wrapper,
    log_llm_stream_wrapper_async as _log_llm_stream_wrapper_async
)


def _resolve_model(use_reasoning: Optional[bool]) -> str:
    """
    根据请求参数决定本次调用使用哪个模型。
    """
    if use_reasoning is True:
        return settings.CHAT_MODEL_REASONING
    if use_reasoning is False:
        return settings.CHAT_MODEL_NON_REASONING
    return settings.ACTIVE_CHAT_MODEL


async def generate_reply(
    character,
    persona,
    recent_history: list,
    user_message: str,
    retrieved_memories: Optional[list] = None,
    graph_knowledge: Optional[str] = None,
    db = None,
    use_reasoning: Optional[bool] = None,
    user_nickname: str = "用户",
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    presence_penalty: Optional[float] = None,
    frequency_penalty: Optional[float] = None,
    repetition_penalty: Optional[float] = None,
    reasoning_effort: Optional[str] = None,
) -> dict:
    """
    基于 Character + SessionPersona + 对话历史 + 检索记忆，生成结构化 JSON 回复。
    """
    model = _resolve_model(use_reasoning)
    messages = await _build_chat_messages(
        character=character,
        persona=persona,
        recent_history=recent_history,
        user_message=user_message,
        retrieved_memories=retrieved_memories,
        graph_knowledge=graph_knowledge,
        db=db,
        user_nickname=user_nickname,
    )

    # 1. 解析角色专属配置
    ext = {}
    if character.extensions:
        try:
            ext = json.loads(character.extensions) if isinstance(character.extensions, str) else character.extensions
        except Exception:
            pass

    # 2. 优先级链合并：Request -> Character Extensions -> Global Settings
    final_temp = temperature if temperature is not None else ext.get("temperature", settings.LLM_TEMPERATURE)
    final_top_p = top_p if top_p is not None else ext.get("top_p", settings.LLM_TOP_P)
    final_presence = presence_penalty if presence_penalty is not None else ext.get("presence_penalty", settings.LLM_PRESENCE_PENALTY)
    final_frequency = frequency_penalty if frequency_penalty is not None else ext.get("frequency_penalty", settings.LLM_FREQUENCY_PENALTY)
    final_repetition = repetition_penalty if repetition_penalty is not None else ext.get("repetition_penalty", settings.LLM_REPETITION_PENALTY)
    final_reasoning_effort = reasoning_effort if reasoning_effort is not None else ext.get("reasoning_effort", settings.LLM_REASONING_EFFORT)

    is_reasoning_active = use_reasoning if use_reasoning is not None else settings.LLM_REASONING_MODE

    kwargs = {
        "model": model,
        "messages": messages,
        "max_tokens": settings.LLM_MAX_TOKENS,
    }

    # 根据模型和推理状态注入参数（推理模型可能不支持 temperature 或者是受限的，且支持 reasoning_effort）
    if "o1" in model.lower() or "o3" in model.lower() or "pro" in model.lower():
        if final_reasoning_effort:
            kwargs["reasoning_effort"] = final_reasoning_effort
    else:
        kwargs["temperature"] = final_temp
        kwargs["top_p"] = final_top_p
        kwargs["presence_penalty"] = final_presence
        kwargs["frequency_penalty"] = final_frequency

    extra_body = {}
    if final_repetition is not None and abs(final_repetition - 1.0) > 1e-5:
        extra_body["repetition_penalty"] = final_repetition

    # 如果是 DeepSeek 模型且开启了思考，根据文档需要传入 thinking: {"type": "enabled"}
    if "deepseek" in model.lower() and is_reasoning_active:
        extra_body["thinking"] = {"type": "enabled"}

    if extra_body:
        kwargs["extra_body"] = extra_body

    try:
        response = await llm_client_async.chat.completions.create(**kwargs)

        content = response.choices[0].message.content

        # 使用高容错方法提取并解析 XML
        result = _extract_xml_block(content)

        return {
            "reply": result["reply"],
            "emotion_tag": result["emotion_tag"],
            "affection_change": result["affection_change"],
            "model_used": model,
        }

    except Exception as e:
        print(f"==========================================")
        print(f"[ERROR] chat_engine.generate_reply 调用大模型 API 失败")
        print(f"[ERROR] 错误类型: {type(e).__name__}")
        print(f"[ERROR] 错误详情: {e}")
        print(f"==========================================")
        return {
            "reply": "（系统错误：无法连接到思考引擎）",
            "emotion_tag": "困惑",
            "affection_change": 0,
        }


async def generate_reply_stream(
    character,
    persona,
    recent_history: list,
    user_message: str,
    retrieved_memories: Optional[list] = None,
    graph_knowledge: Optional[str] = None,
    db = None,
    use_reasoning: Optional[bool] = None,
    user_nickname: str = "用户",
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    presence_penalty: Optional[float] = None,
    frequency_penalty: Optional[float] = None,
    repetition_penalty: Optional[float] = None,
    reasoning_effort: Optional[str] = None,
):
    """
    基于 Character + SessionPersona + 对话历史 + 检索记忆，流式调用大模型获取回复。
    """
    model = _resolve_model(use_reasoning)
    messages = await _build_chat_messages(
        character=character,
        persona=persona,
        recent_history=recent_history,
        user_message=user_message,
        retrieved_memories=retrieved_memories,
        graph_knowledge=graph_knowledge,
        db=db,
        user_nickname=user_nickname,
    )

    # 1. 解析角色专属配置
    ext = {}
    if character.extensions:
        try:
            ext = json.loads(character.extensions) if isinstance(character.extensions, str) else character.extensions
        except Exception:
            pass

    # 2. 优先级链合并：Request -> Character Extensions -> Global Settings
    final_temp = temperature if temperature is not None else ext.get("temperature", settings.LLM_TEMPERATURE)
    final_top_p = top_p if top_p is not None else ext.get("top_p", settings.LLM_TOP_P)
    final_presence = presence_penalty if presence_penalty is not None else ext.get("presence_penalty", settings.LLM_PRESENCE_PENALTY)
    final_frequency = frequency_penalty if frequency_penalty is not None else ext.get("frequency_penalty", settings.LLM_FREQUENCY_PENALTY)
    final_repetition = repetition_penalty if repetition_penalty is not None else ext.get("repetition_penalty", settings.LLM_REPETITION_PENALTY)
    final_reasoning_effort = reasoning_effort if reasoning_effort is not None else ext.get("reasoning_effort", settings.LLM_REASONING_EFFORT)

    is_reasoning_active = use_reasoning if use_reasoning is not None else settings.LLM_REASONING_MODE

    kwargs = {
        "model": model,
        "messages": messages,
        "max_tokens": settings.LLM_MAX_TOKENS,
        "stream": True,
    }

    # 根据模型和推理状态注入参数（推理模型可能不支持 temperature 或者是受限的，且支持 reasoning_effort）
    if "o1" in model.lower() or "o3" in model.lower() or "pro" in model.lower():
        if final_reasoning_effort:
            kwargs["reasoning_effort"] = final_reasoning_effort
    else:
        kwargs["temperature"] = final_temp
        kwargs["top_p"] = final_top_p
        kwargs["presence_penalty"] = final_presence
        kwargs["frequency_penalty"] = final_frequency

    extra_body = {}
    if final_repetition is not None and abs(final_repetition - 1.0) > 1e-5:
        extra_body["repetition_penalty"] = final_repetition

    # 如果是 DeepSeek 模型且开启了思考，根据文档需要传入 thinking: {"type": "enabled"}
    if "deepseek" in model.lower() and is_reasoning_active:
        extra_body["thinking"] = {"type": "enabled"}

    if extra_body:
        kwargs["extra_body"] = extra_body

    try:
        response = await llm_client_async.chat.completions.create(**kwargs)
        # 包装并记录流输出
        logged_stream = log_llm_stream_wrapper_async(response, model, messages)
        return logged_stream, model

    except Exception as e:
        print(f"==========================================")
        print(f"[ERROR] chat_engine.generate_reply_stream 调用大模型 API 失败")
        print(f"[ERROR] 错误类型: {type(e).__name__}")
        print(f"[ERROR] 错误详情: {e}")
        print(f"==========================================")
        raise e
