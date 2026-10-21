"""Authenticated audio downloads; recovery belongs to the media service."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from services.media.audio_service import resolve_audio_file

router = APIRouter()


@router.get("/audio/{filename}")
async def get_audio_file(filename: str):
    try:
        path = await resolve_audio_file(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Audio file not found") from exc
    return FileResponse(path)
