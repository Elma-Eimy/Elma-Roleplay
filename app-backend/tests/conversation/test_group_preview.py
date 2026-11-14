"""只读预览与真实 CLI 的限时本机 HTTP 联通；只使用临时库。"""
import asyncio
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.request import urlopen
from urllib.error import URLError

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from core.database import get_db
from services.conversation.group.session_service import create_group_session
from services.conversation.group import history_service as history
from scripts.group_chat_prototype.preview import preview_app
from tests.conversation import test_group_session_service as fixtures


class GroupPreviewTests(unittest.TestCase):
    setUp = fixtures.GroupSessionServiceTests.setUp

    def sample(self):
        group = asyncio.run(create_group_session(self.cards, self.db))
        sid = group["session_id"]
        ids = tuple(row["persona_id"] for row in group["members"])
        target = history._prepare(sid, "fixture", ids, self.db)
        history._finish(sid, target["candidate_id"], 1, False, self.db)
        report = {"results": [{"id": "fixture", "session_id": sid, "finish_reason": "wait_user"}]}
        return sid, report

    def test_preview_reads_real_routes_and_blocks_all_writes_and_unrelated_gets(self):
        sid, report = self.sample()
        with preview_app(self.engine.url.database, report) as app, patch(
                "application.lifecycle.run_migrations", side_effect=AssertionError("no lifecycle")), TestClient(app) as client:
            self.assertFalse(client.get(f"/group-sessions/{sid}").json()["can_generate"])
            row = client.get(f"/group-sessions/{sid}/rounds").json()["rounds"][0]
            self.assertEqual(2, row["revision"])
            self.assertIsNone(row["finish_reason"])
            self.assertIsNone(row["error_code"])
            for path in (f"/group-sessions/{sid}/delete", "/group-sessions", "/chat/send"):
                self.assertEqual(405, client.post(path, json={}).status_code)
            for path in ("/characters", "/openapi.json", "/../config.yaml", "/preview/"):
                self.assertEqual(404, client.get(path).status_code)
            self.assertEqual(1, client.get("/group-sessions").json()["total"])
            reader = app.dependency_overrides[get_db]()
            try:
                db = next(reader)
                with self.assertRaises(OperationalError):
                    db.execute(text("UPDATE group_round_candidates SET revision=99"))
                db.rollback()
            finally:
                reader.close()

    def test_h5_mount_and_entry_links_do_not_replace_group_api_or_backend_assets(self):
        from scripts.group_chat_prototype.cli import main
        sid, report = self.sample()
        with tempfile.TemporaryDirectory() as temporary:
            dist = Path(temporary)
            (dist / "assets").mkdir()
            (dist / "index.html").write_text("<h1>H5 fixture</h1>", encoding="utf-8")
            (dist / "assets/app.js").write_text("fixture", encoding="utf-8")
            with patch("subprocess.run", side_effect=AssertionError("unmarked build must be rejected")):
                self.assertEqual(2, main(["--serve", "--frontend-dist", str(dist)]))
            with preview_app(self.engine.url.database, report, dist) as app, TestClient(app) as client:
                self.assertIn(f"/preview/#/pages/group/detail?sessionId={sid}", client.get("/").text)
                self.assertIn("H5 fixture", client.get("/preview/").text)
                self.assertEqual("fixture", client.get("/preview/assets/app.js").text)
                self.assertEqual(200, client.get(f"/group-sessions/{sid}/rounds").status_code)

    def test_cli_serves_failed_prefix_then_exits_and_releases_port(self):
        backend = Path(__file__).resolve().parents[2]
        with socket.socket() as free:
            free.bind(("127.0.0.1", 0))
            port = free.getsockname()[1]
        with tempfile.TemporaryDirectory() as output:
            process = subprocess.Popen([sys.executable, "-m", "scripts.group_chat_prototype",
                "--case", "failed-prefix", "--output", output, "--serve", "--port", str(port),
                "--preview-seconds", "3"], cwd=backend, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace")
            try:
                deadline = time.monotonic() + 20
                while True:
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/group-sessions", timeout=0.3) as response:
                            sid = json.load(response)["sessions"][0]["session_id"]
                        break
                    except URLError:
                        if process.poll() is not None or time.monotonic() >= deadline:
                            self.fail("preview did not start")
                        time.sleep(0.05)
                with urlopen(f"http://127.0.0.1:{port}/group-sessions/{sid}/rounds", timeout=1) as response:
                    row = json.load(response)["rounds"][0]
                self.assertEqual(("failed", 5, "invalid_output"), (row["status"], row["revision"], row["error_code"]))
                self.assertEqual(1, len(row["utterances"]))
                self.assertIn("SAVED_PREFIX", row["utterances"][0]["content"])
                stdout, stderr = process.communicate(timeout=15)
                self.assertEqual(0, process.returncode, stdout + stderr)
                report = json.loads(next(Path(output).glob("*/report.json")).read_text(encoding="utf-8"))
                self.assertTrue(all(report["results"][0]["checks"].values()))
                with self.assertRaises(URLError):
                    urlopen(f"http://127.0.0.1:{port}/group-sessions", timeout=0.3)
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.communicate(timeout=10)
