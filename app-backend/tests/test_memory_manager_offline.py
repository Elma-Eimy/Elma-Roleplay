r"""memory_manager 的完全离线诊断测试。

运行方式：
    .\venv\Scripts\python.exe .\tests\test_memory_manager_offline.py

本文件不会连接真实 SQLite、ChromaDB、Embedding API 或对话模型。当前网络环境下
国内向量模型可能因 VPN 无法访问，因此“向量调用失败后回滚/安全降级”是正常且应被
覆盖的行为，不应被误判为测试环境异常。

此前记录的三个已知缺陷现均已转为正式回归测试。
"""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock


if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parents[1]


class MemoryType(str, Enum):
    fact = "fact"
    event = "event"
    emotion = "emotion"
    relationship = "relationship"


class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"


class MemoryChunk:
    def __init__(self, **kwargs):
        self.id = None
        self.chroma_doc_id = None
        self.created_at = None
        for key, value in kwargs.items():
            setattr(self, key, value)


class SessionPersona:
    pass


class ChatMessage:
    session_id = object()
    is_active = object()
    id = object()


class Session:
    pass


class OutboxJob:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def _load_memory_manager():
    """使用依赖替身加载模块，确保导入阶段也不接触真实数据和外部服务。"""
    module_name = "_offline_memory_manager_under_test"
    sys.modules.pop(module_name, None)

    core_pkg = types.ModuleType("core")
    core_pkg.__path__ = []
    models_mod = types.ModuleType("core.models")
    models_mod.MemoryChunk = MemoryChunk
    models_mod.SessionPersona = SessionPersona
    models_mod.ChatMessage = ChatMessage
    models_mod.MemoryType = MemoryType
    models_mod.MessageRole = MessageRole
    models_mod.Session = Session
    models_mod.OutboxJob = OutboxJob
    core_pkg.models = models_mod

    settings = SimpleNamespace(
        APP_RETRIEVAL_TOP_K=3,
        APP_RETRIEVAL_MIN_IMPORTANCE=0.0,
        APP_RETRIEVAL_CANDIDATE_MULTIPLIER=3,
        APP_RETRIEVAL_MAX_DISTANCE=1.2,
        APP_RETRIEVAL_HALF_LIFE_TURNS=50,
        APP_RETRIEVAL_WEIGHT_SIMILARITY=0.6,
        APP_RETRIEVAL_WEIGHT_IMPORTANCE=0.2,
        APP_RETRIEVAL_WEIGHT_TIME=0.2,
        APP_RETRIEVAL_ANCESTOR_WEIGHT=0.8,
    )
    config_mod = types.ModuleType("core.config")
    config_mod.settings = settings

    clients_mod = types.ModuleType("services.clients")
    clients_mod.LLM_MODEL = "offline"
    clients_mod.chroma_client = MagicMock(name="offline_chroma_client")
    clients_mod.openai_ef = MagicMock(name="offline_embedding_function")

    cognition_mod = types.ModuleType("services.cognition_service")
    for name in (
        "get_unsummarized_count",
        "get_effective_memory_extract_limit",
        "get_memory_handoff_history_limit",
        "summarize_and_store_memory",
        "get_cognition_unseen_count",
        "update_cognition_state",
    ):
        setattr(cognition_mod, name, MagicMock(name=name))

    session_service_mod = types.ModuleType("services.session_service")
    session_service_mod.safe_delete_session = MagicMock(name="safe_delete_session")

    replacements = {
        "core": core_pkg,
        "core.models": models_mod,
        "core.config": config_mod,
        "services.clients": clients_mod,
        "services.cognition_service": cognition_mod,
        "services.session_service": session_service_mod,
    }
    saved = {name: sys.modules.get(name) for name in replacements}
    sys.modules.update(replacements)
    try:
        spec = importlib.util.spec_from_file_location(
            module_name, ROOT / "services" / "memory_manager.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


class _AddDB:
    def __init__(self):
        self.rolled_back = False
        self.committed = False
        self.items = []

    def add(self, item):
        self.items.append(item)
        if isinstance(item, MemoryChunk):
            self.chunk = item

    def flush(self):
        self.chunk.id = 41

    def rollback(self):
        self.rolled_back = True

    def commit(self):
        self.committed = True

    def refresh(self, chunk):
        pass


class _StatefulCollection:
    def __init__(self, content="旧内容"):
        self.content = content

    def update(self, *, ids, documents, metadatas):
        self.content = documents[0]


class _UpdateDB:
    def __init__(self, chunk, commit_error=None):
        self.chunk = chunk
        self.commit_error = commit_error
        self.rolled_back = False

    def get(self, model, chunk_id):
        return self.chunk

    def add(self, item):
        self.outbox_job = item

    def flush(self):
        pass

    def commit(self):
        if self.commit_error:
            raise self.commit_error

    def refresh(self, chunk):
        pass

    def rollback(self):
        self.rolled_back = True


class _RetrieveDB:
    def __init__(self, current_message_id=1000):
        self.persona = SimpleNamespace(session_id=9)
        self.current_message_id = current_message_id

    def get(self, model, key):
        return self.persona

    def query(self, model):
        current = SimpleNamespace(id=self.current_message_id)
        terminal = SimpleNamespace(first=lambda: current)
        ordered = SimpleNamespace(order_by=lambda *args, **kwargs: terminal)
        return SimpleNamespace(filter=lambda *args, **kwargs: ordered)


class MemoryManagerOfflineTests(unittest.TestCase):
    def setUp(self):
        self.mm = _load_memory_manager()

    def test_metadata_omits_chroma_unsupported_none_values(self):
        metadata = self.mm._build_chroma_metadata(
            persona_id=7,
            memory_type=MemoryType.fact,
            importance_score=0.8,
            origin_session_id=None,
            created_at=__import__("datetime").datetime(2026, 7, 18),
            source_message_id=None,
        )
        self.assertNotIn("origin_session_id", metadata)
        self.assertNotIn("source_message_id", metadata)

    def test_add_commits_sqlite_and_outbox_without_calling_vector_store(self):
        """向量服务不可达不再阻止 SQLite 保存记忆及持久化同步任务。"""
        db = _AddDB()
        collection = MagicMock()
        collection.add.side_effect = ConnectionError("offline embedding endpoint")
        self.mm.get_character_collection = MagicMock(return_value=collection)

        self.mm.add_memory_chunk(
            persona_id=7,
            character_id=3,
            content="离线测试记忆",
            memory_type=MemoryType.fact,
            importance_score=0.8,
            origin_session_id=2,
            source_message_id=None,
            db=db,
        )

        self.assertTrue(db.committed)
        self.assertFalse(db.rolled_back)
        self.assertEqual("upsert_vector", db.items[-1].task_type)
        self.mm.get_character_collection.assert_not_called()

    def test_vector_count_failure_degrades_to_no_recall(self):
        """向量库暂不可用不应让对话请求崩溃。"""
        collection = MagicMock()
        collection.count.side_effect = ConnectionError("offline vector store")
        self.mm.get_character_collection = MagicMock(return_value=collection)

        result = self.mm.retrieve_memories(
            persona_id=7,
            character_id=3,
            query="测试",
            db=MagicMock(),
        )
        self.assertEqual([], result)

    def test_commit_failure_never_changes_previous_vector_document(self):
        """SQLite commit 失败时 Outbox 一同回滚，旧向量不曾被修改。"""
        collection = _StatefulCollection(content="旧内容")
        persona = SimpleNamespace(character_id=3)
        chunk = SimpleNamespace(
            id=1,
            content="旧内容",
            importance_score=0.5,
            chroma_doc_id="mem_1",
            persona=persona,
            persona_id=7,
            memory_type=MemoryType.fact,
            origin_session_id=2,
            source_start_message_id=None,
            source_message_id=None,
            created_at=None,
        )
        db = _UpdateDB(chunk, commit_error=RuntimeError("sqlite commit failed"))
        self.mm.get_character_collection = MagicMock(return_value=collection)

        with self.assertRaises(RuntimeError):
            self.mm.update_memory_chunk(1, "新内容", 0.9, db)

        self.assertEqual("旧内容", collection.content)
        self.mm.get_character_collection.assert_not_called()
        self.assertTrue(db.rolled_back)

    def test_time_decay_uses_session_turns_not_global_message_id_gap(self):
        """精排使用分支轮次计算结果，而不是全局消息 ID 差值。"""
        collection = MagicMock()
        collection.count.return_value = 1
        collection.query.return_value = {
            "ids": [["mem_1"]],
            "documents": [["一次近期事件"]],
            "metadatas": [[{
                "persona_id": 7,
                "memory_type": "event",
                "importance_score": 0.8,
                "source_message_id": 10,
            }]],
            "distances": [[0.1]],
        }
        self.mm.get_character_collection = MagicMock(return_value=collection)
        self.mm.get_ancestor_persona_ids = MagicMock(return_value=[7])
        self.mm._build_branch_turn_segments = MagicMock(return_value=[])
        self.mm.calculate_memory_age_turns = MagicMock(return_value=1)

        result = self.mm.retrieve_memories(
            persona_id=7,
            character_id=3,
            query="近期发生了什么",
            db=_RetrieveDB(current_message_id=1000),
            top_k=1,
            min_importance=0.0,
        )

        self.assertEqual(1, result[0]["turns_passed"])

    def test_zero_max_distance_does_not_crash_retrieval(self):
        """零距离阈值允许距离为零的精确候选且不会除零。"""
        collection = MagicMock()
        collection.count.return_value = 1
        collection.query.return_value = {
            "ids": [["mem_1"]],
            "documents": [["测试记忆"]],
            "metadatas": [[{
                "persona_id": 7,
                "memory_type": "fact",
                "importance_score": 0.8,
            }]],
            "distances": [[0.0]],
        }
        self.mm.get_character_collection = MagicMock(return_value=collection)
        self.mm.get_ancestor_persona_ids = MagicMock(return_value=[7])
        self.mm.settings.APP_RETRIEVAL_MAX_DISTANCE = 0

        result = self.mm.retrieve_memories(
            persona_id=7,
            character_id=3,
            query="测试",
            db=_RetrieveDB(),
            top_k=1,
            min_importance=0.0,
        )
        self.assertEqual(1, len(result))

    def test_zero_max_distance_filters_nonzero_candidate(self):
        collection = MagicMock()
        collection.count.return_value = 1
        collection.query.return_value = {
            "ids": [["mem_1"]],
            "documents": [["测试记忆"]],
            "metadatas": [[{
                "persona_id": 7,
                "memory_type": "fact",
                "importance_score": 0.8,
            }]],
            "distances": [[0.01]],
        }
        self.mm.get_character_collection = MagicMock(return_value=collection)
        self.mm.get_ancestor_persona_ids = MagicMock(return_value=[7])
        self.mm.settings.APP_RETRIEVAL_MAX_DISTANCE = 0

        result = self.mm.retrieve_memories(
            persona_id=7,
            character_id=3,
            query="测试",
            db=_RetrieveDB(),
            top_k=1,
            min_importance=0.0,
        )
        self.assertEqual([], result)

    def test_negative_max_distance_safely_skips_vector_store(self):
        self.mm.get_character_collection = MagicMock()
        self.mm.settings.APP_RETRIEVAL_MAX_DISTANCE = -0.1

        result = self.mm.retrieve_memories(
            persona_id=7,
            character_id=3,
            query="测试",
            db=_RetrieveDB(),
            top_k=1,
            min_importance=0.0,
        )
        self.assertEqual([], result)
        self.mm.get_character_collection.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
