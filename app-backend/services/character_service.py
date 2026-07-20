"""管理角色创建、更新、删除以及关联外部资源的完整生命周期。"""

import json

from sqlalchemy.orm import Session as DBSession

from core.models import Character, ChatMessage, OutboxJob, Session, SessionPersona


def create_character(data: dict, db: DBSession) -> dict:
    """创建角色；同名角色存在时沿用原有记录。"""
    existing = db.query(Character).filter(Character.name == data["name"]).first()
    if existing is not None:
        return {
            "message": f"Character '{data['name']}' already exists.",
            "character_id": existing.id,
        }

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
        "character_id": character.id,
        "name": character.name,
    }


def update_character(character_id: int, data: dict, db: DBSession) -> dict:
    """更新角色的静态设定。"""
    character = db.get(Character, character_id)
    if character is None:
        raise ValueError("Character not found")

    _apply_character_data(character, data)
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
    """在 SQL 中删除角色，并登记可重试的外部资源清理任务。

    ChromaDB 和文件系统不会在 SQL 提交前被直接修改；相关清理任务与角色删除
    在同一个事务中写入 Outbox，由后台 Worker 最终执行。
    """
    character = db.get(Character, character_id)
    if character is None:
        raise ValueError("Character not found")

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
    if audio_paths:
        db.add(
            OutboxJob(
                task_type="delete_audio",
                payload=json.dumps({"file_paths": audio_paths}),
            )
        )

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
