"""登记单聊回合维护任务，在应用释放数据库运行权前等待线程收尾。"""

import asyncio
import logging

from services.conversation import chat_turn_service


logger = logging.getLogger(__name__)
_runtime = None


class ChatMaintenanceRuntime:
    def __init__(self):
        self.accepting = True
        self.tasks = set()

    async def _run(self, session_id, persona_id):
        work = asyncio.create_task(asyncio.to_thread(
            chat_turn_service.run_post_turn_maintenance, session_id, persona_id,
        ))
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
            logger.warning("chat_maintenance_failed session_id=%s persona_id=%s error_type=%s",
                           session_id, persona_id, type(exc).__name__)
        if cancelled:
            raise asyncio.CancelledError

    async def stop(self):
        self.accepting = False
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        if not tasks:
            return
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


def start_chat_maintenance():
    global _runtime
    if _runtime is not None and (_runtime.accepting or _runtime.tasks):
        raise RuntimeError("单聊维护任务仍由其他应用生命周期持有")
    _runtime = ChatMaintenanceRuntime()
    return _runtime


def schedule_post_turn_maintenance(session_id, persona_id):
    runtime = _runtime
    if runtime is None or not runtime.accepting:
        return None
    task = asyncio.create_task(runtime._run(session_id, persona_id),
                               name=f"chat-maintenance-{session_id}-{persona_id}")
    runtime.tasks.add(task)
    task.add_done_callback(runtime.tasks.discard)
    return task
