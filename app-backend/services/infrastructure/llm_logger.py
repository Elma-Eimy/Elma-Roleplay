"""模型流透明代理与可选、有界的 JSONL 调试记录。"""

import asyncio
import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
import threading
import time
from uuid import uuid4

from core.config import settings
from services.infrastructure.logging_context import current_task_id, log_event


logger = logging.getLogger(__name__)
_lock = threading.RLock()
_handler = None
_handler_options = None


class _DebugHandler(RotatingFileHandler):
    def shouldRollover(self, record):
        if self.stream is None:
            self.stream = self._open()
        self.stream.seek(0, 2)
        value = (self.format(record) + self.terminator).replace("\n", os.linesep)
        return self.stream.tell() + len(value.encode("utf-8")) > self.maxBytes

    def handleError(self, record):
        # logging 默认会将记录和异常写入 stderr，这里仅由外层报告错误类型。
        raise OSError("model debug log write failed")


def close_debug_log():
    global _handler, _handler_options
    with _lock:
        handler = _handler
        _handler = _handler_options = None
        if handler is not None:
            try:
                handler.close()
            except Exception as exc:
                log_event(logger, logging.WARNING, "llm_debug_log_close_failed", error_type=type(exc).__name__)


async def _wait_for_log_io(function, *args):
    # 延迟传播取消，确保写入线程退出后生命周期才能关闭同一个文件句柄。
    work = asyncio.create_task(asyncio.to_thread(function, *args))
    cancelled = False
    try:
        while True:
            try:
                await asyncio.shield(work)
                break
            except asyncio.CancelledError:
                if work.cancelled():
                    raise
                cancelled = True
    except Exception as exc:
        log_event(logger, logging.WARNING, "llm_debug_log_failed", error_type=type(exc).__name__)
    if cancelled:
        raise asyncio.CancelledError


async def close_debug_log_async():
    """在线程中等待文件锁并关闭，避免应用关闭时阻塞事件循环。"""
    await _wait_for_log_io(close_debug_log)


def _write_record(record, options):
    global _handler, _handler_options
    path, max_bytes, backups = options
    with _lock:
        if _handler_options != options:
            close_debug_log()
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            _handler = _DebugHandler(path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
            _handler.setFormatter(logging.Formatter("%(message)s"))
            _handler_options = options
        value = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        # 单条也受文件预算约束，避免超大输入绕过轮转上限。
        if len((value + "\n").encode("utf-8")) > max_bytes:
            record = {key: record[key] for key in ("task_id", "event", "elapsed_ms")}
            record["truncated"] = True
            value = json.dumps(record, separators=(",", ":"))
        _handler.handle(logging.LogRecord(__name__, logging.DEBUG, __file__, 0, value, (), None))


class _Audit:
    def __init__(self, model, messages):
        self.identifier = current_task_id() or f"llm-{uuid4().hex}"
        self.started = time.monotonic()
        self.model = model
        self.options = None
        self.messages = []
        self.content = self.reasoning = ""
        self.truncated = False
        self.secrets = ()
        self.budget = self.reserve = 0
        try:
            if settings.LOG_LLM_DEBUG_ENABLED:
                self.options = (settings.LOG_LLM_DEBUG_PATH, settings.LOG_LLM_DEBUG_MAX_BYTES,
                                settings.LOG_LLM_DEBUG_BACKUP_COUNT)
                self.secrets = tuple(sorted({getattr(settings, key, "") for key in (
                    "CHAT_API_KEY", "EMBEDDING_API_KEY", "MIMO_API_KEY", "ACCESS_API_KEY")
                    if getattr(settings, key, "")}, key=len, reverse=True))
                self.budget = min(settings.LOG_LLM_DEBUG_EXCERPT_BYTES, (self.options[1] - 1024) // 20)
                self.reserve = max((len(value.encode("utf-8")) for value in self.secrets), default=0)
                remaining = self.budget
                for message in messages:
                    if remaining <= 0:
                        self.truncated = True
                        break
                    role = self._clean(str(message.get("role", "")), 24)
                    content = message.get("content", "")
                    content = content if isinstance(content, str) else "[non-text content omitted]"
                    excerpt = self._clean(content, max(0, remaining - 32))
                    self.messages.append({"role": role, "content": excerpt})
                    remaining -= len(excerpt.encode("utf-8")) + 32
        except Exception as exc:
            self.options = None
            self._failure(exc)

    def _clean(self, value, limit):
        for secret in self.secrets:
            value = value.replace(secret, "[REDACTED]")
        data = value.encode("utf-8")
        self.truncated |= len(data) > limit
        return data[:limit].decode("utf-8", errors="ignore")

    def capture(self, content="", reasoning=""):
        if self.options is None:
            return
        try:
            # 多留一个凭据长度，保证跨 chunk 或截断边界处仍可完整脱敏。
            limit = self.budget + self.reserve
            self.content = self._append(self.content, content, limit)
            self.reasoning = self._append(self.reasoning, reasoning, limit)
        except Exception as exc:
            self.options = None
            self._failure(exc)

    def capture_chunk(self, chunk):
        if self.options is None:
            return
        try:
            if getattr(chunk, "choices", None):
                delta = chunk.choices[0].delta
                self.capture(getattr(delta, "content", ""), getattr(delta, "reasoning_content", ""))
        except Exception as exc:
            self.options = None
            self._failure(exc)

    def _append(self, previous, value, limit):
        if not isinstance(value, str):
            return previous
        data = (previous + value).encode("utf-8")
        self.truncated |= len(data) > limit
        return data[:limit].decode("utf-8", errors="ignore")

    def _failure(self, exc):
        log_event(logger, logging.WARNING, "llm_debug_log_failed", task_id=self.identifier,
                  error_type=type(exc).__name__)

    def finish(self, event, error_type=None):
        elapsed = round((time.monotonic() - self.started) * 1000)
        log_event(logger, logging.WARNING if error_type else logging.INFO, event,
                  task_id=self.identifier, elapsed_ms=elapsed, error_type=error_type or "none")
        if self.options is None:
            return
        try:
            record = {"task_id": self.identifier, "event": event, "elapsed_ms": elapsed,
                      "model": self._clean(str(self.model), 128), "messages": self.messages,
                      "content": self._clean(self.content, self.budget),
                      "reasoning": self._clean(self.reasoning, self.budget),
                      "error_type": error_type, "truncated": self.truncated}
            _write_record(record, self.options)
        except Exception as exc:
            self._failure(exc)

    async def finish_async(self, event, error_type=None):
        await _wait_for_log_io(self.finish, event, error_type)


def log_llm_completion(model_name, messages, completion, elapsed=None):
    """记录已解析响应；日志错误不影响调用方的响应对象。"""
    audit = _Audit(model_name, messages)
    try:
        if isinstance(elapsed, (int, float)) and 0 <= elapsed < float("inf"):
            audit.started -= elapsed
        message = completion.choices[0].message
        audit.capture(getattr(message, "content", ""), getattr(message, "reasoning_content", ""))
        audit.finish("llm_completed")
    except Exception as exc:
        audit._failure(exc)


async def log_llm_completion_async(model_name, messages, completion, elapsed=None):
    """异步聊天不在事件循环执行日志处理或文件锁等待。"""
    await _wait_for_log_io(log_llm_completion, model_name, messages, completion, elapsed)


def log_llm_non_stream(model_name, messages, response_raw, elapsed):
    """保留旧原始响应调用入口，不记录 HTTP 头或异常正文。"""
    try:
        log_llm_completion(model_name, messages, response_raw.parse(), elapsed)
    except Exception as exc:
        log_event(logger, logging.WARNING, "llm_debug_log_failed", error_type=type(exc).__name__)


def log_llm_stream_wrapper(stream, model_name, messages):
    audit = _Audit(model_name, messages)
    try:
        for chunk in stream:
            audit.capture_chunk(chunk)
            yield chunk
    except GeneratorExit:
        audit.finish("llm_cancelled")
        raise
    except Exception as exc:
        audit.finish("llm_failed", type(exc).__name__)
        raise
    else:
        audit.finish("llm_completed")


def log_llm_stream_wrapper_async(stream, model_name, messages):
    # 生成器开始迭代时，聊天入口的上下文可能已经退出，须在构造时冻结编号。
    audit = _Audit(model_name, messages)

    async def iterate():
        try:
            async for chunk in stream:
                audit.capture_chunk(chunk)
                yield chunk
        except (asyncio.CancelledError, GeneratorExit):
            await audit.finish_async("llm_cancelled")
            raise
        except Exception as exc:
            await audit.finish_async("llm_failed", type(exc).__name__)
            raise
        else:
            await audit.finish_async("llm_completed")

    return iterate()
