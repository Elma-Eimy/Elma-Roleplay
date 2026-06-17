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
from routers import utils_router, characters_router, sessions_router, chat_router, lorebooks_router

# 初始化并建表
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="AI Roleplay Backend",
    version="2.0",
    # TODO: 正式对外发布前，取消下面两行注释以关闭 API 文档页面
    # docs_url=None,
    # redoc_url=None,
)

# 配置 CORS 跨域中间件
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",  # 配合 allow_credentials 动态反射允许 file://, null, http://localhost 等各种混合 Origin 跨域
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# 挂载静态文件目录以允许前端访问头像等静态资源
app.mount("/assets", StaticFiles(directory="assets"), name="assets")

# 挂载语音合成缓存目录（使用自定义路由以支持缓存文件被手动删除后的延迟自愈重建）
import os
import re
from fastapi.responses import FileResponse
from fastapi import HTTPException
from core.database import SessionLocal
from services.tts_service import TTSService

os.makedirs(settings.TTS_CACHE_DIR, exist_ok=True)

@app.get("/audio/{filename}", dependencies=[Depends(verify_api_key)])
async def get_audio_file(filename: str):
    """
    语音文件请求接口：
    若本地物理文件存在，直接返回；
    若文件被删除但为数据库绑定语音（msg_{id}_{voice}_{speed}.mp3），自动触发被动延时自愈重建。
    """
    filepath = os.path.join(settings.TTS_CACHE_DIR, filename)
    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
        return FileResponse(filepath)

    # 匹配规则：msg_{message_id}_{voice}_{speed}.mp3
    match = re.match(r'^msg_(\d+)_([^_]+)_([\d.]+)\.mp3$', filename)
    if match:
        message_id = int(match.group(1))
        voice = match.group(2)
        try:
            speed = float(match.group(3))
        except ValueError:
            speed = 1.0

        print(f"[INFO] 静态语音文件已从磁盘丢失，触发被动延迟重建: {filename} (Message ID: {message_id})")
        db = SessionLocal()
        try:
            tts_service = TTSService.get_instance()
            await tts_service.generate_speech_async(
                text="",
                voice=voice,
                speed=speed,
                message_id=message_id,
                db=db
            )
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                print(f"[SUCCESS] 延迟重建语音成功: {filepath}")
                return FileResponse(filepath)
        except Exception as e:
            print(f"[ERROR] 延迟重建语音失败: {e}")
        finally:
            db.close()

    raise HTTPException(status_code=404, detail="Audio file not found")

# 注册各个功能模块的路由
# 注册功能模块路由（统一注入 API Key 认证以进行安全性保护）
app.include_router(utils_router, dependencies=[Depends(verify_api_key)])  # 基础及文件上传端点
app.include_router(characters_router, prefix="/characters", tags=["characters"], dependencies=[Depends(verify_api_key)])  # 角色卡模块
app.include_router(sessions_router, prefix="/sessions", tags=["sessions"], dependencies=[Depends(verify_api_key)])  # 会话管理模块
app.include_router(chat_router, prefix="/chat", tags=["chat"], dependencies=[Depends(verify_api_key)])  # 对话通信模块
app.include_router(lorebooks_router, prefix="/lorebooks", tags=["lorebooks"], dependencies=[Depends(verify_api_key)])  # 世界书模块

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


