"""配置读取、规范化与运行状态；构造和重新绑定不隐式保存。"""

import os
import copy
import math
import threading
from pathlib import Path
from types import SimpleNamespace

from core.config_schema import CONFIG_SCHEMA
from core.config_storage import read_yaml_config, write_yaml_config
from core.model_settings import validate_model_settings

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Settings:
    def __init__(self, config_path=None):
        self._config_path = Path(config_path) if config_path is not None else Path(parent_dir) / "config.yaml"
        self._update_lock = threading.RLock()
        self.CHAT_API_KEY = os.getenv("CHAT_API_KEY", "your-chat-api-key")
        self.EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "your-embedding-api-key")
        self.ACCESS_API_KEY = os.getenv("ACCESS_API_KEY", "")
        self.MIMO_API_KEY = os.getenv("MIMO_API_KEY", "")
        self.config = self._load_yaml_config()
        self._persisted_config = copy.deepcopy(self.config)
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
        for name, lower, upper in (("LOG_LLM_DEBUG_MAX_BYTES", 4096, 104857600),
                                   ("LOG_LLM_DEBUG_BACKUP_COUNT", 1, 20),
                                   ("LOG_LLM_DEBUG_EXCERPT_BYTES", 128, 65536)):
            if not lower <= getattr(self, name) <= upper:
                raise ValueError(f"{name} 必须在 {lower} 与 {upper} 之间。")
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
                candidate._persisted_config = copy.deepcopy(candidate.config)
                candidate._save_yaml_config()
                self.__dict__ = candidate.__dict__.copy()

    def persist_normalized(self):
        """显式保存尚未落盘的规范化结果，成功后更新持久化基线。"""
        with self._update_lock:
            if self.config != self._persisted_config:
                persisted = copy.deepcopy(self.config)
                self._save_yaml_config()
                self._persisted_config = persisted

    def _load_yaml_config(self, filepath=None):
        path = Path(filepath) if filepath is not None else self._config_path
        return read_yaml_config(path)

    def _save_yaml_config(self, filepath=None):
        path = Path(filepath) if filepath is not None else self._config_path
        write_yaml_config(path, self.config)
