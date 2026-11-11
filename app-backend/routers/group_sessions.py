"""群聊创建与读取的 HTTP 契约；来源快照由服务端冻结。"""
from fastapi import Depends, HTTPException, Query, Request, Path
from uuid import UUID
from typing import Annotated
from sqlalchemy.orm import Session

from application.session_routes import GroupSessionAPIRouter
from core.database import get_db
from schemas import (GroupSessionCreate, GroupRoundSend, GroupRoundRegenerate, GroupRoundMutation, GroupCandidateCommand,
                     GroupPortraitChange, SQLITE_INT_MAX)
from core.locking import GroupRuntimeOwner
from services.conversation import group_session_service as service
from services.conversation.group_history_service import list_group_rounds
from services.conversation.group_background_service import submit_group_operation
from services.conversation.group_operation_service import accept_group_operation
from services.conversation import group_query_service as queries
from services.media.group_portraits import update_group_portrait

router = GroupSessionAPIRouter()
GroupResourceId = Annotated[int, Path(gt=0, le=SQLITE_INT_MAX)]


@router.get('/{session_id}/members/{persona_id}/compile_prompt')
def compile_group_member_prompt(session_id: GroupResourceId, persona_id: GroupResourceId,
                                db: Session = Depends(get_db)):
    try:
        return queries.compile_member_prompt(session_id, persona_id, db)
    except (service.GroupSessionNotFound, service.GroupSessionValidationError) as exc:
        raise _http_error(exc) from exc


def _http_error(exc):
    return HTTPException(404 if isinstance(exc, service.GroupSessionNotFound) else 422, detail=str(exc))


def _available(result, request):
    owner = getattr(request.app.state, "group_runtime_owner", None)
    ready = bool(isinstance(owner, GroupRuntimeOwner) and owner.active and owner.accepting)
    result["can_generate"] = ready
    if not ready and "current" in result:
        result["current"]["capabilities"].update(can_send=False, can_regenerate=False)
        for candidate in result.get("candidates", [result.get("candidate")]):
            if candidate:
                candidate["can_resume"] = False
    return result


@router.post("")
async def create_group_session(request: GroupSessionCreate, http: Request, db: Session = Depends(get_db)):
    draft = service.GroupSessionDraft(
        members=tuple(service.GroupMember(member.character_id, member.origin.mode, member.origin.source_session_id,
                                          member.greeting_index, member.greeting_content)
                      for member in request.members), title=request.title,
        user_nickname=request.user_nickname, shared_setting=request.shared_setting,
    )
    try:
        return _available(await service.create_group_session(draft, db), http)
    except (service.GroupSessionNotFound, service.GroupSessionValidationError) as exc:
        raise _http_error(exc) from exc


@router.get("")
def list_group_sessions(http: Request, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0, le=SQLITE_INT_MAX),
                        db: Session = Depends(get_db)):
    result = service.list_group_sessions(db, limit=limit, offset=offset)
    for item in result["sessions"]:
        _available(item, http)
    return result


@router.get("/{session_id}")
def get_group_session(session_id: GroupResourceId, http: Request, db: Session = Depends(get_db)):
    try:
        return _available(service.get_group_session_detail(session_id, db), http)
    except service.GroupSessionNotFound as exc:
        raise _http_error(exc) from exc


@router.post("/{session_id}/delete")
async def delete_group_session(session_id: GroupResourceId, db: Session = Depends(get_db)):
    try:
        return await service.delete_group_session(session_id, db)
    except (service.GroupSessionNotFound, service.GroupSessionValidationError) as exc:
        raise _http_error(exc) from exc


@router.get("/{session_id}/portraits")
def get_group_portraits(session_id: GroupResourceId, db: Session = Depends(get_db)):
    try:
        return queries.get_group_portraits(session_id, db)
    except (service.GroupSessionNotFound, service.GroupSessionValidationError) as exc:
        raise _http_error(exc) from exc


@router.put("/{session_id}/members/{persona_id}/portrait")
async def set_group_portrait(session_id: GroupResourceId, persona_id: GroupResourceId,
                            body: GroupPortraitChange, db: Session = Depends(get_db)):
    expected = (body.expected_group_revision, body.observed_round_id,
                body.observed_candidate_id, body.observed_candidate_revision)
    try:
        return await update_group_portrait(session_id, persona_id, body.portrait_id, expected, db)
    except (service.GroupSessionNotFound, service.GroupSessionValidationError) as exc:
        raise _http_error(exc) from exc


@router.get("/{session_id}/rounds")
def get_group_rounds(session_id: GroupResourceId, http: Request, limit: int = Query(20, ge=1, le=100),
                     offset: int = Query(0, ge=0, le=SQLITE_INT_MAX), db: Session = Depends(get_db)):
    try:
        return _available(list_group_rounds(session_id, db, limit=limit, offset=offset), http)
    except service.GroupSessionNotFound as exc:
        raise _http_error(exc) from exc


async def _generate(session_id, kind, body, http, db, round_id=None):
    owner = getattr(http.app.state, "group_runtime_owner", None)
    if not isinstance(owner, GroupRuntimeOwner) or not owner.active:
        raise HTTPException(503, detail="群聊执行服务不可用")
    options = body.model_dump()
    request_id = str(options.pop("client_request_id"))
    revision = options.pop("expected_group_revision")
    try:
        receipt = await submit_group_operation(session_id, request_id, kind, revision, db,
            runtime=owner, round_id=round_id, http_resources=True, **options)
        return {**receipt, "request_id": request_id, "kind": kind}
    except (service.GroupSessionNotFound, service.GroupSessionValidationError) as exc:
        raise _http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(422, detail="模型选择或持久参数无效") from exc


@router.post("/{session_id}/rounds", status_code=202)
async def send_group_round(session_id: GroupResourceId, body: GroupRoundSend, http: Request, db: Session = Depends(get_db)):
    return await _generate(session_id, "send", body, http, db)


@router.post("/{session_id}/rounds/{round_id}/regenerate", status_code=202)
async def regenerate_group_round(session_id: GroupResourceId, body: GroupRoundRegenerate, http: Request,
                                 round_id: int = Path(gt=0, le=SQLITE_INT_MAX), db: Session = Depends(get_db)):
    return await _generate(session_id, "regenerate", body, http, db, round_id)


@router.post("/{session_id}/rounds/{round_id}/resume", status_code=202)
async def resume_group_round(session_id: GroupResourceId, body: GroupCandidateCommand, http: Request,
                             round_id: int = Path(gt=0, le=SQLITE_INT_MAX), db: Session = Depends(get_db)):
    try:
        queries.require_shared_resume(session_id, body.target_candidate_id, db)
    except (service.GroupSessionNotFound, service.GroupSessionValidationError) as exc:
        raise _http_error(exc) from exc
    return await _generate(session_id, "resume", body, http, db, round_id)


async def _mutate(session_id, round_id, kind, body, db):
    options = body.model_dump()
    request_id = str(options.pop("client_request_id"))
    revision = options.pop("expected_group_revision")
    try:
        receipt = await accept_group_operation(session_id, request_id, kind, revision, db, round_id=round_id, **options)
        return {**receipt, "request_id": request_id, "kind": kind}
    except (service.GroupSessionNotFound, service.GroupSessionValidationError) as exc:
        raise _http_error(exc) from exc


@router.post("/{session_id}/rounds/{round_id}/select-candidate")
async def select_group_candidate(session_id: GroupResourceId, body: GroupCandidateCommand,
                                 round_id: int = Path(gt=0, le=SQLITE_INT_MAX), db: Session = Depends(get_db)):
    return await _mutate(session_id, round_id, "select", body, db)


@router.post("/{session_id}/rounds/{round_id}/discard")
async def discard_group_round(session_id: GroupResourceId, body: GroupRoundMutation,
                              round_id: int = Path(gt=0, le=SQLITE_INT_MAX), db: Session = Depends(get_db)):
    return await _mutate(session_id, round_id, "discard", body, db)


@router.get("/{session_id}/requests/{client_request_id}")
def get_group_request(session_id: GroupResourceId, client_request_id: UUID, http: Request, db: Session = Depends(get_db)):
    try:
        return _available(queries.get_group_request(session_id, str(client_request_id), db), http)
    except service.GroupSessionNotFound as exc:
        raise _http_error(exc) from exc


@router.get("/{session_id}/rounds/{round_id}/candidates")
def get_group_candidates(session_id: GroupResourceId, http: Request, round_id: int = Path(gt=0, le=SQLITE_INT_MAX),
                          limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0, le=SQLITE_INT_MAX), db: Session = Depends(get_db)):
    try:
        return _available(queries.list_group_candidates(session_id, round_id, db, limit=limit, offset=offset), http)
    except service.GroupSessionNotFound as exc:
        raise _http_error(exc) from exc


@router.get("/{session_id}/rounds/{round_id}/candidates/{candidate_id}")
def get_group_candidate(session_id: GroupResourceId, http: Request, round_id: int = Path(gt=0, le=SQLITE_INT_MAX),
                         candidate_id: int = Path(gt=0, le=SQLITE_INT_MAX), db: Session = Depends(get_db)):
    try:
        return _available(queries.get_group_candidate(session_id, round_id, candidate_id, db), http)
    except service.GroupSessionNotFound as exc:
        raise _http_error(exc) from exc
