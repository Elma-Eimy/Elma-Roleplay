"""仅监听本机的限时只读预览，不启动应用生命周期或后台任务。"""
from contextlib import asynccontextmanager, contextmanager
from html import escape
from pathlib import Path
import re
import threading


@contextmanager
def preview_app(database_path, report, frontend_dist=None):
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    from sqlalchemy import create_engine, event
    from sqlalchemy.engine import URL
    from sqlalchemy.orm import sessionmaker
    from core.database import get_db
    from application.factory import create_app

    path = Path(database_path).resolve(strict=True)
    engine = create_engine(URL.create("sqlite", database="file:" + path.as_posix(),
        query={"mode": "ro", "uri": "true"}), connect_args={"check_same_thread": False})
    @event.listens_for(engine, "connect")
    def read_only(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA query_only=ON")
    sessions = sessionmaker(bind=engine, autoflush=False)
    def read_db():
        with sessions() as db:
            yield db

    try:
        app = create_app()
        app.router.routes = [route for route in app.router.routes if getattr(route, "path", None) != "/"]
        @asynccontextmanager
        async def no_background_tasks(_):
            yield
        app.router.lifespan_context = no_background_tasks
        app.dependency_overrides[get_db] = read_db
        @app.middleware("http")
        async def only_preview_reads(request, call_next):
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                return JSONResponse(status_code=405, content={"detail": "隔离预览只允许读取"})
            route = request.url.path
            allowed = (route == "/" or re.fullmatch(r"/group-sessions(?:/[1-9]\d*(?:/rounds)?)?", route)
                       or route.startswith("/assets/") or (frontend_dist is not None and route.startswith("/preview/")))
            if not allowed:
                return JSONResponse(status_code=404, content={"detail": "此资源不在隔离预览范围"})
            return await call_next(request)

        @app.get("/", response_class=HTMLResponse)
        def index():
            rows = []
            for result in report["results"]:
                sid = result["session_id"]
                target = f"/preview/#/pages/group/detail?sessionId={sid}" if frontend_dist else f"/group-sessions/{sid}/rounds"
                rows.append(f'<li><a href="{target}">{escape(result["id"])}</a> · {escape(result["finish_reason"])}</li>')
            mode_note = "真实模型结果，语义仍待人工评审。" if report.get("mode") == "online" else "固定响应回放不能证明真实模型质量。"
            return ('<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
                '<title>群聊隔离预览</title><body><h1>群聊隔离预览</h1>'
                '<p>虚构临时数据，只读且限时开放。' + mode_note + '</p><ul>'
                + "".join(rows) + '</ul></body></html>')
        if frontend_dist is not None:
            app.mount("/preview", StaticFiles(directory=str(frontend_dist), html=True), name="preview-h5")
        yield app
    finally:
        engine.dispose()


def serve_preview(database_path, report, port, seconds, frontend_dist=None):
    import uvicorn
    from sqlalchemy import create_engine
    from application.group_runtime import group_runtime

    # 运行权仍绑定普通 SQLite 路径；HTTP 使用另一个 mode=ro 的连接池。
    lock_engine = create_engine("sqlite:///" + Path(database_path).resolve().as_posix())
    try:
        with group_runtime(lock_engine), preview_app(database_path, report, frontend_dist) as app:
            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                lifespan="off", access_log=False, log_level="warning"))
            timer = threading.Timer(seconds, lambda: setattr(server, "should_exit", True))
            timer.daemon = True
            timer.start()
            try:
                server.run()
            finally:
                timer.cancel()
    finally:
        lock_engine.dispose()
