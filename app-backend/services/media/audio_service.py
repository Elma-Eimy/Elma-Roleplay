"""Resolve cached audio and preserve the legacy recovery protocol."""

import os
import re

from core.config import settings
from core.database import SessionLocal
from services.tts_service import TTSService


async def resolve_audio_file(filename: str) -> str:
    filepath = os.path.join(settings.TTS_CACHE_DIR, filename)
    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
        return filepath

    # Preserve the current legacy format; p2 recovery is a separate behavior change.
    match = re.match(r"^msg_(\d+)_([^_]+)_([\d.]+)\.mp3$", filename)
    if match:
        message_id = int(match.group(1))
        voice = match.group(2)
        try:
            speed = float(match.group(3))
        except ValueError:
            speed = 1.0
        db = SessionLocal()
        try:
            await TTSService.get_instance().generate_speech_async(
                text="", voice=voice, speed=speed, message_id=message_id, db=db
            )
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                return filepath
        except Exception as exc:
            print(f"[ERROR] Delayed audio recovery failed: {exc}")
        finally:
            db.close()
    raise FileNotFoundError(filename)
