"""Embedding 失败必须显式传播，禁止静默写入零向量。"""

import unittest
from unittest.mock import patch

from chromadb.utils import embedding_functions

from services.infrastructure.clients import (
    EmbeddingGenerationError,
    RobustOpenAIEmbeddingFunction,
)


class EmbeddingFailurePolicyTests(unittest.TestCase):
    def test_multimodal_failure_raises_instead_of_returning_zero_vectors(self):
        embedding_function = RobustOpenAIEmbeddingFunction(
            api_key="test-key",
            api_base="https://ark.cn-beijing.volces.com/api/v3",
            model_name="test-vision-model",
        )

        with patch(
            "urllib.request.urlopen",
            side_effect=ConnectionError("temporary network fluctuation"),
        ):
            with self.assertRaises(EmbeddingGenerationError) as raised:
                embedding_function(["需要向量化的记忆"])

        self.assertIn("temporary network fluctuation", str(raised.exception))

    def test_standard_embedding_failure_also_propagates(self):
        embedding_function = RobustOpenAIEmbeddingFunction(
            api_key="test-key",
            api_base="https://example.invalid/v1",
            model_name="text-embedding-model",
        )

        with patch.object(
            embedding_functions.OpenAIEmbeddingFunction,
            "__call__",
            side_effect=TimeoutError("embedding timeout"),
        ):
            with self.assertRaises(EmbeddingGenerationError) as raised:
                embedding_function(["需要向量化的记忆"])

        self.assertIn("embedding timeout", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
