"""验收工具的隔离启动、真实服务回放、错误记录、指标边界与报告安全。"""

import copy
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from scripts.memory_quality import cli
from scripts.memory_quality.cases import load_suite, validate_suite
from scripts.memory_quality.worker import comparison, run_case, stability
from scripts.memory_quality.report import render_report


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/memory_quality_cases.json"


class MemoryQualityToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.suite, cls.suite_hash = load_suite(FIXTURE)

    def case(self, case_id):
        return copy.deepcopy(next(case for case in self.suite["cases"] if case["id"] == case_id))

    def execute(self, case, response=None, failure=None):
        with tempfile.TemporaryDirectory() as directory:
            if response is None and failure is None:
                return run_case(case, 1, "offline", Path(directory) / "case.db")
            provider = MagicMock()
            if failure:
                provider.generate.side_effect = failure
            else:
                provider.generate.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(response, ensure_ascii=False)))])
            with patch("services.infrastructure.llm_provider.get_llm_provider", return_value=provider):
                return run_case(case, 1, "online", Path(directory) / "case.db")

    def report(self, results):
        return {"schema_version": 1, "run_id": "test-run", "suite_hash": self.suite_hash, "mode": "offline",
                "model": "fixture-replay", "revision": "test", "dirty": False, "created_at": "2026-10-21T00:00:00Z",
                "retrieval": {"method": "lexical"}, "results": results, "stability": stability(results),
                "comparison": None, "summary": {"total": len(results), "auto_passed": sum(row["auto_passed"] for row in results)}}

    def test_fixed_suite_has_twelve_versioned_cases_with_explicit_expectations(self):
        self.assertEqual(12, len(self.suite["cases"]))
        self.assertEqual(64, len(self.suite_hash))
        malformed = copy.deepcopy(self.suite)
        malformed["cases"][0]["allowed_groups"] = [[{}]]
        with self.assertRaises(ValueError):
            validate_suite(malformed)
        malformed = copy.deepcopy(self.suite)
        malformed["cases"][0]["questions"][0]["fact_indices"] = [999]
        with self.assertRaises(ValueError):
            validate_suite(malformed)
        malformed["cases"][0]["id"] = "../../outside"
        with self.assertRaises(ValueError):
            validate_suite(malformed)

    def test_replay_is_repeatable_and_semantics_remain_unreviewed(self):
        first = self.execute(self.case("station_event"))
        second = self.execute(self.case("station_event"))
        self.assertTrue(first["auto_passed"], first.get("error"))
        self.assertEqual("unreviewed", first["semantic_review"])
        for key in ("before", "after", "recall", "fact_cues", "raw_response", "system_prompt_sha256"):
            self.assertEqual(first[key], second[key])
        self.assertEqual(1, stability([first, second])["station_event"]["variants"])
        self.assertEqual(3, len(first["before"]))
        self.assertEqual(1, len(first["after"]))

    def test_fragment_suite_covers_scattered_cards_below_one_hundred(self):
        suite, _ = load_suite(ROOT / "tests/fixtures/memory_fragment_cases.json")
        self.assertEqual([48, 96], [len(case["cards"]) for case in suite["cases"]])
        case = suite["cases"][1]
        self.assertEqual("cat_0", case["cards"][0]["key"])
        self.assertEqual("cat_1", case["cards"][-1]["key"])
        result = self.execute(case)
        self.assertTrue(result["auto_passed"], result.get("error"))
        self.assertEqual(96, result["preview"]["scanned_count"])
        self.assertEqual(8, len(result["preview"]["groups"]))
        self.assertEqual(82, len(result["after"]))
        self.assertTrue(all(row["after"] for row in result["fact_cues"]))

    def test_suite_accepts_one_hundred_cards_and_rejects_one_hundred_one(self):
        suite, _ = load_suite(ROOT / "tests/fixtures/memory_fragment_cases.json")
        case = suite["cases"][1]
        for index in range(4):
            case["cards"].append({"key": f"boundary_{index}", "type": "fact", "content": f"独立边界事实 {index}。"})
        validate_suite(suite)
        case["cards"].append({"key": "overflow", "type": "fact", "content": "这条超过单批检查上限。"})
        with self.assertRaises(ValueError):
            validate_suite(suite)

    def test_fragment_suite_omits_same_place_events_on_different_dates(self):
        suite, _ = load_suite(ROOT / "tests/fixtures/memory_fragment_cases.json")
        case = suite["cases"][0]
        ids = {card["key"]: index + 1 for index, card in enumerate(case["cards"])}
        result = self.execute(case, {"groups": [{"kind": "event",
            "source_ids": [ids["station_0"], ids["keep_1"]],
            "content": "6月7日用户和林墨在南站相遇，6月8日用户独自到南站取充电器。",
            "reason": "错误地按相同地点合并两次经历。"}]})
        self.assertNotIn("error", result)
        self.assertTrue(result["auto_passed"])
        self.assertEqual([], result["preview"]["groups"])
        self.assertEqual(result["before"], result["after"])

    def test_forbidden_merge_is_detected_even_when_service_schema_accepts_it(self):
        response = {"groups": [{"kind": "duplicate", "source_ids": [1, 2], "content": "用户喜欢在雨天听爵士乐，也在杭州工作。", "reason": "错误地把独立事实合并"}]}
        result = self.execute(self.case("independent_facts"), response)
        self.assertNotIn("error", result)
        self.assertFalse(result["auto_passed"])
        self.assertTrue(any(not check["passed"] and "分组" in check["name"] for check in result["checks"]))

    def test_omitted_promise_produces_a_cue_warning_not_a_semantic_pass(self):
        response = {"groups": [{"kind": "event", "source_ids": [1, 2, 3], "content": "用户和林墨在雨夜的南站相遇，林墨把伞借给用户。", "reason": "同一次相遇"}]}
        result = self.execute(self.case("station_event"), response)
        self.assertTrue(result["auto_passed"])
        self.assertFalse(result["fact_cues"][-1]["after"])
        self.assertEqual("unreviewed", result["semantic_review"])

    def test_conservative_no_merge_is_not_automatically_wrong(self):
        result = self.execute(self.case("station_event"), {"groups": []})
        self.assertTrue(result["auto_passed"])
        self.assertEqual(1, result["unmerged_opportunities"])
        self.assertEqual(result["before"], result["after"])

    def test_provider_error_is_reported_without_exposing_exception_secrets(self):
        result = self.execute(self.case("station_event"), failure=RuntimeError("secret-test-key-should-not-appear"))
        self.assertFalse(result["auto_passed"])
        self.assertEqual("preview", result["error"]["stage"])
        self.assertNotIn("secret-test-key", json.dumps(result))
        self.assertIn("执行失败", render_report(self.report([result])))

    def test_invalid_model_output_preserves_raw_response_for_review(self):
        result = self.execute(self.case("station_event"), {"groups": [{"kind": "event", "source_ids": [1, 999], "content": "模型编造的来源。", "reason": "错误"}]})
        self.assertFalse(result["auto_passed"])
        self.assertIn("999", result["raw_response"])
        self.assertEqual("ConsolidationModelError", result["error"]["type"])

    def test_html_escapes_cards_model_text_and_script_seed(self):
        result = self.execute(self.case("station_event"))
        attack = '</script><script>alert("xss")</script>'
        result["title"] = attack
        result["before"][0]["content"] = attack
        result["raw_response"] = attack
        report = self.report([result]); report["run_id"] = attack
        html = render_report(report)
        self.assertNotIn(attack, html)
        self.assertIn("&lt;/script&gt;", html)
        self.assertIn("\\u003c/script", html)
        self.assertIn("导出审阅 JSON", html)
        self.assertNotIn("<script src=", html)

    def test_baseline_flags_incomparable_modes_and_does_not_treat_failed_runs_as_compression(self):
        passed = self.execute(self.case("station_event"))
        failed = self.execute(self.case("station_event"), failure=RuntimeError("offline"))
        baseline = self.report([passed])
        report = self.report([failed])
        result = comparison(report, baseline)
        self.assertTrue(result["comparable"])
        self.assertIsNone(result["after"]["station_event"]["mean_cards_after"])
        self.assertEqual(1, result["after"]["station_event"]["automatic_failure_rate"])
        report["mode"] = "online"
        self.assertFalse(comparison(report, baseline)["comparable"])

    def test_cli_offline_end_to_end_uses_a_temporary_copy_and_retains_reports(self):
        original_config = (ROOT / "config.yaml").read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.run([sys.executable, "-m", "scripts.memory_quality", "--case", "station_event", "--case", "negation",
                "--repeat", "2", "--output", directory], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=90)
            self.assertEqual(0, process.returncode, process.stdout + process.stderr)
            reports = list(Path(directory).glob("*/report.json"))
            self.assertEqual(1, len(reports))
            report = json.loads(reports[0].read_text(encoding="utf-8"))
            self.assertEqual({"total": 4, "auto_passed": 4, "semantic_review": "unreviewed"}, report["summary"])
            self.assertTrue((reports[0].parent / "index.html").exists())
            self.assertIn("不代表模型质量", process.stdout)
            self.assertEqual(original_config, (ROOT / "config.yaml").read_bytes())

    def test_online_requires_explicit_connection_and_never_writes_credentials_into_artifacts(self):
        with patch.dict(os.environ, {"MEMORY_QUALITY_API_KEY": "private-eval-secret"}):
            with tempfile.TemporaryDirectory() as directory:
                args = cli.parser().parse_args(["--online", "--base-url", "https://example.invalid/v1", "--model", "test-model", "--case", "station_event", "--output", directory])
                def fake_process(command, cwd=None, env=None, **kwargs):
                    if command[0] == "git":
                        return subprocess.CompletedProcess(command, 0, "revision" if "rev-parse" in command else "", "")
                    workspace = Path(cwd)
                    self.assertNotEqual(ROOT, workspace)
                    self.assertFalse((workspace / ".env").exists())
                    self.assertFalse((workspace / "data/test.db").exists())
                    request_text = (workspace / "request.json").read_text(encoding="utf-8")
                    self.assertNotIn("private-eval-secret", request_text)
                    self.assertNotIn("private-eval-secret", (workspace / "config.yaml").read_text())
                    self.assertEqual("private-eval-secret", env["CHAT_API_KEY"])
                    self.assertNotIn("MEMORY_QUALITY_API_KEY", env)
                    destination = Path(json.loads(request_text)["destination"])
                    destination.mkdir(parents=True)
                    (destination / "report.json").write_text(json.dumps({"summary": {"auto_passed": 0, "total": 0}}))
                    return subprocess.CompletedProcess(command, 0, "", "")
                with patch.object(cli.subprocess, "run", side_effect=fake_process), redirect_stdout(io.StringIO()):
                    self.assertEqual(0, cli.run(args, ROOT))
        with self.assertRaises(ValueError):
            cli.run(cli.parser().parse_args(["--online"]), ROOT)
        with self.assertRaises(ValueError):
            cli.run(cli.parser().parse_args(["--model", "some-model"]), ROOT)

    def test_worker_cannot_run_against_the_current_project_directly(self):
        env = dict(os.environ)
        env.pop("MEMORY_QUALITY_WORKER_ROOT", None)
        result = subprocess.run([sys.executable, "-m", "scripts.memory_quality.worker", "missing.json"],
            cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(2, result.returncode)
        self.assertIn("启动隔离验收", result.stderr)

    def test_online_cli_calls_only_local_protocol_stub_and_keeps_key_out_of_reports(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append((self.path, self.headers.get("Authorization"), payload))
                body = json.dumps({"id": "local-fixture", "object": "chat.completion", "created": 0,
                    "model": "quality-protocol-stub", "choices": [{"index": 0, "finish_reason": "stop",
                    "message": {"role": "assistant", "content": '{"groups":[]}'}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                env = dict(os.environ, QUALITY_PROTOCOL_KEY="quality-protocol-test-secret", NO_PROXY="127.0.0.1,localhost")
                process = subprocess.run([sys.executable, "-m", "scripts.memory_quality", "--online", "--base-url",
                    f"http://127.0.0.1:{server.server_port}/v1", "--model", "quality-protocol-stub", "--api-key-env", "QUALITY_PROTOCOL_KEY",
                    "--case", "station_event", "--output", directory], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=90)
                self.assertEqual(0, process.returncode, process.stdout + process.stderr)
                self.assertEqual(1, len(requests))
                self.assertEqual("/v1/chat/completions", requests[0][0])
                self.assertEqual("Bearer quality-protocol-test-secret", requests[0][1])
                self.assertNotIn("allowed_groups", json.dumps(requests[0][2]["messages"]))
                report_path = next(Path(directory).glob("*/report.json"))
                report_text = report_path.read_text(encoding="utf-8")
                self.assertNotIn("quality-protocol-test-secret", report_text + process.stdout + process.stderr)
                report = json.loads(report_text)
                self.assertEqual("online", report["mode"])
                self.assertEqual("unreviewed", report["results"][0]["semantic_review"])
                self.assertEqual('{"groups":[]}', report["results"][0]["raw_response"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
