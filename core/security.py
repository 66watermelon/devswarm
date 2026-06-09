"""
DevSwarm Auth 模块 —— 安全工具

提供密码哈希（原生 bcrypt）、JWT Token 签发与校验功能。
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt  # PyJWT

from core.config import settings


# ---------------------------------------------------------------------------
# 密码哈希上下文（原生 bcrypt 实现）
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """对明文密码进行 bcrypt 哈希。

    Args:
        password: 用户输入的明文密码。

    Returns:
        bcrypt 哈希字符串（可直接存入数据库 hashed_password 字段）。
    """
    # bcrypt 要求输入为 bytes 类型，所以需要 encode('utf-8')
    pwd_bytes = password.encode('utf-8')
    # 生成盐并哈希
    salt = bcrypt.gensalt()
    hashed_bytes = bcrypt.hashpw(pwd_bytes, salt)
    # 将哈希后的 bytes 转回纯文本字符串，方便存入 MySQL 的 VARCHAR 字段
    return hashed_bytes.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文密码与数据库中的哈希值是否匹配。

    Args:
        plain_password: 用户登录时输入的明文密码。
        hashed_password: 数据库中存储的 bcrypt 哈希值。

    Returns:
        True 表示匹配，False 表示密码错误。
    """
    try:
        # bcrypt.checkpw 要求双方都是 bytes 类型
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
    except ValueError:
        # 如果 hashed_password 格式损坏或不是合法的 bcrypt 格式，会抛出 ValueError
        return False


# ---------------------------------------------------------------------------
# JWT Token 签发与校验 
# ---------------------------------------------------------------------------

def create_access_token(user_id: int) -> tuple[str, str, int]:
    """签发 JWT Access Token。

    每次签发生成唯一的 jti（JWT ID），用于 Redis 滑动窗口续期。

    Args:
        user_id: 用户的自增主键 ID。

    Returns:
        三元组 (token_string, jti, expires_in_seconds):
        - token_string: JWT 字符串
        - jti: 唯一的 Token ID（UUID），用于 Redis 缓存键
        - expires_in_seconds: Token 有效时长（秒）
    """
    jti: str = str(uuid.uuid4())

    now = datetime.now(timezone.utc)
    expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    exp = now + expires_delta

    payload: dict = {
        "sub": str(user_id),
        "jti": jti,
        "iat": now,
        "exp": exp,
        "type": "access",
    }

    token: str = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    expires_in: int = int(expires_delta.total_seconds())

    return token, jti, expires_in


def decode_access_token(token: str) -> Optional[dict]:
    """解码并校验 JWT Token。"""
    try:
        payload: dict = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None