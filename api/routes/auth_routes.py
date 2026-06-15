"""
DevSwarm Auth 模块 —— 认证路由

提供用户注册、登录、登出三个核心接口。
"""

from typing import Optional
from fastapi.security import OAuth2PasswordRequestForm
from fastapi import APIRouter, Depends, HTTPException, status, logger
from sqlalchemy.orm import Session

from core.limiter import limiter
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from db.database import get_db, redis_client
from db.neo4j_client import AsyncNeo4jClient
from models.user import User
from schemas.user import (
    UserRegisterRequest,
    UserLoginRequest,
    UserResponse,
    TokenResponse,
)
from core.security import hash_password, verify_password, create_access_token
from core.config import settings
from api.deps import get_current_user

# 创建路由实例，统一前缀 /auth，所有接口打上 auth 标签
router = APIRouter(prefix="/api/auth", tags=["认证"])


# -------------------------------------------------------------------
# POST /auth/register —— 用户注册
# -------------------------------------------------------------------

@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="用户注册",
)
@limiter.limit("5/minute")
async def register(
    body: UserRegisterRequest,
    db: Session = Depends(get_db),
) -> User:
    """注册新用户。

    校验用户名唯一性后，对密码进行 bcrypt 哈希并写入数据库。

    Args:
        body: 注册请求体（username + password）。
        db: 数据库会话。

    Returns:
        新创建的 User 对象（不含密码）。

    Raises:
        HTTPException 409: 用户名已存在。
    """
    # ---- 1. 检查用户名是否已占用 ----
    existing: Optional[User] = (
        db.query(User).filter(User.username == body.username).first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"用户名 '{body.username}' 已被注册。",
        )

    # ---- 2. 创建用户（密码 bcrypt 哈希） ----
    user = User(
        username=body.username,
        hashed_password=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)  # 刷新以获取数据库生成的 id 和 created_at

    # ---- 3. 在 Neo4j 图数据库中同步创建 User 节点 ----
    try:
        driver = AsyncNeo4jClient.get_driver()
        async with driver.session(database="neo4j") as neo4j_session:
            # 使用 MERGE 而不是 CREATE，防止极小概率下的重复创建报错
            await neo4j_session.run(
                "MERGE (u:User {id: $user_id})",
                user_id=user.id
            )
    except Exception as e:
        logger.error(f"⚠️ 用户 {user.id} SQL注册成功，但同步 Neo4j 失败: {e}")

    return user


# -------------------------------------------------------------------
# POST /auth/login —— 用户登录
# -------------------------------------------------------------------

@router.post(
    "/login",
    response_model=TokenResponse,
    summary="用户登录",
)
@limiter.limit("10/minute")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),  # 使用表单依赖
    db: Session = Depends(get_db),
) -> TokenResponse:
    """用户登录 —— 验证凭证后签发 JWT，并将 jti 写入 Redis。"""

    # ---- 1. 查找用户 ----
    user: Optional[User] = (
        db.query(User).filter(User.username == form_data.username).first()
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误。",
        )

    # ---- 2. 验证密码 ----
    if not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误。",
        )

    # ---- 3. 签发 JWT ----
    token_str, jti, expires_in = create_access_token(user.id)

    # ---- 4. 将 jti 写入 Redis ----
    redis_client.setex(
        name=jti,
        time=int(settings.ACCESS_TOKEN_EXPIRE_HOURS * 3600),
        value=str(user.id),
    )

    return TokenResponse(
        access_token=token_str,
        token_type="bearer",
        expires_in=expires_in,
    )


# -------------------------------------------------------------------
# POST /auth/logout —— 用户登出
# -------------------------------------------------------------------

@router.post(
    "/logout",
    summary="用户登出",
    status_code=status.HTTP_204_NO_CONTENT,
)
def logout(
    current_user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
) -> None:
    """用户登出 —— 从 Redis 中删除当前 Token 的 jti，使 Token 立即失效。

    前端调用此接口后，应立即丢弃本地存储的 Token。

    Args:
        current_user: 当前认证用户（由 get_current_user 依赖注入）。
        credentials: Bearer Token（用于提取 jti）。
    """
    # 从 Token payload 中提取 jti
    from core.security import decode_access_token

    token_str: str = credentials.credentials
    payload: Optional[dict] = decode_access_token(token_str)

    if payload is not None:
        jti: Optional[str] = payload.get("jti")
        if jti:
            # 从 Redis 中删除 jti → Token 立即失效
            redis_client.delete(jti)

    # HTTP 204 No Content: 成功但不返回响应体
    return None
