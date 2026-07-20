import os
import json
import asyncio
import traceback
from datetime import datetime, timedelta
from sqlalchemy import and_, or_
from core.database import SessionLocal
from core.models import OutboxJob, OutboxJobStatus
from core.config import settings

# 控制后台任务执行的标志
is_worker_running = True
PROCESSING_LEASE_SECONDS = 300
MAX_BACKOFF_SECONDS = 3600

async def run_outbox_worker():
    global is_worker_running
    print("[OUTBOX WORKER] Starting background worker loop...")
    while is_worker_running:
        try:
            await process_pending_jobs()
        except Exception as e:
            print(f"[OUTBOX WORKER ERROR] Exception in loop: {e}")
            traceback.print_exc()
        await asyncio.sleep(5.0)  # 每 5 秒检查一次

async def process_pending_jobs():
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
            if job.status == OutboxJobStatus.processing:
                job.last_error = "Processing lease expired; retrying idempotently"

            # 标记为正在处理中，并启动/更新其租期。
            job.status = OutboxJobStatus.processing
            job.run_after = datetime.now() + timedelta(seconds=PROCESSING_LEASE_SECONDS)
            db.commit()
            job_id = job.id
            task_type = job.task_type
            payload = job.payload

            try:
                # 在线程执行器（thread executor）中处理任务，以避免阻塞事件循环
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, execute_task, task_type, payload)

                # 成功时：
                # 物理删除该任务，以保持发件箱（outbox）表干净且体积小
                db.delete(job)
                db.commit()
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
                    print(f"[OUTBOX WORKER ERROR] Job #{job.id} ({job.task_type}) exhausted a retry burst; cooling down until {job.run_after}.")
                else:
                    job.status = OutboxJobStatus.failed
                    # 指数退避：在 15 * (2 ** attempts) 秒后重试
                    backoff_seconds = min(
                        MAX_BACKOFF_SECONDS,
                        15 * (2 ** job.attempts),
                    )
                    job.run_after = datetime.now() + timedelta(seconds=backoff_seconds)
                    print(f"[OUTBOX WORKER] Job #{job.id} failed. Attempt {job.attempts}/{job.max_attempts}. Will retry after {job.run_after}")
                
                db.commit()
    finally:
        db.close()

def execute_job(job: OutboxJob):
    """用于诊断和旧调用者的向后兼容外观（facade）。"""
    execute_task(job.task_type, job.payload)


def execute_task(task_type: str, payload: str):
    if task_type == "upsert_vector":
        handle_upsert_vector(payload)
    elif task_type == "delete_vector":
        handle_delete_vector(payload)
    elif task_type == "delete_vector_collection":
        handle_delete_vector_collection(payload)
    elif task_type == "delete_audio":
        handle_delete_audio(payload)
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
        print(f"[OUTBOX] ChromaDB upserted vector id={chunk.chroma_doc_id} for memory_id={memory_id}")
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
        print(f"[OUTBOX] ChromaDB deleted vector ids={doc_ids} for character_id={character_id}")


def handle_delete_vector_collection(payload_str: str):
    """幂等删除已被删除角色所拥有的所有向量。"""
    from chromadb.errors import NotFoundError
    from services.infrastructure.clients import chroma_client

    payload = json.loads(payload_str)
    character_id = payload.get("character_id")
    if not character_id:
        raise ValueError("Invalid delete_vector_collection payload")

    collection_name = f"character_{character_id}"
    try:
        chroma_client.delete_collection(collection_name)
        print(f"[OUTBOX] Deleted ChromaDB collection: {collection_name}")
    except NotFoundError:
        # 成功删除后的重试，或者从未拥有过记忆的角色，目前已经处于所需的最终状态。
        print(f"[OUTBOX] ChromaDB collection already absent: {collection_name}")

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
                print(f"[OUTBOX] Deleted physical audio file: {actual_path}")
            except Exception as e:
                print(f"[OUTBOX ERROR] Failed to delete file {actual_path}: {e}")
                raise e
        else:
            print(f"[OUTBOX] Audio file not found for deletion: {actual_path} (skipped)")
