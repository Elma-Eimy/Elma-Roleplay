"""向量依赖只在使用时初始化，并保留并发复用与失败重试。"""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
from threading import Barrier
import unittest
from unittest.mock import Mock, patch

from services.infrastructure import clients, outbox_worker
from services.memory import memory_manager


class ClientInitializationTests(unittest.TestCase):
    def setUp(self):
        chroma = patch.object(clients, "_chroma_client", None)
        embedding = patch.object(clients, "_embedding_function", None)
        chroma.start()
        embedding.start()
        self.addCleanup(chroma.stop)
        self.addCleanup(embedding.stop)

    def test_importing_services_does_not_construct_vector_dependencies(self):
        # 在隔离测试副本的独立进程中验证真实导入链，不受发现顺序影响。
        code = """
from unittest.mock import patch
with patch('chromadb.PersistentClient') as chroma, patch(
    'chromadb.utils.embedding_functions.OpenAIEmbeddingFunction.__init__',
    return_value=None,
) as embedding:
    from services.infrastructure.clients import EmbeddingGenerationError
    from services.memory import memory_manager
    from application.factory import create_app
    create_app()
    chroma.assert_not_called()
    embedding.assert_not_called()
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_dependencies_use_existing_configuration_and_are_independent(self):
        with patch.object(clients.chromadb, "PersistentClient") as chroma, patch.object(
            clients, "RobustOpenAIEmbeddingFunction"
        ) as embedding:
            self.assertIs(chroma.return_value, clients.get_chroma_client())
            self.assertIs(chroma.return_value, clients.get_chroma_client())
            chroma.assert_called_once_with(path=clients.settings.STORAGE_CHROMA_DB_PATH)
            embedding.assert_not_called()
            self.assertIs(embedding.return_value, clients.get_embedding_function())
            self.assertIs(embedding.return_value, clients.get_embedding_function())
            embedding.assert_called_once_with(
                api_key=clients.settings.EMBEDDING_API_KEY,
                api_base=clients.settings.EMBEDDING_BASE_URL,
                model_name=clients.settings.LLM_EMBEDDING_MODEL,
            )

    def test_failed_initialization_can_be_retried(self):
        for factory, getter in (
            ("chromadb.PersistentClient", clients.get_chroma_client),
            ("RobustOpenAIEmbeddingFunction", clients.get_embedding_function),
        ):
            with self.subTest(factory=factory):
                expected = object()
                with patch(
                    "services.infrastructure.clients." + factory,
                    side_effect=[RuntimeError("temporary initialization failure"), expected],
                ) as constructor:
                    with self.assertRaisesRegex(RuntimeError, "initialization failure"):
                        getter()
                    self.assertIs(expected, getter())
                    self.assertIs(expected, getter())
                    self.assertEqual(2, constructor.call_count)

    def test_concurrent_first_access_reuses_one_instance(self):
        for factory, getter in (
            ("chromadb.PersistentClient", clients.get_chroma_client),
            ("RobustOpenAIEmbeddingFunction", clients.get_embedding_function),
        ):
            with self.subTest(factory=factory):
                start = Barrier(6)

                def access():
                    start.wait(timeout=10)
                    return getter()

                with patch("services.infrastructure.clients." + factory) as constructor:
                    with ThreadPoolExecutor(max_workers=6) as executor:
                        results = list(executor.map(lambda _: access(), range(6)))
                    self.assertTrue(all(item is constructor.return_value for item in results))
                    constructor.assert_called_once()

    def test_collection_and_outbox_use_getters(self):
        chroma, embedding = Mock(), Mock()
        with patch.object(memory_manager, "get_chroma_client", return_value=chroma), patch.object(
            memory_manager, "get_embedding_function", return_value=embedding
        ):
            self.assertIs(
                chroma.get_or_create_collection.return_value,
                memory_manager.get_character_collection(42),
            )
            chroma.get_or_create_collection.assert_called_once_with(
                name="character_42", embedding_function=embedding
            )
        with patch.object(clients, "get_chroma_client", return_value=chroma), patch.object(
            clients, "get_embedding_function"
        ) as get_embedding:
            outbox_worker.handle_delete_vector_collection(json.dumps({"character_id": 42}))
            chroma.delete_collection.assert_called_once_with("character_42")
            get_embedding.assert_not_called()


if __name__ == "__main__":
    unittest.main()
