"""管理角色创建、更新、删除以及关联外部资源的完整生命周期。"""

import json

from sqlalchemy.orm import Session as DBSession
from sqlalchemy import text

from services.conversation.session_access import SessionKindConflict
from core.models import Character, CharacterPortrait, ChatMessage, OutboxJob, Session, SessionPersona


def extract_character_creator(extensions_raw) -> str:
    """从角色 extensions.ai_roleplay_card 提取作者名，无值或格式异常返回空串。"""
    if not extensions_raw:
        return ""
    parsed = extensions_raw
    if isinstance(extensions_raw, str):
        try:
            parsed = json.loads(extensions_raw)
        except Exception:
            return ""
    if not isinstance(parsed, dict):
        return ""
    card_meta = parsed.get("ai_roleplay_card")
    if not isinstance(card_meta, dict):
        return ""
    creator = card_meta.get("creator")
    return creator.strip() if isinstance(creator, str) else ""


def create_character(data: dict, db: DBSession) -> dict:
    """创建独立角色记录；允许存在同名但不同版本或作者的角色卡。"""
    character = Character()
    _apply_character_data(character, data)
    try:
        db.add(character)
        db.commit()
        db.refresh(character)
    except Exception:
        db.rollback()
        raise

    return {
        "message": "Character created successfully",
        "created": True,
        "character_id": character.id,
        "name": character.name,
    }


def update_character(character_id: int, data: dict, db: DBSession) -> dict:
    """更新角色的静态设定。"""
    character = db.get(Character, character_id)
    if character is None:
        raise ValueError("Character not found")

    old_avatar_path = character.avatar_path
    _apply_character_data(character, data)
    if old_avatar_path and old_avatar_path != character.avatar_path:
        db.add(
            OutboxJob(
                task_type="delete_avatar",
                payload=json.dumps(
                    {"file_path": old_avatar_path},
                    ensure_ascii=False,
                ),
            )
        )
    try:
        db.commit()
        db.refresh(character)
    except Exception:
        db.rollback()
        raise

    return {
        "message": "Character updated successfully",
        "character_id": character.id,
        "name": character.name,
    }


def delete_character_service(character_id: int, db: DBSession) -> dict:
    """在同一写事务中检查群聊引用并删除角色聚合。"""
    # 与群聊创建串行化“检查引用→删除”，不能在检查后被新成员引用插入。
    if db.new or db.dirty or db.deleted:
        raise ValueError("角色删除需要没有待提交修改的数据库会话")
    try:
        db.rollback()
        db.execute(text("BEGIN IMMEDIATE"))
        db.expire_all()
        return _delete_character(character_id, db)
    except BaseException:
        db.rollback()
        raise


def _delete_character(character_id: int, db: DBSession) -> dict:
    """在 SQL 中删除角色，并登记可重试的外部资源清理任务。

    ChromaDB 和文件系统不会在 SQL 提交前被直接修改；相关清理任务与角色删除
    在同一个事务中写入 Outbox，由后台 Worker 最终执行。
    """
    character = db.get(Character, character_id)
    if character is None:
        raise ValueError("Character not found")

    if db.query(Session.id).join(SessionPersona, SessionPersona.session_id == Session.id).filter(
        SessionPersona.character_id == character_id, Session.kind == "group"
    ).first():
        raise SessionKindConflict("角色已被群聊使用，请先处理相关群聊")

    avatar_path = character.avatar_path
    portrait_paths = [row[0] for row in db.query(CharacterPortrait.image_path).filter_by(character_id=character_id).all()]
    session_ids = [
        row[0]
        for row in (
            db.query(SessionPersona.session_id)
            .filter(SessionPersona.character_id == character_id)
            .all()
        )
    ]

    audio_paths = []
    if session_ids:
        audio_paths = [
            row[0]
            for row in (
                db.query(ChatMessage.audio_path)
                .filter(
                    ChatMessage.session_id.in_(session_ids),
                    ChatMessage.audio_path.isnot(None),
                    ChatMessage.audio_path != "",
                )
                .all()
            )
        ]

        # 会话通过 Persona 归属于角色，删除时需要清理完整聚合，避免留下无 Persona 会话。
        db.query(Session).filter(Session.id.in_(session_ids)).delete(
            synchronize_session=False
        )

    db.delete(character)
    db.flush()

    db.add(
        OutboxJob(
            task_type="delete_vector_collection",
            payload=json.dumps({"character_id": character_id}),
        )
    )
    if avatar_path:
        db.add(
            OutboxJob(
                task_type="delete_avatar",
                payload=json.dumps(
                    {"file_path": avatar_path},
                    ensure_ascii=False,
                ),
            )
        )
    if audio_paths:
        db.add(
            OutboxJob(
                task_type="delete_audio",
                payload=json.dumps({"file_paths": audio_paths}),
            )
        )

    for path in portrait_paths:
        db.add(OutboxJob(task_type="delete_avatar", payload=json.dumps({"file_path": path})))

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "character_id": character_id,
        "session_ids": session_ids,
        "sessions_deleted_count": len(session_ids),
        "audio_files_queued_count": len(audio_paths),
        "collection_cleanup_queued": True,
        # 保留旧响应字段；物理删除已改为异步，因此用 null 表示仍在处理中。
        "collection_deleted": None,
    }


def _apply_character_data(character: Character, data: dict) -> None:
    """把接口数据统一映射到角色实体，避免创建和更新重复维护字段列表。"""
    character.name = data["name"]
    character.avatar_path = data.get("avatar_path", "")
    character.description = data.get("description", "")
    character.personality = data.get("personality", "")
    character.scenario = data.get("scenario", "")
    character.first_mes = data.get("first_mes", "")
    character.mes_example = data.get("mes_example", "")
    character.creator_notes = data.get("creator_notes", "")
    character.system_prompt_override = data.get("system_prompt_override", "")
    character.post_history_instructions = data.get(
        "post_history_instructions", ""
    )
    character.tags = json.dumps(data.get("tags", []), ensure_ascii=False)
    character.extensions = json.dumps(
        data.get("extensions", {}), ensure_ascii=False
    )
