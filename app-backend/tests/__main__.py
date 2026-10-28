"""Run automatic regressions in an isolated backend copy: python -m tests."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


GROUPS = ("api", "conversation", "core", "infrastructure", "lorebook", "memory", "parsing", "tts")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", choices=GROUPS, help="Run one test domain")
    parser.add_argument("--pattern", default="test_*.py", help="unittest filename pattern")
    args = parser.parse_args()
    backend = Path(__file__).resolve().parents[1]
    env = dict(
        os.environ,
        CHAT_API_KEY="test-key",
        EMBEDDING_API_KEY="test-key",
        MIMO_API_KEY="test-key",
        ACCESS_API_KEY="",
        PYTHONIOENCODING="utf-8",
        ANONYMIZED_TELEMETRY="False",
    )
    with tempfile.TemporaryDirectory(prefix="ai-roleplay-tests-") as temporary:
        workspace = Path(temporary)
        for name in ("application", "core", "routers", "services", "scripts", "alembic", "tests"):
            shutil.copytree(
                backend / name,
                workspace / name,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "manual"),
            )
        for name in ("main.py", "schemas.py", "alembic.ini"):
            shutil.copy2(backend / name, workspace / name)
        # 仅复制接口索引和固定领域契约，不带入 docs/local 或运行数据。
        from scripts.api_documentation import DOMAIN_DOCUMENTS
        docs = workspace / "project_docs"
        (docs / "docs" / "api").mkdir(parents=True)
        shutil.copy2(backend.parent / "API_TABLE.md", docs / "API_TABLE.md")
        for name in DOMAIN_DOCUMENTS:
            shutil.copy2(backend.parent / "docs" / "api" / name, docs / "docs" / "api" / name)
        config = {
            "llm": {
                "chat_base_url": "https://example.invalid/v1",
                "embedding_base_url": "https://example.invalid/v1",
            },
            "app": {"sqlite_db_path": "data/test.db", "chroma_db_path": "data/chroma"},
            "tts": {"cache_dir": "data/audio"},
        }
        # JSON is valid YAML. Do not copy the developer's config, secrets or data.
        (workspace / "config.yaml").write_text(json.dumps(config), encoding="utf-8")
        (workspace / "data").mkdir()
        avatars = workspace / "assets" / "avatars"
        avatars.mkdir(parents=True)
        (avatars / "fixture.txt").write_text("test avatar", encoding="utf-8")
        migration = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if migration.returncode:
            print(migration.stdout + migration.stderr, file=sys.stderr)
            return migration.returncode
        start = "tests" if args.group is None else "tests/" + args.group
        # Detect empty selections so a misspelled filename cannot appear to pass.
        bootstrap = (
            "import sys,unittest; "
            "suite=unittest.defaultTestLoader.discover(sys.argv[1],pattern=sys.argv[2],top_level_dir='.'); "
            "count=suite.countTestCases(); "
            "sys.exit('No automatic tests matched the selection.') if not count else None; "
            "result=unittest.TextTestRunner(verbosity=2).run(suite); "
            "sys.exit(0 if count and result.wasSuccessful() else 1)"
        )
        return subprocess.run(
            [sys.executable, "-c", bootstrap, start, args.pattern],
            cwd=workspace,
            env=env,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
