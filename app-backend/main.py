"""
主入口 — FastAPI 启动引导与路由注册
"""

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from core import Base, engine
from core.config import settings
from core.auth import verify_api_key
from core.utils import get_local_ips
from routers import utils_router, characters_router, sessions_router, chat_router

# 初始化并建表
Base.metadata.create_all(bind=engine)

def run_migrations(db_engine):
    from sqlalchemy import inspect, text
    inspector = inspect(db_engine)
    columns = [col['name'] for col in inspector.get_columns('chat_messages')]
    
    with db_engine.begin() as conn:
        if 'parent_id' not in columns:
            try:
                # SQLite supports adding columns. Let's add parent_id
                conn.execute(text("ALTER TABLE chat_messages ADD COLUMN parent_id INTEGER REFERENCES chat_messages(id) ON DELETE CASCADE"))
                print("[MIGRATION] Successfully added parent_id to chat_messages.")
            except Exception as e:
                print(f"[MIGRATION] Error adding parent_id: {e}")
        if 'is_active' not in columns:
            try:
                # Add is_active column default True
                conn.execute(text("ALTER TABLE chat_messages ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"))
                print("[MIGRATION] Successfully added is_active to chat_messages.")
            except Exception as e:
                print(f"[MIGRATION] Error adding is_active: {e}")

run_migrations(engine)

app = FastAPI(
    title="AI Roleplay Backend",
    version="2.0",
    # 全局注入 API Key 认证依赖，所有路由自动受保护
    # 开发时只需保持 ACCESS_API_KEY 为空即可无密地测试
    dependencies=[Depends(verify_api_key)],
    # TODO: 正式对外发布前，取消下面两行注释以关闭 API 文档页面
    # docs_url=None,
    # redoc_url=None,
)

# 配置 CORS 跨域中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.SECURITY_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# 挂载静态文件目录以允许前端访问头像等静态资源
app.mount("/assets", StaticFiles(directory="assets"), name="assets")

# 注册各个功能模块的路由
app.include_router(utils_router)  # 基础及文件上传端点
app.include_router(characters_router, prefix="/characters", tags=["characters"])  # 角色卡模块
app.include_router(sessions_router, prefix="/sessions", tags=["sessions"])  # 会话管理模块
app.include_router(chat_router, prefix="/chat", tags=["chat"])  # 对话通信模块

@app.on_event("startup")
async def show_startup_banner():
    local_ips = get_local_ips()
    
    def banner_print(msg=""):
        print(msg, flush=True)
        
    banner_print("\n" + "=" * 80)
    banner_print(" [OK] AI Roleplay Backend 已成功启动并就绪！")
    banner_print("=" * 80)
    banner_print(" 1. 本地开发调试地址 (当前机器访问):")
    banner_print("    -> http://127.0.0.1:8000")
    banner_print("\n 2. 局域网访问地址 (同一 Wi-Fi 或局域网内的手机/其他设备访问):")
    if local_ips:
        for ip in local_ips:
            banner_print(f"    -> http://{ip}:8000")
        banner_print("\n * 使用提示：")
        banner_print("    - 如果在手机 App/小程序中连接此后端，请在设置中输入上述任意一个局域网地址。")
        banner_print("    - 确保手机与运行本后端的电脑连接在【同一个 Wi-Fi】下。")
        banner_print("    - 若连接失败，请检查电脑防火墙是否允许 8000 端口入站流量。")
    else:
        banner_print("      [!] 未检测到活跃的局域网 IP，请检查您的网线/无线连接。")
    banner_print("=" * 80 + "\n")


