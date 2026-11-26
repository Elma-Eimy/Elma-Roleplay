"""配置导入只读、显式持久化与迁移入口的隔离回归。"""

import copy
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

from core.config import Settings


class ConfigBoundaryTests(unittest.TestCase):
    def run_child(self, script, root):
        return subprocess.run([sys.executable, "-c", script], cwd=root,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=60)

    def copy_core(self, root):
        backend = Path(__file__).resolve().parents[2]
        shutil.copytree(backend / "core", root / "core", ignore=shutil.ignore_patterns("__pycache__"))
        return backend

    def test_schema_and_settings_class_import_without_reading_runtime_files(self):
        script = """
import os, sys
def audit(event, args):
    if event == 'open' and isinstance(args[0], (str, bytes)):
        if os.path.basename(os.fsdecode(args[0])) in ('config.yaml', '.env'):
            raise AssertionError('runtime file was accessed')
sys.addaudithook(audit)
from core.config_schema import CONFIG_SCHEMA
from core.config_settings import Settings
assert CONFIG_SCHEMA['llm']['temperature']['default'] == 0.7
assert callable(Settings)
assert not {'core.config', 'core.database', 'dotenv'} & sys.modules.keys()
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_core(root)
            result = self.run_child(script, root)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_compatibility_import_does_not_create_or_migrate_yaml_on_disk(self):
        script = """
import importlib
from pathlib import Path
path = Path('config.yaml')
before = path.read_bytes() if path.exists() else None
from core.config import settings, Settings, CONFIG_SCHEMA
from core.config_settings import Settings as Implementation
from core.config_schema import CONFIG_SCHEMA as Schema
assert Settings is Implementation and CONFIG_SCHEMA is Schema
assert settings is importlib.import_module('core.config').settings
assert settings.LLM_MAX_TOKENS == 4096
assert (path.read_bytes() if path.exists() else None) == before
assert not list(Path('.').glob('*.tmp'))
"""
        for content in (None, "llm:\n  chat_model: custom-legacy\n  reasoning_mode: true\n"):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.copy_core(root)
                if content is not None:
                    (root / "config.yaml").write_text(content, encoding="utf-8")
                result = self.run_child(script, root)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_construction_and_rebinding_only_normalize_in_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            config = Settings(path)
            self.assertFalse(path.exists())
            path.write_text("llm:\n  temperature: 0.5\n", encoding="utf-8")
            before = path.read_bytes()
            config = Settings(path)
            config.migrate_and_bind_config()
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(0.5, config.LLM_TEMPERATURE)
            self.assertEqual(4096, config.LLM_MAX_TOKENS)

    def test_explicit_persistence_preserves_legacy_selection_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text("llm:\n  chat_model: custom-legacy\n  reasoning_mode: true\n  custom: keep\n", encoding="utf-8")
            config = Settings(path)
            identity = id(config)
            config.persist_normalized()
            saved = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual("custom-legacy", saved["llm"]["default_chat_model"])
            self.assertEqual("keep", saved["llm"]["custom"])
            self.assertEqual(4096, saved["llm"]["max_tokens"])
            self.assertEqual(identity, id(config))
            with patch.object(config, "_save_yaml_config") as save:
                config.persist_normalized()
                save.assert_not_called()
            loaded = Settings(path)
            with patch.object(loaded, "_save_yaml_config") as save:
                loaded.persist_normalized()
                save.assert_not_called()

    def test_failed_initial_persistence_keeps_old_file_and_can_be_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text("llm: {}\n", encoding="utf-8")
            before = path.read_bytes()
            config = Settings(path)
            state = copy.deepcopy(config.config)
            with patch("core.config.os.replace", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    config.persist_normalized()
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(state, config.config)
            self.assertEqual([], list(path.parent.glob("*.tmp")))
            config.persist_normalized()
            self.assertEqual(state, yaml.safe_load(path.read_text(encoding="utf-8")))

    def test_update_persistence_is_not_overwritten_by_later_startup_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            config = Settings(path)
            config.update_and_persist({"temperature": 0.9})
            with patch.object(config, "_save_yaml_config") as save:
                config.persist_normalized()
                save.assert_not_called()
            self.assertEqual(0.9, Settings(path).LLM_TEMPERATURE)

    def test_standalone_alembic_upgrade_does_not_rewrite_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = self.copy_core(root)
            shutil.copytree(backend / "alembic", root / "alembic", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copy2(backend / "alembic.ini", root / "alembic.ini")
            path = root / "config.yaml"
            path.write_text("app:\n  sqlite_db_path: test.db\n", encoding="utf-8")
            before = path.read_bytes()
            result = self.run_child("from alembic.config import main; main(['upgrade', 'head'])", root)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertTrue((root / "test.db").exists())
            self.assertEqual(before, path.read_bytes())
