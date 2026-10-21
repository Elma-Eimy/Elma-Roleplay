r"""Regression tests for direct Alembic CLI execution.

The subprocess reuses the currently running project virtual environment through
``sys.executable`` and never invokes an environment-variable Python executable.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class AlembicCliTests(unittest.TestCase):
    def _run_alembic(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=30,
            check=False,
        )

    def test_heads_runs_without_recursive_environment_import(self):
        result = self._run_alembic("heads")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("f5a6b7c8d9e0", result.stdout)

    def test_current_runs_without_recursive_environment_import(self):
        result = self._run_alembic("current")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("f5a6b7c8d9e0", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
