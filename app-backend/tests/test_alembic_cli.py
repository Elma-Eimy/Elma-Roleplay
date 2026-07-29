r"""Regression tests for direct Alembic CLI execution.

The subprocess reuses the currently running project virtual environment through
``sys.executable`` and never invokes an environment-variable Python executable.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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
        self.assertIn("b1c2d3e4f5a6", result.stdout)

    def test_current_runs_without_recursive_environment_import(self):
        result = self._run_alembic("current")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"(a9b8c7d6e5f4|b1c2d3e4f5a6)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
