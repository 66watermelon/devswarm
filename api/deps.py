"""
DevSwarm Auth 模块 —— FastAPI 依赖注入 (V2 纯异步满血版)

提供 get_current_user 依赖函数，实现 JWT + Redis 滑动窗口续期鉴权。
完全剥离了同步的 I/O 操作，确保 FastAPI 事件循环在高并发下不卡顿。
"""

from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.database import get_async_db, async_redis_client
from models.user import User
from core.security import decode_access_token
from core.config import settings

# HTTPBearer: 从请求头 Authorization: Bearer <token> 中提取 Token
_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_async_db), # 注入 AsyncSession
) -> User:
    """JWT + Redis 滑动窗口鉴权依赖 (全链路异步化)。"""

    # ---- 1. 提取 Token ----
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证 Token，请先登录。",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token: str = credentials.credentials

    # ---- 2. 解码 JWT ----
    payload: Optional[dict] = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 无效或已过期，请重新登录。",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ---- 3. 提取 Payload 字段 ----
    jti: Optional[str] = payload.get("jti")
    user_id_str: Optional[str] = payload.get("sub")

    if not jti or not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 格式异常，缺少必要字段。",
        )

    # ---- 4. Redis 滑动窗口续期 (异步化) ----

    # 使用 await 释放线程，不阻塞等待 Redis 查询
    token_exists = await async_redis_client.exists(jti)
    if not token_exists:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 已失效（已登出或超时），请重新登录。",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 使用 await 异步执行 Redis 过期时间刷新
    await async_redis_client.expire(jti, int(settings.ACCESS_TOKEN_EXPIRE_HOURS * 3600))

    # ---- 5. 查询用户 (异步化) ----
    user_id: int = int(user_id_str)

    # 使用 SQLAlchemy 2.0 异步查询范式
    stmt = select(User).filter(User.id == user_id)
    result = await db.execute(stmt)
    user: Optional[User] = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已被删除。",
        )

    return user