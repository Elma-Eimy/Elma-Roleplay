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
from openai import OpenAI
from chromadb.utils import embedding_functions
from core.config import settings
import core.models as models


# ══════════════════════════════════════════════
# 基础设施初始化（memory_manager.py 依赖这些导出）
# ══════════════════════════════════════════════

# ChromaDB 持久化客户端
CHROMA_DATA_PATH = settings.STORAGE_CHROMA_DB_PATH
chroma_client = chromadb.PersistentClient(path=CHROMA_DATA_PATH)

# 兼容 OpenAI 的稳健嵌入函数
class RobustOpenAIEmbeddingFunction(embedding_functions.OpenAIEmbeddingFunction):
    # 用于缓存向量维度的静态类成员
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
                
                # 提取嵌入
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
                    dim = 1024
                print(f"[INFO] Falling back to zero-vector mock embeddings of dimension {dim}.")
                print(f"==========================================")
                return [[0.0] * dim for _ in input]
        else:
            # 标准文本 API 端点
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

# LLM 对话客户端
llm_client = OpenAI(
    api_key=settings.CHAT_API_KEY,
    base_url=settings.CHAT_BASE_URL,
    timeout=15.0
)
# LLM_MODEL 保留为全局默认值（memory_manager 等内部调用的回退）
LLM_MODEL = settings.ACTIVE_CHAT_MODEL

def _resolve_model(use_reasoning: bool | None) -> str:
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


def build_system_prompt(
    character,
    persona,
    retrieved_memories: list[dict] | None = None,
    recent_history: list[dict] | None = None,
    user_message: str | None = None
) -> dict:
    """
    重构后：静态 System Prompt 组装。返回静态部分，并提取动态变量供 User Message 拼接。
    """
    sections = []

    # 1. 核心人设 (静态)
    if character.system_prompt_override:
        sections.append(character.system_prompt_override)
    else:
        if character.description:
            sections.append(f"【角色设定】\n{character.description}")
        if character.personality:
            sections.append(f"【性格特点】\n{character.personality}")

    # 2. 结构化输出指令 (静态)
    json_instructions = """【重要：输出格式要求】
你必须且只能以有效的 JSON 格式进行响应。响应必须严格以 '{' 开头，以 '}' 结尾，绝对不要包含任何 markdown 标记（如 ```json）。
你的 JSON 响应必须且仅包含以下键：
{
  "reply": "你的角色扮演回复文本（字符串）",
  "emotion_tag": "当前心情标签（中文字符串，如'开心'、'平静'、'困惑'、'害羞'等多个情绪词语，这里只是举例几个而已。）",
  "affection_change": 0
}
请确保 affection_change 是整数类型（取值范围为 -5 到 5），绝对不要包含多余的键或格式。"""
    sections.append(json_instructions)

    # 3. 后置扮演规则 (静态)
    post_instructions = character.post_history_instructions or None
    if post_instructions:
        sections.append(f"【扮演补充规则】\n{post_instructions}")

    # 4. 对话示例 (静态 - 仅非子会话附加以保 caching)
    if not (persona and persona.parent_persona_id):
        if character.mes_example and character.mes_example.strip():
            sections.append(f"【对话示例】\n{character.mes_example.strip()}")

    system_prompt = "\n\n".join(sections)

    # ── 动态变量处理 ──
    
    # 世界书 (Lorebook) 匹配
    lorebook_result = {"before_char": [], "after_char": []}
    if recent_history is not None or user_message is not None:
        try:
            lorebook_result = process_lorebook(
                character=character,
                recent_history=recent_history,
                user_message=user_message
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

def _extract_json_block(text: str) -> dict | None:
    """
    尝试以多种容错方式从文本中解析提取 JSON 字典。
    - 支持标准 JSON 解析。
    - 兼容包含 ```json ... ``` 或 ``` ... ``` 标记的代码块。
    - 兼容以非大括号字符开头或结尾的杂乱文本，自动截取首个大括号块。
    """
    if not text:
        return None
    text = text.strip()
    
    # 1. 尝试直接解析
    try:
        return json.loads(text)
    except Exception:
        pass
        
    # 2. 尝试从 ```json ... ``` 代码块中提取
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
            
    # 3. 尝试搜索第一个 {...} 大括号块
    match = re.search(r'(\{.*?\})', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    return None

# ══════════════════════════════════════════════
# LLM 回复生成
# ══════════════════════════════════════════════

def generate_reply(
    character,
    persona,
    recent_history: list[dict],
    user_message: str,
    retrieved_memories: list[dict] | None = None,
    db = None,
    use_reasoning: bool | None = None,
) -> dict:
    """
    基于 Character + SessionPersona + 对话历史 + 检索记忆，生成结构化 JSON 回复。
    """
    # Step 1: 组装 缓存友好型 静态 System Prompt 并抽取动态要素
    prompt_result = build_system_prompt(
        character=character,
        persona=persona,
        retrieved_memories=retrieved_memories,
        recent_history=recent_history,
        user_message=user_message,
    )

    # 动态示例继承：如果是子会话，拉取父会话最后 4 条消息作为真实的 Few-shot 伪历史
    if persona and persona.parent_persona_id and db is not None:
        parent_persona = db.get(models.SessionPersona, persona.parent_persona_id)
        if parent_persona:
            parent_msgs = db.query(models.ChatMessage).filter(
                models.ChatMessage.session_id == parent_persona.session_id,
                models.ChatMessage.role.in_([models.MessageRole.user, models.MessageRole.assistant])
            ).order_by(models.ChatMessage.id.desc()).limit(4).all()
            
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
            # 拼接到真实的 recent_history 最前方，由后续统一处理 assistant JSON 封装
            recent_history = parent_history_formatted + recent_history

    # Step 2: 构建 messages 列表 (首位为单条静态 system prompt)
    messages = [{"role": "system", "content": prompt_result["system_prompt"]}]

    # 添加对话历史，并确保 assistant 的历史消息均格式化为 JSON 字符串，保留真实的情绪/好感变动
    for msg in recent_history:
        if msg["role"] == "assistant":
            content_str = msg["content"]
            try:
                # 检查是否已经是 JSON 格式
                json.loads(content_str)
                messages.append({"role": "assistant", "content": content_str})
            except Exception:
                # 否则，利用携带的真实情绪字段重新包装为标准 JSON 格式
                emo = msg.get("emotion_tag") or "平静"
                change = msg.get("affection_change") or 0
                fallback_json = json.dumps({
                    "reply": content_str,
                    "emotion_tag": emo,
                    "affection_change": int(change)
                }, ensure_ascii=False)
                messages.append({"role": "assistant", "content": fallback_json})
        else:
            messages.append({"role": msg["role"], "content": msg["content"]})

    # Step 3: 动态上下文包装 (XML 闭包标签) 并统一挂载到最后一轮 User 消息中
    dynamic_context_blocks = []

    # 3.1 场景与认知状态
    scenario = prompt_result.get("scenario")
    if scenario:
        dynamic_context_blocks.append(f"<current_scenario>\n{scenario}\n</current_scenario>")
    
    cognition = prompt_result.get("cognition_state")
    if cognition:
        dynamic_context_blocks.append(f"<cognition_state>\n{cognition}\n</cognition_state>")
        
    # 3.2 心情与好感度
    status_parts = []
    aff_score = prompt_result.get("affection_score")
    if aff_score is not None:
        status_parts.append(f"对用户好感度: {aff_score}")
    mood = prompt_result.get("current_mood")
    if mood:
        status_parts.append(f"当前心情: {mood}")
    if status_parts:
        dynamic_context_blocks.append(f"<current_status>\n" + "\n".join(status_parts) + "\n</current_status>")

    # 3.3 世界书 (Lorebook) 知识
    lorebook_res = prompt_result.get("lorebook_result", {"before_char": [], "after_char": []})
    lore_contents = []
    for e in (lorebook_res.get("before_char", []) + lorebook_res.get("after_char", [])):
        content = e.get("content", "").strip()
        if content:
            lore_contents.append(content)
    if lore_contents:
        dynamic_context_blocks.append(f"<lorebook_knowledge>\n" + "\n\n".join(lore_contents) + "\n</lorebook_knowledge>")

    # 3.4 召回长期记忆 (RAG)
    retrieved_mem = prompt_result.get("retrieved_memories_text")
    if retrieved_mem:
        dynamic_context_blocks.append(f"<recalled_memories>\n{retrieved_mem}\n</recalled_memories>")

    # 3.5 拼装增强的 User 消息内容，确保上下文与提问有清晰边界
    enhanced_user_content = ""
    if dynamic_context_blocks:
        enhanced_user_content += "【系统提供的上下文背景信息（大模型请注意结合以下背景进行角色扮演回复）：】\n"
        enhanced_user_content += "\n\n".join(dynamic_context_blocks) + "\n\n"
    
    enhanced_user_content += f"【当前用户的最新消息：】\n{user_message}"

    messages.append({"role": "user", "content": enhanced_user_content})

    # 在调用 LLM 之前主动提交并结束当前事务，释放 SQLite 文件锁
    if db is not None:
        try:
            db.commit()
        except Exception as e:
            print(f"[WARN] chat_engine.generate_reply: 释放 SQLite 锁失败: {e}")

    # Step 4: 调用 LLM
    model = _resolve_model(use_reasoning)
    
    # 针对 DeepSeek-V4/V3 或任何 DeepSeek 模型，完全禁用 JSON Mode 约束以防 logits processor 冲突导致返回空白，而由高容错解析器 _extract_json_block 负责解析
    is_deepseek = "deepseek" in model.lower()
    resp_fmt = None if is_deepseek else {"type": "json_object"}
    max_t = settings.LLM_MAX_TOKENS
    
    start_time = time.time()
    try:
        response_raw = llm_client.chat.completions.with_raw_response.create(
            model=model,
            messages=messages,
            response_format=resp_fmt,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=max_t,
        )
        elapsed = time.time() - start_time
        
        # 记录及解析响应
        # _log_llm_non_stream(model, messages, response_raw, elapsed)
        response = response_raw.parse()

        content = response.choices[0].message.content
        
        # 使用高容错方法提取并解析 JSON
        result = _extract_json_block(content)
        if result:
            reply = result.get("reply", "")
            emotion_tag = result.get("emotion_tag", "平静")
            affection_change = int(result.get("affection_change", 0))
        else:
            try:
                print(f"[WARN] chat_engine.generate_reply: JSON 解析失败，开启备用解析模式。原始返回内容: {repr(content)}")
            except UnicodeEncodeError:
                # 兼容 Windows 控制台 GBK 编码防崩溃
                safe_content = content.encode('ascii', errors='replace').decode('ascii')
                print(f"[WARN] chat_engine.generate_reply: JSON 解析失败，开启备用解析模式。原始返回内容 (安全模式): {repr(safe_content)}")
            reply = content.strip()
            emotion_tag = "平静"
            affection_change = 0

        # 容错：确保返回值包含必要字段
        return {
            "reply": reply,
            "emotion_tag": emotion_tag,
            "affection_change": affection_change,
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


def generate_reply_stream(
    character,
    persona,
    recent_history: list[dict],
    user_message: str,
    retrieved_memories: list[dict] | None = None,
    db = None,
    use_reasoning: bool | None = None,
):
    """
    基于 Character + SessionPersona + 对话历史 + 检索记忆，流式调用大模型获取回复。
    """
    # Step 1: 组装 缓存友好型 静态 System Prompt 并抽取动态要素
    prompt_result = build_system_prompt(
        character=character,
        persona=persona,
        retrieved_memories=retrieved_memories,
        recent_history=recent_history,
        user_message=user_message,
    )

    # 动态示例继承：如果是子会话，拉取父会话最后 4 条消息作为真实的 Few-shot 伪历史
    if persona and persona.parent_persona_id and db is not None:
        parent_persona = db.get(models.SessionPersona, persona.parent_persona_id)
        if parent_persona:
            parent_msgs = db.query(models.ChatMessage).filter(
                models.ChatMessage.session_id == parent_persona.session_id,
                models.ChatMessage.role.in_([models.MessageRole.user, models.MessageRole.assistant])
            ).order_by(models.ChatMessage.id.desc()).limit(4).all()
            
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
            # 拼接到真实的 recent_history 最前方，由后续统一处理 assistant JSON 封装
            recent_history = parent_history_formatted + recent_history

    # Step 2: 构建 messages 列表 (首位为单条静态 system prompt)
    messages = [{"role": "system", "content": prompt_result["system_prompt"]}]

    # 添加对话历史，并确保 assistant 的历史消息均格式化为 JSON 字符串，保留真实的情绪/好感变动
    for msg in recent_history:
        if msg["role"] == "assistant":
            content_str = msg["content"]
            try:
                # 检查是否已经是 JSON 格式
                json.loads(content_str)
                messages.append({"role": "assistant", "content": content_str})
            except Exception:
                # 否则，利用携带的真实情绪字段重新包装为标准 JSON 格式
                emo = msg.get("emotion_tag") or "平静"
                change = msg.get("affection_change") or 0
                fallback_json = json.dumps({
                    "reply": content_str,
                    "emotion_tag": emo,
                    "affection_change": int(change)
                }, ensure_ascii=False)
                messages.append({"role": "assistant", "content": fallback_json})
        else:
            messages.append({"role": msg["role"], "content": msg["content"]})

    # Step 3: 动态上下文包装 (XML 闭包标签) 并统一挂载到最后一轮 User 消息中
    dynamic_context_blocks = []

    # 3.1 场景与认知状态
    scenario = prompt_result.get("scenario")
    if scenario:
        dynamic_context_blocks.append(f"<current_scenario>\n{scenario}\n</current_scenario>")
    
    cognition = prompt_result.get("cognition_state")
    if cognition:
        dynamic_context_blocks.append(f"<cognition_state>\n{cognition}\n</cognition_state>")
        
    # 3.2 心情与好感度
    status_parts = []
    aff_score = prompt_result.get("affection_score")
    if aff_score is not None:
        status_parts.append(f"对用户好感度: {aff_score}")
    mood = prompt_result.get("current_mood")
    if mood:
        status_parts.append(f"当前心情: {mood}")
    if status_parts:
        dynamic_context_blocks.append(f"<current_status>\n" + "\n".join(status_parts) + "\n</current_status>")

    # 3.3 世界书 (Lorebook) 知识
    lorebook_res = prompt_result.get("lorebook_result", {"before_char": [], "after_char": []})
    lore_contents = []
    for e in (lorebook_res.get("before_char", []) + lorebook_res.get("after_char", [])):
        content = e.get("content", "").strip()
        if content:
            lore_contents.append(content)
    if lore_contents:
        dynamic_context_blocks.append(f"<lorebook_knowledge>\n" + "\n\n".join(lore_contents) + "\n</lorebook_knowledge>")

    # 3.4 召回长期记忆 (RAG)
    retrieved_mem = prompt_result.get("retrieved_memories_text")
    if retrieved_mem:
        dynamic_context_blocks.append(f"<recalled_memories>\n{retrieved_mem}\n</recalled_memories>")

    # 3.5 拼装增强的 User 消息内容，确保上下文与提问有清晰边界
    enhanced_user_content = ""
    if dynamic_context_blocks:
        enhanced_user_content += "【系统提供的上下文背景信息（大模型请注意结合以下背景进行角色扮演回复）：】\n"
        enhanced_user_content += "\n\n".join(dynamic_context_blocks) + "\n\n"
    
    enhanced_user_content += f"【当前用户的最新消息：】\n{user_message}"

    messages.append({"role": "user", "content": enhanced_user_content})

    # 在调用 LLM 之前主动提交并结束当前事务，释放 SQLite 文件锁
    if db is not None:
        try:
            db.commit()
        except Exception as e:
            print(f"[WARN] chat_engine.generate_reply_stream: 释放 SQLite 锁失败: {e}")

    # Step 4: 调用 LLM
    model = _resolve_model(use_reasoning)
    
    # 针对 DeepSeek-V4/V3 或任何 DeepSeek 模型，完全禁用 JSON Mode 约束以防 logits processor 冲突导致返回空白，而由高容错解析器 _extract_json_block 负责解析
    is_deepseek = "deepseek" in model.lower()
    resp_fmt = None if is_deepseek else {"type": "json_object"}
    max_t = settings.LLM_MAX_TOKENS
    
    try:
        response = llm_client.chat.completions.create(
            model=model,
            messages=messages,
            response_format=resp_fmt,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=max_t,
            stream=True,
        )
        # 包装并记录流输出
        logged_stream = _log_llm_stream_wrapper(response, model, messages)
        return logged_stream, model

    except Exception as e:
        print(f"==========================================")
        print(f"[ERROR] chat_engine.generate_reply_stream 调用大模型 API 失败")
        print(f"[ERROR] 错误类型: {type(e).__name__}")
        print(f"[ERROR] 错误详情: {e}")
        print(f"==========================================")
        raise e

