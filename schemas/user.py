"""
DevSwarm Auth 模块 —— Pydantic 请求/响应校验模型

定义注册、登录、Token 返回等接口的数据结构。
所有请求体经过 Pydantic 校验后再进入业务逻辑层。
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class UserRegisterRequest(BaseModel):
    """用户注册请求体。

    Attributes:
        username: 用户名（3-64 字符，仅允许字母/数字/下划线）。
        password: 明文密码（6-128 字符）。
    """
    username: str = Field(
        ..., min_length=3, max_length=64,
        description="用户名，3-64 字符",
    )
    password: str = Field(
        ..., min_length=6, max_length=128,
        description="明文密码，6-128 字符",
    )

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        """校验用户名仅包含合法字符。"""
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("用户名仅允许字母、数字、下划线和连字符")
        return v.strip()


class UserLoginRequest(BaseModel):
    """用户登录请求体。

    Attributes:
        username: 用户名。
        password: 明文密码。
    """
    username: str = Field(..., min_length=1, description="用户名")
    password: str = Field(..., min_length=1, description="明文密码")


# ---------------------------------------------------------------------------
# 响应模型
# ---------------------------------------------------------------------------

class UserResponse(BaseModel):
    """用户信息响应体（不含密码）。

    Attributes:
        id: 用户 ID。
        username: 用户名。
        created_at: 注册时间。
    """
    id: int
    username: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    """登录成功后的 Token 响应体。

    Attributes:
        access_token: JWT 字符串。
        token_type: 固定值 "bearer"。
        expires_in: Token 有效时长（秒）。
    """
    access_token: str = Field(..., description="JWT Access Token")
    token_type: str = Field(default="bearer", description="Token 类型")
    expires_in: int = Field(..., description="有效时长（秒）")
