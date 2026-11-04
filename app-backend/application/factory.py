"""Compose the HTTP application without starting migrations or workers."""

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse


def create_app() -> FastAPI:
    from core.auth import verify_api_key
    from routers import characters_router, chat_router, lorebooks_router, sessions_router, utils_router
    from routers.audio import router as audio_router
    from routers.group_sessions import router as group_sessions_router
    from application.lifecycle import lifespan
    from application.session_routes import SingleChatRoute, validate_session_routes

    app = FastAPI(title="AI Roleplay Backend", version="2.0", lifespan=lifespan)
    app.router.route_class = SingleChatRoute
    from services.conversation.session_access import SessionKindConflict

    @app.exception_handler(SessionKindConflict)
    async def session_kind_conflict(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    from application.charx_upload import CharxUploadMiddleware
    app.add_middleware(CharxUploadMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=".*",
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    assets = Path(__file__).resolve().parents[1] / "assets"
    (assets / "avatars").mkdir(parents=True, exist_ok=True)
    app.mount("/assets", StaticFiles(directory=assets), name="assets")
    dependencies = [Depends(verify_api_key)]
    app.include_router(audio_router, dependencies=dependencies)
    app.include_router(utils_router, dependencies=dependencies)
    app.include_router(characters_router, prefix="/characters", tags=["characters"], dependencies=dependencies)
    app.include_router(sessions_router, prefix="/sessions", tags=["sessions"], dependencies=dependencies)
    app.include_router(group_sessions_router, prefix="/group-sessions", tags=["group-sessions"], dependencies=dependencies)
    app.include_router(chat_router, prefix="/chat", tags=["chat"], dependencies=dependencies)
    app.include_router(lorebooks_router, prefix="/lorebooks", tags=["lorebooks"], dependencies=dependencies)
    validate_session_routes(app)
    return app
