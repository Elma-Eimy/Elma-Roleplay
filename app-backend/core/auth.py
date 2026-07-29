"""
访问控制 — 基于静态 API Key 的轻量认证

设计说明：
  本项目定位为「单人/私有部署」场景，无需完整的账户注册/登录系统。
  通过在请求 Header 中携带共享密钥（X-API-Key）来阻止公网陌生人访问。

使用方式：
  1. 在 .env 中设置 ACCESS_API_KEY=<你的强随机密码>
  2. 前端每次请求时在 Header 中附加：X-API-Key: <你的密码>
  3. 若 ACCESS_API_KEY 为空（默认），则跳过认证（方便本地开发）

# TODO: 多用户账户系统
#   如需支持多用户独立数据隔离，需实现完整的账户模块，包括：
#   - User 数据库表（id, username, hashed_password, created_at）
#   - JWT Token 注册/登录端点（POST /auth/register, POST /auth/login）
#   - characters、sessions 表增加 owner_id 外键
#   - 所有 Router 查询加 .filter(owner_id == current_user.id) 过滤
#   - 前端实现登录页 + Token 持久化 + 请求拦截器
#   参考评估文档：multiuser_upgrade_evaluation.md
"""

import secrets
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader
from typing import Optional
from core.config import settings

# Header 名称：X-API-Key
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(
    api_key_header: Optional[str] = Security(_api_key_header),
) -> None:
    """
    FastAPI 依赖函数，校验请求头中的 API Key。

    - 若 settings.ACCESS_API_KEY 为空字符串：跳过校验（本地开发模式）
    - 若 密钥缺失或值不匹配：返回 403 Forbidden
    - 使用 secrets.compare_digest 防止时序攻击
    """
    expected = settings.ACCESS_API_KEY

    # 未配置 Key 时跳过认证（本地开发友好）
    if not expected:
        return

    # 长期密钥只允许出现在请求头中，避免被写入 URL、访问日志或浏览器历史。
    if not api_key_header or not secrets.compare_digest(api_key_header, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API Key.",
        )
