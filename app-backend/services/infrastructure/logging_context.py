"""为运行日志提供任务编号；只记录调用方明确选择的诊断字段。"""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import inspect
import logging
from uuid import uuid4


_task_id = ContextVar("diagnostic_task_id", default=None)


def current_task_id():
    return _task_id.get()


@contextmanager
def task_context(identifier):
    token = _task_id.set(identifier)
    try:
        yield identifier
    finally:
        _task_id.reset(token)


def log_event(logger, level, event, **fields):
    fields.setdefault("task_id", current_task_id() or "-")
    # 不配置宿主日志器；日志处理器故障也不能改变业务结果。
    try:
        logger.log(level, "%s %s", event, " ".join(f"{key}={value}" for key, value in fields.items()))
    except Exception:
        pass


def diagnostic_task(kind):
    """嵌套调用共用任务编号；保持公开函数签名供资源边界发现使用。"""
    def decorate(function):
        logger = logging.getLogger(function.__module__)
        signature = inspect.signature(function)

        @contextmanager
        def scope(args, kwargs):
            fields = {"operation": kind}
            arguments = signature.bind_partial(*args, **kwargs).arguments
            message_id = arguments.get("message_id")
            if isinstance(message_id, int):
                fields["message_id"] = message_id
            session_id = getattr(arguments.get("request"), "session_id", None)
            if isinstance(session_id, int):
                fields["session_id"] = session_id
            with task_context(current_task_id() or f"{kind}-{uuid4().hex}"):
                log_event(logger, logging.INFO, "task_started", **fields)
                try:
                    yield
                except Exception as exc:
                    log_event(logger, logging.WARNING, "task_failed", **fields, error_type=type(exc).__name__)
                    raise
                else:
                    log_event(logger, logging.INFO, "task_completed", **fields)

        if inspect.iscoroutinefunction(function):
            @wraps(function)
            async def asynchronous(*args, **kwargs):
                with scope(args, kwargs):
                    return await function(*args, **kwargs)
            return asynchronous

        @wraps(function)
        def synchronous(*args, **kwargs):
            with scope(args, kwargs):
                return function(*args, **kwargs)
        return synchronous
    return decorate
