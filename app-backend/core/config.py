import os
import yaml
import copy
import math
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

from core.model_settings import validate_model_settings
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
load_dotenv(os.path.join(parent_dir, ".env"))

# 声明式系统配置蓝图 (CONFIG_SCHEMA)
# 作用: 只要在这里新增配置项，系统在启动时就会自动为用户的 config.yaml 补齐默认值，并动态绑定为类属性，实现“零修改升级”
CONFIG_SCHEMA = {
    "llm": {
        "group_json_mode": {"type": bool, "default": False, "dynamic": False, "attr": "LLM_GROUP_JSON_MODE"},
        # 新版对话模型独立于思考开关；旧配置升级时保留原先实际选中的模型。
        "default_chat_model": {"type": str, "default": "", "dynamic": True, "attr": "LLM_DEFAULT_CHAT_MODEL"},
        "model_profiles": {"type": list, "default": [], "dynamic": True, "attr": "LLM_MODEL_PROFILES"},
        "chat_thinking_mode": {"type": str, "default": "disabled", "dynamic": True, "attr": "LLM_CHAT_THINKING_MODE"},
        "translation_thinking_mode": {"type": str, "default": "disabled", "dynamic": True, "attr": "LLM_TRANSLATION_THINKING_MODE"},
        "translation_reasoning_effort": {"type": str, "default": "high", "dynamic": True, "attr": "LLM_TRANSLATION_REASONING_EFFORT", "allow_none": True},
        "translation_model": {"type": str, "default": "", "dynamic": True, "attr": "LLM_TRANSLATION_MODEL"},
        "memory_thinking_mode": {"type": str, "default": "disabled", "dynamic": True, "attr": "LLM_MEMORY_THINKING_MODE"},
        "memory_reasoning_effort": {"type": str, "default": "high", "dynamic": True, "attr": "LLM_MEMORY_REASONING_EFFORT", "allow_none": True},
        "tts_preprocess_model": {"type": str, "default": "", "dynamic": True, "attr": "LLM_TTS_PREPROCESS_MODEL"},
        "tts_thinking_mode": {"type": str, "default": "disabled", "dynamic": True, "attr": "LLM_TTS_THINKING_MODE"},
        "tts_reasoning_effort": {"type": str, "default": "high", "dynamic": True, "attr": "LLM_TTS_REASONING_EFFORT", "allow_none": True},
        # 旧客户端 use_reasoning=True 使用的模型槽
        "chat_model": {"type": str, "default": "gpt-3.5-turbo", "dynamic": False, "attr": "CHAT_MODEL_REASONING", "legacy_model": True},
        # 旧客户端 use_reasoning=False 使用的模型槽，同时作为旧配置 TTS 初始值
        "non_reasoning_chat_model": {"type": str, "default": "", "dynamic": False, "attr": "CHAT_MODEL_NON_REASONING", "legacy_model": True},
        # 专门用于记忆提取、归纳与归并的大模型模型标识
        "memory_model": {"type": str, "default": "", "dynamic": True, "attr": "LLM_MEMORY_MODEL"},
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
        "reasoning_mode": {"type": bool, "default": False, "dynamic": True, "attr": "LLM_REASONING_MODE", "legacy": True},
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
        "group_turn_planning": {"type": bool, "default": True, "dynamic": False, "attr": "APP_GROUP_TURN_PLANNING"},
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
        "max_charx_size_mb": {"type": int, "default": 20, "dynamic": False, "attr": "SECURITY_MAX_CHARX_SIZE_MB"},
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
    def __init__(self, config_path=None):
        self._config_path = Path(config_path) if config_path is not None else Path(parent_dir) / "config.yaml"
        self._update_lock = threading.RLock()
        self.CHAT_API_KEY = os.getenv("CHAT_API_KEY", "your-chat-api-key")
        self.EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "your-embedding-api-key")
        self.ACCESS_API_KEY = os.getenv("ACCESS_API_KEY", "")
        self.MIMO_API_KEY = os.getenv("MIMO_API_KEY", "")
        self.config = self._load_yaml_config()
        self.migrate_and_bind_config()

    @property
    def LLM_REASONING_MODE(self):
        return self.LLM_CHAT_THINKING_MODE == "enabled"

    @LLM_REASONING_MODE.setter
    def LLM_REASONING_MODE(self, value):
        self.LLM_CHAT_THINKING_MODE = "enabled" if value else "disabled"

    def _bind(self):
        for namespace, items in CONFIG_SCHEMA.items():
            section = self.config.setdefault(namespace, {})
            if not isinstance(section, dict):
                raise ValueError(f"配置段 {namespace} 必须是对象。")
            for key, meta in items.items():
                if meta.get("legacy"):
                    continue
                if meta.get("legacy_model"):
                    # 新配置不再生成双槽位；仅为旧请求提供原槽位或当前默认模型。
                    value = section.get(key) or section.get("chat_model") or self.LLM_DEFAULT_CHAT_MODEL
                    setattr(self, meta["attr"], value)
                    continue
                value = self._convert_value(section.setdefault(key, copy.deepcopy(meta["default"])), meta)
                setattr(self, meta["attr"], value)
        self._post_process_config()

    def migrate_and_bind_config(self):
        with self._update_lock:
            candidate = copy.copy(self)
            candidate.config = copy.deepcopy(self.config)
            llm = candidate.config.setdefault("llm", {})
            if not isinstance(llm, dict):
                raise ValueError("配置段 llm 必须是对象。")
            legacy_chat = "chat_thinking_mode" not in llm
            legacy_mode = candidate._convert_value(llm.get("reasoning_mode", False), {"type": bool, "default": False})
            legacy_pro = llm.get("chat_model") or "gpt-3.5-turbo"
            legacy_flash = llm.get("non_reasoning_chat_model") or legacy_pro
            has_legacy_slots = "chat_model" in llm or "non_reasoning_chat_model" in llm
            if has_legacy_slots:
                llm["chat_model"] = legacy_pro
                llm["non_reasoning_chat_model"] = legacy_flash
            if not llm.get("default_chat_model"):
                llm["default_chat_model"] = legacy_pro if legacy_mode else legacy_flash
            llm.setdefault("chat_thinking_mode", "enabled" if legacy_mode else "disabled")
            # 只在读取旧配置时冻结辅助任务原来的模型；运行时不再依赖双槽位。
            for key, initial in (("memory_model", legacy_pro if has_legacy_slots else llm["default_chat_model"]),
                                 ("tts_preprocess_model", legacy_flash if has_legacy_slots else llm["default_chat_model"]),
                                 ("translation_model", legacy_flash if has_legacy_slots else llm["default_chat_model"])):
                if not llm.get(key):
                    llm[key] = initial
            candidate._bind()
            candidate._normalize_model_modes(legacy_chat=legacy_chat)
            if candidate.config != self.config:
                candidate._save_yaml_config()
            self.__dict__ = candidate.__dict__.copy()

    def _normalize_model_modes(self, **kwargs):
        modes = validate_model_settings(self, **kwargs)
        self.config["llm"].update(modes)
        self._bind()

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
                    if val.lower() not in ("true", "1", "yes", "false", "0", "no"):
                        raise ValueError("布尔配置必须是 true 或 false。")
                    return val.lower() in ("true", "1", "yes")
                return bool(val)
            converted = target_type(val)
            if isinstance(converted, float) and not math.isfinite(converted):
                raise ValueError("配置数值必须是有限值。")
            return converted
        except (ValueError, TypeError) as exc:
            raise ValueError("配置值类型无效。") from exc

    def _post_process_config(self):
        self.ACTIVE_CHAT_MODEL = self.LLM_DEFAULT_CHAT_MODEL
        self.config["llm"]["reasoning_mode"] = self.LLM_REASONING_MODE

    def snapshot(self):
        with self._update_lock:
            values = {key: copy.deepcopy(value) for key, value in vars(self).items() if key.isupper()}
            values["LLM_REASONING_MODE"] = self.LLM_REASONING_MODE
            return SimpleNamespace(**values)

    def prepare_update(self, updates):
        candidate = copy.copy(self)
        candidate.config = copy.deepcopy(self.config)
        updates = dict(updates)
        if "reasoning_mode" in updates and updates["reasoning_mode"] is not None:
            alias = "enabled" if self._convert_value(updates["reasoning_mode"], {"type": bool, "default": False}) else "disabled"
            if updates.get("chat_thinking_mode", alias) != alias:
                raise ValueError("chat_thinking_mode 与兼容字段 reasoning_mode 冲突。")
            updates["chat_thinking_mode"] = alias
        changed = False
        for field, value in updates.items():
            if value is None and field not in ("reasoning_effort", "memory_reasoning_effort", "tts_reasoning_effort", "translation_reasoning_effort"):
                continue
            for namespace, fields in CONFIG_SCHEMA.items():
                meta = fields.get(field)
                if meta is not None:
                    if meta.get("dynamic") and not meta.get("legacy"):
                        converted = candidate._convert_value(value, meta)
                        candidate.config[namespace][field] = converted
                        changed = True
                    break
        candidate._bind()
        candidate._normalize_model_modes(updates=updates)
        return candidate, changed

    def update_and_persist(self, updates):
        """先验证并原子保存候选配置，成功后一次发布运行状态。"""
        with self._update_lock:
            candidate, changed = self.prepare_update(updates)
            if changed:
                candidate._save_yaml_config()
                self.__dict__ = candidate.__dict__.copy()

    def _load_yaml_config(self, filepath=None):
        path = Path(filepath) if filepath is not None else self._config_path
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = yaml.safe_load(handle)
        except FileNotFoundError:
            return {}
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("配置文件根节点必须是对象。")
        return value

    def _save_yaml_config(self, filepath=None):
        path = Path(filepath) if filepath is not None else self._config_path
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                yaml.safe_dump(self.config, handle, allow_unicode=True, sort_keys=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


settings = Settings()
