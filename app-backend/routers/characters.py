from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from core.database import get_db
from core import models
from services.parse import parse_character_card
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
        existing_char = db.query(models.Character).filter(
            models.Character.name == character_data.name
        ).first()
        if existing_char:
            return {
                "message": f"Character '{character_data.name}' already exists.",
                "character_id": existing_char.id,
            }

        tags_str = json.dumps(character_data.tags, ensure_ascii=False)
        extensions_str = json.dumps(character_data.extensions, ensure_ascii=False)

        new_char = models.Character(
            name=character_data.name,
            avatar_path=character_data.avatar_path,
            description=character_data.description,
            personality=character_data.personality,
            scenario=character_data.scenario,
            first_mes=character_data.first_mes,
            mes_example=character_data.mes_example,
            creator_notes=character_data.creator_notes,
            system_prompt_override=character_data.system_prompt_override,
            post_history_instructions=character_data.post_history_instructions,
            tags=tags_str,
            extensions=extensions_str,
        )
        db.add(new_char)
        db.commit()
        db.refresh(new_char)

        return {
            "message": "Character created successfully",
            "character_id": new_char.id,
            "name": new_char.name,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to create character: {str(e)}")

@router.get("")
def list_characters(db: Session = Depends(get_db)):
    """获取所有可用角色的简要列表"""
    characters = db.query(models.Character).all()
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
        "created_at": character.created_at.isoformat() if character.created_at else None,
    }

@router.put("/{character_id}")
def update_character(character_id: int, character_data: CharacterCreate, db: Session = Depends(get_db)):
    """更新已存在角色的设定属性"""
    character = db.get(models.Character, character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    character.name = character_data.name
    character.avatar_path = character_data.avatar_path
    character.description = character_data.description
    character.personality = character_data.personality
    character.scenario = character_data.scenario
    character.first_mes = character_data.first_mes
    character.mes_example = character_data.mes_example
    character.creator_notes = character_data.creator_notes
    character.system_prompt_override = character_data.system_prompt_override
    character.post_history_instructions = character_data.post_history_instructions
    character.tags = json.dumps(character_data.tags, ensure_ascii=False)
    character.extensions = json.dumps(character_data.extensions, ensure_ascii=False)

    db.commit()
    db.refresh(character)
    return {
        "message": "Character updated successfully",
        "character_id": character.id,
        "name": character.name
    }

@router.delete("/{character_id}")
def delete_character(character_id: int, db: Session = Depends(get_db)):
    """删除指定角色，并清理关联会话和向量数据库"""
    character = db.get(models.Character, character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # 1. 查找所有关联的 SessionPersona
    personas = db.query(models.SessionPersona).filter(
        models.SessionPersona.character_id == character_id
    ).all()

    # 2. 清除该角色在 ChromaDB 中的向量集合
    #    注意：所有关联 Persona 的记忆均存放在同一个角色 collection 中 (character_{character_id})
    from services.chat_engine import chroma_client
    collection_deleted = False
    collection_name = f"character_{character_id}"
    try:
        chroma_client.delete_collection(collection_name)
        print(f"[INFO] Deleted ChromaDB collection: {collection_name}")
        collection_deleted = True
    except Exception as e:
        print(f"[WARN] Failed to delete ChromaDB collection '{collection_name}': {e}")

    # 3. 级联删除关联的会话 (Session)
    session_ids = [p.session_id for p in personas]
    if session_ids:
        db.query(models.Session).filter(models.Session.id.in_(session_ids)).delete(synchronize_session="fetch")

    # 4. 删除角色自身记录
    db.delete(character)
    db.commit()

    return {
        "message": "Character and all associated sessions/memories deleted successfully",
        "character_id": character_id,
        "sessions_deleted_count": len(session_ids),
        "collection_deleted": collection_deleted,
    }
