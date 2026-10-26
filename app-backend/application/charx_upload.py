"""在 multipart 解析前鉴权并限制 CHARX 请求体；包括无 Content-Length 的上传。"""
import asyncio
import tempfile

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from core.auth import verify_api_key
from services.media.charx_import import upload_limit

UPLOAD_IDLE_TIMEOUT = 30
UPLOAD_TOTAL_TIMEOUT = 300


class CharxUploadMiddleware:
    def __init__(self, app):
        self.app = app
        self.active = 0

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] != 'POST' or scope['path'].rstrip('/') != '/characters/charx/preview':
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        try:
            verify_api_key(headers.get('x-api-key'))
        except HTTPException as exc:
            return await JSONResponse({'detail': exc.detail}, exc.status_code)(scope, receive, send)
        # 只允许少量 multipart 头开销；文件自身仍受独立大小校验。
        maximum = upload_limit() + 64 * 1024
        try:
            length = int(headers.get('content-length', '0'))
            if length < 0:
                raise ValueError()
        except ValueError:
            return await JSONResponse({'detail': '无效的 Content-Length'}, 400)(scope, receive, send)
        if length > maximum:
            return await JSONResponse({'detail': '角色包请求体超过大小限制'}, 413)(scope, receive, send)
        if self.active >= 3:
            return await JSONResponse({'detail': '同时上传过多，请稍后重试'}, 429)(scope, receive, send)
        self.active += 1
        try:
            with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as body:
                size = 0
                deadline = asyncio.get_running_loop().time() + UPLOAD_TOTAL_TIMEOUT
                while True:
                    remaining = deadline - asyncio.get_running_loop().time()
                    try:
                        message = await asyncio.wait_for(receive(), timeout=min(UPLOAD_IDLE_TIMEOUT, max(0, remaining)))
                    except asyncio.TimeoutError:
                        return await JSONResponse({'detail': '角色包上传超时，请重试'}, 408)(scope, receive, send)
                    if message['type'] == 'http.disconnect':
                        return
                    chunk = message.get('body', b'')
                    size += len(chunk)
                    if size > maximum:
                        return await JSONResponse({'detail': '角色包请求体超过大小限制'}, 413)(scope, receive, send)
                    await run_in_threadpool(body.write, chunk)
                    if not message.get('more_body', False):
                        break
                body.seek(0)

                async def replay():
                    chunk = await run_in_threadpool(body.read, 64 * 1024)
                    return {'type': 'http.request', 'body': chunk, 'more_body': body.tell() < size}

                await self.app(scope, replay, send)
        finally:
            self.active -= 1
