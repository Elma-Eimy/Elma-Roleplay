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
import chromadb
import time
from openai import OpenAI
from chromadb.utils import embedding_functions
from core.config import settings


# ══════════════════════════════════════════════
# 基础设施初始化（memory_manager.py 依赖这些导出）
# ══════════════════════════════════════════════

# ChromaDB 持久化客户端
CHROMA_DATA_PATH = settings.STORAGE_CHROMA_DB_PATH
chroma_client = chromadb.PersistentClient(path=CHROMA_DATA_PATH)

# OpenAI 兼容的 Embedding 函数
openai_ef = embedding_functions.OpenAIEmbeddingFunction(
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

def process_lorebook(
    character,
    recent_history: list[dict] | None,
    user_message: str | None
) -> dict:
    """
    处理角色专属的世界书（Lorebook/CharacterBook）匹配与筛选。
    """
    if not recent_history and not user_message:
        return {"before_char": [], "after_char": []}

    # 1. 安全解析 extensions
    extensions_dict = {}
    if character.extensions:
        if isinstance(character.extensions, str):
            try:
                extensions_dict = json.loads(character.extensions)
            except Exception:
                pass
        elif isinstance(character.extensions, dict):
            extensions_dict = character.extensions
            
    character_book = extensions_dict.get("character_book", {}) if isinstance(extensions_dict, dict) else {}
    if not isinstance(character_book, dict):
        character_book = {}
        
    entries = character_book.get("entries", [])
    if not isinstance(entries, list) or not entries:
        return {"before_char": [], "after_char": []}
        
    # 2. 提取配置（支持 YAML 可配置回退）
    scan_depth = character_book.get("scan_depth")
    if scan_depth is None or not isinstance(scan_depth, int) or scan_depth < 0:
        scan_depth = settings.APP_LOREBOOK_SCAN_DEPTH
        
    token_budget = character_book.get("token_budget")
    if token_budget is None or not isinstance(token_budget, int) or token_budget <= 0:
        token_budget = settings.APP_LOREBOOK_TOKEN_BUDGET
        
    recursive_scanning = bool(character_book.get("recursive_scanning", False))
    
    # 3. 构造基础扫描文本
    history_to_scan = recent_history[-scan_depth:] if scan_depth > 0 and recent_history else []
    scan_parts = []
    for msg in history_to_scan:
        scan_parts.append(msg.get("content", ""))
    if user_message:
        scan_parts.append(user_message)
    scan_text = "\n".join(scan_parts)
    
    # 4. 条目触发匹配 (支持递归扫描)
    max_passes = settings.APP_LOREBOOK_MAX_RECURSIVE_PASSES if recursive_scanning else 1
    triggered_indexes = set()
    triggered_entries = []
    
    current_scan_text = scan_text
    
    for _ in range(max_passes):
        new_trigger_added = False
        for idx, entry in enumerate(entries):
            if idx in triggered_indexes:
                continue
                
            if not isinstance(entry, dict):
                continue
                
            if not entry.get("enabled", True):
                continue
                
            constant = bool(entry.get("constant", False))
            if constant:
                triggered_indexes.add(idx)
                triggered_entries.append(entry)
                new_trigger_added = True
                content = entry.get("content", "")
                if content:
                    current_scan_text += "\n" + content
                continue
                
            keys = entry.get("keys", [])
            secondary_keys = entry.get("secondary_keys", [])
            selective = bool(entry.get("selective", False))
            case_sensitive = bool(entry.get("case_sensitive", False))
            
            if not isinstance(keys, list):
                keys = [keys] if keys else []
            if not isinstance(secondary_keys, list):
                secondary_keys = [secondary_keys] if secondary_keys else []
                
            if not case_sensitive:
                text_to_search = current_scan_text.lower()
                keys_to_search = [str(k).lower() for k in keys if k]
                secondary_keys_to_search = [str(k).lower() for k in secondary_keys if k]
            else:
                text_to_search = current_scan_text
                keys_to_search = [str(k) for k in keys if k]
                secondary_keys_to_search = [str(k) for k in secondary_keys if k]
                
            primary_matched = any(k in text_to_search for k in keys_to_search) if keys_to_search else False
            if selective:
                secondary_matched = any(k in text_to_search for k in secondary_keys_to_search) if secondary_keys_to_search else False
                matched = primary_matched and secondary_matched
            else:
                matched = primary_matched
                
            if matched:
                triggered_indexes.add(idx)
                triggered_entries.append(entry)
                new_trigger_added = True
                content = entry.get("content", "")
                if content:
                    current_scan_text += "\n" + content
                    
        if not new_trigger_added:
            break
            
    # 5. 预算控制与排序
    triggered_entries.sort(key=lambda e: (
        int(e.get("insertion_order", 100)),
        int(e.get("priority", 100))
    ))
    
    budget_used = 0
    selected_entries = []
    for entry in triggered_entries:
        content = entry.get("content", "").strip()
        if not content:
            continue
        content_len = len(content)
        if budget_used + content_len <= token_budget:
            selected_entries.append(entry)
            budget_used += content_len
            
    # 6. 分类位置归宿
    before_char = []
    after_char = []
    for entry in selected_entries:
        pos = entry.get("position", "after_char")
        if pos == "before_char":
            before_char.append(entry)
        else:
            after_char.append(entry)
            
    return {
        "before_char": before_char,
        "after_char": after_char
    }


def build_system_prompt(
    character,
    persona,
    retrieved_memories: list[dict] | None = None,
    recent_history: list[dict] | None = None,
    user_message: str | None = None
) -> dict:
    """
    从 Character + SessionPersona 组装完整的分层 System Prompt。
    """
    sections = []

    # ── Lorebook before_char 注入 ──
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

    # before_char 设定文本注入
    before_char_text = "\n\n".join([e.get("content", "").strip() for e in lorebook_result["before_char"] if e.get("content")])
    if before_char_text:
        sections.append(before_char_text)

    # ── Layer 1: 核心人设 ──
    if character.system_prompt_override:
        sections.append(character.system_prompt_override)
    else:
        if character.description:
            sections.append(f"【角色设定】\n{character.description}")
        if character.personality:
            sections.append(f"【性格特点】\n{character.personality}")

    # ── Layer 2: 场景 ──
    scenario = None
    if persona and persona.current_scenario_override:
        scenario = persona.current_scenario_override
    elif character.scenario:
        scenario = character.scenario

    if scenario:
        sections.append(f"【当前场景】\n{scenario}")

    # ── Lorebook after_char 注入 ──
    after_char_text = "\n\n".join([e.get("content", "").strip() for e in lorebook_result["after_char"] if e.get("content")])
    if after_char_text:
        sections.append(after_char_text)

    # ── Layer 3: 动态认知 ──
    if persona and persona.cognition_state:
        sections.append(f"【角色认知】\n{persona.cognition_state}")

    # ── Layer 4: 当前状态 ──
    if persona:
        status_parts = []
        if persona.affection_score is not None:
            status_parts.append(f"对用户的好感度：{persona.affection_score}")
        if persona.current_mood:
            status_parts.append(f"当前心情：{persona.current_mood}")
        if status_parts:
            sections.append(f"【当前状态】\n" + "；".join(status_parts))

    # ── Layer 5: 检索到的记忆 ──
    if retrieved_memories:
        memory_lines = []
        for mem in retrieved_memories:
            content = mem.get("content", "") if isinstance(mem, dict) else str(mem)
            mem_type = mem.get("memory_type", "") if isinstance(mem, dict) else ""
            if content:
                prefix = f"[{mem_type}] " if mem_type else ""
                memory_lines.append(f"- {prefix}{content}")

        if memory_lines:
            sections.append(f"【相关记忆】\n" + "\n".join(memory_lines))

    # ── Layer 6: 对话示例 ──
    if character.mes_example:
        sections.append(f"【对话示例】\n{character.mes_example}")

    # ── Layer 7: 结构化输出指令 ──
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

    # 组合主 System Prompt
    system_prompt = "\n\n".join(sections)

    # ── Layer 8: post_history_instructions（单独返回）──
    post_instructions = character.post_history_instructions or None

    return {
        "system_prompt": system_prompt,
        "post_history_instructions": post_instructions,
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

    参数：
      character          — Character ORM 对象
      persona            — SessionPersona ORM 对象（可为 None）
      recent_history     — [{"role": "user"|"assistant", "content": "..."}]
      user_message       — 当前用户输入
      retrieved_memories — memory_manager.retrieve_memories() 的返回值
      db                 — 可选的 SQLAlchemy Session，用于在调用 LLM 前提交事务释放锁
      use_reasoning      — 覆盖 config.yaml 的模型选择：
                           True=思考模型 / False=非思考模型 / None=默认配置

    返回：
      {
        "reply": str,              # 角色回复文本
        "emotion_tag": str,        # 情绪标签（中文）
        "affection_change": int,   # 好感度变动（-5 ~ 5）
        "model_used": str,         # 实际使用的模型名（调试用）
      }
    """
    # Step 1: 组装 System Prompt
    prompt_result = build_system_prompt(
        character=character,
        persona=persona,
        retrieved_memories=retrieved_memories,
        recent_history=recent_history,
        user_message=user_message,
    )

    # Step 2: 构建 messages 列表
    messages = [{"role": "system", "content": prompt_result["system_prompt"]}]

    # 添加对话历史，并确保 assistant 的历史消息均格式化为 JSON 字符串，以保证大模型上下文格式的绝对一致性
    for msg in recent_history:
        if msg["role"] == "assistant":
            content_str = msg["content"]
            try:
                # 检查是否已经是 JSON 格式
                json.loads(content_str)
                messages.append({"role": "assistant", "content": content_str})
            except Exception:
                # 否则，将其包装为标准 JSON 格式，以契合 System Prompt 要求的 assistant 输出规范
                fallback_json = json.dumps({
                    "reply": content_str,
                    "emotion_tag": "平静",
                    "affection_change": 0
                }, ensure_ascii=False)
                messages.append({"role": "assistant", "content": fallback_json})
        else:
            messages.append({"role": msg["role"], "content": msg["content"]})

    # 插入 post_history_instructions（在用户消息之前）
    if prompt_result["post_history_instructions"]:
        messages.append({
            "role": "system",
            "content": prompt_result["post_history_instructions"]
        })

    # 添加当前用户消息
    messages.append({"role": "user", "content": user_message})

    # 在调用 LLM 之前主动提交并结束当前事务，释放 SQLite 文件锁
    if db is not None:
        try:
            db.commit()
        except Exception as e:
            print(f"[WARN] chat_engine.generate_reply: 释放 SQLite 锁失败: {e}")

    # Step 3: 调用 LLM
    model = _resolve_model(use_reasoning)
    
    # 针对 DeepSeek-V4（不管是 Pro 还是 Flash 模型）或者任何 DeepSeek 模型，完全禁用 JSON Mode 约束以防 logits processor 冲突导致返回空白，而由高容错解析器 _extract_json_block 负责解析
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

    参数：
      character          — Character ORM 对象
      persona            — SessionPersona ORM 对象（可为 None）
      recent_history     — [{"role": "user"|"assistant", "content": "..."}]
      user_message       — 当前用户输入
      retrieved_memories — memory_manager.retrieve_memories() 的返回值
      db                 — 可选的 SQLAlchemy Session，用于在调用 LLM 前提交事务释放锁
      use_reasoning      — 覆盖 config.yaml 的模型选择

    返回：
      (response_stream, model_used)
    """
    # Step 1: 组装 System Prompt
    prompt_result = build_system_prompt(
        character=character,
        persona=persona,
        retrieved_memories=retrieved_memories,
        recent_history=recent_history,
        user_message=user_message,
    )

    # Step 2: 构建 messages 列表
    messages = [{"role": "system", "content": prompt_result["system_prompt"]}]

    # 添加对话历史，并确保 assistant 的历史消息均格式化为 JSON 字符串，以保证大模型上下文格式的绝对一致性
    for msg in recent_history:
        if msg["role"] == "assistant":
            content_str = msg["content"]
            try:
                # 检查是否已经是 JSON 格式
                json.loads(content_str)
                messages.append({"role": "assistant", "content": content_str})
            except Exception:
                # 否则，将其包装为标准 JSON 格式，以契合 System Prompt 要求的 assistant 输出规范
                fallback_json = json.dumps({
                    "reply": content_str,
                    "emotion_tag": "平静",
                    "affection_change": 0
                }, ensure_ascii=False)
                messages.append({"role": "assistant", "content": fallback_json})
        else:
            messages.append({"role": msg["role"], "content": msg["content"]})

    # 插入 post_history_instructions（在用户消息之前）
    if prompt_result["post_history_instructions"]:
        messages.append({
            "role": "system",
            "content": prompt_result["post_history_instructions"]
        })

    # 添加当前用户消息
    messages.append({"role": "user", "content": user_message})

    # 在调用 LLM 之前主动提交并结束当前事务，释放 SQLite 文件锁
    if db is not None:
        try:
            db.commit()
        except Exception as e:
            print(f"[WARN] chat_engine.generate_reply_stream: 释放 SQLite 锁失败: {e}")

    # Step 3: 调用 LLM
    model = _resolve_model(use_reasoning)
    
    # 针对 DeepSeek-V4（不管是 Pro 还是 Flash 模型）或者任何 DeepSeek 模型，完全禁用 JSON Mode 约束以防 logits processor 冲突导致返回空白，而由高容错解析器 _extract_json_block 负责解析
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

