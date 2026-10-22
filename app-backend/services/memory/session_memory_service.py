"""Session-scoped memory mutation policies."""

from sqlalchemy.orm import Session as DBSession
from sqlalchemy import text

from core.models import MemoryChunk, MemoryType, Session
import services.memory.memory_manager as memory_manager


class SessionMemoryNotFoundError(ValueError):
    pass


class InheritedMemoryMutationError(ValueError):
    pass


class ProtectedMemoryMutationError(ValueError):
    pass


def _check_consolidation_protection(memory_id, db):
    from services.memory.memory_visibility import is_consolidation_protected
    if is_consolidation_protected(memory_id, db):
        raise ProtectedMemoryMutationError("这条记忆关联已应用的整理，请先撤销整理；已有分支引用时保留来源只读")


def _get_persona(session_id: int, db: DBSession):
    session = db.get(Session, session_id)
    if session is None or session.persona is None:
        raise SessionMemoryNotFoundError("Session or Persona not found")
    return session.persona


def create_memory(
    session_id: int,
    content: str,
    memory_type: str,
    importance_score: float | None,
    db: DBSession,
) -> MemoryChunk:
    persona = _get_persona(session_id, db)
    try:
        parsed_type = MemoryType(memory_type)
    except ValueError:
        parsed_type = MemoryType.fact

    return memory_manager.add_memory_chunk(
        persona_id=persona.id,
        character_id=persona.character_id,
        content=content,
        memory_type=parsed_type,
        importance_score=(
            importance_score if importance_score is not None else 0.8
        ),
        origin_session_id=session_id,
        source_message_id=None,
        db=db,
    )


def update_memory(
    session_id: int,
    memory_id: int,
    content: str,
    importance_score: float | None,
    db: DBSession,
) -> MemoryChunk:
    db.commit()
    db.execute(text("BEGIN IMMEDIATE"))
    persona = _get_persona(session_id, db)
    chunk = db.get(MemoryChunk, memory_id)
    if chunk is None:
        raise SessionMemoryNotFoundError("Memory not found")
    if chunk.persona_id != persona.id:
        raise InheritedMemoryMutationError("Cannot edit inherited memories")

    _check_consolidation_protection(memory_id, db)

    try:
        return memory_manager.update_memory_chunk(
            chunk_id=memory_id,
            content=content,
            importance_score=importance_score,
            db=db,
        )
    except ValueError as exc:
        raise SessionMemoryNotFoundError(str(exc)) from exc


def delete_memory(session_id: int, memory_id: int, db: DBSession) -> None:
    db.commit()
    db.execute(text("BEGIN IMMEDIATE"))
    persona = _get_persona(session_id, db)
    chunk = db.get(MemoryChunk, memory_id)
    if chunk is None:
        raise SessionMemoryNotFoundError("Memory not found")
    if chunk.persona_id != persona.id:
        raise InheritedMemoryMutationError("Cannot delete inherited memories")

    _check_consolidation_protection(memory_id, db)

    memory_manager.delete_memory_chunk(memory_id, db)
