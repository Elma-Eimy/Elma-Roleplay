"""标准库启动器：在导入应用前构建独立源码、配置和数据目录。"""

import argparse
import hashlib
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
from uuid import uuid4

from .cases import load_suite


def parser():
    result = argparse.ArgumentParser(description="记忆整理质量验收；默认固定响应离线回放，不读取开发配置或数据库。")
    result.add_argument("--cases", type=Path, help="版本化 JSON 样本集；默认使用仓库虚构样本")
    result.add_argument("--case", action="append", default=[], help="仅运行指定场景 ID，可重复指定")
    result.add_argument("--repeat", type=int, choices=range(1, 6), default=1)
    result.add_argument("--output", type=Path, help="报告父目录；每次新建运行子目录，不覆盖旧结果")
    result.add_argument("--baseline", type=Path, help="上一份 report.json，用于对比自动检查和线索命中数")
    result.add_argument("--online", action="store_true", help="实际调用记忆模型；会发送所选样本并产生服务费用")
    result.add_argument("--base-url", help="在线模式的兼容 API 地址；不从开发配置读取")
    result.add_argument("--model", help="在线模式模型 ID")
    result.add_argument("--api-key-env", default="MEMORY_QUALITY_API_KEY", help="在线密钥的环境变量名称；不能传入密钥正文")
    result.add_argument("--adapter", choices=("auto", "compatible", "deepseek", "reasoning"), default="auto")
    result.add_argument("--thinking-mode", choices=("enabled", "disabled"), default="disabled")
    result.add_argument("--reasoning-effort", choices=("low", "medium", "high", "max"), default="high")
    return result


def run(args, backend):
    suite, suite_hash = load_suite(args.cases or backend / "tests/fixtures/memory_quality_cases.json")
    selected = set(args.case)
    unknown = selected - {case["id"] for case in suite["cases"]}
    if unknown:
        raise ValueError("指定的场景不存在")
    if selected:
        suite["cases"] = [case for case in suite["cases"] if case["id"] in selected]
    if args.online:
        if not args.base_url or not args.model or not args.model.strip():
            raise ValueError("在线模式必须显式指定 --base-url 和 --model")
        url = urlsplit(args.base_url)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("API 地址须为 HTTP(S)，不能包含凭据、查询参数或片段")
        key = os.environ.get(args.api_key_env)
        if not key:
            raise ValueError("在线密钥环境变量未设置；不会读取 .env")
    else:
        if args.base_url or args.model:
            raise ValueError("指定模型或连接地址时须显式添加 --online")
        key = "offline-placeholder"
    baseline = None
    if args.baseline:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        if baseline.get("schema_version") != 1 or not isinstance(baseline.get("results"), list):
            raise ValueError("基线必须是本工具生成的 report.json")
    run_id = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
    destination = (args.output or backend.parent / "docs/local/memory-quality").resolve() / run_id
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=backend, capture_output=True, text=True).stdout.strip() or "unknown"
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=backend, capture_output=True, text=True).stdout.strip())
    fingerprint = hashlib.sha256()
    for relative in ("services/memory/memory_consolidation_service.py", "services/memory/memory_consolidation_guard.py", "services/memory/memory_visibility.py",
                     "services/memory/memory_manager.py", "core/models.py", "scripts/memory_quality/worker.py", "scripts/memory_quality/cases.py"):
        fingerprint.update(relative.encode())
        fingerprint.update((backend / relative).read_bytes())
    request = {"run_id": run_id, "suite": suite, "suite_hash": suite_hash, "repeat": args.repeat,
               "mode": "online" if args.online else "offline", "model": args.model if args.online else "fixture-replay",
               "base_url": args.base_url if args.online else None, "revision": revision, "dirty": dirty,
               "code_sha256": fingerprint.hexdigest(), "baseline": baseline, "destination": str(destination)}
    env = dict(os.environ, CHAT_API_KEY=key, EMBEDDING_API_KEY="offline-placeholder", MIMO_API_KEY="",
               ACCESS_API_KEY="", OPENAI_API_KEY=key, ANONYMIZED_TELEMETRY="False", PYTHONIOENCODING="utf-8")
    # 密钥不进入参数、请求 JSON、配置文件或报告。
    if args.api_key_env not in {"CHAT_API_KEY", "OPENAI_API_KEY"}:
        env.pop(args.api_key_env, None)
    with tempfile.TemporaryDirectory(prefix="roleplay-memory-quality-") as temporary:
        workspace = Path(temporary)
        env["MEMORY_QUALITY_WORKER_ROOT"] = str(workspace.resolve())
        for name in ("core", "services", "scripts", "alembic"):
            shutil.copytree(backend / name, workspace / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for name in ("schemas.py", "alembic.ini"):
            shutil.copy2(backend / name, workspace / name)
        llm = {"chat_base_url": args.base_url if args.online else "https://example.invalid/v1",
               "embedding_base_url": "https://example.invalid/v1", "memory_model": request["model"],
               "default_chat_model": request["model"], "memory_thinking_mode": args.thinking_mode,
               "memory_reasoning_effort": args.reasoning_effort, "timeout": 60}
        if args.adapter != "auto":
            llm["model_profiles"] = [{"id": request["model"], "adapter": args.adapter}]
        config = {"llm": llm, "app": {"sqlite_db_path": "data/bootstrap.db", "chroma_db_path": "data/chroma",
                  "retrieval_top_k": 3, "retrieval_min_importance": 0, "retrieval_max_distance": .95},
                  "tts": {"cache_dir": "data/audio"}}
        (workspace / "config.yaml").write_text(json.dumps(config), encoding="utf-8")
        (workspace / "request.json").write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        process = subprocess.run([sys.executable, "-m", "scripts.memory_quality.worker", "request.json"],
                                 cwd=workspace, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if process.returncode not in (0, 1) or not (destination / "report.json").exists():
            raise RuntimeError("验收子进程未能生成报告；请检查依赖环境（未输出可能含服务凭据的原始异常）")
    report = json.loads((destination / "report.json").read_text(encoding="utf-8"))
    print(f"{'在线模型验收' if args.online else '离线固定响应回放（不代表模型质量）'}：自动检查通过 {report['summary']['auto_passed']}/{report['summary']['total']}，语义均待人工审阅。")
    print(f"HTML 报告：{destination / 'index.html'}")
    print(f"机器结果：{destination / 'report.json'}")
    return process.returncode


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    arguments = parser()
    args = arguments.parse_args(argv)
    try:
        return run(args, Path(__file__).resolve().parents[2])
    except (ValueError, OSError, RuntimeError) as exc:
        # ValueError 文本仅由本模块/样本校验器提供；不打印配置或服务异常原文。
        print(str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "无法读取输入或写入报告，请检查路径与权限。", file=sys.stderr)
        return 2
