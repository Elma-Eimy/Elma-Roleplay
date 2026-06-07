"""
对话引擎 — 负责 System Prompt 组装与 LLM 回复生成

职责：
  1. 初始化 ChromaDB 客户端 / Embedding 函数 / LLM 客户端（基础设施，供 memory_manager 共享）
  2. 从 Character（静态蓝图）+ SessionPersona（动态状态）组装分层 System Prompt
  3. 调用 LLM 生成结构化 JSON 回复

导出给 memory_manager.py 使用的基础设施：
  chroma_client, openai_ef, llm_client, LLM_MODEL
"""

import json
import re
import chromadb
import time
from typing import Optional
from openai import OpenAI, AsyncOpenAI
from chromadb.utils import embedding_functions
from core.config import settings
import core.models as models


# ══════════════════════════════════════════════
# 基础设施初始化（memory_manager.py 依赖这些导出）
# ══════════════════════════════════════════════

# ChromaDB 持久化客户端
CHROMA_DATA_PATH = settings.STORAGE_CHROMA_DB_PATH
chroma_client = chromadb.PersistentClient(path=CHROMA_DATA_PATH)

# OpenAI Compatible Robust Embedding Function
class RobustOpenAIEmbeddingFunction(embedding_functions.OpenAIEmbeddingFunction):
    # Static class member to cache vector dimension
    _cached_dim = None

    def __call__(self, input):
        import urllib.request
        import json

        model_name = getattr(self, "model_name", "") or settings.LLM_EMBEDDING_MODEL
        is_vision = "vision" in model_name.lower()

        if is_vision:
            try:
                # Multimodal API endpoint: /api/v3/embeddings/multimodal
                base_url = (self.api_base or settings.EMBEDDING_BASE_URL).rstrip("/")
                url = f"{base_url}/embeddings/multimodal"
                
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key or settings.EMBEDDING_API_KEY}"
                }
                
                # Format input for Volcengine multimodal schema
                multimodal_input = [{"type": "text", "text": doc} for doc in input]
                
                payload = {
                    "model": model_name,
                    "encoding_format": "float",
                    "input": multimodal_input
                }
                
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers=headers,
                    method="POST"
                )
                
                with urllib.request.urlopen(req, timeout=15.0) as response:
                    res_data = json.loads(response.read().decode("utf-8"))
                    
                if not isinstance(res_data, dict):
                    raise ValueError(f"API returned non-dictionary response: {res_data}")
                    
                if "error" in res_data:
                    raise ValueError(f"API returned error: {res_data['error']}")
                
                data_field = res_data.get("data", [])
                
                # Extract embeddings
                embeddings = []
                if isinstance(data_field, dict):
                    # Single dictionary format support: {"embedding": [...]}
                    embedding = data_field.get("embedding")
                    if isinstance(embedding, list):
                        embeddings.append(embedding)
                    else:
                        raise ValueError(f"Expected list for 'embedding' inside data dict: {data_field}")
                elif isinstance(data_field, list):
                    # Standard list format support: [{"embedding": [...]}, ...]
                    for item in data_field:
                        if isinstance(item, dict) and "embedding" in item:
                            embeddings.append(item["embedding"])
                        elif isinstance(item, list):
                            embeddings.append(item)
                        else:
                            raise ValueError(f"Unexpected item format in data list: {item}")
                else:
                    raise ValueError(f"API returned unexpected data field type: {type(data_field)}")
                        
                if embeddings and len(embeddings) > 0:
                    self.__class__._cached_dim = len(embeddings[0])
                return embeddings
            except Exception as e:
                print(f"==========================================")
                print(f"[WARNING] Multimodal Embedding API call failed: {e}")
                
                dim = self.__class__._cached_dim
                if dim is None:
                    dim = 2048  # Match the real model's default dimension of 2048
                print(f"[INFO] Falling back to zero-vector mock embeddings of dimension {dim}.")
                print(f"==========================================")
                return [[0.0] * dim for _ in input]
        else:
            # Standard Text API endpoint
            try:
                embeddings = super().__call__(input)
                if embeddings and len(embeddings) > 0:
                    self.__class__._cached_dim = len(embeddings[0])
                return embeddings
            except Exception as e:
                print(f"==========================================")
                print(f"[WARNING] Embedding API call failed: {e}")
                
                dim = self.__class__._cached_dim
                if dim is None:
                    model_lower = model_name.lower()
                    if "3-large" in model_lower:
                        dim = 3072
                    elif "ada-002" in model_lower or "3-small" in model_lower:
                        dim = 1536
                    elif "bge-large" in model_lower or "doubao" in model_lower:
                        dim = 1024
                    else:
                        dim = 1536
                
                print(f"[INFO] Falling back to zero-vector mock embeddings of dimension {dim}.")
                print(f"==========================================")
                return [[0.0] * dim for _ in input]

openai_ef = RobustOpenAIEmbeddingFunction(
    api_key=settings.EMBEDDING_API_KEY,
    api_base=settings.EMBEDDING_BASE_URL,
    model_name=settings.LLM_EMBEDDING_MODEL
)

# LLM 对话客户端 (同步)
llm_client = OpenAI(
    api_key=settings.CHAT_API_KEY,
    base_url=settings.CHAT_BASE_URL,
    timeout=settings.LLM_TIMEOUT
)

# LLM 对话客户端 (异步)
llm_client_async = AsyncOpenAI(
    api_key=settings.CHAT_API_KEY,
    base_url=settings.CHAT_BASE_URL,
    timeout=settings.LLM_TIMEOUT
)

# LLM_MODEL 保留为全局默认值（memory_manager 等内部调用的回退）
LLM_MODEL = settings.ACTIVE_CHAT_MODEL

def _resolve_model(use_reasoning: Optional[bool]) -> str:
    """
    根据请求参数决定本次调用使用哪个模型。

    use_reasoning=True  → CHAT_MODEL_REASONING（思考模型）
    use_reasoning=False → CHAT_MODEL_NON_REASONING（非思考模型）
    use_reasoning=None  → 沿用 config.yaml reasoning_mode 的默认选择
    """
    if use_reasoning is True:
        return settings.CHAT_MODEL_REASONING
    if use_reasoning is False:
        return settings.CHAT_MODEL_NON_REASONING
    return settings.ACTIVE_CHAT_MODEL  # None → 走默认配置


# ══════════════════════════════════════════════
# System Prompt 组装与世界书 (Lorebook) 处理
# ══════════════════════════════════════════════

from services.lorebook_engine import process_lorebook
from services.prompt_compiler import compile_system_prompt, replace_placeholders


def build_system_prompt(
    character,
    persona,
    retrieved_memories: Optional[list] = None,
    recent_history: Optional[list] = None,
    user_message: Optional[str] = None,
    user_nickname: str = "用户"
) -> dict:
    """
    重构后：静态 System Prompt 组装与编译。返回已编译静态部分，并提取动态变量供 User Message 拼接。
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


# ══════════════════════════════════════════════
# LLM 日志与诊断功能 (llm_debug.log)
# ══════════════════════════════════════════════

def _log_llm_non_stream(model_name: str, messages: list, response_raw, elapsed: float):
    """记录非流式大模型请求与原始 HTTP 响应头、状态码，辅助诊断空白字符及报错。"""
    log_file = "llm_debug.log"
    try:
        status_code = response_raw.status_code
        headers = dict(response_raw.headers)
        completion = response_raw.parse()
        msg = completion.choices[0].message
        content = getattr(msg, "content", None) or ""
        reasoning = getattr(msg, "reasoning_content", None) or ""
        
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("\n" + "="*80 + "\n")
            f.write(f"🌐 [NON-STREAM REQUEST] Model: {model_name} | Time: {time.strftime('%Y-%m-%d %H:%M:%S')} | Elapsed: {elapsed:.2f}s\n")
            f.write(f"📥 [HTTP STATUS] {status_code}\n")
            f.write(f"📥 [HEADERS] Trace-ID: {headers.get('x-ds-trace-id', 'N/A')} | Server: {headers.get('server', 'N/A')}\n")
            f.write("--- MESSAGES SENT TO LLM ---\n")
            f.write(json.dumps(messages, ensure_ascii=False, indent=2) + "\n")
            if reasoning:
                f.write("--- RAW REASONING CONTENT ---\n")
                f.write(reasoning + "\n")
            f.write("--- RAW CONTENT ---\n")
            f.write(content + "\n")
            f.write("="*80 + "\n")
    except Exception as e:
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"❌ [NON-STREAM LOG ERROR] Failed to parse and log response: {str(e)}\n")
                f.write("="*80 + "\n")
        except:
            pass

def _log_llm_stream_wrapper(stream, model_name: str, messages: list):
    """透明代理流的迭代过程，捕获并向 llm_debug.log 写入每一次 chunk 产生的正文与思考过程。"""
    log_file = "llm_debug.log"
    start_time = time.time()
    
    # 立即记录请求起始部分
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("\n" + "="*80 + "\n")
            f.write(f"🌐 [STREAM REQUEST] Model: {model_name} | Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("--- MESSAGES SENT TO LLM ---\n")
            f.write(json.dumps(messages, ensure_ascii=False, indent=2) + "\n")
            f.write("----------------------------\n")
    except:
        pass
        
    full_content = []
    full_reasoning = []
    
    try:
        for chunk in stream:
            if chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                content_delta = getattr(delta, "content", None) or ""
                reasoning_delta = getattr(delta, "reasoning_content", None) or ""
                
                if content_delta:
                    full_content.append(content_delta)
                if reasoning_delta:
                    full_reasoning.append(reasoning_delta)
            yield chunk
            
        elapsed = time.time() - start_time
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"📥 [STREAM RESPONSE COMPLETED] Elapsed: {elapsed:.2f}s\n")
            if full_reasoning:
                f.write("--- RAW REASONING CONTENT ---\n")
                f.write("".join(full_reasoning) + "\n")
            f.write("--- RAW CONTENT ---\n")
            f.write("".join(full_content) + "\n")
            f.write("="*80 + "\n")
    except Exception as e:
        elapsed = time.time() - start_time
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"❌ [STREAM ERROR] Elapsed: {elapsed:.2f}s | Error: {str(e)}\n")
                f.write("="*80 + "\n")
        except:
            pass
        raise e


async def _log_llm_stream_wrapper_async(stream, model_name: str, messages: list):
    """透明代理异步流的迭代过程，捕获并向 llm_debug.log 写入每一次 chunk 产生的正文与思考过程。"""
    log_file = "llm_debug.log"
    start_time = time.time()
    
    # 立即记录请求起始部分
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("\n" + "="*80 + "\n")
            f.write(f"🌐 [STREAM REQUEST] Model: {model_name} | Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("--- MESSAGES SENT TO LLM ---\n")
            f.write(json.dumps(messages, ensure_ascii=False, indent=2) + "\n")
            f.write("----------------------------\n")
    except:
        pass
        
    full_content = []
    full_reasoning = []
    
    try:
        async for chunk in stream:
            if chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                content_delta = getattr(delta, "content", None) or ""
                reasoning_delta = getattr(delta, "reasoning_content", None) or ""
                
                if content_delta:
                    full_content.append(content_delta)
                if reasoning_delta:
                    full_reasoning.append(reasoning_delta)
            yield chunk
            
        elapsed = time.time() - start_time
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"📥 [STREAM RESPONSE COMPLETED] Elapsed: {elapsed:.2f}s\n")
            if full_reasoning:
                f.write("--- RAW REASONING CONTENT ---\n")
                f.write("".join(full_reasoning) + "\n")
            f.write("--- RAW CONTENT ---\n")
            f.write("".join(full_content) + "\n")
            f.write("="*80 + "\n")
    except Exception as e:
        elapsed = time.time() - start_time
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"❌ [STREAM ERROR] Elapsed: {elapsed:.2f}s | Error: {str(e)}\n")
                f.write("="*80 + "\n")
        except:
            pass
        raise e

def _extract_xml_block(text: str) -> dict:
    """
    使用正则表达式，从文本中提取 <reply>...</reply> 以及 <status emotion="..." affection_change="..."/>
    使用不区分大小写且容忍空格的正则表达式，以防模型输出 <Reply>、</reply  > 等格式。
    """
    if not text:
        return {"reply": "", "emotion_tag": "平静", "affection_change": 0}
    
    text = text.strip()
    
    # 提取 <reply>...</reply>（不区分大小写，容忍空格）
    reply_match = re.search(r'<\s*reply\s*>(.*?)</\s*reply\s*>', text, re.DOTALL | re.IGNORECASE)
    if reply_match:
        reply = reply_match.group(1).strip()
    else:
        # 兼容性兜底：若无标签或格式破坏，过滤掉 status 标签并把整段作为 reply
        clean_text = re.sub(r'<\s*status\s+.*?>', '', text, flags=re.DOTALL | re.IGNORECASE)
        # 清理可能残留的闭合标签
        clean_text = re.sub(r'</\s*reply\s*>', '', clean_text, flags=re.IGNORECASE)
        reply = clean_text.strip()

    # 提取 <status emotion="..." affection_change="..." />
    # 使用 ["\'] 以完美兼容双引号与单引号包裹的 XML 属性，且不区分大小写
    status_match = re.search(r'<\s*status\s+emotion=["\']([^"\']*)["\']\s+affection_change=["\']([^"\']*)["\']\s*/?>', text, re.IGNORECASE)
    if not status_match:
        # 兼容属性顺序颠倒的情况
        status_match = re.search(r'<\s*status\s+affection_change=["\']([^"\']*)["\']\s+emotion=["\']([^"\']*)["\']\s*/?>', text, re.IGNORECASE)
        if status_match:
            try:
                affection_change = int(status_match.group(1) or 0)
            except ValueError:
                affection_change = 0
            emotion_tag = status_match.group(2) or "平静"
        else:
            emotion_tag = "平静"
            affection_change = 0
    else:
        emotion_tag = status_match.group(1) or "平静"
        try:
            affection_change = int(status_match.group(2) or 0)
        except ValueError:
            affection_change = 0

    return {
        "reply": reply,
        "emotion_tag": emotion_tag,
        "affection_change": affection_change
    }

# ══════════════════════════════════════════════
# LLM 回复生成
# ══════════════════════════════════════════════

async def _build_chat_messages(
    character,
    persona,
    recent_history: list,
    user_message: str,
    retrieved_memories: Optional[list] = None,
    db=None,
    user_nickname: str = "用户",
) -> list:
    """
    组装 LLM 所需的完整 messages 列表（system + history + 动态上下文）。

    被 generate_reply 和 generate_reply_stream 共同调用，消除重复代码。
    包含以下步骤：
      1. 构建静态 System Prompt 并提取动态要素
      2. 若是子会话，拉取父会话最后 4 条消息作为 Few-shot 伪历史
      3. 组装 messages 列表（system + history in XML format）
      4. 拼接动态上下文块（场景 / 认知 / 心情 / Lorebook / RAG）到最后的 user 消息
      5. 调用前主动提交释放 SQLite 文件锁
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

    # Step 2: 动态示例继承（子会话拉取父会话最后 4 条作为 Few-shot 伪历史）
    if persona and persona.parent_persona_id and db is not None:
        from fastapi.concurrency import run_in_threadpool

        def fetch_parent_history():
            parent_persona = db.get(models.SessionPersona, persona.parent_persona_id)
            if parent_persona:
                return db.query(models.ChatMessage).filter(
                    models.ChatMessage.session_id == parent_persona.session_id,
                    models.ChatMessage.role.in_([models.MessageRole.user, models.MessageRole.assistant])
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
            print(f"[WARN] chat_engine._build_chat_messages: 释放 SQLite 锁失败: {e}")

    return messages

async def generate_reply(
    character,
    persona,
    recent_history: list,
    user_message: str,
    retrieved_memories: Optional[list] = None,
    db = None,
    use_reasoning: Optional[bool] = None,
    user_nickname: str = "用户",
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    presence_penalty: Optional[float] = None,
    frequency_penalty: Optional[float] = None,
    repetition_penalty: Optional[float] = None,
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

    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": final_temp,
        "top_p": final_top_p,
        "presence_penalty": final_presence,
        "frequency_penalty": final_frequency,
        "max_tokens": settings.LLM_MAX_TOKENS,
    }
    if final_repetition is not None and abs(final_repetition - 1.0) > 1e-5:
        kwargs["extra_body"] = {"repetition_penalty": final_repetition}

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
    db = None,
    use_reasoning: Optional[bool] = None,
    user_nickname: str = "用户",
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    presence_penalty: Optional[float] = None,
    frequency_penalty: Optional[float] = None,
    repetition_penalty: Optional[float] = None,
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

    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": final_temp,
        "top_p": final_top_p,
        "presence_penalty": final_presence,
        "frequency_penalty": final_frequency,
        "max_tokens": settings.LLM_MAX_TOKENS,
        "stream": True,
    }
    if final_repetition is not None and abs(final_repetition - 1.0) > 1e-5:
        kwargs["extra_body"] = {"repetition_penalty": final_repetition}

    try:
        response = await llm_client_async.chat.completions.create(**kwargs)
        # 包装并记录流输出
        logged_stream = _log_llm_stream_wrapper_async(response, model, messages)
        return logged_stream, model

    except Exception as e:
        print(f"==========================================")
        print(f"[ERROR] chat_engine.generate_reply_stream 调用大模型 API 失败")
        print(f"[ERROR] 错误类型: {type(e).__name__}")
        print(f"[ERROR] 错误详情: {e}")
        print(f"==========================================")
        raise e

