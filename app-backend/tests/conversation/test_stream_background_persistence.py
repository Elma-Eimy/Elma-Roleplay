"""流式请求在客户端断开时后台持久化与锁状态的离线回归测试。"""

import asyncio
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from core.database import SessionLocal
from core.locking import get_session_lock, is_session_locked
from core.models import Character, ChatMessage, MessageRole, Session as SessionModel, SessionPersona
from routers import chat as chat_router
from routers import sessions as sessions_router
from schemas import ChatRequest
import services.conversation.chat_turn_service as chat_turn_service


class StreamBackgroundPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        character = Character(
            name="测试伴侣",
            description="流式持久化测试设定",
            personality="温和",
            first_mes="你好呀",
        )
        session = SessionModel(title="流式断连测试会话")
        self.db.add_all([character, session])
        self.db.flush()

        persona = SessionPersona(
            session_id=session.id,
            character_id=character.id,
            affection_score=10,
            current_mood="平静",
        )
        self.db.add(persona)
        self.db.commit()

        self.session_id = session.id
        self.persona_id = persona.id
        self.character_id = character.id

    def tearDown(self):
        # 确保锁释放与数据清理
        lock = get_session_lock(self.session_id)
        if lock.locked():
            lock.release()
        self.db.close()

    def _make_mock_chunk(self, content=None, reasoning=None):
        delta = SimpleNamespace(content=content, reasoning_content=reasoning)
        choice = SimpleNamespace(delta=delta)
        return SimpleNamespace(choices=[choice])

    def test_stream_worker_persists_turn_and_releases_lock(self):
        """Worker 在消费完 stream 后，必须原子落库 AI 消息并释放会话锁。"""
        lock = get_session_lock(self.session_id)
        # 获取锁模拟由 chat_stream 外层取得锁
        asyncio.run(lock.acquire())
        self.assertTrue(is_session_locked(self.session_id))

        turn = chat_turn_service.prepare_chat_turn(
            session_id=self.session_id,
            user_message="测试用户发送",
            is_regenerate=False,
            db=self.db,
        )
        user_message_id = turn.user_message.id

        async def mock_stream():
            yield self._make_mock_chunk(reasoning="思考中...")
            yield self._make_mock_chunk(content="<reply>你好呀，这是后台完")
            yield self._make_mock_chunk(content='整生成的回复！</reply><status emotion="开心" affection_change="2"/>')

        queue = asyncio.Queue()

        async def run_test():
            await chat_router._run_stream_worker(
                turn=turn,
                stream=mock_stream(),
                model="test-model",
                queue=queue,
                lock=lock,
                session_id=self.session_id,
                persona_id=self.persona_id,
                user_message_id=user_message_id,
                old_reply_id=None,
                is_regenerate=False,
            )

        asyncio.run(run_test())

        # 验证会话锁已被 Worker 释放
        self.assertFalse(is_session_locked(self.session_id))

        # 验证数据库中落库完整性
        with SessionLocal() as verify_db:
            user_msg = verify_db.get(ChatMessage, user_message_id)
            self.assertIsNotNone(user_msg)
            self.assertEqual("测试用户发送", user_msg.content)

            ai_msg = (
                verify_db.query(ChatMessage)
                .filter(
                    ChatMessage.session_id == self.session_id,
                    ChatMessage.role == MessageRole.assistant,
                    ChatMessage.parent_id == user_message_id,
                )
                .first()
            )
            self.assertIsNotNone(ai_msg)
            self.assertEqual("你好呀，这是后台完整生成的回复！", ai_msg.content)
            self.assertEqual("开心", ai_msg.emotion_tag)
            self.assertEqual(2, ai_msg.affection_change)

            persona = verify_db.get(SessionPersona, self.persona_id)
            self.assertEqual(12, persona.affection_score)
            self.assertEqual("开心", persona.current_mood)

    def test_client_disconnect_cancellation_does_not_abort_turn(self):
        """当客户端断开连接（event_generator 抛出 CancelledError）时，Worker 必须继续落库。"""
        lock = get_session_lock(self.session_id)

        turn = chat_turn_service.prepare_chat_turn(
            session_id=self.session_id,
            user_message="断开连接消息",
            is_regenerate=False,
            db=self.db,
        )
        user_message_id = turn.user_message.id

        # 慢速流：模拟大模型生成需要一点时间
        async def slow_mock_stream():
            yield self._make_mock_chunk(content="<reply>正在回答")
            await asyncio.sleep(0.05)
            yield self._make_mock_chunk(content="前半部分")
            await asyncio.sleep(0.05)
            yield self._make_mock_chunk(content='与后半部分完整内容</reply><status emotion="温柔" affection_change="1"/>')

        async def run_scenario():
            await lock.acquire()
            queue = asyncio.Queue()

            worker_task = asyncio.create_task(
                chat_router._run_stream_worker(
                    turn=turn,
                    stream=slow_mock_stream(),
                    model="test-model",
                    queue=queue,
                    lock=lock,
                    session_id=self.session_id,
                    persona_id=self.persona_id,
                    user_message_id=user_message_id,
                    old_reply_id=None,
                    is_regenerate=False,
                )
            )

            # 模拟消费端在读取第一个 chunk 后被 ASGI 取消
            async def event_generator():
                try:
                    while True:
                        event = await queue.get()
                        if event is None:
                            break
                        # 模拟读取一个事件后发生客户端中断
                        raise asyncio.CancelledError()
                except asyncio.CancelledError:
                    pass

            # 运行 consumer，触发 CancelledError
            await event_generator()

            # 等待 worker_task 在后台自然运行完成
            await worker_task

        asyncio.run(run_scenario())

        # 验证即使连接中途断开，锁正常释放，回复成功入库，用户消息未被清理
        self.assertFalse(is_session_locked(self.session_id))

        with SessionLocal() as verify_db:
            user_msg = verify_db.get(ChatMessage, user_message_id)
            self.assertIsNotNone(user_msg, "用户消息绝不能被删除回滚")

            ai_msg = (
                verify_db.query(ChatMessage)
                .filter(
                    ChatMessage.session_id == self.session_id,
                    ChatMessage.role == MessageRole.assistant,
                    ChatMessage.parent_id == user_message_id,
                )
                .first()
            )
            self.assertIsNotNone(ai_msg, "AI 助手回复必须在后台持久化成功")
            self.assertEqual("正在回答前半部分与后半部分完整内容", ai_msg.content)
            self.assertEqual("温柔", ai_msg.emotion_tag)

    def test_stream_worker_aborts_turn_on_real_model_error(self):
        """当模型调用真正发生非断开的内部异常时，必须正确执行 abort 并删除用户消息。"""
        lock = get_session_lock(self.session_id)
        asyncio.run(lock.acquire())

        turn = chat_turn_service.prepare_chat_turn(
            session_id=self.session_id,
            user_message="将要失败的消息",
            is_regenerate=False,
            db=self.db,
        )
        user_message_id = turn.user_message.id

        async def failing_stream():
            yield self._make_mock_chunk(content="一部分内容")
            raise RuntimeError("大模型上游 500 服务异常")

        queue = asyncio.Queue()

        async def run_test():
            await chat_router._run_stream_worker(
                turn=turn,
                stream=failing_stream(),
                model="test-model",
                queue=queue,
                lock=lock,
                session_id=self.session_id,
                persona_id=self.persona_id,
                user_message_id=user_message_id,
                old_reply_id=None,
                is_regenerate=False,
            )

        asyncio.run(run_test())

        # 验证锁已释放
        self.assertFalse(is_session_locked(self.session_id))

        # 验证错误时用户消息被回滚删除
        with SessionLocal() as verify_db:
            user_msg = verify_db.get(ChatMessage, user_message_id)
            self.assertIsNone(user_msg, "模型故障时，未完成的用户消息应被安全删除")

    def test_session_history_reports_is_generating(self):
        """验证 get_session_history 接口正确返回 is_generating 状态。"""
        lock = get_session_lock(self.session_id)

        # 1. 锁未被占用时
        res1 = sessions_router.get_session_history(session_id=self.session_id, db=self.db)
        self.assertFalse(res1.get("is_generating"))

        # 2. 占用锁（模拟正在生成）
        asyncio.run(lock.acquire())
        try:
            res2 = sessions_router.get_session_history(session_id=self.session_id, db=self.db)
            self.assertTrue(res2.get("is_generating"))
        finally:
            lock.release()

        # 3. 释放锁后恢复 False
        res3 = sessions_router.get_session_history(session_id=self.session_id, db=self.db)
        self.assertFalse(res3.get("is_generating"))

    def test_stream_worker_cancels_and_aborts_on_cancelled_error(self):
        """当 Worker 任务由于服务关闭或外界取消时，必须执行 abort 清理掉已写入的用户消息。"""
        lock = get_session_lock(self.session_id)
        asyncio.run(lock.acquire())

        turn = chat_turn_service.prepare_chat_turn(
            session_id=self.session_id,
            user_message="被取消任务的消息",
            is_regenerate=False,
            db=self.db,
        )
        user_message_id = turn.user_message.id

        # 挂起流以确保能被 cancel
        async def hang_stream():
            yield self._make_mock_chunk(content="刚刚开始")
            await asyncio.sleep(10)
            yield self._make_mock_chunk(content="永远到不了的结束")

        async def run_scenario():
            queue = asyncio.Queue()
            task = asyncio.create_task(
                chat_router._run_stream_worker(
                    turn=turn,
                    stream=hang_stream(),
                    model="test-model",
                    queue=queue,
                    lock=lock,
                    session_id=self.session_id,
                    persona_id=self.persona_id,
                    user_message_id=user_message_id,
                    old_reply_id=None,
                    is_regenerate=False,
                )
            )
            # 等待 Worker 运行并消费第一个 chunk
            await asyncio.sleep(0.05)
            # 取消任务
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run_scenario())

        # 验证锁已释放
        self.assertFalse(is_session_locked(self.session_id))

        # 验证用户消息已被回滚清理
        with SessionLocal() as verify_db:
            user_msg = verify_db.get(ChatMessage, user_message_id)
            self.assertIsNone(user_msg, "Worker 被取消时，未完成的用户消息必须被 abort 清理")

    def test_cancel_all_stream_tasks_integration(self):
        """验证 cancel_all_stream_tasks 能够取消所有活跃的 worker 并完成清理。"""
        lock = get_session_lock(self.session_id)
        asyncio.run(lock.acquire())

        turn = chat_turn_service.prepare_chat_turn(
            session_id=self.session_id,
            user_message="应用关闭时正在运行的消息",
            is_regenerate=False,
            db=self.db,
        )
        user_message_id = turn.user_message.id

        async def slow_stream():
            yield self._make_mock_chunk(content="一部分")
            await asyncio.sleep(10)

        async def run_scenario():
            queue = asyncio.Queue()
            task = asyncio.create_task(
                chat_router._run_stream_worker(
                    turn=turn,
                    stream=slow_stream(),
                    model="test-model",
                    queue=queue,
                    lock=lock,
                    session_id=self.session_id,
                    persona_id=self.persona_id,
                    user_message_id=user_message_id,
                    old_reply_id=None,
                    is_regenerate=False,
                )
            )
            chat_router._background_stream_tasks.add(task)
            task.add_done_callback(chat_router._background_stream_tasks.discard)

            await asyncio.sleep(0.05)
            # 执行全局取消
            await chat_router.cancel_all_stream_tasks(timeout=2.0)

        asyncio.run(run_scenario())

        self.assertFalse(is_session_locked(self.session_id))
        with SessionLocal() as verify_db:
            user_msg = verify_db.get(ChatMessage, user_message_id)
            self.assertIsNone(user_msg)


    def test_cancellation_waits_for_persistence_without_aborting_committed_turn(self):
        turn = chat_turn_service.prepare_chat_turn(
            session_id=self.session_id, user_message="保存时取消", db=self.db,
        )
        user_id = turn.user_message.id
        started = threading.Event()
        release = threading.Event()
        original_save = chat_router.session_service.save_chat_response

        def slow_save(**kwargs):
            started.set()
            if not release.wait(3):
                raise RuntimeError("test did not release save")
            return original_save(**kwargs)

        async def stream():
            yield self._make_mock_chunk(content='<reply>已保存</reply><status emotion="开心" affection_change="2"/>')

        async def scenario():
            lock = get_session_lock(self.session_id)
            await lock.acquire()
            with patch.object(chat_router.session_service, "save_chat_response", side_effect=slow_save), patch.object(
                chat_turn_service, "abort_chat_turn", wraps=chat_turn_service.abort_chat_turn
            ) as abort:
                task = asyncio.create_task(chat_router._run_stream_worker(
                    turn, stream(), "test", asyncio.Queue(), lock,
                    self.session_id, self.persona_id, user_id, None, False,
                ))
                try:
                    for _ in range(1000):
                        if started.is_set():
                            break
                        await asyncio.sleep(0.001)
                    self.assertTrue(started.is_set())
                    task.cancel()
                    await asyncio.sleep(0)
                    task.cancel()  # 超时或二次关闭也不能打断写库等待。
                    await asyncio.sleep(0)
                    self.assertTrue(lock.locked())
                    self.assertFalse(task.done())
                    abort.assert_not_called()
                finally:
                    release.set()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                abort.assert_not_called()
                self.assertFalse(lock.locked())

        asyncio.run(scenario())
        with SessionLocal() as db:
            self.assertIsNotNone(db.get(ChatMessage, user_id))
            self.assertEqual(1, db.query(ChatMessage).filter_by(parent_id=user_id).count())
            self.assertEqual(12, db.get(SessionPersona, self.persona_id).affection_score)

    def test_history_remains_pending_when_worker_finishes_during_history_query(self):
        turn = chat_turn_service.prepare_chat_turn(
            session_id=self.session_id, user_message="查询期间完成", db=self.db,
        )
        user_id = turn.user_message.id
        lock = get_session_lock(self.session_id)
        asyncio.run(lock.acquire())

        def finish_during_query(*args, **kwargs):
            with SessionLocal() as db:
                chat_router.session_service.save_chat_response(
                    self.session_id, self.persona_id, user_id, "完成的回复", "", "开心", 1, False, None, db,
                )
            lock.release()
            return {}

        with patch.object(sessions_router.session_service, "get_candidates_by_parent", side_effect=finish_during_query):
            result = sessions_router.get_session_history(self.session_id, db=self.db)
        self.assertTrue(result["is_generating"])
        self.assertEqual("user", result["messages"][-1]["role"])
        self.db.rollback()
        result = sessions_router.get_session_history(self.session_id, db=self.db)
        self.assertFalse(result["is_generating"])
        self.assertEqual("完成的回复", result["messages"][-1]["content"])


if __name__ == "__main__":
    unittest.main()
