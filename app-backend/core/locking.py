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
from typing import Dict

_session_locks: Dict[int, asyncio.Lock] = {}


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
