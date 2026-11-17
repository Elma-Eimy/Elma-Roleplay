"""缓存模块独立性、版本兼容与文件淘汰的离线回归。"""

import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from services.media.tts_cache import TTSAudioCache, prune_cache
from services.tts_service import TTSService


class TTSCacheTests(unittest.TestCase):
    def test_cache_import_and_file_operations_do_not_initialize_runtime(self):
        script = """
import sys, tempfile
from services.media.tts_cache import TTSAudioCache
with tempfile.TemporaryDirectory() as directory:
    cache = TTSAudioCache.for_text(directory, '你好。', '2', 'testvoice', 1.0)
    assert not cache.is_ready()
    cache.write(b'audio')
    assert cache.is_ready()
forbidden = ('services.tts_service', 'core.config', 'core.database',
             'services.infrastructure.llm_provider', 'httpx', 'sqlalchemy')
assert not [name for name in forbidden if name in sys.modules]
"""
        result = subprocess.run([sys.executable, "-c", script], capture_output=True,
            text=True, encoding="utf-8", timeout=30)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_cache_names_preserve_p2_and_use_explicit_version_and_rounded_speed(self):
        text = TTSAudioCache.for_text("cache", " 你好。 ", "2", "testvoice", 1.0)
        self.assertEqual("02434807217a181a509f46a2ffe7cea0.mp3", text.filename)
        message = TTSAudioCache.for_message("cache", 7, "2", "testvoice", 1.004)
        self.assertEqual("/audio/msg_7_p2_testvoice_1.00.mp3", message.audio_url)
        self.assertEqual(os.path.join("cache", message.filename), message.filepath)
        self.assertNotEqual(text.filename,
            TTSAudioCache.for_text("cache", "你好。", "3", "testvoice", 1.0).filename)
        self.assertEqual("msg_7_p3_testvoice_1.25.mp3",
            TTSAudioCache.for_message("cache", 7, "3", "testvoice", 1.25).filename)

    def test_compatibility_cleanup_entry_prunes_by_mtime_and_preserves_other_files(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "services.tts_service.settings.TTS_CACHE_DIR", directory,
        ), patch("services.tts_service.settings.TTS_MAX_CACHE_FILES", 1):
            paths = [Path(directory) / name for name in ("old.mp3", "middle.mp3", "new.mp3")]
            for index, path in enumerate(paths):
                path.write_bytes(b"audio")
                os.utime(path, (100 + index, 100 + index))
            unrelated = Path(directory) / "keep.txt"
            unrelated.write_text("keep", encoding="utf-8")
            self.assertTrue(TTSAudioCache(directory, "old.mp3").is_ready())
            TTSService()._prune_cache_background()
            self.assertEqual({"new.mp3", "keep.txt"}, {path.name for path in Path(directory).iterdir()})

    def test_cleanup_continues_after_delete_failure_and_logs_only_error_type(self):
        logger = logging.getLogger("test.tts.cache")
        with tempfile.TemporaryDirectory() as directory:
            for index, name in enumerate(("locked.mp3", "old.mp3", "new.mp3")):
                path = Path(directory) / name
                path.write_bytes(b"audio")
                os.utime(path, (100 + index, 100 + index))
            remove = os.remove

            def delete(path):
                if Path(path).name == "locked.mp3":
                    raise OSError("private-path-and-details")
                remove(path)

            with patch("services.media.tts_cache.os.remove", side_effect=delete), self.assertLogs(
                logger, level="INFO",
            ) as captured:
                prune_cache(directory, 1, logger=logger)
            self.assertEqual({"locked.mp3", "new.mp3"}, {path.name for path in Path(directory).iterdir()})
            output = " ".join(captured.output)
            self.assertIn("tts_cache_delete_failed error_type=OSError", output)
            self.assertIn("tts_cache_prune_completed count=1", output)
            self.assertNotIn("private-path-and-details", output)
