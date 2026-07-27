from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from typing import Optional
from sqlalchemy.orm import Session
from core.database import get_db
from core import models
from services.parse import parse_character_card
import services.character_service as character_service
from core.locking import cleanup_session_lock
from schemas import CharacterCreate
import json
import os
import shutil
import uuid

router = APIRouter()

from core.config import settings

# 从配置动态加载路径与限制
UPLOAD_DIR = settings.STORAGE_UPLOAD_AVATAR_DIR
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 角色卡解析允许的文件类型
ALLOWED_CARD_EXTENSIONS = {".png", ".json"}
MAX_CARD_SIZE_BYTES = settings.SECURITY_MAX_CARD_SIZE_MB * 1024 * 1024

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
        content = file.file.read()
        if len(content) > MAX_CARD_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"文件过大，最大允许 {MAX_CARD_SIZE_BYTES // 1024 // 1024} MB。"
            )

        filename = os.path.basename(file.filename or "card.png")
        if not filename:
            filename = "card.png"
        # 加 UUID 短码前缀，防止同名角色卡相互覆盖
        unique_filename = f"{uuid.uuid4().hex[:8]}_{filename}"
        file_path = os.path.join(UPLOAD_DIR, unique_filename)
        with open(file_path, "wb") as buffer:
            buffer.write(content)

        card_data = parse_character_card(file_path)

        avatar_path = file_path if ext == ".png" else ""
        if avatar_path:
            # 统一使用正斜杠以适配 Web/URL 访问路径
            avatar_path = avatar_path.replace("\\", "/")
        card_data["avatar_path"] = avatar_path

        return {"message": "Character parsed successfully", "data": card_data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse character: {str(e)}")

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
