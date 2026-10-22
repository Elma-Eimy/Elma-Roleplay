from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Request
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile as FormUploadFile
from typing import Optional
from sqlalchemy.orm import Session
from core.database import get_db
from core import models
from services.media.character_card_import import import_character_card
import services.character_service as character_service
import services.media.character_portraits as portrait_service
import services.media.charx_import as charx_service
import services.memory.session_memory_query_service as session_memory_query_service
from core.locking import cleanup_session_lock
from schemas import CharacterCreate, CharacterTranslationRequest, PortraitNameUpdate, CharxImportRequest
import services.character_translation_service as translation_service
import json
import os
import zipfile

router = APIRouter()

from core.config import settings

# 从配置动态加载路径与限制
UPLOAD_DIR = settings.STORAGE_UPLOAD_AVATAR_DIR
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 角色卡解析允许的文件类型
ALLOWED_CARD_EXTENSIONS = {".png", ".json"}
MAX_CARD_SIZE_BYTES = settings.SECURITY_MAX_CARD_SIZE_MB * 1024 * 1024


@router.post("/charx/preview")
async def preview_charx(request: Request):
    async with request.form(max_files=1, max_fields=0) as form:
        file = form.get("file")
        if not isinstance(file, FormUploadFile) or len(form) != 1:
            raise HTTPException(422, detail="须上传且仅上传一个 file 文件")
        if os.path.splitext(file.filename or "")[1].lower() not in (".charx", ".zip"):
            raise HTTPException(422, detail="请选择 CHARX 或结构符合 CHARX 的 ZIP")
        content = await file.read(charx_service.upload_limit() + 1)
        if len(content) > charx_service.upload_limit():
            raise HTTPException(413, detail=f"角色包不得超过 {charx_service.upload_limit() // 1024 // 1024} MB")
    try:
        return await run_in_threadpool(charx_service.preview_package, content)
    except charx_service.CharxConflict as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    except (ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@router.get("/charx/previews/{token}/images")
def get_charx_preview_images(token: str, offset: int = Query(0, ge=0), limit: int = Query(12, ge=1, le=12)):
    try:
        return charx_service.preview_images(token, offset, limit)
    except LookupError as exc:
        raise HTTPException(404, detail=str(exc)) from exc


@router.get("/charx/previews/{token}/status")
def get_charx_status(token: str, db: Session = Depends(get_db)):
    try:
        return charx_service.preview_status(token, db)
    except LookupError as exc:
        raise HTTPException(404, detail=str(exc)) from exc


@router.post("/charx/previews/{token}/cancel")
def cancel_charx_preview(token: str):
    try:
        return charx_service.cancel_preview(token)
    except LookupError as exc:
        raise HTTPException(404, detail=str(exc)) from exc


@router.post("/charx/previews/{token}/import")
def import_charx(token: str, request: CharxImportRequest, db: Session = Depends(get_db)):
    try:
        return charx_service.import_package(token, request.model_dump(), db)
    except charx_service.CharxConflict as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@router.get("/{character_id}/portraits")
def list_portraits(character_id: int, offset: int = Query(0, ge=0), limit: int = Query(24, ge=1, le=100), db: Session = Depends(get_db)):
    try:
        return portrait_service.list_portraits(character_id, db, offset, limit)
    except LookupError as exc:
        raise HTTPException(404, detail=str(exc)) from exc


@router.post("/{character_id}/portraits")
def add_portrait(character_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        content = file.file.read(MAX_CARD_SIZE_BYTES + 1)
        if len(content) > MAX_CARD_SIZE_BYTES:
            raise HTTPException(413, detail="图片超过大小限制")
        return portrait_service.add_portrait(character_id, content, file.filename, db)
    except LookupError as exc:
        raise HTTPException(404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@router.post("/{character_id}/portraits/{portrait_id}/delete")
def delete_portrait(character_id: int, portrait_id: int, db: Session = Depends(get_db)):
    try:
        return portrait_service.delete_portrait(character_id, portrait_id, db)
    except LookupError as exc:
        raise HTTPException(404, detail=str(exc)) from exc


@router.put("/{character_id}/portraits/{portrait_id}")
def rename_portrait(character_id: int, portrait_id: int, request: PortraitNameUpdate, db: Session = Depends(get_db)):
    try:
        return portrait_service.rename_portrait(character_id, portrait_id, request.name, db)
    except LookupError as exc:
        raise HTTPException(404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc

@router.post("/parse")
def parse_character(file: UploadFile = File(...)):
    """
    仅解析上传的角色卡文件（PNG 或 JSON），不存入数据库。
    返回解析出的角色属性和头像路径，供前端确认/编辑。
    """
    # 校验文件扩展名
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_CARD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型 '{ext}'。仅支持: {', '.join(ALLOWED_CARD_EXTENSIONS)}"
        )

    try:
        # 校验文件大小
        content = file.file.read(MAX_CARD_SIZE_BYTES + 1)
        if len(content) > MAX_CARD_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"文件过大，最大允许 {MAX_CARD_SIZE_BYTES // 1024 // 1024} MB。"
            )

        card_data = import_character_card(content, ext, UPLOAD_DIR)

        return {"message": "Character parsed successfully", "data": card_data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse character: {str(e)}")

@router.post("/translation-cache")
def get_translation_cache(request: CharacterTranslationRequest, db: Session = Depends(get_db)):
    """仅查询已保存的阅读译文，不调用模型。"""
    try:
        return {"translation": translation_service.cached_translation(request.card.model_dump(), db)}
    except translation_service.TranslationError as exc:
        raise HTTPException(400, detail=str(exc)) from exc


@router.post("/translate")
async def translate_character(request: CharacterTranslationRequest, db: Session = Depends(get_db)):
    """手动生成独立的中文阅读版本，支持尚未导入的角色卡。"""
    try:
        return {"translation": await translation_service.translate_card(request.card.model_dump(), db, request.force)}
    except translation_service.TranslationError as exc:
        raise HTTPException(502, detail=str(exc)) from exc


@router.post("/create")
def create_character(character_data: CharacterCreate, db: Session = Depends(get_db)):
    """接收结构化的角色数据，存入数据库。"""
    try:
        return character_service.create_character(character_data.dict(), db)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to create character: {str(e)}")

@router.get("")
def list_characters(
    limit: Optional[int] = Query(None, description="限制返回数量"),
    offset: Optional[int] = Query(None, description="偏移量"),
    db: Session = Depends(get_db)
):
    """获取所有可用角色的简要列表 (支持分页与大字段延迟拉取)"""
    query = db.query(
        models.Character.id,
        models.Character.name,
        models.Character.avatar_path,
        models.Character.description
    )
    if offset is not None:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
        
    characters = query.all()
    result = []
    for char in characters:
        result.append({
            "id": char.id,
            "name": char.name,
            "avatar_path": char.avatar_path,
            "description": (
                char.description[:100] + "..."
                if char.description and len(char.description) > 100
                else char.description
            ),
        })
    return {"characters": result}


@router.get("/{character_id}/memory-overview")
def get_character_memory_overview(
    character_id: int,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """获取角色的故事记忆导航、最后消息及分支级记忆统计。"""
    try:
        return session_memory_query_service.get_character_memory_overview(
            character_id=character_id,
            limit=limit,
            offset=offset,
            db=db,
        )
    except session_memory_query_service.MemoryQueryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{character_id}")
def get_character_detail(character_id: int, db: Session = Depends(get_db)):
    """获取单个角色的完整设定"""
    character = db.get(models.Character, character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # 解析 tags 和 extensions（处理 JSON 格式反序列化）
    tags_list = []
    if character.tags:
        try:
            tags_list = json.loads(character.tags)
        except Exception:
            tags_list = [t.strip() for t in character.tags.split(",") if t.strip()]

    extensions_dict = {}
    if character.extensions:
        try:
            extensions_dict = json.loads(character.extensions)
        except Exception:
            pass

    lorebooks_list = []
    if character.lorebooks:
        for lb in character.lorebooks:
            lorebooks_list.append({
                "id": lb.id,
                "name": lb.name
            })

    return {
        "id": character.id,
        "name": character.name,
        "avatar_path": character.avatar_path,
        "description": character.description,
        "personality": character.personality,
        "scenario": character.scenario,
        "first_mes": character.first_mes,
        "mes_example": character.mes_example,
        "creator_notes": character.creator_notes,
        "system_prompt_override": character.system_prompt_override,
        "post_history_instructions": character.post_history_instructions,
        "tags": tags_list,
        "extensions": extensions_dict,
        "lorebooks": lorebooks_list,
        "created_at": character.created_at.isoformat() if character.created_at else None,
    }

@router.put("/{character_id}")
def update_character(character_id: int, character_data: CharacterCreate, db: Session = Depends(get_db)):
    """更新已存在角色的设定属性"""
    try:
        return character_service.update_character(
            character_id, character_data.dict(), db
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.delete("/{character_id}")
@router.post("/{character_id}/delete")
def delete_character(character_id: int, db: Session = Depends(get_db)):
    """删除指定角色，并通过 Outbox 异步清理关联外部资源。"""
    try:
        result = character_service.delete_character_service(character_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    for session_id in result.pop("session_ids"):
        cleanup_session_lock(session_id)

    return {
        "message": "Character and all associated sessions/memories deleted successfully",
        **result,
    }
