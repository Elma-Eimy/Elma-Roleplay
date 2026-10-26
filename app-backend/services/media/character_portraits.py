"""无标签立绘资源管理和手动选择；不从名称或正文猜测触发规则。"""
import hashlib
import io
import json
import uuid
import warnings
from pathlib import Path

from PIL import Image
from sqlalchemy import text
from core.config import settings
from core.models import Character, CharacterPortrait, ChatMessage, Session, OutboxJob


class PortraitConflict(ValueError):
    pass


def require_character(character_id, db):
    character = db.get(Character, character_id)
    if character is None:
        raise LookupError("角色不存在")
    return character


def serialize(portrait):
    result = {"id": portrait.id, "name": portrait.name, "image_path": portrait.image_path}
    for key in ("source_type", "source_name", "source_uri"):
        if getattr(portrait, key):
            result[key] = getattr(portrait, key)
    return result


def list_portraits(character_id, db, offset=0, limit=24):
    require_character(character_id, db)
    query = db.query(CharacterPortrait).filter_by(character_id=character_id)
    total = query.count()
    return {"portraits": [serialize(p) for p in query.order_by(CharacterPortrait.id).offset(offset).limit(limit).all()],
            "total": total, "has_more": offset + limit < total}


def add_portrait(character_id, content, filename, db):
    require_character(character_id, db)
    if not content or len(content) > settings.SECURITY_MAX_CARD_SIZE_MB * 1024 * 1024:
        raise ValueError("图片为空或超过大小限制")
    # 验证真实图片内容，文件名和 MIME 不能作为图片有效性的依据。
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                extension = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}.get(image.format)
                if extension is None or image.width * image.height > 25_000_000:
                    raise ValueError("仅支持不超过 2500 万像素的 PNG、JPEG、WebP 图片")
                image.verify()
            # verify 对 JPEG 等格式不执行像素解码；重新打开以检查截断数据。
            with Image.open(io.BytesIO(content)) as image:
                image.load()
    except Exception as exc:
        raise ValueError("无法读取图片，请选择有效的 PNG、JPEG 或 WebP 图片") from exc
    root = Path(settings.STORAGE_UPLOAD_AVATAR_DIR)
    root.mkdir(parents=True, exist_ok=True)
    target = root / ("portrait_" + uuid.uuid4().hex + extension)
    name = Path((filename or "立绘").replace("\\", "/")).stem.strip()[:80] or "立绘"
    portrait = CharacterPortrait(character_id=character_id, name=name, image_path=target.as_posix(),
                                 content_sha256=hashlib.sha256(content).hexdigest())
    try:
        target.write_bytes(content)
        db.add(portrait)
        db.flush()
        result = serialize(portrait)
        db.commit()
        return result
    except Exception:
        db.rollback()
        target.unlink(missing_ok=True)
        raise


def delete_portrait(character_id, portrait_id, db):
    portrait = db.query(CharacterPortrait).filter_by(id=portrait_id, character_id=character_id).first()
    if portrait is None:
        raise LookupError("立绘不存在")
    db.add(OutboxJob(task_type="delete_avatar", payload=json.dumps({"file_path": portrait.image_path})))
    db.delete(portrait)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"message": "立绘已删除；使用该图的故事将回退角色头像"}


def rename_portrait(character_id, portrait_id, name, db):
    portrait = db.query(CharacterPortrait).filter_by(id=portrait_id, character_id=character_id).first()
    if portrait is None:
        raise LookupError("立绘不存在")
    name = name.strip()
    if not name or len(name) > 80 or any(ord(char) < 32 for char in name):
        raise ValueError("名称须为 1–80 字，不能包含控制字符")
    portrait.name = name
    try:
        db.commit()
        return serialize(portrait)
    except Exception:
        db.rollback()
        raise


def resolve_selection(session_id, db, before_id=None):
    session = db.get(Session, session_id)
    if session is None or session.persona is None:
        raise LookupError("故事不存在")
    selected = session.persona.portrait_base or 0
    query = db.query(ChatMessage.id, ChatMessage.portrait_selection).filter_by(session_id=session_id, is_active=True)
    if before_id is not None:
        query = query.filter(ChatMessage.id < before_id)
    messages = query.order_by(ChatMessage.id).all()
    for _, value in messages:
        if value is not None:
            selected = value
    revision = hashlib.sha256(json.dumps([session.persona.portrait_base, [list(row) for row in messages]]).encode()).hexdigest()
    return selected, revision, messages, session.persona


def selection_before_message(message, db):
    boundary = message.parent_id if message.parent_id is not None else message.id
    selected = resolve_selection(message.session_id, db, before_id=boundary)[0]
    if message.parent_id is not None:
        parent = db.get(ChatMessage, message.parent_id)
        if parent is not None and parent.portrait_selection is not None:
            selected = parent.portrait_selection
    return selected


def get_selection(session_id, db):
    selected, revision, _, persona = resolve_selection(session_id, db)
    portrait = db.query(CharacterPortrait).filter_by(id=selected, character_id=persona.character_id).first() if selected else None
    return {"session_id": session_id, "portrait_id": portrait.id if portrait else None,
            "image_path": portrait.image_path if portrait else persona.character.avatar_path or "", "revision": revision}


def update_selection(session_id, portrait_id, expected_revision, db):
    try:
        db.execute(text("BEGIN IMMEDIATE"))
        _, revision, messages, persona = resolve_selection(session_id, db)
        if revision != expected_revision:
            raise PortraitConflict("剧情或立绘选择已变化，请重新加载后再选择")
        if portrait_id is not None and db.query(CharacterPortrait).filter_by(id=portrait_id, character_id=persona.character_id).first() is None:
            raise ValueError("立绘不存在或不属于当前角色")
        if messages:
            db.get(ChatMessage, messages[-1][0]).portrait_selection = portrait_id or 0
        else:
            persona.portrait_base = portrait_id or 0
        db.flush()
        result = get_selection(session_id, db)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
