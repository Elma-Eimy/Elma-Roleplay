"""群聊聚合：原子创建、不可变来源快照与整群删除。"""
import asyncio
import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, text
from sqlalchemy.orm import selectinload

from core.locking import get_session_lock
from core.models import (Session, SessionPersona, Character, CharacterPortrait, ChatMessage,
                         MemoryChunk, OutboxJob, GroupPersonaOrigin, GroupInheritedMemorySnapshot)
from services.conversation.session_access import (get_single_session, get_group_session,
                                                 group_session_operation, SessionKindConflict)
from services.conversation.role_state_service import _resolve_state
from services.conversation.role_state_schema import validate_patch, encode_state
from services.conversation.role_state_schema import decode_state
from services.media.character_portraits import _resolve_selection
from services.memory.memory_extraction_service import get_confirmed_message_upper_bound
from services.memory.memory_visibility import memory_view, memory_source_bound


class GroupSessionNotFound(LookupError):
    pass


class GroupSessionValidationError(ValueError):
    pass


@dataclass(frozen=True)
class GroupMember:
    character_id: int
    mode: str = "card"
    source_session_id: int | None = None
    greeting_index: int | None = None
    greeting_content: str | None = None


@dataclass(frozen=True)
class GroupSessionDraft:
    members: tuple[GroupMember, ...]
    title: str = "新的群聊"
    user_nickname: str = "用户"
    shared_setting: str | None = None


def _draft(draft):
    if not isinstance(draft, GroupSessionDraft) or not isinstance(draft.members, tuple):
        raise GroupSessionValidationError("群聊创建需要固定的成员列表")
    if not 2 <= len(draft.members) <= 3:
        raise GroupSessionValidationError("群聊需要 2–3 个 AI 成员")
    seen = set()
    for member in draft.members:
        if not isinstance(member, GroupMember) or type(member.character_id) is not int or member.character_id <= 0:
            raise GroupSessionValidationError("成员角色 ID 必须是正整数")
        if member.character_id in seen:
            raise GroupSessionValidationError("同一角色卡不能重复加入群聊")
        seen.add(member.character_id)
        if member.greeting_index is not None and (type(member.greeting_index) is not int or member.greeting_index < 0):
            raise GroupSessionValidationError("开场索引必须为非负整数")
        if member.greeting_content is not None and (not isinstance(member.greeting_content, str) or len(member.greeting_content) > 20000):
            raise GroupSessionValidationError("开场白最多 20000 字")
        if member.mode != "card" and (member.greeting_index is not None or member.greeting_content is not None):
            raise GroupSessionValidationError("导入人格不能指定开场白")
        if member.mode == "card":
            if member.source_session_id is not None:
                raise GroupSessionValidationError("原卡起步不能指定来源故事")
        elif member.mode == "single_snapshot":
            if type(member.source_session_id) is not int or member.source_session_id <= 0:
                raise GroupSessionValidationError("导入快照需要有效的来源单聊 ID")
        else:
            raise GroupSessionValidationError("不支持的成员来源模式")
    for value, name in ((draft.title, "标题"), (draft.user_nickname, "用户昵称")):
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 50:
            raise GroupSessionValidationError(f"{name}需要 1–50 字")
    setting = draft.shared_setting
    if setting is not None and (not isinstance(setting, str) or len(setting) > 20000):
        raise GroupSessionValidationError("共同设定最多 20000 字")
    return replace(draft, title=draft.title.strip(), user_nickname=draft.user_nickname.strip(),
                   shared_setting=setting.strip() or None if setting is not None else None)


def _begin_write(db):
    if db.new or db.dirty or db.deleted:
        raise GroupSessionValidationError("群聊操作需要没有待提交修改的数据库会话")
    # 路由的预读取不能成为冻结快照；重新取得 SQLite 写事务后再加载来源。
    db.rollback()
    db.execute(text("BEGIN IMMEDIATE"))
    db.expire_all()


async def _locked_write(session_ids, operation, *arguments):
    locks = []
    try:
        for session_id in sorted(set(session_ids)):
            lock = get_session_lock(session_id)
            if lock.locked():
                raise SessionKindConflict("相关故事正在处理，请结束后再操作群聊")
            await lock.acquire()
            locks.append(lock)
        # 数据库线程结束后才能释放锁；请求取消不能让同一会话并发写入。
        work = asyncio.create_task(run_in_threadpool(operation, *arguments))
        cancelled = False
        while True:
            try:
                result = await asyncio.shield(work)
                break
            except asyncio.CancelledError:
                if work.cancelled():
                    raise
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError
        return result
    finally:
        for lock in reversed(locks):
            lock.release()


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _initial_state(character, source, db):
    if source is None:
        return {"role_state": {}, "affection_score": 0, "current_mood": None,
                "cognition_state": None, "current_scenario_override": None, "portrait_base": 0}
    persona = source.persona
    state = _resolve_state(source, db)[0]["state"]
    # 只接受已有状态契约中的形状；不将任意 JSON 当成新成员基线。
    try:
        validate_patch(state, manual=True)
    except (ValueError, TypeError) as exc:
        raise GroupSessionValidationError("来源角色状态不符合快照格式") from exc
    portrait_id = _resolve_selection(source, db)[0]
    if portrait_id and db.query(CharacterPortrait.id).filter_by(id=portrait_id, character_id=character.id).first() is None:
        portrait_id = 0
    return {"role_state": state, "affection_score": persona.affection_score,
            "current_mood": persona.current_mood, "cognition_state": persona.cognition_state,
            "current_scenario_override": persona.current_scenario_override, "portrait_base": portrait_id}


def _freeze_memories(persona, receiver, confirmed_before, captured_at, db):
    visible, hidden = memory_view(persona.id, db, before_message_id=confirmed_before or 0)
    cards = db.query(MemoryChunk).filter(visible, MemoryChunk.id.not_in(hidden)).order_by(MemoryChunk.id).yield_per(500)
    fingerprints = []
    # 同一事务内分批读取；不截断、不重新开始读取快照。
    for card in cards:
        payload = {"content": card.content, "memory_type": card.memory_type.value,
                   "importance_score": card.importance_score, "temporal_status": card.temporal_status,
                   "temporal_note": card.temporal_note, "source_evidence_json": card.source_evidence_json,
                   "source_memory_id": card.id, "source_persona_id": card.persona_id,
                   "source_session_id": card.origin_session_id if card.origin_session_id is not None else card.persona.session_id,
                   "source_start_message_id": card.source_start_message_id,
                   "source_message_id": card.source_message_id,
                   "source_message_id_bound": memory_source_bound(card)}
        fingerprint = _fingerprint(payload)
        db.add(GroupInheritedMemorySnapshot(persona_id=receiver.id, **payload,
               source_created_at=card.created_at, captured_at=captured_at, content_fingerprint=fingerprint))
        fingerprints.append(fingerprint)
        if len(fingerprints) % 500 == 0:
            db.flush()
    return fingerprints


async def create_group_session(draft: GroupSessionDraft, db):
    draft = _draft(draft)
    sources = [member.source_session_id for member in draft.members if member.source_session_id is not None]
    return await _locked_write(sources, _create, draft, db)


def _greeting(member, character, nickname):
    if member.mode != "card":
        return None
    content = character.first_mes or ""
    if member.greeting_index is not None:
        try:
            extensions = json.loads(character.extensions or '{}') if isinstance(character.extensions, str) else character.extensions or {}
            content = extensions.get('alternate_greetings', [])[member.greeting_index]
            if not isinstance(content, str):
                raise ValueError()
        except (ValueError, TypeError, AttributeError, IndexError, KeyError):
            raise GroupSessionValidationError("备用开场不存在，请重新选择") from None
    if member.greeting_content is not None:
        content = member.greeting_content
    from services.conversation.prompting.compiler import replace_placeholders
    content = replace_placeholders(content, character.name, nickname).strip()
    if len(content) > 20000:
        raise GroupSessionValidationError("开场白最多 20000 字")
    return content or None


def public_greetings(group):
    """只返回创建时冻结的公开开场，不读取其他成员的角色卡设定。"""
    return [{"persona_id": member.id, "speaker_name": member.character.name, "content": member.group_origin.greeting_content}
            for member in sorted(group.personas, key=lambda member: member.member_slot)
            if member.group_origin and member.group_origin.greeting_content]


def _create(draft, db):
    try:
        _begin_write(db)
        captured_at = datetime.utcnow()
        group = Session(kind="group", title=draft.title, user_nickname=draft.user_nickname,
                        shared_setting=draft.shared_setting, created_at=captured_at, updated_at=captured_at)
        db.add(group)
        db.flush()
        for slot, member in enumerate(draft.members, 1):
            character = db.get(Character, member.character_id)
            if character is None:
                raise GroupSessionNotFound("成员角色不存在")
            source = None
            if member.mode == "single_snapshot":
                source = get_single_session(member.source_session_id, db)
                if source is None or source.persona is None:
                    raise GroupSessionNotFound("来源故事或人格不存在")
                if source.persona.character_id != member.character_id:
                    raise GroupSessionValidationError("来源单聊必须属于该成员的角色卡")
            greeting = _greeting(member, character, draft.user_nickname)
            state = _initial_state(character, source, db)
            receiver = SessionPersona(session_id=group.id, character_id=member.character_id,
                member_slot=slot, role_state_base=encode_state(state["role_state"]),
                **{key: value for key, value in state.items() if key != "role_state"})
            db.add(receiver)
            db.flush()
            confirmed_before = get_confirmed_message_upper_bound(source.id, db) if source else None
            fingerprints = _freeze_memories(source.persona, receiver, confirmed_before, captured_at, db) if source else []
            last_active = db.query(func.max(ChatMessage.id)).filter_by(session_id=source.id, is_active=True).scalar() if source else None
            db.add(GroupPersonaOrigin(persona_id=receiver.id, mode=member.mode, captured_at=captured_at,
                initial_state_json=encode_state(state), source_session_id=source.id if source else None,
                source_persona_id=source.persona.id if source else None,
                source_last_active_message_id=last_active, source_confirmed_before_id=confirmed_before,
                greeting_content=greeting,
                content_fingerprint=_fingerprint({"state": state, "memories": fingerprints, "greeting": greeting})))
        db.flush()
        # 响应也在提交前构造，避免提交后查询失败诱发重复创建。
        result = _detail(group, db)
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise


def _iso(value):
    return value.isoformat() if value else None


def _detail(group, db):
    counts = dict(db.query(GroupInheritedMemorySnapshot.persona_id, func.count(GroupInheritedMemorySnapshot.id))
                  .join(SessionPersona, SessionPersona.id == GroupInheritedMemorySnapshot.persona_id)
                  .filter(SessionPersona.session_id == group.id).group_by(GroupInheritedMemorySnapshot.persona_id).all())
    return _serialize(group, counts)


def _serialize(group, counts):
    members = []
    for persona in group.personas:
        origin, character = persona.group_origin, persona.character
        members.append({"persona_id": persona.id, "slot": persona.member_slot,
            "character": {"id": character.id, "name": character.name, "avatar_path": character.avatar_path},
            "state": {"affection_score": persona.affection_score, "current_mood": persona.current_mood,
                      "cognition_state": persona.cognition_state, "current_scenario_override": persona.current_scenario_override,
                      "role_state": decode_state(persona.role_state_base), "portrait_base": persona.portrait_base},
            "greeting_content": origin.greeting_content,
            "origin": {"mode": origin.mode, "snapshot_version": origin.snapshot_version,
                       "captured_at": _iso(origin.captured_at), "source_session_id": origin.source_session_id,
                       "source_persona_id": origin.source_persona_id,
                       "inherited_memory_count": counts.get(persona.id, 0)}})
    return {"kind": "group", "session_id": group.id, "title": group.title,
            "user_nickname": group.user_nickname, "shared_setting": group.shared_setting,
            "created_at": _iso(group.created_at), "updated_at": _iso(group.updated_at),
            "can_generate": False, "group_revision": group.group_revision, "members": members}


@group_session_operation
def get_group_session_detail(session_id, db):
    group = get_group_session(session_id, db)
    if group is None:
        raise GroupSessionNotFound("群聊不存在")
    return _detail(group, db)


def list_group_sessions(db, *, limit=20, offset=0):
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise GroupSessionValidationError("分页参数无效")
    query = db.query(Session).filter_by(kind="group")
    total = query.count()
    groups = query.options(selectinload(Session.personas).selectinload(SessionPersona.character),
                           selectinload(Session.personas).selectinload(SessionPersona.group_origin))
    groups = groups.order_by(Session.updated_at.desc(), Session.id.desc()).offset(offset).limit(limit).all()
    ids = [group.id for group in groups]
    counts = dict(db.query(GroupInheritedMemorySnapshot.persona_id, func.count(GroupInheritedMemorySnapshot.id))
                  .join(SessionPersona, SessionPersona.id == GroupInheritedMemorySnapshot.persona_id)
                  .filter(SessionPersona.session_id.in_(ids)).group_by(GroupInheritedMemorySnapshot.persona_id).all()) if ids else {}
    items = [_serialize(group, counts) for group in groups]
    return {"sessions": items, "total": total, "limit": limit, "offset": offset,
            "has_more": offset + len(items) < total}


@group_session_operation
async def delete_group_session(session_id, db):
    # 在取得锁前先拒绝错误类型，避免错误请求竞争其他故事的锁。
    group = get_group_session(session_id, db)
    if group is None:
        raise GroupSessionNotFound("群聊不存在")
    return await _locked_write([session_id], _delete, session_id, db)


def _delete(session_id, db):
    try:
        _begin_write(db)
        group = get_group_session(session_id, db)
        if group is None:
            raise GroupSessionNotFound("群聊不存在")
        from services.conversation.group_execution_scope import has_active_operation
        if has_active_operation(session_id, db):
            raise SessionKindConflict("群聊存在活动操作，不能删除")
        personas = group.personas
        ids = [p.id for p in personas]
        chunks = db.query(MemoryChunk).filter(MemoryChunk.persona_id.in_(ids)).all()
        for persona in personas:
            doc_ids = [chunk.chroma_doc_id for chunk in chunks if chunk.persona_id == persona.id and chunk.chroma_doc_id]
            if doc_ids:
                db.add(OutboxJob(task_type="delete_vector", payload=json.dumps({"character_id": persona.character_id, "doc_ids": doc_ids})))
        audio = [row[0] for row in db.query(ChatMessage.audio_path).filter(
            ChatMessage.session_id == session_id, ChatMessage.audio_path.isnot(None), ChatMessage.audio_path != "").all()]
        shared_audio = {row[0] for row in db.query(ChatMessage.audio_path).filter(
            ChatMessage.session_id != session_id, ChatMessage.audio_path.in_(audio)).all()} if audio else set()
        audio = set(audio) - shared_audio
        if audio:
            db.add(OutboxJob(task_type="delete_audio", payload=json.dumps({"file_paths": sorted(set(audio))})))
        db.delete(group)
        db.flush()
        result = {"deleted_session_id": session_id, "members_deleted": len(ids), "local_memories_deleted": len(chunks)}
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise
