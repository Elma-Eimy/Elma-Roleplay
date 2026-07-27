import os
import yaml
import copy
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
load_dotenv(os.path.join(parent_dir, ".env"))

# 声明式系统配置蓝图 (CONFIG_SCHEMA)
# 作用: 只要在这里新增配置项，系统在启动时就会自动为用户的 config.yaml 补齐默认值，并动态绑定为类属性，实现“零修改升级”
CONFIG_SCHEMA = {
    "llm": {
        # 默认对话模型（带推理思考能力），用于主聊天端点聊天回复
        "chat_model": {"type": str, "default": "gpt-3.5-turbo", "dynamic": False, "attr": "CHAT_MODEL_REASONING"},
        # 快速非推理对话模型，用于 TTS 预处理文本分析、记忆提取等辅助大模型调用
        "non_reasoning_chat_model": {"type": str, "default": "", "dynamic": False, "attr": "CHAT_MODEL_NON_REASONING"},
        # 专门用于记忆提取、归纳与归并的大模型模型标识
        "memory_model": {"type": str, "default": "", "dynamic": False, "attr": "LLM_MEMORY_MODEL"},
        # 向量嵌入大模型模型标识，用于生成记忆与世界书的向量特征值
        "embedding_model": {"type": str, "default": "text-embedding-ada-002", "dynamic": False, "attr": "LLM_EMBEDDING_MODEL"},
        # OpenAI 兼容聊天接口的基础 URL
        "chat_base_url": {"type": str, "default": "https://api.openai.com/v1", "dynamic": False, "attr": "CHAT_BASE_URL"},
        # OpenAI 兼容向量嵌入接口的基础 URL
        "embedding_base_url": {"type": str, "default": "https://api.openai.com/v1", "dynamic": False, "attr": "EMBEDDING_BASE_URL"},
        # 聊天模型调用的默认生成温度 (Temperature)
        "temperature": {"type": float, "default": 0.7, "dynamic": True, "attr": "LLM_TEMPERATURE"},
        # 提取/合并记忆模型调用时的生成温度
        "memory_temperature": {"type": float, "default": 0.3, "dynamic": False, "attr": "LLM_MEMORY_TEMPERATURE"},
        # 聊天模型单词响应生成的最大 Token 限制
        "max_tokens": {"type": int, "default": 4096, "dynamic": True, "attr": "LLM_MAX_TOKENS"},
        # 是否默认开启聊天模型的深度推理思考模式 (Reasoning Mode)
        "reasoning_mode": {"type": bool, "default": False, "dynamic": True, "attr": "LLM_REASONING_MODE"},
        # 大模型网络请求超时时长 (秒)
        "timeout": {"type": float, "default": 60.0, "dynamic": False, "attr": "LLM_TIMEOUT"},
        # 聊天生成采样时的 Top-P (核采样) 阀值
        "top_p": {"type": float, "default": 1.0, "dynamic": True, "attr": "LLM_TOP_P"},
        # 聊天生成时的存在惩罚系数 (Presence Penalty)，用于控制话题新鲜度
        "presence_penalty": {"type": float, "default": 0.0, "dynamic": True, "attr": "LLM_PRESENCE_PENALTY"},
        # 聊天生成时的频率惩罚系数 (Frequency Penalty)，用于防止词汇过度重复
        "frequency_penalty": {"type": float, "default": 0.0, "dynamic": True, "attr": "LLM_FREQUENCY_PENALTY"},
        # 聊天生成时的重复惩罚系数 (Repetition Penalty)，常用在国产模型如 DeepSeek
        "repetition_penalty": {"type": float, "default": 1.0, "dynamic": True, "attr": "LLM_REPETITION_PENALTY"},
        # 推理思考强度参数（如 OpenAI o3-mini 的 reasoning_effort，可设为 low, medium, high）
        "reasoning_effort": {"type": str, "default": None, "dynamic": True, "attr": "LLM_REASONING_EFFORT", "allow_none": True},
    },
    "app": {
        # 直接注入提示词上下文的最近对话消息数量限制（单边计数，如10表示最近5轮交互共10条）
        "context_history_limit": {"type": int, "default": 10, "dynamic": True, "attr": "APP_CONTEXT_HISTORY_LIMIT"},
        # 从向量记忆库中检索注入上下文的相关记忆条目数 (Top-K)
        "retrieval_top_k": {"type": int, "default": 3, "dynamic": True, "attr": "APP_RETRIEVAL_TOP_K"},
        # 用于在检索查询中解析指代的最近用户轮数。
        "retrieval_context_turns": {"type": int, "default": 3, "dynamic": True, "attr": "APP_RETRIEVAL_CONTEXT_TURNS"},
        # 当前问题加上仅检索上下文的硬字符预算限制。
        "retrieval_query_max_chars": {"type": int, "default": 2400, "dynamic": True, "attr": "APP_RETRIEVAL_QUERY_MAX_CHARS"},
        # 触发记忆提取的未整理消息轮数阈值
        "memory_extract_history_limit": {"type": int, "default": 20, "dynamic": False, "attr": "APP_MEMORY_EXTRACT_LIMIT"},
        # 在短期历史窗口淘汰前预留多少条消息作为异步提纯缓冲区
        "memory_handoff_margin": {"type": int, "default": 2, "dynamic": True, "attr": "APP_MEMORY_HANDOFF_MARGIN"},
        # 被检索记忆的最低重要度得分阈值 (低于该值的记忆将被过滤丢弃)
        "retrieval_min_importance": {"type": float, "default": 0.3, "dynamic": True, "attr": "APP_RETRIEVAL_MIN_IMPORTANCE"},
        # 触发高层认知状态 (Cognition State) 汇总更新的消息轮数间隔
        "cognition_update_interval": {"type": int, "default": 10, "dynamic": False, "attr": "APP_COGNITION_UPDATE_INTERVAL"},
        # 参与更新认知状态所需记忆块的最低重要性评分阈值
        "cognition_importance_threshold": {"type": float, "default": 0.8, "dynamic": False, "attr": "APP_COGNITION_IMPORTANCE_THRESHOLD"},
        # 世界书扫描文本以触发关键词的最大历史消息轮数深度
        "lorebook_scan_depth": {"type": int, "default": 5, "dynamic": True, "attr": "APP_LOREBOOK_SCAN_DEPTH"},
        # 注入上下文的世界书卡片总字符数/Token最大预算限制 (超支将被截断)
        "lorebook_token_budget": {"type": int, "default": 3000, "dynamic": True, "attr": "APP_LOREBOOK_TOKEN_BUDGET"},
        # 世界书递归扫描（被激发的设定激发其它设定）的最大循环轮数深度限制
        "lorebook_max_recursive_passes": {"type": int, "default": 3, "dynamic": True, "attr": "APP_LOREBOOK_MAX_RECURSIVE_PASSES"},
        # SQLite 关系型数据库文件的存储路径
        "sqlite_db_path": {"type": str, "default": "data.db", "dynamic": False, "attr": "STORAGE_SQLITE_DB_PATH", "is_path": True},
        # Chroma 向量数据库数据目录的存储路径
        "chroma_db_path": {"type": str, "default": "./chroma_data", "dynamic": False, "attr": "STORAGE_CHROMA_DB_PATH", "is_path": True},
        # 上传的角色和用户头像本地存储目录路径
        "upload_avatar_dir": {"type": str, "default": "./assets/avatars", "dynamic": False, "attr": "STORAGE_UPLOAD_AVATAR_DIR", "is_path": True},
        # 跨域 CORS 允许的 Origin 源列表
        "cors_origins": {"type": list, "default": ["*"], "dynamic": False, "attr": "SECURITY_CORS_ORIGINS", "is_list": True},
        # 角色卡（如SillyTavern卡片）允许上传的最大文件大小 (MB)
        "max_card_size_mb": {"type": int, "default": 10, "dynamic": False, "attr": "SECURITY_MAX_CARD_SIZE_MB"},
        # 会话历史消息拉取接口返回的默认消息数
        "history_fetch_default": {"type": int, "default": 50, "dynamic": False, "attr": "APP_HISTORY_FETCH_DEFAULT"},
        # 会话历史消息拉取接口允许单次返回的最大消息上限
        "history_fetch_max": {"type": int, "default": 500, "dynamic": False, "attr": "APP_HISTORY_FETCH_MAX"},
        # 向量相似性检索的最大相似度距离（用于 Chroma 余弦距离，超出的记忆被认定为不相关）
        "retrieval_max_distance": {"type": float, "default": 1.2, "dynamic": True, "attr": "APP_RETRIEVAL_MAX_DISTANCE"},
        # 认知状态字段所允许保存的最大汇总字符长度
        "cognition_max_words": {"type": int, "default": 200, "dynamic": True, "attr": "APP_COGNITION_MAX_WORDS"},
        # 记忆写入时挑选 same/replace/coexist 判断候选的向量距离阈值
        "dedup_write_threshold": {"type": float, "default": 0.15, "dynamic": True, "attr": "APP_DEDUP_WRITE_THRESHOLD"},
        # 知识图谱 (Graph RAG) 实体/关系网络检索时的最低重要度评级要求
        "graph_min_importance": {"type": float, "default": 0.5, "dynamic": True, "attr": "APP_GRAPH_MIN_IMPORTANCE"},
        # 注入上下文的知识图谱三元组最大关联条目上限限制
        "graph_max_relations": {"type": int, "default": 12, "dynamic": True, "attr": "APP_GRAPH_MAX_RELATIONS"},
        # 记忆排序评估公式中的语义相似度得分所占权重
        "retrieval_weight_similarity": {"type": float, "default": 0.6, "dynamic": True, "attr": "APP_RETRIEVAL_WEIGHT_SIMILARITY"},
        # 记忆排序评估公式中的记忆重要度得分所占权重
        "retrieval_weight_importance": {"type": float, "default": 0.2, "dynamic": True, "attr": "APP_RETRIEVAL_WEIGHT_IMPORTANCE"},
        # 记忆排序评估公式中的时间衰减得分所占权重
        "retrieval_weight_time": {"type": float, "default": 0.2, "dynamic": True, "attr": "APP_RETRIEVAL_WEIGHT_TIME"},
        # 记忆排序公式中用于计算时间指数衰减的半衰期消息轮数参数 (Half life)
        "retrieval_half_life_turns": {"type": int, "default": 50, "dynamic": True, "attr": "APP_RETRIEVAL_HALF_LIFE_TURNS"},
        # 向量记忆初步粗筛候选池规模乘数（最终 Top-K 乘以该数决定初筛候选数量）
        "retrieval_candidate_multiplier": {"type": int, "default": 3, "dynamic": True, "attr": "APP_RETRIEVAL_CANDIDATE_MULTIPLIER"},
        # 继承祖先会话的记忆在排序评分中需乘以的衰减折减权重系数
        "retrieval_ancestor_weight": {"type": float, "default": 0.8, "dynamic": True, "attr": "APP_RETRIEVAL_ANCESTOR_WEIGHT"},
        # 对话交互轮数映射的时间划分阶梯，用于格式化记忆在提示词中呈现的相对时间
        "rp_time_tiers": {"type": list, "default": [
            {"max_turns": 30, "label": "刚刚"},
            {"max_turns": 100, "label": "近期"},
            {"max_turns": 300, "label": "一段时间前"},
            {"max_turns": 9999999, "label": "很久以前"}
        ], "dynamic": False, "attr": "APP_RP_TIME_TIERS", "is_list": True}
    },
    "tts": {
        # TTS 语音合成总开关，控制是否启用语音合成及对应功能
        "enabled": {"type": bool, "default": True, "dynamic": False, "attr": "TTS_ENABLED"},
        # 小米 MiMo 语音合成 API 基础 URL 路由
        "base_url": {"type": str, "default": "https://api.xiaomimimo.com/v1", "dynamic": False, "attr": "TTS_MIMO_BASE_URL"},
        # MiMo 语音合成服务的生成引擎模型名称标识
        "model": {"type": str, "default": "mimo-v2.5-tts", "dynamic": False, "attr": "TTS_MIMO_MODEL"},
        # 全局默认发音人，在角色卡或会话中没有明确指定发音人时使用
        "default_voice": {"type": str, "default": "冰糖", "dynamic": False, "attr": "TTS_DEFAULT_VOICE"},
        # 生成音频文件在服务器本地的缓存存放目录路径
        "cache_dir": {"type": str, "default": "data/audio_cache", "dynamic": False, "attr": "TTS_CACHE_DIR", "is_path": True},
        # 音频缓存文件的最大保存数量限制 (超出后将触发垃圾回收删除旧缓存文件)
        "max_cache_files": {"type": int, "default": 500, "dynamic": False, "attr": "TTS_MAX_CACHE_FILES"}
    }
}

class Settings:
    def __init__(self):
        # 敏感信息从环境变量获取，彻底分离 Chat 和 Embedding
        self.CHAT_API_KEY = os.getenv("CHAT_API_KEY", "your-chat-api-key")
        self.EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "your-embedding-api-key")
        self.ACCESS_API_KEY = os.getenv("ACCESS_API_KEY", "")
        self.MIMO_API_KEY = os.getenv("MIMO_API_KEY", "")
        
        # 非敏感配置从 config.yaml 获取
        self.config = self._load_yaml_config()
        
        # 进行配置升级合并与类属性绑定
        self.migrate_and_bind_config()

    def migrate_and_bind_config(self):
        """对比 Schema，自动合并缺失配置项，并动态绑定为类属性"""
        has_updates = False
        
        for namespace, items in CONFIG_SCHEMA.items():
            ns_dict = self.config.setdefault(namespace, {})
            
            for key, meta in items.items():
                # 1. 自动补全缺失字段
                if key not in ns_dict:
                    ns_dict[key] = copy.deepcopy(meta["default"])
                    has_updates = True
                
                # 2. 获取值并强制转换类型
                val = ns_dict[key]
                converted_val = self._convert_value(val, meta)
                
                # 3. 动态属性名绑定
                attr_name = meta.get("attr") or f"{namespace.upper()}_{key.upper()}"
                setattr(self, attr_name, converted_val)

        # 4. 后置动态推导处理（fallback 机制）
        self._post_process_config()

        # 5. 如果发生变更，自动回写升级配置文件
        if has_updates:
            self._save_yaml_config()

    def _convert_value(self, val, meta):
        """根据 Schema 元数据转换值类型"""
        target_type = meta["type"]
        allow_none = meta.get("allow_none", False)
        
        # 归一化处理各种空值形式 (如 None, 空字符串 "", "null", "none" 字符串)
        is_empty_val = (
            val is None or 
            (isinstance(val, str) and val.strip().lower() in ("", "null", "none"))
        )
        
        if is_empty_val:
            if allow_none:
                return None
            return copy.deepcopy(meta["default"])
            
        # 处理特殊标志：Path 绝对路径解析
        if meta.get("is_path", False):
            val_str = str(val)
            if not os.path.isabs(val_str):
                return os.path.abspath(os.path.join(parent_dir, val_str))
            return val_str
            
        # 处理特殊标志：List 解析
        if meta.get("is_list", False):
            if not isinstance(val, list):
                return [str(val)]
            return val
            
        # 标准转换
        try:
            if target_type == bool:
                if isinstance(val, str):
                    return val.lower() in ("true", "1", "yes")
                return bool(val)
            return target_type(val)
        except (ValueError, TypeError):
            return copy.deepcopy(meta["default"])

    def _post_process_config(self):
        """处理后置参数的默认回退和激活状态"""
        # 模型别名与回退默认值设定
        if not getattr(self, "CHAT_MODEL_NON_REASONING", ""):
            self.CHAT_MODEL_NON_REASONING = getattr(self, "CHAT_MODEL_REASONING", "")
        if not getattr(self, "LLM_MEMORY_MODEL", ""):
            self.LLM_MEMORY_MODEL = getattr(self, "CHAT_MODEL_REASONING", "")

        # 激活的默认对话模型选取
        if getattr(self, "LLM_REASONING_MODE", False):
            self.ACTIVE_CHAT_MODEL = getattr(self, "CHAT_MODEL_REASONING", "")
        else:
            self.ACTIVE_CHAT_MODEL = getattr(self, "CHAT_MODEL_NON_REASONING", "")

    def update_and_persist(self, updates: dict):
        """动态更新运行时配置，并回写持久化到 config.yaml (零 Hardcode)"""
        updated = False
        
        for field, value in updates.items():
            if value is None:
                continue
            
            # 在 Schema 中动态检索字段定义
            found = False
            for namespace, items in CONFIG_SCHEMA.items():
                if field in items:
                    meta = items[field]
                    if meta.get("dynamic", False):
                        converted_val = self._convert_value(value, meta)
                        
                        # 1. 动态更新类内存属性
                        attr_name = meta.get("attr") or f"{namespace.upper()}_{field.upper()}"
                        setattr(self, attr_name, converted_val)
                        
                        # 2. 动态更新树状配置字典结构
                        self.config.setdefault(namespace, {})[field] = converted_val
                        updated = True
                        found = True
                    break
            
            if not found:
                print(f"[WARN] Settings: 字段 {field} 未定义或不允许运行时修改，跳过更新。")

        if updated:
            # 回写前更新联动后置属性 (如从 reasoning_mode 更新 ACTIVE_CHAT_MODEL)
            self._post_process_config()
            self._save_yaml_config()

    def _load_yaml_config(self, filepath="config.yaml"):
        full_path = os.path.join(parent_dir, filepath)
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"Failed to load config.yaml at {full_path}: {e}")
            return {}

    def _save_yaml_config(self, filepath="config.yaml"):
        full_path = os.path.join(parent_dir, filepath)
        try:
            with open(full_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(self.config, f, allow_unicode=True, sort_keys=False)
            print(f"[INFO] Settings: 成功持久化保存了更新后的设置到 {full_path}")
        except Exception as e:
            print(f"[ERROR] Settings: 持久化保存设置失败: {e}")

settings = Settings()
