import os
import yaml
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
# 兼容从核心包启动时寻找 .env
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
load_dotenv(os.path.join(parent_dir, ".env"))

class Settings:
    def __init__(self):
        # 敏感信息从环境变量获取，彻底分离 Chat 和 Embedding
        self.CHAT_API_KEY = os.getenv("CHAT_API_KEY", "your-chat-api-key")
        self.EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "your-embedding-api-key")
        # 公网访问控制密钥；为空时跳过认证（本地开发模式）
        self.ACCESS_API_KEY = os.getenv("ACCESS_API_KEY", "")
        
        # 非敏感配置从 config.yaml 获取
        self.config = self._load_yaml_config()
        
        llm_config = self.config.get("llm", {})
        
        # 读取模型名
        chat_model = llm_config.get("chat_model", "gpt-3.5-turbo")
        non_reasoning_chat_model = llm_config.get("non_reasoning_chat_model", "")
        self.LLM_EMBEDDING_MODEL = llm_config.get("embedding_model", "text-embedding-ada-002")
        self.LLM_MEMORY_MODEL = llm_config.get("memory_model", chat_model)

        # 两个模型名单独保留，供运行时按请求动态选择
        self.CHAT_MODEL_REASONING = chat_model
        self.CHAT_MODEL_NON_REASONING = non_reasoning_chat_model if non_reasoning_chat_model else chat_model

        # 读取 Base URL
        self.CHAT_BASE_URL = llm_config.get("chat_base_url", "https://api.openai.com/v1")
        self.EMBEDDING_BASE_URL = llm_config.get("embedding_base_url", "https://api.openai.com/v1")

        self.LLM_TEMPERATURE = float(llm_config.get("temperature", 0.7))
        self.LLM_MEMORY_TEMPERATURE = float(llm_config.get("memory_temperature", 0.3))
        self.LLM_MAX_TOKENS = int(llm_config.get("max_tokens", 4096))
        self.LLM_REASONING_MODE = bool(llm_config.get("reasoning_mode", False))

        # config.yaml 中配置的默认激活模型（未传 use_reasoning 时的回退）
        if self.LLM_REASONING_MODE:
            self.ACTIVE_CHAT_MODEL = self.CHAT_MODEL_REASONING
        else:
            self.ACTIVE_CHAT_MODEL = self.CHAT_MODEL_NON_REASONING

        app_config = self.config.get("app", {})
        self.APP_CONTEXT_HISTORY_LIMIT = int(app_config.get("context_history_limit", 10))
        self.APP_RETRIEVAL_TOP_K = int(app_config.get("retrieval_top_k", 3))
        self.APP_MEMORY_EXTRACT_LIMIT = int(app_config.get("memory_extract_history_limit", 20))
        self.APP_RETRIEVAL_MIN_IMPORTANCE = float(app_config.get("retrieval_min_importance", 0.3))
        self.APP_COGNITION_UPDATE_INTERVAL = int(app_config.get("cognition_update_interval", 10))
        self.APP_COGNITION_IMPORTANCE_THRESHOLD = float(app_config.get("cognition_importance_threshold", 0.8))
        self.APP_LOREBOOK_SCAN_DEPTH = int(app_config.get("lorebook_scan_depth", 5))
        self.APP_LOREBOOK_TOKEN_BUDGET = int(app_config.get("lorebook_token_budget", 3000))
        self.APP_LOREBOOK_MAX_RECURSIVE_PASSES = int(app_config.get("lorebook_max_recursive_passes", 3))

        # 存储与路径配置
        self.STORAGE_SQLITE_DB_PATH = str(app_config.get("sqlite_db_path", "data.db"))
        self.STORAGE_CHROMA_DB_PATH = str(app_config.get("chroma_db_path", "./chroma_data"))
        self.STORAGE_UPLOAD_AVATAR_DIR = str(app_config.get("upload_avatar_dir", "./assets/avatars"))

        # 安全与限制配置
        self.SECURITY_CORS_ORIGINS = app_config.get("cors_origins", ["*"])
        if not isinstance(self.SECURITY_CORS_ORIGINS, list):
            self.SECURITY_CORS_ORIGINS = [str(self.SECURITY_CORS_ORIGINS)]
        self.SECURITY_MAX_CARD_SIZE_MB = int(app_config.get("max_card_size_mb", 10))

        # 检索与认知高级配置
        self.APP_HISTORY_FETCH_DEFAULT = int(app_config.get("history_fetch_default", 50))
        self.APP_HISTORY_FETCH_MAX = int(app_config.get("history_fetch_max", 500))
        self.APP_RETRIEVAL_MAX_DISTANCE = float(app_config.get("retrieval_max_distance", 1.2))
        self.APP_COGNITION_MAX_WORDS = int(app_config.get("cognition_max_words", 200))
        
        # 混合打分与时间衰减高级配置
        self.APP_RETRIEVAL_WEIGHT_SIMILARITY = float(app_config.get("retrieval_weight_similarity", 0.6))
        self.APP_RETRIEVAL_WEIGHT_IMPORTANCE = float(app_config.get("retrieval_weight_importance", 0.2))
        self.APP_RETRIEVAL_WEIGHT_TIME = float(app_config.get("retrieval_weight_time", 0.2))
        self.APP_RETRIEVAL_HALF_LIFE_TURNS = int(app_config.get("retrieval_half_life_turns", 50))
        self.APP_RETRIEVAL_CANDIDATE_MULTIPLIER = int(app_config.get("retrieval_candidate_multiplier", 3))
        self.APP_RETRIEVAL_ANCESTOR_WEIGHT = float(app_config.get("retrieval_ancestor_weight", 0.8))
        self.APP_RP_TIME_TIERS = app_config.get("rp_time_tiers", [
            {"max_turns": 30, "label": "刚刚"},
            {"max_turns": 100, "label": "近期"},
            {"max_turns": 300, "label": "一段时间前"},
            {"max_turns": 9999999, "label": "很久以前"}
        ])

    def update_and_persist(self, updates: dict):
        """
        动态更新内存中的运行时配置，并将其同步回写持久化到 config.yaml。
        """
        # 1. 定义合法的动态更新字段及其对应的类型转换器
        allowed_fields = {
            "temperature": float,
            "max_tokens": int,
            "reasoning_mode": bool,
            "context_history_limit": int,
            "retrieval_top_k": int,
            "retrieval_min_importance": float,
            "retrieval_max_distance": float,
            "lorebook_scan_depth": int,
            "lorebook_token_budget": int,
            "lorebook_max_recursive_passes": int,
            "cognition_max_words": int,
            "retrieval_weight_similarity": float,
            "retrieval_weight_importance": float,
            "retrieval_weight_time": float,
            "retrieval_half_life_turns": int,
            "retrieval_candidate_multiplier": int,
            "retrieval_ancestor_weight": float
        }

        # 2. 遍历更新字段，进行类型验证并更新内存属性与 config 字典
        llm_updated = False
        app_updated = False

        for field, value in updates.items():
            if value is None:
                continue
            if field not in allowed_fields:
                continue
            
            # 进行类型安全强制转换
            try:
                converter = allowed_fields[field]
                converted_val = converter(value)
            except (ValueError, TypeError):
                print(f"[WARN] Settings: 字段 {field} 的值 {value} 转换成 {converter.__name__} 失败。跳过。")
                continue

            # ── 更新内存属性 ──
            if field == "temperature":
                self.LLM_TEMPERATURE = converted_val
                self.config.setdefault("llm", {})["temperature"] = converted_val
                llm_updated = True
            elif field == "max_tokens":
                self.LLM_MAX_TOKENS = converted_val
                self.config.setdefault("llm", {})["max_tokens"] = converted_val
                llm_updated = True
            elif field == "reasoning_mode":
                self.LLM_REASONING_MODE = converted_val
                # 同步更新默认激活模型
                if self.LLM_REASONING_MODE:
                    self.ACTIVE_CHAT_MODEL = self.CHAT_MODEL_REASONING
                else:
                    self.ACTIVE_CHAT_MODEL = self.CHAT_MODEL_NON_REASONING
                self.config.setdefault("llm", {})["reasoning_mode"] = converted_val
                llm_updated = True
            elif field == "context_history_limit":
                self.APP_CONTEXT_HISTORY_LIMIT = converted_val
                self.config.setdefault("app", {})["context_history_limit"] = converted_val
                app_updated = True
            elif field == "retrieval_top_k":
                self.APP_RETRIEVAL_TOP_K = converted_val
                self.config.setdefault("app", {})["retrieval_top_k"] = converted_val
                app_updated = True
            elif field == "retrieval_min_importance":
                self.APP_RETRIEVAL_MIN_IMPORTANCE = converted_val
                self.config.setdefault("app", {})["retrieval_min_importance"] = converted_val
                app_updated = True
            elif field == "retrieval_max_distance":
                self.APP_RETRIEVAL_MAX_DISTANCE = converted_val
                self.config.setdefault("app", {})["retrieval_max_distance"] = converted_val
                app_updated = True
            elif field == "lorebook_scan_depth":
                self.APP_LOREBOOK_SCAN_DEPTH = converted_val
                self.config.setdefault("app", {})["lorebook_scan_depth"] = converted_val
                app_updated = True
            elif field == "lorebook_token_budget":
                self.APP_LOREBOOK_TOKEN_BUDGET = converted_val
                self.config.setdefault("app", {})["lorebook_token_budget"] = converted_val
                app_updated = True
            elif field == "lorebook_max_recursive_passes":
                self.APP_LOREBOOK_MAX_RECURSIVE_PASSES = converted_val
                self.config.setdefault("app", {})["lorebook_max_recursive_passes"] = converted_val
                app_updated = True
            elif field == "cognition_max_words":
                self.APP_COGNITION_MAX_WORDS = converted_val
                self.config.setdefault("app", {})["cognition_max_words"] = converted_val
                app_updated = True
            elif field == "retrieval_weight_similarity":
                self.APP_RETRIEVAL_WEIGHT_SIMILARITY = converted_val
                self.config.setdefault("app", {})["retrieval_weight_similarity"] = converted_val
                app_updated = True
            elif field == "retrieval_weight_importance":
                self.APP_RETRIEVAL_WEIGHT_IMPORTANCE = converted_val
                self.config.setdefault("app", {})["retrieval_weight_importance"] = converted_val
                app_updated = True
            elif field == "retrieval_weight_time":
                self.APP_RETRIEVAL_WEIGHT_TIME = converted_val
                self.config.setdefault("app", {})["retrieval_weight_time"] = converted_val
                app_updated = True
            elif field == "retrieval_half_life_turns":
                self.APP_RETRIEVAL_HALF_LIFE_TURNS = converted_val
                self.config.setdefault("app", {})["retrieval_half_life_turns"] = converted_val
                app_updated = True
            elif field == "retrieval_candidate_multiplier":
                self.APP_RETRIEVAL_CANDIDATE_MULTIPLIER = converted_val
                self.config.setdefault("app", {})["retrieval_candidate_multiplier"] = converted_val
                app_updated = True
            elif field == "retrieval_ancestor_weight":
                self.APP_RETRIEVAL_ANCESTOR_WEIGHT = converted_val
                self.config.setdefault("app", {})["retrieval_ancestor_weight"] = converted_val
                app_updated = True

        # 3. 序列化回写到 config.yaml，确保重启不丢失
        if llm_updated or app_updated:
            full_path = os.path.join(parent_dir, "config.yaml")
            try:
                with open(full_path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(self.config, f, allow_unicode=True, sort_keys=False)
                print(f"[INFO] Settings: 成功持久化保存了更新后的设置到 {full_path}")
            except Exception as e:
                print(f"[ERROR] Settings: 持久化保存设置失败: {e}")

    def _load_yaml_config(self, filepath="config.yaml"):
        full_path = os.path.join(parent_dir, filepath)
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"Failed to load config.yaml at {full_path}: {e}")
            return {}

settings = Settings()
