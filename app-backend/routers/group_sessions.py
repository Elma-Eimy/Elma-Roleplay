"""群聊创建与读取的 HTTP 契约；来源快照由服务端冻结。"""
from fastapi import Depends, HTTPException, Query
from sqlalchemy.orm import Session

from application.session_routes import GroupSessionAPIRouter
from core.database import get_db
from schemas import GroupSessionCreate
from services.conversation import group_session_service as service
from services.conversation.group_history_service import list_group_rounds

router = GroupSessionAPIRouter()


def _http_error(exc):
    return HTTPException(404 if isinstance(exc, service.GroupSessionNotFound) else 422, detail=str(exc))


@router.post("")
async def create_group_session(request: GroupSessionCreate, db: Session = Depends(get_db)):
    draft = service.GroupSessionDraft(
        members=tuple(service.GroupMember(member.character_id, member.origin.mode, member.origin.source_session_id)
                      for member in request.members), title=request.title,
        user_nickname=request.user_nickname, shared_setting=request.shared_setting,
    )
    try:
        return await service.create_group_session(draft, db)
    except (service.GroupSessionNotFound, service.GroupSessionValidationError) as exc:
        raise _http_error(exc) from exc


@router.get("")
def list_group_sessions(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                        db: Session = Depends(get_db)):
    return service.list_group_sessions(db, limit=limit, offset=offset)


@router.get("/{session_id}")
def get_group_session(session_id: int, db: Session = Depends(get_db)):
    try:
        return service.get_group_session_detail(session_id, db)
    except service.GroupSessionNotFound as exc:
        raise _http_error(exc) from exc


@router.post("/{session_id}/delete")
async def delete_group_session(session_id: int, db: Session = Depends(get_db)):
    try:
        return await service.delete_group_session(session_id, db)
    except (service.GroupSessionNotFound, service.GroupSessionValidationError) as exc:
        raise _http_error(exc) from exc


@router.get("/{session_id}/rounds")
def get_group_rounds(session_id: int, limit: int = Query(20, ge=1, le=100),
                     offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    try:
        return list_group_rounds(session_id, db, limit=limit, offset=offset)
    except service.GroupSessionNotFound as exc:
        raise _http_error(exc) from exc
