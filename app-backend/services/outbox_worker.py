import os
import json
import asyncio
import traceback
from datetime import datetime, timedelta
from sqlalchemy import and_
from core.database import SessionLocal
from core.models import OutboxJob, OutboxJobStatus
from core.config import settings

# A flag to control the background task execution
is_worker_running = True

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
        # Query for jobs that are:
        # 1. status is 'pending' OR 'failed' (but attempts < max_attempts)
        # 2. run_after <= now
        jobs = db.query(OutboxJob).filter(
            and_(
                OutboxJob.status.in_([OutboxJobStatus.pending, OutboxJobStatus.failed]),
                OutboxJob.attempts < OutboxJob.max_attempts,
                OutboxJob.run_after <= now
            )
        ).order_by(OutboxJob.id.asc()).limit(10).all()

        if not jobs:
            return

        for job in jobs:
            # Mark as processing
            job.status = OutboxJobStatus.processing
            db.commit()

            try:
                # Process the task in a thread executor to avoid blocking the event loop
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, execute_job, job)

                # On success:
                # Physically delete the job to keep the outbox table clean and small
                db.delete(job)
                db.commit()
            except Exception as e:
                db.rollback()
                
                # On failure:
                job.attempts += 1
                job.last_error = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
                
                if job.attempts >= job.max_attempts:
                    job.status = OutboxJobStatus.failed
                    print(f"[OUTBOX WORKER ERROR] Job #{job.id} ({job.task_type}) failed permanently after {job.attempts} attempts.")
                else:
                    job.status = OutboxJobStatus.failed  # Revert back to failed state to retry later
                    # Exponential backoff: retry in 15 * (2 ** attempts) seconds
                    backoff_seconds = 15 * (2 ** job.attempts)
                    job.run_after = datetime.now() + timedelta(seconds=backoff_seconds)
                    print(f"[OUTBOX WORKER] Job #{job.id} failed. Attempt {job.attempts}/{job.max_attempts}. Will retry after {job.run_after}")
                
                db.commit()
    finally:
        db.close()

def execute_job(job: OutboxJob):
    if job.task_type == "delete_vector":
        handle_delete_vector(job.payload)
    elif job.task_type == "delete_audio":
        handle_delete_audio(job.payload)
    else:
        raise ValueError(f"Unknown task type: {job.task_type}")

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
