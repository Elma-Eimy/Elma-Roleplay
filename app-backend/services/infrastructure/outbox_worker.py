import os
import json
import asyncio
import logging
import threading
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy import and_, or_
from core.database import SessionLocal
from core.models import OutboxJob, OutboxJobStatus
from core.config import settings
from services.infrastructure.logging_context import log_event, task_context

# 控制后台任务执行的标志
is_worker_running = True
PROCESSING_LEASE_SECONDS = 300
MAX_BACKOFF_SECONDS = 3600
logger = logging.getLogger(__name__)

async def run_outbox_worker():
    global is_worker_running
    log_event(logger, logging.INFO, "outbox_worker_started")
    while is_worker_running:
        try:
            await process_pending_jobs()
        except Exception as e:
            log_event(logger, logging.ERROR, "outbox_poll_failed", error_type=type(e).__name__)
        await asyncio.sleep(5.0)  # 每 5 秒检查一次

async def process_pending_jobs():
    """在线程内完成一轮处理；取消后等待当前任务及数据库会话清理。"""
    stop_requested = threading.Event()
    work = asyncio.create_task(asyncio.to_thread(_process_pending_jobs, stop_requested))
    cancelled = False
    try:
        while True:
            try:
                await asyncio.shield(work)
                break
            except asyncio.CancelledError:
                if work.cancelled():
                    raise
                stop_requested.set()
                cancelled = True
    except Exception as exc:
        if not cancelled:
            raise
        log_event(logger, logging.WARNING, "outbox_shutdown_failed", error_type=type(exc).__name__)
    if cancelled:
        raise asyncio.CancelledError


def _process_pending_jobs(stop_requested):
    if stop_requested.is_set():
        return
    db = SessionLocal()
    try:
        now = datetime.now()
        # processing 使用 run_after 作为租约截止时间。进程若在外部写入后崩溃，
        # 租约到期后任务会再次执行；向量 upsert/delete 都是幂等的。
        jobs = db.query(OutboxJob).filter(
            or_(
                and_(
                    OutboxJob.status.in_([OutboxJobStatus.pending, OutboxJobStatus.failed]),
                    OutboxJob.attempts < OutboxJob.max_attempts,
                    OutboxJob.run_after <= now,
                ),
                and_(
                    OutboxJob.status == OutboxJobStatus.processing,
                    OutboxJob.run_after <= now,
                ),
            )
        ).order_by(OutboxJob.id.asc()).limit(10).all()

        if not jobs:
            return

        for job in jobs:
            if stop_requested.is_set():
                break
            with task_context(f"outbox-{job.id}"):
                if job.status == OutboxJobStatus.processing:
                    job.last_error = "Processing lease expired; retrying idempotently"

                # 标记为正在处理中，并启动/更新其租期。
                job.status = OutboxJobStatus.processing
                job.run_after = datetime.now() + timedelta(seconds=PROCESSING_LEASE_SECONDS)
                db.commit()
                job_id = job.id
                task_type = job.task_type
                payload = job.payload

                log_event(logger, logging.INFO, "outbox_job_started", job_id=job_id, task_type=task_type)
                try:
                    # Session 与外部执行留在同一个线程，取消不打断当前任务的持久结果。
                    execute_task(task_type, payload)

                    # 成功时：
                    # 物理删除该任务，以保持发件箱（outbox）表干净且体积小
                    db.delete(job)
                    db.commit()
                    log_event(logger, logging.INFO, "outbox_job_completed", job_id=job_id)
                except Exception as e:
                    db.rollback()
                    job = db.get(OutboxJob, job_id)
                    if job is None:
                        continue

                    # 失败时：
                    job.attempts += 1
                    job.last_error = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
                
                    if job.attempts >= job.max_attempts:
                        job.status = OutboxJobStatus.failed
                        # max_attempts 限制的是单次重试并发次数，而不是持久任务的生命周期。冷却并稍后启动另一次重试。
                        job.attempts = 0
                        job.run_after = datetime.now() + timedelta(seconds=MAX_BACKOFF_SECONDS)
                        log_event(logger, logging.ERROR, "outbox_job_cooling_down", job_id=job_id, error_type=type(e).__name__)
                    else:
                        job.status = OutboxJobStatus.failed
                        # 指数退避：在 15 * (2 ** attempts) 秒后重试
                        backoff_seconds = min(
                            MAX_BACKOFF_SECONDS,
                            15 * (2 ** job.attempts),
                        )
                        job.run_after = datetime.now() + timedelta(seconds=backoff_seconds)
                        log_event(logger, logging.WARNING, "outbox_job_deferred", job_id=job_id, attempts=job.attempts, error_type=type(e).__name__)
                
                    db.commit()
    finally:
        db.close()

def execute_job(job: OutboxJob):
    """用于诊断和旧调用者的向后兼容外观（facade）。"""
    execute_task(job.task_type, job.payload)


def execute_task(task_type: str, payload: str):
    if task_type == "sync_group_card":
        from services.memory.group_memory_index import sync_group_card
        sync_group_card(json.loads(payload)["id"], SessionLocal)
    elif task_type == "rebuild_group_index":
        from services.memory.group_memory_index import rebuild_group_index
        rebuild_group_index(SessionLocal)
    elif task_type == "upsert_vector":
        handle_upsert_vector(payload)
    elif task_type == "delete_vector":
        handle_delete_vector(payload)
    elif task_type == "delete_vector_collection":
        handle_delete_vector_collection(payload)
    elif task_type == "delete_audio":
        handle_delete_audio(payload)
    elif task_type == "delete_avatar":
        handle_delete_avatar(payload)
    else:
        raise ValueError(f"Unknown task type: {task_type}")


def handle_upsert_vector(payload_str: str):
    """从 SQLite 读取最新值，并按稳定文档 ID 幂等写入 ChromaDB。"""
    from core.models import MemoryChunk
    from services.memory.memory_manager import (
        _build_chroma_metadata,
        get_character_collection,
    )

    payload = json.loads(payload_str)
    memory_id = payload.get("memory_id")
    fallback_character_id = payload.get("character_id")
    fallback_doc_id = payload.get("chroma_doc_id")
    if not memory_id or not fallback_character_id or not fallback_doc_id:
        raise ValueError("Invalid upsert_vector payload")

    db = SessionLocal()
    try:
        chunk = db.get(MemoryChunk, memory_id)
        if chunk is None:
            # 该记忆可能会在任务排队后被删除。
            collection = get_character_collection(fallback_character_id)
            collection.delete(ids=[fallback_doc_id])
            return

        character_id = chunk.persona.character_id
        collection = get_character_collection(character_id)
        metadata = _build_chroma_metadata(
            persona_id=chunk.persona_id,
            memory_type=chunk.memory_type,
            importance_score=chunk.importance_score,
            origin_session_id=chunk.origin_session_id,
            created_at=chunk.created_at or datetime.now(),
            source_message_id=chunk.source_message_id,
            source_start_message_id=chunk.source_start_message_id,
        )
        collection.upsert(
            ids=[chunk.chroma_doc_id],
            documents=[chunk.content],
            metadatas=[metadata],
        )
        log_event(logger, logging.DEBUG, "outbox_vector_upserted", memory_id=memory_id)
    finally:
        db.close()

def handle_delete_vector(payload_str: str):
    # 在处理程序内部导入以避免循环依赖
    from services.memory.memory_manager import get_character_collection
    payload = json.loads(payload_str)
    character_id = payload.get("character_id")
    doc_ids = payload.get("doc_ids", [])
    if character_id and doc_ids:
        collection = get_character_collection(character_id)
        collection.delete(ids=doc_ids)
        log_event(logger, logging.DEBUG, "outbox_vectors_deleted", character_id=character_id, count=len(doc_ids))


def handle_delete_vector_collection(payload_str: str):
    """幂等删除已被删除角色所拥有的所有向量。"""
    from chromadb.errors import NotFoundError
    from services.infrastructure.clients import get_chroma_client

    payload = json.loads(payload_str)
    character_id = payload.get("character_id")
    if not character_id:
        raise ValueError("Invalid delete_vector_collection payload")

    collection_name = f"character_{character_id}"
    try:
        get_chroma_client().delete_collection(collection_name)
        log_event(logger, logging.DEBUG, "outbox_collection_deleted", character_id=character_id)
    except NotFoundError:
        # 成功删除后的重试，或者从未拥有过记忆的角色，目前已经处于所需的最终状态。
        log_event(logger, logging.DEBUG, "outbox_collection_absent", character_id=character_id)

def handle_delete_audio(payload_str: str):
    payload = json.loads(payload_str)
    file_paths = payload.get("file_paths", [])
    for fp in file_paths:
        if not fp:
            continue
        actual_path = fp
        if not os.path.isabs(actual_path) and not os.path.exists(actual_path):
            base_name = os.path.basename(fp)
            actual_path = os.path.join(settings.TTS_CACHE_DIR, base_name)
        
        if os.path.exists(actual_path):
            try:
                os.remove(actual_path)
                log_event(logger, logging.DEBUG, "outbox_audio_deleted")
            except Exception as e:
                log_event(logger, logging.WARNING, "outbox_audio_delete_failed", error_type=type(e).__name__)
                raise e
        else:
            log_event(logger, logging.DEBUG, "outbox_audio_absent")


def _resolve_managed_avatar_path(file_path: str):
    """Resolve an avatar path only when it stays inside the managed upload root."""
    if not isinstance(file_path, str) or not file_path.strip():
        return None

    managed_root = Path(settings.STORAGE_UPLOAD_AVATAR_DIR).resolve()
    candidate = Path(file_path)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
        if not candidate.exists() and Path(file_path).name == file_path:
            candidate = managed_root / file_path
    candidate = candidate.resolve()

    try:
        candidate.relative_to(managed_root)
    except ValueError:
        return None
    if candidate == managed_root:
        return None
    return candidate


def _avatar_is_still_referenced(target_path: Path) -> bool:
    """Avoid deleting a managed file that another character still references."""
    from core.models import Character, CharacterPortrait

    db = SessionLocal()
    try:
        paths = (
            db.query(Character.avatar_path)
            .filter(
                Character.avatar_path.isnot(None),
                Character.avatar_path != "",
            )
            .all()
        )
        paths += db.query(CharacterPortrait.image_path).all()
        for (avatar_path,) in paths:
            resolved = _resolve_managed_avatar_path(avatar_path)
            if resolved == target_path:
                return True
        return False
    finally:
        db.close()


def handle_delete_avatar(payload_str: str):
    """Idempotently delete an unreferenced avatar owned by this application."""
    payload = json.loads(payload_str)
    file_path = payload.get("file_path")
    target_path = _resolve_managed_avatar_path(file_path)
    if target_path is None:
        log_event(logger, logging.WARNING, "outbox_avatar_path_rejected")
        return

    if _avatar_is_still_referenced(target_path):
        log_event(logger, logging.DEBUG, "outbox_avatar_referenced")
        return

    if not target_path.exists():
        log_event(logger, logging.DEBUG, "outbox_avatar_absent")
        return
    if not target_path.is_file():
        raise ValueError(f"Avatar cleanup target is not a file: {target_path}")

    target_path.unlink()
    log_event(logger, logging.DEBUG, "outbox_avatar_deleted")
