from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
import os
import uuid
from sqlalchemy.orm import Session
from core.database import get_db
from core.config import settings
from schemas import SettingsUpdate, TTSRequest
from services.tts_service import TTSService

router = APIRouter()

UPLOAD_DIR = "./assets/avatars"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 头像上传允许的文件类型与大小限制
ALLOWED_AVATAR_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_AVATAR_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB

@router.get("/")
def read_root():
    return {"status": "Core Engine is running"}

@router.post("/upload/avatar")
def upload_avatar(file: UploadFile = File(...)):
    """通用头像上传接口"""
    # 校验文件扩展名
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_AVATAR_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型 '{ext}'。仅支持: {', '.join(ALLOWED_AVATAR_EXTENSIONS)}"
        )

    try:
        # 校验文件大小（读入内存后检查，避免写入超大文件）
        content = file.file.read()
        if len(content) > MAX_AVATAR_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"文件过大，最大允许 {MAX_AVATAR_SIZE_BYTES // 1024 // 1024} MB。"
            )

        filename = os.path.basename(file.filename or "avatar.png")
        if not filename:
            filename = "avatar.png"
        # 加 UUID 短码前缀，防止同名头像相互覆盖
        unique_filename = f"{uuid.uuid4().hex[:8]}_{filename}"
        file_path = os.path.join(UPLOAD_DIR, unique_filename)
        with open(file_path, "wb") as buffer:
            buffer.write(content)

        return {"message": "Avatar uploaded successfully", "avatar_path": file_path}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to upload avatar: {str(e)}")


@router.get("/utils/settings")
def get_settings():
    """获取当前允许由前端动态修改的对话与检索参数值。"""
    return {
        "temperature": settings.LLM_TEMPERATURE,
        "reasoning_mode": settings.LLM_REASONING_MODE,
        "context_history_limit": settings.APP_CONTEXT_HISTORY_LIMIT,
        "retrieval_top_k": settings.APP_RETRIEVAL_TOP_K,
        "retrieval_min_importance": settings.APP_RETRIEVAL_MIN_IMPORTANCE,
        "retrieval_max_distance": settings.APP_RETRIEVAL_MAX_DISTANCE,
        "lorebook_scan_depth": settings.APP_LOREBOOK_SCAN_DEPTH,
        "lorebook_token_budget": settings.APP_LOREBOOK_TOKEN_BUDGET,
        "lorebook_max_recursive_passes": settings.APP_LOREBOOK_MAX_RECURSIVE_PASSES,
        "cognition_max_words": settings.APP_COGNITION_MAX_WORDS,
        "retrieval_half_life_turns": settings.APP_RETRIEVAL_HALF_LIFE_TURNS,
        "retrieval_candidate_multiplier": settings.APP_RETRIEVAL_CANDIDATE_MULTIPLIER,
        "max_tokens": settings.LLM_MAX_TOKENS,
        "top_p": settings.LLM_TOP_P,
        "presence_penalty": settings.LLM_PRESENCE_PENALTY,
        "frequency_penalty": settings.LLM_FREQUENCY_PENALTY,
        "repetition_penalty": settings.LLM_REPETITION_PENALTY,
        "reasoning_effort": settings.LLM_REASONING_EFFORT
    }


@router.put("/utils/settings")
def update_settings(request: SettingsUpdate):
    """动态修改对话与检索配置（内存即时生效，并自动持久化写入 config.yaml）。"""
    updates = request.model_dump(exclude_unset=True)
    if not updates:
        return {"message": "No settings to update", "updated": {}}
    
    try:
        settings.update_and_persist(updates)
        return {
            "message": "Settings updated and persisted successfully",
            "updated": updates
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update settings: {str(e)}")


@router.post("/utils/tts")
async def text_to_speech(request: TTSRequest, db: Session = Depends(get_db)):
    """
    文字转语音合成接口（云端 MIMO-v2.5-tts API）
    """
    try:
        tts_service = TTSService.get_instance()
        audio_url = await tts_service.generate_speech_async(
            text=request.text,
            voice=request.voice,
            speed=request.speed or 1.0,
            message_id=request.message_id,
            db=db
        )
        return {"audio_url": audio_url}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"语音合成失败: {str(e)}")

