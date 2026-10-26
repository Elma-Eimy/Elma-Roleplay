"""在独立进程中验证应用内迁移保留宿主日志配置。"""

import subprocess
import sys
import unittest


class MigrationLoggingTests(unittest.TestCase):
    def test_embedded_migrations_preserve_uvicorn_and_consolidation_logging(self):
        script = '''
import io
import logging
from logging.config import dictConfig
from uvicorn.config import LOGGING_CONFIG

dictConfig(LOGGING_CONFIG)
from core.database import run_migrations
from services.memory.memory_consolidation_service import logger

names = ("", "uvicorn.error", "uvicorn.access", logger.name, "application.lifecycle")
loggers = [logging.getLogger(name) for name in names]
def state():
    return [(item.disabled, item.level, item.propagate, tuple(item.handlers)) for item in loggers]

stream = io.StringIO()
handler = logging.StreamHandler(stream)
logger.addHandler(handler)
before = state()
for _ in range(2):
    run_migrations()
    assert state() == before, "Embedded migration changed host logging configuration"
    assert logger.isEnabledFor(logging.INFO), "Consolidation INFO logger is disabled"
    logger.info("[MEMORY CONSOLIDATION] startup-regression")
assert stream.getvalue().count("[MEMORY CONSOLIDATION] startup-regression") == 2
'''
        result = subprocess.run([sys.executable, "-c", script], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=60)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
