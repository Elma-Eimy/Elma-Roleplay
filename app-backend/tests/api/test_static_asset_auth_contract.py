from __future__ import annotations

import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import main
from core.config import settings


class StaticAssetAuthContractTests(unittest.TestCase):
    def setUp(self):
        self.original_access_api_key = settings.ACCESS_API_KEY
        settings.ACCESS_API_KEY = "contract-test-key"
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        settings.ACCESS_API_KEY = self.original_access_api_key

    def test_avatar_is_public_without_api_key(self):
        avatar = next(Path("assets/avatars").glob("*"))

        response = self.client.get(f"/assets/avatars/{avatar.name}")

        self.assertEqual(200, response.status_code)

    def test_audio_accepts_x_api_key_header(self):
        response = self.client.get(
            "/audio/contract-test-missing.mp3",
            headers={"X-API-Key": "contract-test-key"},
        )

        # 404 表示认证已通过，并进入了音频文件查找流程。
        self.assertEqual(404, response.status_code)

    def test_audio_rejects_missing_or_query_parameter_api_key(self):
        urls = [
            "/audio/contract-test-missing.mp3",
            "/audio/contract-test-missing.mp3?api_key=contract-test-key",
            "/audio/contract-test-missing.mp3?token=contract-test-key",
        ]

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(403, response.status_code)


if __name__ == "__main__":
    unittest.main()
