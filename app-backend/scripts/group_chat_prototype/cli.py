"""导入应用前创建临时源码和配置，不读取开发数据库。"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from uuid import uuid4
from urllib.parse import urlsplit


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="群聊导演隔离原型；默认离线回放，不代表模型质量。")
    parser.add_argument("--case", action="append", default=[], help="仅运行指定虚构场景，可重复")
    parser.add_argument("--output", type=Path, help="报告父目录；每次新建子目录")
    parser.add_argument("--online", action="store_true", help="显式调用真实模型，会产生费用")
    parser.add_argument("--base-url")
    parser.add_argument("--model")
    parser.add_argument("--api-key-env", default="GROUP_PROTOTYPE_API_KEY")
    parser.add_argument("--serve", action="store_true", help="回放后限时提供本机只读预览")
    parser.add_argument("--port", type=int, default=8767, help="只读预览端口，固定监听 127.0.0.1")
    parser.add_argument("--preview-seconds", type=int, default=600, help="预览存活 1–3600 秒，结束后清理临时库")
    parser.add_argument("--frontend-dist", type=Path, help="使用 /preview/ 为 base 构建的 H5 目录，须配合 --serve")
    args = parser.parse_args(argv)
    backend = Path(__file__).resolve().parents[2]
    try:
        suite = json.loads((backend / "tests/fixtures/group_director_cases.json").read_text(encoding="utf-8"))
        cases = suite["cases"]
        if set(args.case) - {case["id"] for case in cases}:
            raise ValueError("场景 ID 不存在")
        if args.case:
            cases = [case for case in cases if case["id"] in args.case]
        if not 1 <= args.port <= 65535 or not 1 <= args.preview_seconds <= 3600:
            raise ValueError("预览端口或时长无效")
        if args.frontend_dist and (not args.serve or not (args.frontend_dist / "index.html").is_file()
                                  or not (args.frontend_dist / "assets").is_dir()):
            raise ValueError("--frontend-dist 需要 --serve 及有效 H5 构建目录")
        if args.frontend_dist and 'name="group-chat-preview" content="true"' not in (
                args.frontend_dist / "index.html").read_text(encoding="utf-8"):
            raise ValueError("预览只接受 VITE_GROUP_PREVIEW=true 的专用 H5 构建，避免连接本机保存的服务器")
        key = "offline-placeholder"
        if args.online:
            if args.case and any(case.get("offline_only") for case in cases):
                raise ValueError("故障注入场景仅支持离线回放")
            cases = [case for case in cases if not case.get("offline_only")]
            parsed = urlsplit(args.base_url or "")
            if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password
                    or parsed.query or parsed.fragment or not args.model or not args.model.strip()):
                raise ValueError("在线模式须显式指定无凭据的 HTTP(S) 地址和模型")
            key = os.environ.get(args.api_key_env)
            if not key:
                raise ValueError("在线密钥环境变量未设置，不读取 .env")
        elif args.model or args.base_url:
            raise ValueError("连接参数必须与 --online 一起指定")
        destination = (args.output or backend.parent / "docs/local/group-chat-prototype").resolve() / uuid4().hex
        env = dict(os.environ, CHAT_API_KEY=key, EMBEDDING_API_KEY="offline-placeholder", MIMO_API_KEY="",
                   OPENAI_API_KEY=key, ACCESS_API_KEY="", PYTHONIOENCODING="utf-8", ANONYMIZED_TELEMETRY="False")
        with tempfile.TemporaryDirectory(prefix="group-director-prototype-") as temporary:
            root = Path(temporary)
            for name in ("application", "core", "routers", "services", "scripts", "alembic"):
                shutil.copytree(backend / name, root / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            for name in ("schemas.py", "alembic.ini"):
                shutil.copy2(backend / name, root / name)
            if args.frontend_dist:
                shutil.copytree(args.frontend_dist, root / "h5", ignore=shutil.ignore_patterns(".*", "src", "node_modules"))
            config = {"llm": {"chat_base_url": args.base_url if args.online else "https://example.invalid/v1",
                              "embedding_base_url": "https://example.invalid/v1",
                              "default_chat_model": args.model or "fixture-replay"},
                      "app": {"sqlite_db_path": "data/prototype.db", "chroma_db_path": "data/chroma"},
                      "tts": {"cache_dir": "data/audio"}}
            (root / "config.yaml").write_text(json.dumps(config), encoding="utf-8")
            (root / "request.json").write_text(json.dumps({"cases": cases, "online": args.online,
                "model": args.model or "fixture-replay", "destination": str(destination),
                "serve": args.serve, "port": args.port, "preview_seconds": args.preview_seconds,
                "frontend_dist": bool(args.frontend_dist)}, ensure_ascii=False), encoding="utf-8")
            env["GROUP_PROTOTYPE_WORKER_ROOT"] = str(root.resolve())
            if args.serve:
                print(f"回放完成后预览：http://127.0.0.1:{args.port}/（最长 {args.preview_seconds} 秒）", flush=True)
                print("报告：" + str(destination / "report.json"), flush=True)
            process = subprocess.run([sys.executable, "-m", "scripts.group_chat_prototype.worker"], cwd=root,
                env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if process.returncode not in (0, 1) or not (destination / "report.json").exists():
                raise RuntimeError("隔离原型未生成报告；未输出可能包含服务数据的原始异常。")
        print("群聊导演原型：" + ("真实模型，语义待人工审阅" if args.online else "离线固定响应回放，不代表模型质量"))
        print("报告：" + str(destination / "report.json"))
        return process.returncode
    except (ValueError, OSError, RuntimeError) as exc:
        print(str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "无法读取样本或写入报告。", file=sys.stderr)
        return 2
