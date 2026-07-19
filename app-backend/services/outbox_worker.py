import os
import json
import asyncio
import traceback
from datetime import datetime, timedelta
from sqlalchemy import and_, or_
from core.database import SessionLocal
from core.models import OutboxJob, OutboxJobStatus
from core.config import settings

# A flag to control the background task execution
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
        await asyncio.sleep(5.0)  # Check every 5 seconds

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

            # Mark as processing and start/renew its lease.
            job.status = OutboxJobStatus.processing
            job.run_after = datetime.now() + timedelta(seconds=PROCESSING_LEASE_SECONDS)
            db.commit()
            job_id = job.id
            task_type = job.task_type
            payload = job.payload

            try:
                # Process the task in a thread executor to avoid blocking the event loop
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, execute_task, task_type, payload)

                # On success:
                # Physically delete the job to keep the outbox table clean and small
                db.delete(job)
                db.commit()
            except Exception as e:
                db.rollback()
                job = db.get(OutboxJob, job_id)
                if job is None:
                    continue

                # On failure:
                job.attempts += 1
                job.last_error = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
                
                if job.attempts >= job.max_attempts:
                    job.status = OutboxJobStatus.failed
                    # max_attempts limits one retry burst, not the lifetime of a
                    # persistent task. Cool down and start another burst later.
                    job.attempts = 0
                    job.run_after = datetime.now() + timedelta(seconds=MAX_BACKOFF_SECONDS)
                    print(f"[OUTBOX WORKER ERROR] Job #{job.id} ({job.task_type}) exhausted a retry burst; cooling down until {job.run_after}.")
                else:
                    job.status = OutboxJobStatus.failed
                    # Exponential backoff: retry in 15 * (2 ** attempts) seconds
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
    """Backward-compatible facade used by diagnostics and older callers."""
    execute_task(job.task_type, job.payload)


def execute_task(task_type: str, payload: str):
    if task_type == "upsert_vector":
        handle_upsert_vector(payload)
    elif task_type == "delete_vector":
        handle_delete_vector(payload)
    elif task_type == "delete_audio":
        handle_delete_audio(payload)
    else:
        raise ValueError(f"Unknown task type: {task_type}")


def handle_upsert_vector(payload_str: str):
    """从 SQLite 读取最新值，并按稳定文档 ID 幂等写入 ChromaDB。"""
    from core.models import MemoryChunk
    from services.memory_manager import (
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
            # The memory may have been deleted after this task was enqueued.
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
    # Import inside handler to avoid circular dependencies
    from services.memory_manager import get_character_collection
    payload = json.loads(payload_str)
    character_id = payload.get("character_id")
    doc_ids = payload.get("doc_ids", [])
    if character_id and doc_ids:
        collection = get_character_collection(character_id)
        collection.delete(ids=doc_ids)
        print(f"[OUTBOX] ChromaDB deleted vector ids={doc_ids} for character_id={character_id}")

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
