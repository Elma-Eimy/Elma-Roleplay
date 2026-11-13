"""后台拥有接受事务、独立 Session 与执行权；请求取消只停止等待回执。"""
import asyncio
import logging
from sqlalchemy.orm import Session
from core.locking import group_execution, require_group_runtime
from core.models import GroupRoundCandidate
from services.conversation import group_operation_service as operations, group_history_service as history
from services.conversation import group_generation_service as generation, group_checkpoint_service as checkpoints
from services.conversation.group_call_snapshot import capture_group_calls, restore_group_calls
from services.conversation.group_round_service import _execute_round, GroupRoundBudget
from services.conversation.group_execution_scope import bind_target
from services.conversation.session_access import group_session_operation, SessionKindConflict
from services.infrastructure.llm_provider import group_model_session

logger = logging.getLogger(__name__)


@group_session_operation
async def submit_group_operation(session_id, client_request_id, kind, expected_group_revision, db,
                                 *, runtime, call_model=None, **options):
    history._require_group(session_id, db)
    history._require_clean_transaction(db)
    engine = db.get_bind()
    require_group_runtime(runtime, engine)
    if kind not in ("send", "regenerate", "resume"):
        raise history.GroupSessionValidationError("后台入口只处理生成操作")
    request_id, request, fingerprint = operations._command(client_request_id, kind, expected_group_revision, **options)
    previous = operations._existing(session_id, request_id, fingerprint, db)
    if previous is not None:
        return previous
    if not runtime.accepting:
        raise SessionKindConflict("应用正在关闭")
    accepted = asyncio.get_running_loop().create_future()
    task = asyncio.create_task(_work(session_id, request_id, request, fingerprint, engine, runtime, accepted, call_model))
    # 创建与登记之间没有 await；关闭也能看到尚未取得执行权的任务。
    runtime.tasks.add(task)
    def completed(work):
        runtime.tasks.discard(work)
        if not accepted.done():
            accepted.set_result((False, SessionKindConflict("后台任务在接受前已停止")))
        if not work.cancelled():
            work.exception()
    task.add_done_callback(completed)
    ok, result = await asyncio.shield(accepted)
    if not ok:
        raise result
    return result


async def _work(session_id, request_id, request, fingerprint, engine, runtime, accepted, call_model):
    with Session(engine, autoflush=False) as db:
        async with group_execution(session_id, engine, runtime) as execution:
            scope = None
            target = None
            try:
                snapshot = None
                if request["kind"] != "resume":
                    snapshot = await generation._database(capture_group_calls, session_id, db,
                        model=request["model"], thinking_mode=request["thinking_mode"], reasoning_effort=request["reasoning_effort"])
                cancelled = False
                try:
                    receipt, created = await generation._database(operations._accept, session_id, request_id,
                                                                  request, fingerprint, snapshot, db, True)
                except generation._DatabaseCancelled as exc:
                    if not isinstance(exc.result, tuple):
                        raise
                    receipt, created = exc.result
                    cancelled = True
                if not created:
                    accepted.set_result((True, receipt))
                    return
                scope = bind_target(execution, receipt, db)
                target = dict(round_id=scope.round_id, candidate_id=scope.candidate_id,
                              revision=receipt["accepted"]["candidate_revision"])
                accepted.set_result((True, receipt))
                if cancelled:
                    raise asyncio.CancelledError
                progress = await generation._database(checkpoints.start, scope, target["revision"], db)
                if snapshot is None:
                    snapshot, _ = restore_group_calls(db.get(GroupRoundCandidate, scope.candidate_id), history._members(session_id, db))
                    db.rollback()
                budget = GroupRoundBudget(max(1, progress["remaining"]), 300, snapshot.call_timeout, director_ending=snapshot.director_ending)
                async def execute(invoke):
                    return await _execute_round(session_id, progress["user_content"], db, execution, snapshot, budget,
                        invoke, False, 2, target=target, scope=scope, progress=progress)
                if progress["remaining"] == 0 or call_model is not None:
                    return await execute(call_model)
                async with group_model_session(snapshot.connection, timeout=snapshot.call_timeout) as client:
                    async def invoke(stage, parameters):
                        return await client.chat.completions.create(**parameters)
                    return await execute(invoke)
            except BaseException as exc:
                if scope is not None:
                    try:
                        await generation._database(checkpoints.fail, scope, target["revision"],
                            "cancelled" if isinstance(exc, asyncio.CancelledError) else "execution_failed", db)
                    except BaseException as marker_error:
                        logger.warning("后台群聊收敛未完成 error_type=%s", type(marker_error).__name__)
                if not accepted.done():
                    accepted.set_result((False, exc))
                if isinstance(exc, asyncio.CancelledError):
                    raise
                logger.warning("后台群聊未完成 error_type=%s", type(exc).__name__)
