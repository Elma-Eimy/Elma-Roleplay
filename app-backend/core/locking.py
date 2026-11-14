"""
会话级并发锁管理

使用 asyncio.Lock 替代 threading.Lock，以正确配合 FastAPI 的异步运行时：
  - threading.Lock 需要占用线程池线程坐等锁，浪费资源
  - asyncio.Lock 直接在事件循环层挂起协程，零线程开销

用法：
  lock = get_session_lock(session_id)
  try:
      await asyncio.wait_for(lock.acquire(), timeout=30.0)
  except asyncio.TimeoutError:
      raise HTTPException(429, ...)
  try:
      ...
  finally:
      lock.release()

会话删除时调用 cleanup_session_lock(session_id) 防止内存泄漏。
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Dict

_session_locks: Dict[int, asyncio.Lock] = {}


class GroupRuntimeOwner:
    """由应用生命周期持有的数据库进程运行权。"""
    def __init__(self, db_engine):
        self.engine = db_engine
        self.active = True
        self.accepting = True
        self.tasks = set()
        self.executions = {}


class _GroupExecution:
    def __init__(self, owner, session_id, lock, task):
        self.owner, self.session_id, self.lock, self.task = owner, session_id, lock, task
        self.active = True


def require_group_execution(execution, session_id, db_engine):
    if not isinstance(execution, _GroupExecution) or not execution.active:
        raise RuntimeError("群聊步骤缺少有效执行权")
    require_group_runtime(execution.owner, db_engine)
    if (execution.session_id != session_id or execution.task is not asyncio.current_task()
            or execution.owner.executions.get(execution.task) is not execution or not execution.lock.locked()
            or get_session_lock(session_id) is not execution.lock):
        raise RuntimeError("群聊步骤不能借用其他任务或会话的执行权")


@asynccontextmanager
async def group_execution(session_id, db_engine, owner):
    from services.conversation.session_access import SessionKindConflict
    require_group_runtime(owner, db_engine)
    if not owner.accepting:
        raise SessionKindConflict("应用正在关闭，不能启动群聊")
    task = asyncio.current_task()
    if task in owner.executions:
        raise SessionKindConflict("当前任务已持有群聊执行权")
    lock = get_session_lock(session_id)
    if lock.locked():
        raise SessionKindConflict("群聊正在处理")
    await lock.acquire()
    execution = _GroupExecution(owner, session_id, lock, task)
    owner.tasks.add(task)
    owner.executions[task] = execution
    try:
        yield execution
    finally:
        execution.active = False
        owner.tasks.discard(task)
        owner.executions.pop(task, None)
        lock.release()


async def stop_group_executions(owner):
    """停止接收并等待已登记任务；调用方须在此后才释放文件运行权。"""
    owner.accepting = False
    tasks = tuple(task for task in owner.tasks if task is not asyncio.current_task())
    for task in tasks:
        task.cancel()
    if tasks:
        pending = asyncio.gather(*tasks, return_exceptions=True)
        cancelled = False
        while True:
            try:
                await asyncio.shield(pending)
                break
            except asyncio.CancelledError:
                if pending.cancelled():
                    raise
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError


def require_group_runtime(owner, db_engine):
    if not isinstance(owner, GroupRuntimeOwner) or not owner.active or owner.engine is not db_engine:
        raise RuntimeError("群聊生成必须持有对应数据库的运行权")


def get_session_lock(session_id: int) -> asyncio.Lock:
    """获取指定会话的异步锁，不存在时自动创建。"""
    if session_id not in _session_locks:
        _session_locks[session_id] = asyncio.Lock()
    return _session_locks[session_id]


def cleanup_session_lock(session_id: int) -> None:
    """
    会话删除时清理对应的锁，防止内存随会话数量增长而缓慢泄漏。
    应在 safe_delete_session / delete_character 完成后调用。
    """
    _session_locks.pop(session_id, None)


def is_session_locked(session_id: int) -> bool:
    """检查指定会话当前是否正在持有锁（如正在进行流式生成）。"""
    lock = _session_locks.get(session_id)
    return lock.locked() if lock else False
